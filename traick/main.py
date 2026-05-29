"""
Traick — WhatsApp AI project tracker
=====================================
Run with:
    uvicorn traick.main:app --reload
or:
    traick
"""

import logging
from contextlib import asynccontextmanager

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from traick.admin.router import router as admin_router
from traick.config import settings
from traick.db.database import init_db
from traick.dev.router import router as dev_router
from traick.scheduler.jobs import (
    ensure_active_project_followups,
    process_pending_messages,
    send_due_reminders,
)
from traick.webhook.router import router as webhook_router

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
# Keep noisy third-party loggers at WARNING regardless of log level
for _noisy in ("httpx", "httpcore", "apscheduler"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    logger.info("Database initialised at %s", settings.db_path)

    _scheduler.add_job(
        process_pending_messages,
        "interval",
        minutes=settings.process_interval_minutes,
        id="process_messages",
        replace_existing=True,
    )
    _scheduler.add_job(
        send_due_reminders,
        "interval",
        minutes=settings.reminder_interval_minutes,
        id="send_reminders",
        replace_existing=True,
    )
    _scheduler.add_job(
        ensure_active_project_followups,
        "interval",
        hours=24,
        id="ensure_followups",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "Scheduler started — processing every %dm, reminders every %dm",
        settings.process_interval_minutes,
        settings.reminder_interval_minutes,
    )

    yield

    # Shutdown
    _scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")


class _AdminSubdomainMiddleware:
    """Rewrite requests from the admin subdomain so /foo is served as /admin/foo.

    Paths that already start with /admin or /static are left untouched so that
    static assets and direct /admin/* links continue to work normally.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and settings.admin_hostname:
            headers = {k: v for k, v in scope["headers"]}
            host = headers.get(b"host", b"").decode().split(":")[0]
            if host == settings.admin_hostname:
                path: str = scope["path"]
                if not path.startswith("/admin") and not path.startswith("/static"):
                    new_path = "/admin" + path
                    scope = {**scope, "path": new_path, "raw_path": new_path.encode()}
        await self.app(scope, receive, send)


app = FastAPI(title="Traick", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.admin_secret_key)
app.add_middleware(_AdminSubdomainMiddleware)
app.include_router(webhook_router)
app.include_router(admin_router)
if settings.dev_mode:
    app.include_router(dev_router)
    logger.info("Dev mode enabled — chat UI available at /dev/chat")
app.mount("/static", StaticFiles(directory="traick/admin/static"), name="static")


@app.get("/health")
async def health():
    return {"status": "ok"}


def run():
    uvicorn.run("traick.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    run()
