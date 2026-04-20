import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlencode as _urlencode

import aiosqlite
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from traick.ai.extractor import extract_from_messages
from traick.config import settings
from traick.db.repository import create_action_item as repo_create_action_item
from traick.db.repository import schedule_follow_up as repo_schedule_follow_up

logger = logging.getLogger(__name__)

_PROJECTS_SORT = {"id", "owner_number", "name", "status", "created_at", "updated_at"}
_ACTION_ITEMS_SORT = {
    "id": "ai.id",
    "project_name": "p.name",
    "description": "ai.description",
    "deadline": "ai.deadline",
    "status": "ai.status",
    "created_at": "ai.created_at",
}
_FOLLOW_UPS_SORT = {
    "id": "fu.id",
    "project_name": "p.name",
    "action_item_desc": "ai.description",
    "message": "fu.message",
    "scheduled_at": "fu.scheduled_at",
    "sent": "fu.sent",
}

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="traick/admin/templates")


def _require_auth(request: Request) -> None:
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=307, headers={"Location": "/admin/login"})


# All routes on `protected` require an active session
protected = APIRouter(dependencies=[Depends(_require_auth)])


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if username == settings.admin_username and password == settings.admin_password:
        request.session["authenticated"] = True
        return RedirectResponse("/admin/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": "Invalid credentials"},
        status_code=401,
    )


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


@protected.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    async with aiosqlite.connect(settings.db_path) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM projects")
        (count,) = await cursor.fetchone()
    return templates.TemplateResponse(
        request=request, name="dashboard.html", context={"project_count": count}
    )


@protected.get("/projects", response_class=HTMLResponse)
async def list_projects(
    request: Request,
    sort_by: str = Query("id"),
    sort_order: str = Query("desc"),
    status: str = Query("active"),
    q: str = Query(""),
):
    col = sort_by if sort_by in _PROJECTS_SORT else "id"
    order = "ASC" if sort_order.lower() == "asc" else "DESC"
    sort_order_norm = order.lower()
    where_parts: list[str] = []
    params: list = []
    if status:
        where_parts.append("status = ?")
        params.append(status)
    if q:
        where_parts.append("(name LIKE ? OR description LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    filter_qs = ("&" + _urlencode({k: v for k, v in [("status", status), ("q", q)] if v})) if (status or q) else ""
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT * FROM projects {where_sql} ORDER BY {col} {order}",
            params,
        )
        projects = await cursor.fetchall()
    return templates.TemplateResponse(
        request=request,
        name="projects.html",
        context={
            "projects": projects,
            "sort_by": col,
            "sort_order": sort_order_norm,
            "status": status,
            "q": q,
            "filter_qs": filter_qs,
        },
    )


@protected.get("/projects/new", response_class=HTMLResponse)
async def new_project_form(request: Request):
    return templates.TemplateResponse(request=request, name="project_form.html")


@protected.post("/projects/new")
async def create_project(
    request: Request,
    owner_number: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
):
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            """
            INSERT INTO projects (owner_number, name, description, created_at, updated_at)
            VALUES (?, ?, ?, datetime('now'), datetime('now'))
            """,
            (owner_number, name, description),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT id FROM projects WHERE owner_number = ? AND name = ?",
            (owner_number, name),
        )
        row = await cursor.fetchone()
        project_id = row["id"]

    await _generate_project_ai_content(project_id, name, description)

    return RedirectResponse(f"/admin/projects/{project_id}", status_code=303)


