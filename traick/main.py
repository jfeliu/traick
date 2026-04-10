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
from traick.scheduler.jobs import process_pending_messages, send_due_reminders
from traick.webhook.router import router as webhook_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
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


app = FastAPI(title="Traick", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.admin_secret_key)
app.include_router(webhook_router)
app.include_router(admin_router)
app.mount("/static", StaticFiles(directory="traick/admin/static"), name="static")


@app.get("/health")
async def health():
    return {"status": "ok"}


def run():
    uvicorn.run("traick.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    run()
