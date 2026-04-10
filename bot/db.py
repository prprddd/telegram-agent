"""SQLite database layer using aiosqlite."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL UNIQUE,        -- Telegram chat id
    name TEXT NOT NULL,                     -- Hebrew/English nickname used by the user
    aliases TEXT NOT NULL DEFAULT '[]',     -- JSON list of additional aliases
    description TEXT,                       -- Free-text description for LLM context
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_groups_name ON groups(name);

CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    group_name TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    sent_message_id INTEGER,                -- message_id in the destination group (for delete)
    content_type TEXT NOT NULL,             -- text, photo, document, voice, audio, link
    content_preview TEXT,                   -- short preview / caption / text
    sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_history_sent_at ON history(sent_at DESC);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    remind_at TEXT NOT NULL,                -- ISO 8601 in local TZ
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fired INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_reminders_remind_at ON reminders(remind_at);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nickname TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL,
    full_name TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS calendars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nickname TEXT NOT NULL UNIQUE,          -- nickname used in commands ("משפחתי")
    google_id TEXT NOT NULL,                -- actual Google Calendar id
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS created_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    google_event_id TEXT NOT NULL,
    calendar_id TEXT NOT NULL,
    title TEXT NOT NULL,
    start_at TEXT NOT NULL,
    end_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(SCHEMA)
            await db.commit()

    def _conn(self) -> aiosqlite.Connection:
        return aiosqlite.connect(self.path)

    # ---------- Groups ----------
    async def add_group(
        self,
        chat_id: int,
        name: str,
        aliases: Optional[list[str]] = None,
        description: Optional[str] = None,
    ) -> int:
        async with self._conn() as db:
            cur = await db.execute(
                "INSERT INTO groups (chat_id, name, aliases, description) VALUES (?, ?, ?, ?)",
                (chat_id, name, json.dumps(aliases or [], ensure_ascii=False), description),
            )
            await db.commit()
            return cur.lastrowid or 0

    async def remove_group(self, identifier: str | int) -> bool:
        async with self._conn() as db:
            if isinstance(identifier, int):
                cur = await db.execute("DELETE FROM groups WHERE id = ? OR chat_id = ?", (identifier, identifier))
            else:
                cur = await db.execute("DELETE FROM groups WHERE name = ?", (identifier,))
            await db.commit()
            return (cur.rowcount or 0) > 0

    async def list_groups(self) -> list[dict[str, Any]]:
        async with self._conn() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM groups ORDER BY name")
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_group_by_name(self, name: str) -> Optional[dict[str, Any]]:
        async with self._conn() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM groups WHERE name = ?", (name,))
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_group_by_id(self, group_id: int) -> Optional[dict[str, Any]]:
        async with self._conn() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM groups WHERE id = ?", (group_id,))
            row = await cur.fetchone()
            return dict(row) if row else None

    async def count_groups_created_last_24h(self) -> int:
        async with self._conn() as db:
            cur = await db.execute(
                "SELECT COUNT(*) FROM groups WHERE created_at > datetime('now', '-1 day')"
            )
            row = await cur.fetchone()
            return int(row[0]) if row else 0

    # ---------- History ----------
    async def add_history(
        self,
        group_id: int,
        group_name: str,
        chat_id: int,
        sent_message_id: Optional[int],
        content_type: str,
        content_preview: Optional[str],
    ) -> int:
        async with self._conn() as db:
            cur = await db.execute(
                """INSERT INTO history
                   (group_id, group_name, chat_id, sent_message_id, content_type, content_preview)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (group_id, group_name, chat_id, sent_message_id, content_type, content_preview),
            )
            await db.commit()
            return cur.lastrowid or 0

    async def get_recent_history(self, limit: int = 20) -> list[dict[str, Any]]:
        async with self._conn() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM history ORDER BY sent_at DESC LIMIT ?", (limit,)
            )
            return [dict(r) for r in await cur.fetchall()]

    async def get_last_history(self) -> Optional[dict[str, Any]]:
        async with self._conn() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM history ORDER BY sent_at DESC LIMIT 1")
            row = await cur.fetchone()
            return dict(row) if row else None

    async def delete_history_entry(self, history_id: int) -> bool:
        async with self._conn() as db:
            cur = await db.execute("DELETE FROM history WHERE id = ?", (history_id,))
            await db.commit()
            return (cur.rowcount or 0) > 0

    # ---------- Reminders ----------
    async def add_reminder(self, text: str, remind_at: datetime) -> int:
        async with self._conn() as db:
            cur = await db.execute(
                "INSERT INTO reminders (text, remind_at) VALUES (?, ?)",
                (text, remind_at.isoformat()),
            )
            await db.commit()
            return cur.lastrowid or 0

    async def list_open_reminders(self) -> list[dict[str, Any]]:
        async with self._conn() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM reminders WHERE fired = 0 ORDER BY remind_at"
            )
            return [dict(r) for r in await cur.fetchall()]

    async def list_all_reminders(self) -> list[dict[str, Any]]:
        async with self._conn() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM reminders ORDER BY remind_at")
            return [dict(r) for r in await cur.fetchall()]

    async def mark_reminder_fired(self, reminder_id: int) -> None:
        async with self._conn() as db:
            await db.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (reminder_id,))
            await db.commit()

    async def delete_reminder(self, reminder_id: int) -> bool:
        async with self._conn() as db:
            cur = await db.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
            await db.commit()
            return (cur.rowcount or 0) > 0

    # ---------- Contacts ----------
    async def add_contact(self, nickname: str, email: str, full_name: Optional[str] = None) -> int:
        async with self._conn() as db:
            cur = await db.execute(
                "INSERT OR REPLACE INTO contacts (nickname, email, full_name) VALUES (?, ?, ?)",
                (nickname, email, full_name),
            )
            await db.commit()
            return cur.lastrowid or 0

    async def get_contact(self, nickname: str) -> Optional[dict[str, Any]]:
        async with self._conn() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM contacts WHERE nickname = ?", (nickname,))
            row = await cur.fetchone()
            return dict(row) if row else None

    async def list_contacts(self) -> list[dict[str, Any]]:
        async with self._conn() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM contacts ORDER BY nickname")
            return [dict(r) for r in await cur.fetchall()]

    async def delete_contact(self, nickname: str) -> bool:
        async with self._conn() as db:
            cur = await db.execute("DELETE FROM contacts WHERE nickname = ?", (nickname,))
            await db.commit()
            return (cur.rowcount or 0) > 0

    # ---------- Calendars ----------
    async def add_calendar(self, nickname: str, google_id: str, is_default: bool = False) -> int:
        async with self._conn() as db:
            if is_default:
                await db.execute("UPDATE calendars SET is_default = 0")
            cur = await db.execute(
                "INSERT OR REPLACE INTO calendars (nickname, google_id, is_default) VALUES (?, ?, ?)",
                (nickname, google_id, 1 if is_default else 0),
            )
            await db.commit()
            return cur.lastrowid or 0

    async def list_calendars(self) -> list[dict[str, Any]]:
        async with self._conn() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM calendars ORDER BY nickname")
            return [dict(r) for r in await cur.fetchall()]

    async def get_calendar(self, nickname: str) -> Optional[dict[str, Any]]:
        async with self._conn() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM calendars WHERE nickname = ?", (nickname,))
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_default_calendar(self) -> Optional[dict[str, Any]]:
        async with self._conn() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM calendars WHERE is_default = 1 LIMIT 1")
            row = await cur.fetchone()
            return dict(row) if row else None

    async def delete_calendar(self, nickname: str) -> bool:
        async with self._conn() as db:
            cur = await db.execute("DELETE FROM calendars WHERE nickname = ?", (nickname,))
            await db.commit()
            return (cur.rowcount or 0) > 0

    # ---------- Created Events ----------
    async def save_created_event(
        self, google_event_id: str, calendar_id: str, title: str, start_at: str, end_at: str | None = None
    ) -> int:
        async with self._conn() as db:
            cur = await db.execute(
                "INSERT INTO created_events (google_event_id, calendar_id, title, start_at, end_at) VALUES (?, ?, ?, ?, ?)",
                (google_event_id, calendar_id, title, start_at, end_at),
            )
            await db.commit()
            return cur.lastrowid or 0

    async def list_recent_created_events(self, limit: int = 10) -> list[dict[str, Any]]:
        async with self._conn() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM created_events ORDER BY created_at DESC LIMIT ?", (limit,)
            )
            return [dict(r) for r in await cur.fetchall()]

    async def get_created_event(self, event_db_id: int) -> Optional[dict[str, Any]]:
        async with self._conn() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM created_events WHERE id = ?", (event_db_id,))
            row = await cur.fetchone()
            return dict(row) if row else None
