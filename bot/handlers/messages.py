"""Top-level message handlers (text, voice, media)."""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes, ConversationHandler

from bot.handlers.router import parse_and_dispatch
from bot.utils.auth import owner_only

logger = logging.getLogger(__name__)


VOICE_REPLY_PREFIXES = (
    "תדבר איתי",
    "דבר איתי",
    "דבר אלי",
    "תענה בקול",
    "תענה בהודעה קולית",
    "תענה לי בקול",
    "ענה בקול",
    "הקרא לי",
    "תקריא לי",
)


def _strip_voice_prefix(text: str) -> tuple[str, bool]:
    """Return (remaining_text, wants_voice). If a voice-reply prefix matched,
    strip it and return True."""
    stripped = text.strip()
    low = stripped.lower()
    for prefix in VOICE_REPLY_PREFIXES:
        if low.startswith(prefix):
            return stripped[len(prefix):].lstrip(" ,.:;-—"), True
    return stripped, False


@owner_only
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not msg or not msg.text:
        return

    # Check if we're waiting for a correction
    if context.user_data.get("awaiting_correction"):
        corrected = msg.text.strip()
        force_text = context.user_data["awaiting_correction"]["force_text"]
        context.user_data.pop("awaiting_correction", None)
        context.user_data.pop("last_transcription", None)
        await msg.reply_text(f"✏️ תוקן: _{corrected}_", parse_mode="Markdown")
        if not force_text:
            context.user_data["reply_with_voice"] = True
        try:
            await parse_and_dispatch(update, context, corrected, payload_message=msg)
        finally:
            context.user_data.pop("reply_with_voice", None)
        return

    remaining, wants_voice = _strip_voice_prefix(msg.text)
    if wants_voice:
        tts = context.application.bot_data.get("tts")
        if not tts or not tts.enabled:
            await msg.reply_text("TTS לא מוגדר (חסר OPENAI_API_KEY). ממשיך בטקסט.")
        else:
            context.user_data["reply_with_voice"] = True
        # Nothing else to do after stripping the prefix → conversational reply
        payload_text = remaining or "אמור משהו"
        try:
            await parse_and_dispatch(update, context, payload_text, payload_message=msg)
        finally:
            context.user_data.pop("reply_with_voice", None)
        return

    await parse_and_dispatch(update, context, msg.text, payload_message=msg)


@owner_only
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not msg or not msg.voice:
        return

    transcriber = context.application.bot_data.get("transcriber")
    if not transcriber or not transcriber.enabled:
        await msg.reply_text(
            "תמלול לא מוגדר. הוסף OPENAI_API_KEY ל-.env כדי להפעיל הודעות קוליות."
        )
        return

    try:
        await context.bot.send_chat_action(chat_id=msg.chat_id, action=ChatAction.TYPING)
    except Exception:
        pass

    file = await msg.voice.get_file()
    with tempfile.NamedTemporaryFile(suffix=".oga", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        await file.download_to_drive(custom_path=tmp_path)
        # Convert oga→mp3 for gpt-4o-transcribe compatibility
        mp3_path = tmp_path.with_suffix(".mp3")
        try:
            import subprocess
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(tmp_path), "-q:a", "2", str(mp3_path)],
                capture_output=True, check=True, timeout=30,
            )
            audio_path = mp3_path
        except (FileNotFoundError, subprocess.SubprocessError):
            # ffmpeg not available — send oga as-is (works with whisper-1)
            audio_path = tmp_path
            mp3_path = None
        try:
            text = await transcriber.transcribe(audio_path, language="he")
        except Exception as e:
            logger.exception("Whisper transcription failed")
            await msg.reply_text(f"שגיאה בתמלול: {e}")
            return
        if not text:
            await msg.reply_text("לא הצלחתי לתמלל — לא חזר טקסט.")
            return
        # If the user asked for text reply, don't answer with voice
        text_lower = text.strip()
        force_text = False
        for prefix in ("תענה בטקסט", "תענה בהודעת טקסט", "תעני בטקסט", "תעני בהודעת טקסט", "כתוב לי", "כתבי לי"):
            if text_lower.startswith(prefix):
                text = text_lower[len(prefix):].strip(" ,.")
                force_text = True
                break

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ תקן", callback_data="fix_transcription")]
        ])
        transcription_msg = await msg.reply_text(
            f"📝 _{text}_",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        # Store transcription info so correction handler can use it
        context.user_data["last_transcription"] = {
            "transcription_msg_id": transcription_msg.message_id,
            "force_text": force_text,
        }
        if not force_text:
            context.user_data["reply_with_voice"] = True
        try:
            await parse_and_dispatch(update, context, text, payload_message=msg)
        finally:
            context.user_data.pop("reply_with_voice", None)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
            if mp3_path:
                mp3_path.unlink(missing_ok=True)
        except Exception:
            pass


async def fix_transcription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the '✏️ תקן' button press."""
    query = update.callback_query
    await query.answer()
    from bot.config import get_settings
    if query.from_user.id != get_settings().telegram_owner_id:
        return

    last = context.user_data.get("last_transcription")
    if not last:
        await query.edit_message_reply_markup(reply_markup=None)
        return

    # Remove the button and ask for correction
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text("מה הטקסט הנכון? ✏️")
    context.user_data["awaiting_correction"] = {
        "force_text": last.get("force_text", False),
    }


@owner_only
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Photos / documents / video / audio with optional caption."""
    msg = update.message
    if not msg:
        return

    caption = msg.caption or ""
    if not caption.strip():
        await msg.reply_text(
            "צירוף מדיה ללא תיאור — אנא שלח שוב עם הוראה כמו \"לקבוצת עבודה\" כקאפשן."
        )
        return
    await parse_and_dispatch(update, context, caption, payload_message=msg)
