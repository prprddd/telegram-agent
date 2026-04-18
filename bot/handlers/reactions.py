"""Handle 👍/❤ reactions on bot-sent messages → flip the `done` flag in history.

Requires the bot to be admin in the target group (Telegram only delivers
`message_reaction` updates to bots that are admins). The reaction must come
from the bot's owner; reactions from others are ignored.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import get_settings
from bot.db import Database

logger = logging.getLogger(__name__)

# Normalized (VS-16 stripped) emojis that mark an item as complete.
DONE_EMOJIS = {"👍", "❤"}


def _extract_emojis(reactions: Iterable[Any] | None) -> set[str]:
    out: set[str] = set()
    for r in reactions or ():
        emoji = getattr(r, "emoji", None)
        if emoji:
            out.add(emoji.replace("\ufe0f", ""))
    return out


async def handle_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reaction = update.message_reaction
    if not reaction:
        return

    # Only trust reactions from the bot owner (single-user bot)
    settings = get_settings()
    if reaction.user and reaction.user.id != settings.telegram_owner_id:
        return

    db: Database = context.application.bot_data["db"]
    chat_id = reaction.chat.id
    msg_id = reaction.message_id

    new = _extract_emojis(reaction.new_reaction)
    old = _extract_emojis(reaction.old_reaction)

    has_done_now = bool(new & DONE_EMOJIS)
    had_done_before = bool(old & DONE_EMOJIS)

    if has_done_now and not had_done_before:
        ok = await db.mark_history_done(chat_id, msg_id, True)
        logger.info("Marked DONE (chat=%s msg=%s, db_hit=%s)", chat_id, msg_id, ok)
    elif had_done_before and not has_done_now:
        ok = await db.mark_history_done(chat_id, msg_id, False)
        logger.info("Marked OPEN (chat=%s msg=%s, db_hit=%s)", chat_id, msg_id, ok)
