"""Single-user authorization guard."""
from __future__ import annotations

import logging
from functools import wraps
from typing import Any, Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import get_settings

logger = logging.getLogger(__name__)


def owner_only(
    func: Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[Any]],
) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[Any]]:
    """Decorator: only allow the configured owner to invoke the handler."""

    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Any:
        settings = get_settings()
        user = update.effective_user
        if user is None or user.id != settings.telegram_owner_id:
            logger.warning(
                "Blocked unauthorized access from user_id=%s username=%s",
                user.id if user else None,
                user.username if user else None,
            )
            if update.effective_message:
                await update.effective_message.reply_text(
                    "מצטער, הבוט הזה אישי. אין לך גישה."
                )
            return None
        return await func(update, context)

    return wrapper
