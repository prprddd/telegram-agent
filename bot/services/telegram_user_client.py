"""Lightweight Telethon helper used on-demand for actions the Bot API can't perform.

Used only when needed (e.g. creating a new group). Connects, performs the operation,
disconnects — to minimize conflict with the long-running userbot scanner if present.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from telethon import TelegramClient, functions

from bot.config import get_settings

logger = logging.getLogger(__name__)


class TelegramUserClient:
    def __init__(self) -> None:
        s = get_settings()
        self._configured = bool(s.telegram_api_id and s.telegram_api_hash)
        self._session_path = str(s.database_path.parent / s.telethon_session_name)
        self._api_id = s.telegram_api_id
        self._api_hash = s.telegram_api_hash

    @property
    def configured(self) -> bool:
        return self._configured

    @asynccontextmanager
    async def connect(self):
        if not self._configured:
            raise RuntimeError(
                "Telethon לא מוגדר. הוסף TELEGRAM_API_ID ו-TELEGRAM_API_HASH ל-.env "
                "(ראה docs/setup.md סעיף 6)."
            )
        client = TelegramClient(self._session_path, self._api_id, self._api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            raise RuntimeError(
                "Telethon לא מאומת. הרץ פעם אחת `python -m userbot.main` כדי לאמת מול טלגרם."
            )
        try:
            yield client
        finally:
            await client.disconnect()

    async def create_group_with_bot(self, name: str, bot_username: str) -> tuple[int, str]:
        """Create a small private group and add the given bot.

        Returns (chat_id_for_bot_api, group_title).
        """
        async with self.connect() as client:
            result = await client(
                functions.messages.CreateChatRequest(
                    users=[bot_username],
                    title=name,
                )
            )
            # Find the resulting chat
            chats = []
            updates_obj = getattr(result, "updates", None)
            if updates_obj is not None and hasattr(updates_obj, "chats"):
                chats = updates_obj.chats
            elif hasattr(result, "chats"):
                chats = result.chats
            if not chats:
                raise RuntimeError("יצירת הקבוצה לא החזירה chat object")
            chat = chats[0]
            # Bot API uses -<id> for legacy small groups
            bot_api_chat_id = -int(chat.id)
            title = getattr(chat, "title", name)
            logger.info("Created Telegram group title=%r bot_api_chat_id=%d", title, bot_api_chat_id)
            return bot_api_chat_id, title
