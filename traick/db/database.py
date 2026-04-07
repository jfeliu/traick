from contextlib import asynccontextmanager

import aiosqlite
from traick.config import settings

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS raw_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wa_message_id   TEXT UNIQUE,
    from_number     TEXT NOT NULL,
    body            TEXT NOT NULL,
    timestamp       DATETIME NOT NULL,
    processed       INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS projects (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_number TEXT NOT NULL,
    name         TEXT NOT NULL,
    description  TEXT,
    status       TEXT DEFAULT 'active',
    created_at   DATETIME NOT NULL,
    updated_at   DATETIME NOT NULL,
    UNIQUE (owner_number, name)
);

CREATE TABLE IF NOT EXISTS action_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER REFERENCES projects(id),
    description TEXT NOT NULL,
    deadline    DATETIME,
    status      TEXT DEFAULT 'open',
    created_at  DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS follow_ups (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER REFERENCES projects(id),
    action_item_id  INTEGER REFERENCES action_items(id),
    message         TEXT NOT NULL,
    scheduled_at    DATETIME NOT NULL,
    sent            INTEGER DEFAULT 0
);
"""


@asynccontextmanager
async def get_db():
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        yield db


async def init_db() -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.executescript(CREATE_TABLES)
        await db.commit()