async def _generate_project_ai_content(
    project_id: int, name: str, description: str
) -> None:
    """Use the AI extractor to create action items and follow-ups for a new project."""
    if not description:
        return

    synthetic_message = f"Project: {name}\n{description}"
    result = await extract_from_messages(
        messages=[{"body": synthetic_message}],
    )

    for update in result.updates:
        first_action_item_id: int | None = None
        for item in update.action_items:
            deadline_ts: int | None = None
            if item.deadline_iso:
                try:
                    dt = datetime.fromisoformat(item.deadline_iso).replace(
                        tzinfo=timezone.utc
                    )
                    deadline_ts = int(dt.timestamp())
                except ValueError:
                    logger.warning("Bad deadline format: %s", item.deadline_iso)

            action_item_id = await repo_create_action_item(
                project_id=project_id,
                description=item.description,
                deadline=deadline_ts,
            )
            if first_action_item_id is None:
                first_action_item_id = action_item_id

        if update.follow_up_message and update.follow_up_days is not None:
            await repo_schedule_follow_up(
                project_id=project_id,
                action_item_id=first_action_item_id,
                message=update.follow_up_message,
                scheduled_at=int(time.time()) + update.follow_up_days * 86400,
            )
            logger.info(
                "Scheduled follow-up for project %d ('%s') in %d days",
                project_id,
                name,
                update.follow_up_days,
            )


async def _generate_project_ai_content(
    project_id: int, name: str, description: str
) -> None:
    """Use the AI extractor to create action items and follow-ups for a new project."""
    if not description:
        return

    synthetic_message = f"Project: {name}\n{description}"
    result = await extract_from_messages(
        messages=[{"body": synthetic_message}],
    )

    for update in result.updates:
        first_action_item_id: int | None = None
        for item in update.action_items:
            deadline_ts: int | None = None
            if item.deadline_iso:
                try:
                    dt = datetime.fromisoformat(item.deadline_iso).replace(
                        tzinfo=timezone.utc
                    )
                    deadline_ts = int(dt.timestamp())
                except ValueError:
                    logger.warning("Bad deadline format: %s", item.deadline_iso)

            action_item_id = await repo_create_action_item(
                project_id=project_id,
                description=item.description,
                deadline=deadline_ts,
            )
            if first_action_item_id is None:
                first_action_item_id = action_item_id

        if update.follow_up_message and update.follow_up_days is not None:
            await repo_schedule_follow_up(
                project_id=project_id,
                action_item_id=first_action_item_id,
                message=update.follow_up_message,
                scheduled_at=int(time.time()) + update.follow_up_days * 86400,
            )
            logger.info(
                "Scheduled follow-up for project %d ('%s') in %d days",
                project_id,
                name,
                update.follow_up_days,
            )


@protected.get("/projects/{project_id}", response_class=HTMLResponse)
async def view_project(request: Request, project_id: int):
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        project = await cursor.fetchone()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        cursor = await db.execute(
            "SELECT * FROM action_items WHERE project_id = ? ORDER BY status ASC, created_at DESC",
            (project_id,),
        )
        action_items = await cursor.fetchall()
        cursor = await db.execute(
            """SELECT fu.*, ai.description as action_item_desc
               FROM follow_ups fu
               LEFT JOIN action_items ai ON fu.action_item_id = ai.id
               WHERE fu.project_id = ?
               ORDER BY fu.scheduled_at ASC""",
            (project_id,),
        )
        follow_ups = await cursor.fetchall()
    return templates.TemplateResponse(
        request=request,
        name="project_detail.html",
        context={"project": project, "action_items": action_items, "follow_ups": follow_ups},
    )


@protected.get("/projects/{project_id}/edit", response_class=HTMLResponse)
async def edit_project_form(request: Request, project_id: int):
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        project = await cursor.fetchone()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return templates.TemplateResponse(
        request=request, name="project_form.html", context={"project": project}
    )


@protected.post("/projects/{project_id}/edit")
async def update_project(
    request: Request,
    project_id: int,
    owner_number: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
):
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """
            UPDATE projects SET owner_number = ?, name = ?, description = ?, updated_at = datetime('now') WHERE id = ?
            """,
            (owner_number, name, description, project_id),
        )
        await db.commit()
    return RedirectResponse("/admin/projects", status_code=303)


@protected.post("/projects/{project_id}/delete")
async def delete_project(request: Request, project_id: int):
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        await db.commit()
    return RedirectResponse("/admin/projects", status_code=303)


