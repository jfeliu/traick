"""CRUD operations for all tables."""

from datetime import datetime, timezone


from traick.db.database import get_db


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ── Raw messages ──────────────────────────────────────────────────────────────


async def save_raw_message(
    wa_id: str, from_number: str, body: str, timestamp: int
) -> None:
    ts = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    async with get_db() as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO raw_messages (wa_message_id, from_number, body, timestamp)
            VALUES (?, ?, ?, ?)
            """,
            (wa_id, from_number, body, ts),
        )
        await db.commit()


async def get_pending_messages(limit: int = 20) -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM raw_messages WHERE processed = 0 ORDER BY timestamp LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_recent_messages(from_number: str, limit: int = 10) -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM raw_messages WHERE from_number = ? ORDER BY timestamp DESC LIMIT ?",
            (from_number, limit),
        )
        rows = await cursor.fetchall()
        return list(reversed([dict(r) for r in rows]))


async def mark_messages_processed(ids: list[int]) -> None:
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    async with get_db() as db:
        await db.execute(
            f"UPDATE raw_messages SET processed = 1 WHERE id IN ({placeholders})",
            ids,
        )
        await db.commit()


# ── Projects ──────────────────────────────────────────────────────────────────


async def upsert_project(
    owner_number: str, name: str, description: str | None, status: str
) -> int:
    now = _now()
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO projects (owner_number, name, description, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner_number, name) DO UPDATE SET
                description = COALESCE(excluded.description, description),
                status      = excluded.status,
                updated_at  = excluded.updated_at
            """,
            (owner_number, name, description, status, now, now),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT id FROM projects WHERE owner_number = ? AND name = ?",
            (owner_number, name),
        )
        row = await cursor.fetchone()
        return row["id"]


async def get_active_projects(owner_number: str | None = None) -> list[dict]:
    async with get_db() as db:
        if owner_number:
            cursor = await db.execute(
                "SELECT * FROM projects WHERE status = 'active' AND owner_number = ? ORDER BY updated_at DESC",
                (owner_number,),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM projects WHERE status = 'active' ORDER BY updated_at DESC"
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ── Action items ──────────────────────────────────────────────────────────────


async def create_action_item(
    project_id: int, description: str, deadline: int | None
) -> int:
    deadline_str: str | None = None
    if deadline is not None:
        deadline_str = datetime.fromtimestamp(deadline, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    async with get_db() as db:
        cursor = await db.execute(
            """
            INSERT INTO action_items (project_id, description, deadline, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (project_id, description, deadline_str, _now()),
        )
        await db.commit()
        return cursor.lastrowid


async def get_open_action_items(project_id: int) -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM action_items WHERE project_id = ? AND status = 'open'",
            (project_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ── Follow-ups ────────────────────────────────────────────────────────────────


async def schedule_follow_up(
    project_id: int,
    action_item_id: int | None,
    message: str,
    scheduled_at: int,
) -> None:
    scheduled_str = datetime.fromtimestamp(scheduled_at, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO follow_ups (project_id, action_item_id, message, scheduled_at)
            VALUES (?, ?, ?, ?)
            """,
            (project_id, action_item_id, message, scheduled_str),
        )
        await db.commit()


async def get_due_follow_ups() -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT f.*, p.owner_number
            FROM follow_ups f
            JOIN projects p ON f.project_id = p.id
            WHERE f.scheduled_at <= datetime('now') AND f.sent = 0
            ORDER BY f.scheduled_at
            """
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def mark_follow_up_sent(follow_up_id: int) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE follow_ups SET sent = 1 WHERE id = ?",
            (follow_up_id,),
        )
        await db.commit()
