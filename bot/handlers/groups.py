"""Group management commands and helpers."""
from __future__ import annotations

import logging
from typing import Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.db import Database
from bot.utils.auth import owner_only

logger = logging.getLogger(__name__)


def _get_db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.application.bot_data["db"]


@owner_only
async def cmd_groups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _get_db(context)
    groups = await db.list_groups()
    if not groups:
        await update.message.reply_text(
            "אין קבוצות מוגדרות עדיין.\n\n"
            "להוסיף קבוצה: הוסף אותי לקבוצה בטלגרם, ואז שלח כאן /addgroup <שם> בתוך הקבוצה, "
            "או \"הוסף קבוצה <שם>\" בצ'אט פרטי איתי תוך כדי forward של הודעה מהקבוצה."
        )
        return
    lines = ["*הקבוצות המוגדרות:*\n"]
    for g in groups:
        desc = f" — {g['description']}" if g.get("description") else ""
        lines.append(f"• *{g['name']}* (id={g['id']}){desc}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@owner_only
async def cmd_addgroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Use this command *inside the target group* to register it.

    Usage: /addgroup <nickname> [description...]
    """
    db = _get_db(context)
    chat = update.effective_chat

    if chat.type == "private":
        await update.message.reply_text(
            "כדי להוסיף קבוצה — הוסף אותי לקבוצה בטלגרם, "
            "ואז שלח שם בתוך הקבוצה: /addgroup שם-הקבוצה [תיאור]"
        )
        return

    args = context.args or []
    if not args:
        await update.message.reply_text("שימוש: /addgroup שם-הקבוצה [תיאור]")
        return

    name = args[0]
    description = " ".join(args[1:]) if len(args) > 1 else None

    try:
        gid = await db.add_group(
            chat_id=chat.id,
            name=name,
            description=description,
        )
    except Exception as e:
        await update.message.reply_text(f"שגיאה בהוספת הקבוצה: {e}")
        return

    await update.message.reply_text(
        f"✅ הקבוצה \"{name}\" נוספה (id={gid}, chat_id={chat.id}).\n"
        f"מעכשיו תוכל לשלוח לי בצ'אט פרטי \"שלח לקבוצת {name}: ...\"."
    )


@owner_only
async def cmd_removegroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Usage: /removegroup <name-or-id>"""
    db = _get_db(context)
    args = context.args or []
    if not args:
        await update.message.reply_text("שימוש: /removegroup שם-הקבוצה")
        return
    target = args[0]
    # Try int first, then name
    removed: bool
    try:
        removed = await db.remove_group(int(target))
    except ValueError:
        removed = await db.remove_group(target)
    if removed:
        await update.message.reply_text(f"✅ הקבוצה \"{target}\" הוסרה.")
    else:
        await update.message.reply_text(f"לא נמצאה קבוצה בשם \"{target}\".")