@protected.get("/action_items", response_class=HTMLResponse)
async def list_action_items(
    request: Request,
    sort_by: str = Query("id"),
    sort_order: str = Query("desc"),
    status: str = Query("open"),
    q: str = Query(""),
):
    col_expr = _ACTION_ITEMS_SORT.get(sort_by, "ai.id")
    order = "ASC" if sort_order.lower() == "asc" else "DESC"
    sort_order_norm = order.lower()
    where_parts: list[str] = []
    params: list = []
    if status:
        where_parts.append("ai.status = ?")
        params.append(status)
    if q:
        where_parts.append("ai.description LIKE ?")
        params.append(f"%{q}%")
    where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    filter_qs = ("&" + _urlencode({k: v for k, v in [("status", status), ("q", q)] if v})) if (status or q) else ""
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT ai.*, p.name as project_name FROM action_items ai LEFT JOIN projects p ON ai.project_id = p.id {where_sql} ORDER BY {col_expr} {order}",
            params,
        )
        action_items = await cursor.fetchall()
    return templates.TemplateResponse(
        request=request,
        name="action_items.html",
        context={
            "action_items": action_items,
            "sort_by": sort_by if sort_by in _ACTION_ITEMS_SORT else "id",
            "sort_order": sort_order_norm,
            "status": status,
            "q": q,
            "filter_qs": filter_qs,
        },
    )


@protected.get("/action_items/new", response_class=HTMLResponse)
async def new_action_item_form(request: Request, project_id: int | None = Query(None)):
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT id, name FROM projects ORDER BY name")
        projects = await cursor.fetchall()
    return templates.TemplateResponse(
        request=request,
        name="action_item_form.html",
        context={"projects": projects, "preselect_project_id": project_id},
    )


@protected.post("/action_items/new")
async def create_action_item(
    request: Request,
    project_id: int = Form(...),
    description: str = Form(...),
    deadline: str = Form(""),
):
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """
            INSERT INTO action_items (project_id, description, deadline, created_at)
            VALUES (?, ?, ?, datetime('now'))
            """,
            (project_id, description, deadline),
        )
        await db.commit()
    return RedirectResponse("/admin/action_items", status_code=303)


@protected.get("/action_items/{action_item_id}/edit", response_class=HTMLResponse)
async def edit_action_item_form(request: Request, action_item_id: int):
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM action_items WHERE id = ?", (action_item_id,)
        )
        action_item = await cursor.fetchone()
        cursor = await db.execute("SELECT id, name FROM projects ORDER BY name")
        projects = await cursor.fetchall()
    if not action_item:
        raise HTTPException(status_code=404, detail="Action item not found")
    return templates.TemplateResponse(
        request=request,
        name="action_item_form.html",
        context={"action_item": action_item, "projects": projects},
    )


@protected.post("/action_items/{action_item_id}/edit")
async def update_action_item(
    request: Request,
    action_item_id: int,
    project_id: int = Form(...),
    description: str = Form(...),
    deadline: str = Form(""),
):
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """
            UPDATE action_items SET project_id = ?, description = ?, deadline = ? WHERE id = ?
            """,
            (project_id, description, deadline, action_item_id),
        )
        await db.commit()
    return RedirectResponse("/admin/action_items", status_code=303)


@protected.post("/action_items/{action_item_id}/delete")
async def delete_action_item(request: Request, action_item_id: int):
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute("DELETE FROM action_items WHERE id = ?", (action_item_id,))
        await db.commit()
    return RedirectResponse("/admin/action_items", status_code=303)


@protected.get("/follow_ups", response_class=HTMLResponse)
async def list_follow_ups(
    request: Request,
    sort_by: str = Query("id"),
    sort_order: str = Query("desc"),
    sent: str = Query("0"),
    q: str = Query(""),
):
    col_expr = _FOLLOW_UPS_SORT.get(sort_by, "fu.id")
    order = "ASC" if sort_order.lower() == "asc" else "DESC"
    sort_order_norm = order.lower()
    where_parts: list[str] = []
    params: list = []
    if sent in ("0", "1"):
        where_parts.append("fu.sent = ?")
        params.append(int(sent))
    if q:
        where_parts.append("fu.message LIKE ?")
        params.append(f"%{q}%")
    where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    filter_qs = ("&" + _urlencode({k: v for k, v in [("sent", sent), ("q", q)] if v})) if (sent or q) else ""
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT fu.*, p.name as project_name, ai.description as action_item_desc FROM follow_ups fu LEFT JOIN projects p ON fu.project_id = p.id LEFT JOIN action_items ai ON fu.action_item_id = ai.id {where_sql} ORDER BY {col_expr} {order}",
            params,
        )
        follow_ups = await cursor.fetchall()
    return templates.TemplateResponse(
        request=request,
        name="follow_ups.html",
        context={
            "follow_ups": follow_ups,
            "sort_by": sort_by if sort_by in _FOLLOW_UPS_SORT else "id",
            "sort_order": sort_order_norm,
            "sent": sent,
            "q": q,
            "filter_qs": filter_qs,
        },
    )


