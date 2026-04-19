"""Bot entry point — wires handlers, services, scheduler, resilience."""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

# MessageReactionHandler was added in PTB 20.8 but is optional at runtime:
# if the installed PTB doesn't expose it, we log and skip — the bot should
# still boot and serve everything else.
try:
    from telegram.ext import MessageReactionHandler  # type: ignore
    from bot.handlers.reactions import handle_reaction
    _REACTIONS_AVAILABLE = True
except Exception as _exc:  # noqa: BLE001
    MessageReactionHandler = None  # type: ignore[assignment]
    handle_reaction = None  # type: ignore[assignment]
    _REACTIONS_AVAILABLE = False
    _REACTIONS_IMPORT_ERROR = _exc
else:
    _REACTIONS_IMPORT_ERROR = None

from bot.config import get_settings
from bot.db import Database
from bot.handlers.commands import cmd_help, cmd_id, cmd_start
from bot.handlers.groups import cmd_addgroup, cmd_groups, cmd_removegroup
from bot.handlers.messages import fix_transcription_callback, handle_media, handle_text, handle_voice
from bot.handlers.reminders import restore_reminders
from bot.handlers.router import create_group_callback, route_callback
from bot.services.calendar_client import CalendarClient
from bot.services.claude_client import ClaudeClient
from bot.services.telegram_user_client import TelegramUserClient
from bot.services.transcriber import Transcriber
from bot.services.tts import TTS
from bot.utils.logging_setup import setup_logging

logger = logging.getLogger(__name__)


async def _on_startup(app: Application) -> None:
    db: Database = app.bot_data["db"]
    await db.init()
    try:
        me = await app.bot.get_me()
        app.bot_data["bot_username"] = me.username
        logger.info("Bot identity: @%s (%s)", me.username, me.first_name)
    except Exception:
        logger.exception("Failed to fetch bot identity")
    await restore_reminders(app)
    logger.info("Bot startup complete.")


async def _on_error(update: object, context) -> None:
    logger.exception("Unhandled exception in handler", exc_info=context.error)


def build_application() -> Application:
    settings = get_settings()
    setup_logging(settings.log_level)

    app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(_on_startup)
        .build()
    )

    # Wire shared services into bot_data so handlers can grab them
    app.bot_data["db"] = Database(settings.database_path)
    app.bot_data["claude"] = ClaudeClient()
    app.bot_data["calendar"] = CalendarClient()
    app.bot_data["transcriber"] = Transcriber()
    app.bot_data["tts"] = TTS()
    app.bot_data["telegram_user"] = TelegramUserClient()

    # Slash commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("groups", cmd_groups))
    app.add_handler(CommandHandler("addgroup", cmd_addgroup))
    app.add_handler(CommandHandler("removegroup", cmd_removegroup))

    # Inline-button callback for transcription correction
    app.add_handler(CallbackQueryHandler(fix_transcription_callback, pattern=r"^fix_transcription$"))
    # Inline-button callback for ambiguous routing
    app.add_handler(CallbackQueryHandler(route_callback, pattern=r"^route:"))
    # Inline-button callback for group creation confirmation
    app.add_handler(CallbackQueryHandler(create_group_callback, pattern=r"^creategroup:"))

    # Voice messages
    app.add_handler(MessageHandler(filters.VOICE & filters.ChatType.PRIVATE, handle_voice))

    # Media (photos, documents, video, audio) — only in private chat
    app.add_handler(
        MessageHandler(
            (filters.PHOTO | filters.Document.ALL | filters.VIDEO | filters.AUDIO)
            & filters.ChatType.PRIVATE,
            handle_media,
        )
    )

    # Plain text — last so commands and media are matched first
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_text)
    )

    # Reactions on bot-sent messages in groups (requires the bot to be admin).
    # Used to flip history.done when owner reacts with 👍 or ❤.
    if _REACTIONS_AVAILABLE:
        try:
            app.add_handler(MessageReactionHandler(handle_reaction))
            logger.info("MessageReactionHandler registered (👍/❤ tracking active)")
        except Exception:
            logger.exception("Failed to register MessageReactionHandler — continuing without reaction tracking")
    else:
        logger.warning(
            "MessageReactionHandler unavailable in installed PTB (%s) — reaction tracking disabled",
            _REACTIONS_IMPORT_ERROR,
        )

    app.add_error_handler(_on_error)
    return app


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args):
        pass


def _start_health_server() -> None:
    """Start a tiny HTTP server so Render's free Web Service sees an open port."""
    port = int(os.environ.get("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    logger.info("Health-check server listening on port %d", port)


def run() -> None:
    """Run the bot with auto-restart on unexpected failures."""
    setup_logging(get_settings().log_level)
    _start_health_server()
    backoff = 5
    while True:
        try:
            app = build_application()
            logger.info("Starting bot polling...")
            app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
            backoff = 5  # reset on clean exit
            break  # clean shutdown — don't restart
        except KeyboardInterrupt:
            logger.info("Interrupted by user — shutting down.")
            break
        except Exception:
            logger.exception("Bot crashed — restarting in %ss", backoff)
            try:
                import time
                time.sleep(backoff)
            except KeyboardInterrupt:
                break
            backoff = min(backoff * 2, 300)


if __name__ == "__main__":
    run()
