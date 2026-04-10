"""Userbot — independent process. Daily scan that moves "other" chats into a folder.

Runs in isolation from the bot. If it crashes, the bot keeps working.
The bot's group registry (SQLite) defines which chats are "ours" — anything else
in the user's chat list gets moved into a folder named USERBOT_OTHER_FOLDER.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Iterable

import pytz
from telethon import TelegramClient, functions, types
import aiosqlite

from bot.config import get_settings
from bot.utils.logging_setup import setup_logging

logger = logging.getLogger(__name__)


async def _load_known_chat_ids(db_path: Path) -> set[int]:
    """Read all chat_ids registered as 'our' groups in the bot DB."""
    if not db_path.exists():
        return set()
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("SELECT chat_id FROM groups")
        rows = await cur.fetchall()
        return {int(r[0]) for r in rows}


def _normalize_id(peer_id: int) -> int:
    """Telethon dialog ids may be negative for groups/channels — normalize."""
    return abs(peer_id)


async def _ensure_folder(client: TelegramClient, folder_name: str) -> int:
    """Find or create a Telegram chat folder (DialogFilter). Returns its id."""
    result = await client(functions.messages.GetDialogFiltersRequest())
    filters_list = result.filters if hasattr(result, "filters") else result
    used_ids: set[int] = set()
    for f in filters_list:
        if isinstance(f, types.DialogFilter):
            used_ids.add(f.id)
            title = getattr(f.title, "text", None) or getattr(f, "title", None)
            if isinstance(title, str) and title == folder_name:
                return f.id
    # Pick a free id (Telegram uses 2..255 for user folders)
    new_id = next(i for i in range(2, 256) if i not in used_ids)
    return new_id


async def _scan_and_sort(client: TelegramClient, known_ids: set[int], folder_name: str) -> None:
    logger.info("Scanning dialogs...")
    other_peers: list[types.InputPeer] = []
    seen = 0
    async for dialog in client.iter_dialogs():
        seen += 1
        entity = dialog.entity
        # Resolve numeric id
        eid = getattr(entity, "id", None)
        if eid is None:
            continue
        if eid in known_ids:
            continue
        # Skip the user's own "Saved Messages" chat
        if isinstance(entity, types.User) and getattr(entity, "is_self", False):
            continue
        try:
            other_peers.append(await client.get_input_entity(entity))
        except Exception:
            logger.debug("Could not get input entity for %s", eid)
    logger.info("Saw %d dialogs, %d not in known groups → folder", seen, len(other_peers))

    if not other_peers:
        logger.info("Nothing to sort.")
        return

    folder_id = await _ensure_folder(client, folder_name)

    # Build a DialogFilter and upsert it
    new_filter = types.DialogFilter(
        id=folder_id,
        title=types.TextWithEntities(text=folder_name, entities=[]),
        pinned_peers=[],
        include_peers=other_peers,
        exclude_peers=[],
        contacts=False,
        non_contacts=False,
        groups=False,
        broadcasts=False,
        bots=False,
        exclude_muted=False,
        exclude_read=False,
        exclude_archived=False,
    )
    await client(functions.messages.UpdateDialogFilterRequest(id=folder_id, filter=new_filter))
    logger.info("Updated folder \"%s\" (id=%d) with %d chats.", folder_name, folder_id, len(other_peers))


async def _next_scan_delay(scan_time: str, tz_name: str) -> float:
    tz = pytz.timezone(tz_name)
    now = datetime.now(tz)
    h, m = [int(x) for x in scan_time.split(":")]
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if target <= now:
        target = target.replace(day=target.day + 1) if target.day < 28 else target  # safe-ish
        from datetime import timedelta
        target = now.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=1)
    return (target - now).total_seconds()


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    if not settings.telegram_api_id or not settings.telegram_api_hash:
        logger.error("Userbot requires TELEGRAM_API_ID and TELEGRAM_API_HASH in .env")
        return

    session_path = settings.database_path.parent / settings.telethon_session_name
    client = TelegramClient(
        str(session_path),
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )
    await client.start()  # interactive on first run
    logger.info("Userbot connected.")

    while True:
        try:
            known_ids = await _load_known_chat_ids(settings.database_path)
            logger.info("Loaded %d known chat_ids from bot DB", len(known_ids))
            await _scan_and_sort(client, known_ids, settings.userbot_other_folder)
        except Exception:
            logger.exception("Scan failed")
        delay = await _next_scan_delay(settings.userbot_scan_time, settings.timezone)
        logger.info("Next scan in %.0f seconds", delay)
        await asyncio.sleep(delay)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