@protected.get("/follow_ups/new", response_class=HTMLResponse)
async def new_follow_up_form(request: Request, project_id: int | None = Query(None)):
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT id, name FROM projects ORDER BY name")
        projects = await cursor.fetchall()
        cursor = await db.execute(
            "SELECT id, description, project_id FROM action_items ORDER BY description"
        )
        action_items = await cursor.fetchall()
    return templates.TemplateResponse(
        request=request,
        name="follow_up_form.html",
        context={"projects": projects, "action_items": action_items, "preselect_project_id": project_id},
    )


@protected.post("/follow_ups/new")
async def create_follow_up(
    request: Request,
    project_id: int = Form(...),
    action_item_id: int = Form(...),
    message: str = Form(...),
    scheduled_at: str = Form(...),
):
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """
            INSERT INTO follow_ups (project_id, action_item_id, message, scheduled_at)
            VALUES (?, ?, ?, ?)
            """,
            (project_id, action_item_id, message, scheduled_at.replace("T", " ")),
        )
        await db.commit()
    return RedirectResponse("/admin/follow_ups", status_code=303)


@protected.get("/follow_ups/{follow_up_id}/edit", response_class=HTMLResponse)
async def edit_follow_up_form(request: Request, follow_up_id: int):
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM follow_ups WHERE id = ?", (follow_up_id,)
        )
        follow_up = await cursor.fetchone()
        cursor = await db.execute("SELECT id, name FROM projects ORDER BY name")
        projects = await cursor.fetchall()
        cursor = await db.execute(
            "SELECT id, description, project_id FROM action_items ORDER BY description"
        )
        action_items = await cursor.fetchall()
    if not follow_up:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    return templates.TemplateResponse(
        request=request,
        name="follow_up_form.html",
        context={
            "follow_up": follow_up,
            "projects": projects,
            "action_items": action_items,
        },
    )


@protected.post("/follow_ups/{follow_up_id}/edit")
async def update_follow_up(
    request: Request,
    follow_up_id: int,
    project_id: int = Form(...),
    action_item_id: int = Form(...),
    message: str = Form(...),
    scheduled_at: str = Form(...),
):
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """
            UPDATE follow_ups SET project_id = ?, action_item_id = ?, message = ?, scheduled_at = ? WHERE id = ?
            """,
            (
                project_id,
                action_item_id,
                message,
                scheduled_at.replace("T", " "),
                follow_up_id,
            ),
        )
        await db.commit()
    return RedirectResponse("/admin/follow_ups", status_code=303)


@protected.post("/follow_ups/{follow_up_id}/delete")
async def delete_follow_up(request: Request, follow_up_id: int):
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute("DELETE FROM follow_ups WHERE id = ?", (follow_up_id,))
        await db.commit()
    return RedirectResponse("/admin/follow_ups", status_code=303)


@protected.get("/db", response_class=HTMLResponse)
async def db_overview(request: Request):
    async with aiosqlite.connect(settings.db_path) as db:
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in await cursor.fetchall()]
        table_counts = {}
        for table in tables:
            cur = await db.execute(f"SELECT COUNT(*) FROM {table}")
            (count,) = await cur.fetchone()
            table_counts[table] = count
    return templates.TemplateResponse(
        request=request,
        name="db_overview.html",
        context={"tables": tables, "table_counts": table_counts},
    )


router.include_router(protected)
