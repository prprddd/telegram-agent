"""Reminder scheduling using PTB's JobQueue (APScheduler under the hood)."""
from __future__ import annotations

import logging
from datetime import datetime

import pytz
from telegram.ext import Application, ContextTypes

from bot.config import get_settings
from bot.db import Database

logger = logging.getLogger(__name__)


async def _fire_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    if not job or not job.data:
        return
    settings = get_settings()
    db: Database = context.application.bot_data["db"]
    rid: int = job.data["id"]
    text: str = job.data["text"]
    try:
        await context.bot.send_message(
            chat_id=settings.telegram_owner_id,
            text=f"⏰ תזכורת: {text}",
        )
        await db.mark_reminder_fired(rid)
    except Exception:
        logger.exception("Failed to fire reminder %s", rid)


def schedule_reminder(app: Application, reminder_id: int, text: str, when: datetime) -> None:
    if app.job_queue is None:
        logger.warning("JobQueue not available — reminder %s NOT scheduled", reminder_id)
        return
    settings = get_settings()
    tz = pytz.timezone(settings.timezone)
    if when.tzinfo is None:
        when = tz.localize(when)
    now = datetime.now(tz)
    if when <= now:
        # Past-due reminder — fire on next tick (5 seconds out)
        when = now.replace(microsecond=0)
    app.job_queue.run_once(
        _fire_reminder,
        when=when,
        data={"id": reminder_id, "text": text},
        name=f"reminder:{reminder_id}",
    )
    logger.info("Scheduled reminder %s for %s", reminder_id, when.isoformat())


async def restore_reminders(app: Application) -> None:
    """Re-schedule all open reminders on startup."""
    db: Database = app.bot_data["db"]
    rows = await db.list_open_reminders()
    for r in rows:
        try:
            when = datetime.fromisoformat(r["remind_at"])
            schedule_reminder(app, r["id"], r["text"], when)
        except Exception:
            logger.exception("Failed to restore reminder %s", r.get("id"))
    logger.info("Restored %d reminders", len(rows))
