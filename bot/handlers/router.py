"""Central NLU router — interprets free-form messages and dispatches to actions."""
from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pytz
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.config import get_settings
from bot.db import Database
from bot.services.claude_client import ClaudeClient
from bot.services.calendar_client import CalendarClient
from bot.services.telegram_user_client import TelegramUserClient
from bot.handlers.commands import HELP_TEXT

MAX_GROUPS_PER_DAY = 5
MAX_RECENT_TURNS = 5

logger = logging.getLogger(__name__)


def _match_groups_locally(text: str, groups: list[dict[str, Any]]) -> list[int]:
    """Return group IDs whose name or any alias appears as substring in text.

    Deterministic pre-LLM match — fixes inconsistent Claude fuzzy-matching of
    group names across consecutive messages.
    """
    text_low = (text or "").lower()
    if not text_low.strip():
        return []
    matches: list[tuple[int, int]] = []
    for g in groups:
        name = (g.get("name") or "").lower().strip()
        raw_aliases = g.get("aliases") or "[]"
        try:
            aliases = json.loads(raw_aliases) if isinstance(raw_aliases, str) else list(raw_aliases)
        except (ValueError, TypeError):
            aliases = []
        candidates = [c for c in [name, *[str(a).lower().strip() for a in aliases]] if c and len(c) >= 2]
        best = 0
        for cand in candidates:
            if cand in text_low:
                best = max(best, len(cand))
        if best > 0:
            matches.append((g["id"], best))
    if not matches:
        return []
    # Prefer the longest match (most specific) — avoids "אלפרד" stealing when "מגדירים את אלפרד" matches
    matches.sort(key=lambda x: -x[1])
    top_len = matches[0][1]
    return [gid for gid, ln in matches if ln == top_len]


def _summarize_intent_for_history(intent: dict[str, Any]) -> str:
    """Short textual summary of what the bot understood/replied, for future turn context."""
    action = intent.get("action", "unknown")
    if action in ("chat", "unknown"):
        return (intent.get("reply") or intent.get("reason") or "")[:200]
    parts = [f"[{action}]"]
    for key in ("group_id", "content", "text", "remind_at", "title", "start", "nickname", "email", "name", "range"):
        val = intent.get(key)
        if val not in (None, "", []):
            parts.append(f"{key}={val}")
    return " ".join(parts)[:200]


async def _smart_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    parse_mode: str | None = None,
    **kwargs,
) -> None:
    """Reply with voice if the user sent a voice message, otherwise text."""
    use_voice = bool(context.user_data.get("reply_with_voice"))
    tts = context.application.bot_data.get("tts")

    if use_voice and tts and tts.enabled:
        # Send text as well so the user can read it
        await update.effective_message.reply_text(text, parse_mode=parse_mode, **kwargs)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            out_path = Path(tmp.name)
        try:
            # Strip markdown for TTS
            clean = text.replace("*", "").replace("_", "").replace("[", "").replace("]", "")
            await tts.synthesize(clean, out_path)
            with out_path.open("rb") as f:
                await update.effective_message.reply_voice(voice=f)
        except Exception:
            logger.exception("TTS failed in smart_reply")
        finally:
            try:
                out_path.unlink(missing_ok=True)
            except Exception:
                pass
    else:
        await update.effective_message.reply_text(text, parse_mode=parse_mode, **kwargs)


def _db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.application.bot_data["db"]


def _claude(context: ContextTypes.DEFAULT_TYPE) -> ClaudeClient:
    return context.application.bot_data["claude"]


def _calendar(context: ContextTypes.DEFAULT_TYPE) -> CalendarClient:
    return context.application.bot_data["calendar"]


def _tg_user(context: ContextTypes.DEFAULT_TYPE) -> TelegramUserClient:
    return context.application.bot_data["telegram_user"]


async def parse_and_dispatch(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    payload_message: Optional[Any] = None,
) -> None:
    """Parse text via Claude and dispatch to the appropriate action.

    `payload_message` is the original message (for media forwarding) — defaults to update.message.
    """
    settings = get_settings()
    db = _db(context)
    claude = _claude(context)
    tz = pytz.timezone(settings.timezone)
    now = datetime.now(tz)

    groups = await db.list_groups()
    contacts = await db.list_contacts()
    calendars = await db.list_calendars()
    recent_events = await db.list_recent_created_events(limit=10)

    local_group_matches = _match_groups_locally(text, groups)
    recent_turns = context.user_data.get("recent_turns", [])

    intent = await claude.parse_intent(
        text=text,
        groups=groups,
        contacts=contacts,
        calendars=calendars,
        recent_events=recent_events,
        now=now,
        timezone=settings.timezone,
        local_group_matches=local_group_matches,
        recent_turns=recent_turns,
    )
    logger.info(
        "Parsed intent (local_group_matches=%s, recent_turns=%d): %s",
        local_group_matches, len(recent_turns), intent,
    )

    # For route_to_group: if local match is unique and Claude didn't resolve, apply it.
    if intent.get("action") == "route_to_group" and intent.get("group_id") is None:
        if len(local_group_matches) == 1:
            intent["group_id"] = local_group_matches[0]
            intent.pop("group_candidates", None)
            logger.info("Applied local group match as group_id=%s", intent["group_id"])

    # Save this turn into conversation history (capped)
    bot_summary = _summarize_intent_for_history(intent)
    recent_turns = recent_turns + [{"user": text, "bot": bot_summary}]
    context.user_data["recent_turns"] = recent_turns[-MAX_RECENT_TURNS:]

    action = intent.get("action", "unknown")

    handlers = {
        "chat": _action_chat,
        "route_to_group": _action_route_to_group,
        "create_reminder": _action_create_reminder,
        "list_reminders": _action_list_reminders,
        "delete_reminder": _action_delete_reminder,
        "create_event": _action_create_event,
        "update_event": _action_update_event,
        "delete_event": _action_delete_event,
        "list_events": _action_list_events,
        "summarize_group": _action_summarize_group,
        "show_history": _action_show_history,
        "delete_last_message": _action_delete_last_message,
        "list_groups": _action_list_groups,
        "add_contact": _action_add_contact,
        "list_contacts": _action_list_contacts,
        "delete_contact": _action_delete_contact,
        "create_telegram_group": _action_create_telegram_group,
        "help": _action_help,
        "unknown": _action_chat,  # treat unknown as chat fallback
    }
    handler = handlers.get(action, _action_chat)
    await handler(update, context, intent, payload_message or update.message)


# ---------- Action handlers ----------

async def _action_route_to_group(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    intent: dict[str, Any],
    payload_message: Any,
) -> None:
    db = _db(context)
    group_id = intent.get("group_id")
    candidates: list[int] = intent.get("group_candidates") or []
    content: str = intent.get("content") or ""

    if group_id is None and candidates:
        # Ask user to pick
        keyboard = []
        for gid in candidates:
            g = await db.get_group_by_id(gid)
            if g:
                keyboard.append([InlineKeyboardButton(g["name"], callback_data=f"route:{gid}")])
        # Stash content + payload references in user_data so the callback can use them
        context.user_data["pending_route"] = {
            "content": content,
            "source_chat_id": payload_message.chat_id,
            "source_message_id": payload_message.message_id,
        }
        await update.message.reply_text(
            "לאיזו קבוצה לשלוח?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if group_id is None:
        await update.message.reply_text(
            "לא הצלחתי לזהות קבוצה. אפשר לציין במפורש: \"שלח לקבוצת <שם>: <תוכן>\"."
        )
        return

    await _send_to_group(update, context, group_id, content, payload_message)


async def _send_to_group(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    group_id: int,
    content: str,
    payload_message: Any,
) -> None:
    db = _db(context)
    group = await db.get_group_by_id(group_id)
    if not group:
        await update.effective_message.reply_text("הקבוצה לא נמצאה במסד.")
        return

    bot = context.bot
    chat_id = group["chat_id"]

    sent_msg = None
    content_type = "text"
    preview = content

    # Determine media type from the original payload message
    if payload_message.photo:
        photo = payload_message.photo[-1]
        sent_msg = await bot.send_photo(
            chat_id=chat_id, photo=photo.file_id, caption=content or payload_message.caption
        )
        content_type = "photo"
        preview = content or payload_message.caption or "[תמונה]"
    elif payload_message.document:
        sent_msg = await bot.send_document(
            chat_id=chat_id,
            document=payload_message.document.file_id,
            caption=content or payload_message.caption,
        )
        content_type = "document"
        preview = content or payload_message.caption or payload_message.document.file_name or "[קובץ]"
    elif payload_message.voice:
        sent_msg = await bot.send_voice(
            chat_id=chat_id,
            voice=payload_message.voice.file_id,
            caption=content or None,
        )
        content_type = "voice"
        preview = content or "[הודעה קולית]"
    elif payload_message.audio:
        sent_msg = await bot.send_audio(
            chat_id=chat_id,
            audio=payload_message.audio.file_id,
            caption=content or None,
        )
        content_type = "audio"
        preview = content or "[שמע]"
    elif payload_message.video:
        sent_msg = await bot.send_video(
            chat_id=chat_id,
            video=payload_message.video.file_id,
            caption=content or payload_message.caption,
        )
        content_type = "video"
        preview = content or payload_message.caption or "[וידאו]"
    else:
        sent_msg = await bot.send_message(chat_id=chat_id, text=content)
        content_type = "text"
        preview = content

    await db.add_history(
        group_id=group_id,
        group_name=group["name"],
        chat_id=chat_id,
        sent_message_id=sent_msg.message_id if sent_msg else None,
        content_type=content_type,
        content_preview=(preview or "")[:300],
    )

    await _smart_reply(
        update, context,
        f"✅ נשלח לקבוצה *{group['name']}*", parse_mode=ParseMode.MARKDOWN
    )


async def route_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline-button press for ambiguous routing."""
    settings = get_settings()
    query = update.callback_query
    await query.answer()
    if query.from_user.id != settings.telegram_owner_id:
        return
    data = query.data or ""
    if not data.startswith("route:"):
        return
    try:
        group_id = int(data.split(":", 1)[1])
    except ValueError:
        return

    pending = context.user_data.get("pending_route") or {}
    content = pending.get("content", "")

    # Re-fetch original message for media
    payload_message = query.message
    src_chat = pending.get("source_chat_id")
    src_msg = pending.get("source_message_id")
    if src_chat and src_msg:
        try:
            payload_message = await context.bot.forward_message(
                chat_id=src_chat,  # forward back to self to capture (no-op fallback)
                from_chat_id=src_chat,
                message_id=src_msg,
                disable_notification=True,
            )
            # Immediately delete the no-op forward to keep chat clean
            try:
                await context.bot.delete_message(chat_id=src_chat, message_id=payload_message.message_id)
            except Exception:
                pass
        except Exception:
            payload_message = query.message

    await _send_to_group(update, context, group_id, content, payload_message)
    context.user_data.pop("pending_route", None)


async def _action_create_reminder(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    intent: dict[str, Any],
    payload_message: Any,
) -> None:
    from bot.handlers.reminders import schedule_reminder

    settings = get_settings()
    db = _db(context)
    text = intent.get("text") or ""
    remind_at_str = intent.get("remind_at")
    if not remind_at_str:
        await update.message.reply_text("לא הצלחתי להבין מתי להזכיר. נסה שוב עם זמן מפורש.")
        return
    try:
        remind_at = datetime.fromisoformat(remind_at_str)
    except ValueError:
        await update.message.reply_text(f"פורמט זמן לא תקין: {remind_at_str}")
        return
    tz = pytz.timezone(settings.timezone)
    if remind_at.tzinfo is None:
        remind_at = tz.localize(remind_at)

    rid = await db.add_reminder(text=text, remind_at=remind_at)
    schedule_reminder(context.application, rid, text, remind_at)
    await _smart_reply(
        update, context,
        f"⏰ תזכורת נקבעה ל-{remind_at.strftime('%Y-%m-%d %H:%M')}: {text}"
    )


async def _action_list_reminders(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    intent: dict[str, Any],
    payload_message: Any,
) -> None:
    db = _db(context)
    reminders = await db.list_open_reminders()
    if not reminders:
        await update.message.reply_text("אין תזכורות פתוחות.")
        return
    lines = ["*תזכורות פתוחות:*\n"]
    for r in reminders:
        when = datetime.fromisoformat(r["remind_at"]).strftime("%Y-%m-%d %H:%M")
        lines.append(f"• #{r['id']} — {when} — {r['text']}")
    await _smart_reply(update, context, "\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def _action_delete_reminder(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    intent: dict[str, Any],
    payload_message: Any,
) -> None:
    db = _db(context)
    rid = intent.get("reminder_id")
    if rid is None:
        await update.message.reply_text("ציין מספר תזכורת. /reminders להצגת הרשימה.")
        return
    ok = await db.delete_reminder(int(rid))
    await _smart_reply(update, context, "✅ נמחקה." if ok else "תזכורת לא נמצאה.")


async def _action_create_event(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    intent: dict[str, Any],
    payload_message: Any,
) -> None:
    settings = get_settings()
    db = _db(context)
    cal = _calendar(context)
    if not cal.configured:
        await update.message.reply_text(
            "Google Calendar לא מוגדר. ראה docs/setup.md."
        )
        return

    title = intent.get("title") or "אירוע ללא כותרת"
    start_str = intent.get("start")
    end_str = intent.get("end")
    if not start_str:
        await update.message.reply_text("לא הצלחתי להבין מתי האירוע. נסה שוב עם זמן מפורש.")
        return
    tz = pytz.timezone(settings.timezone)
    try:
        start = datetime.fromisoformat(start_str)
        if start.tzinfo is None:
            start = tz.localize(start)
    except ValueError:
        await update.message.reply_text(f"פורמט זמן התחלה לא תקין: {start_str}")
        return
    if end_str:
        try:
            end = datetime.fromisoformat(end_str)
            if end.tzinfo is None:
                end = tz.localize(end)
        except ValueError:
            end = start + timedelta(hours=1)
    else:
        end = start + timedelta(hours=1)

    # Resolve calendar
    calendar_nickname = intent.get("calendar_nickname")
    if calendar_nickname:
        cal_row = await db.get_calendar(calendar_nickname)
        calendar_id = cal_row["google_id"] if cal_row else settings.google_default_calendar
    else:
        default = await db.get_default_calendar()
        calendar_id = default["google_id"] if default else settings.google_default_calendar

    # Resolve attendees
    attendee_emails: list[str] = []
    for nick in intent.get("attendee_nicknames") or []:
        c = await db.get_contact(nick)
        if c:
            attendee_emails.append(c["email"])
        else:
            await update.message.reply_text(f"⚠️ איש קשר \"{nick}\" לא נמצא — דילגתי עליו.")

    try:
        event = cal.create_event(
            calendar_id=calendar_id,
            title=title,
            start=start,
            end=end,
            description=intent.get("description"),
            attendee_emails=attendee_emails or None,
            reminder_minutes_before=60,
            timezone=settings.timezone,
        )
    except Exception as e:
        logger.exception("Failed to create calendar event")
        await update.message.reply_text(f"שגיאה ביצירת האירוע: {e}")
        return

    # Save event for future updates
    await db.save_created_event(
        google_event_id=event["id"],
        calendar_id=calendar_id,
        title=title,
        start_at=start.isoformat(),
        end_at=end.isoformat(),
    )

    link = event.get("htmlLink", "")
    when = start.strftime("%Y-%m-%d %H:%M")
    msg = f"📅 נקבע: *{title}* ב-{when}"
    if attendee_emails:
        msg += f"\nמוזמנים: {', '.join(attendee_emails)}"
    if link:
        msg += f"\n[פתח ביומן]({link})"
    await _smart_reply(update, context, msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


async def _action_update_event(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    intent: dict[str, Any],
    payload_message: Any,
) -> None:
    settings = get_settings()
    db = _db(context)
    cal = _calendar(context)
    if not cal.configured:
        await update.message.reply_text("Google Calendar לא מוגדר.")
        return

    event_db_id = intent.get("event_id")
    tz = pytz.timezone(settings.timezone)

    # Find the event — by ID or by matching recent events
    event_row = None
    if event_db_id:
        event_row = await db.get_created_event(int(event_db_id))

    if not event_row:
        # Try to match by title/keyword from recent events
        search = (intent.get("event_query") or intent.get("title") or "").strip().lower()
        recent = await db.list_recent_created_events(limit=20)
        if not recent:
            await update.message.reply_text("אין אירועים שנוצרו לאחרונה שאפשר לתקן.")
            return
        if search:
            for ev in recent:
                if search in ev["title"].lower():
                    event_row = ev
                    break
        if not event_row:
            # Default to the most recent event
            event_row = recent[0]

    # Build update fields
    new_title = intent.get("new_title")
    new_start_str = intent.get("new_start")
    new_end_str = intent.get("new_end")
    new_description = intent.get("new_description")

    new_start = None
    new_end = None
    if new_start_str:
        try:
            new_start = datetime.fromisoformat(new_start_str)
            if new_start.tzinfo is None:
                new_start = tz.localize(new_start)
        except ValueError:
            pass
    if new_end_str:
        try:
            new_end = datetime.fromisoformat(new_end_str)
            if new_end.tzinfo is None:
                new_end = tz.localize(new_end)
        except ValueError:
            pass

    # Resolve attendees
    attendee_emails = None
    if intent.get("attendee_nicknames") is not None:
        attendee_emails = []
        for nick in intent["attendee_nicknames"]:
            c = await db.get_contact(nick)
            if c:
                attendee_emails.append(c["email"])

    try:
        updated = cal.update_event(
            calendar_id=event_row["calendar_id"],
            event_id=event_row["google_event_id"],
            title=new_title,
            start=new_start,
            end=new_end,
            description=new_description,
            attendee_emails=attendee_emails,
            timezone=settings.timezone,
        )
    except Exception as e:
        logger.exception("Failed to update calendar event")
        await update.message.reply_text(f"שגיאה בעדכון האירוע: {e}")
        return

    final_title = updated.get("summary", event_row["title"])
    await _smart_reply(
        update, context,
        f"✅ האירוע *{final_title}* עודכן בהצלחה!",
        parse_mode=ParseMode.MARKDOWN,
    )


async def _action_delete_event(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    intent: dict[str, Any],
    payload_message: Any,
) -> None:
    settings = get_settings()
    db = _db(context)
    cal = _calendar(context)
    if not cal.configured:
        await update.message.reply_text("Google Calendar לא מוגדר.")
        return

    event_db_id = intent.get("event_id")
    event_row = None
    if event_db_id:
        event_row = await db.get_created_event(int(event_db_id))

    if not event_row:
        search = (intent.get("event_query") or intent.get("title") or "").strip().lower()
        recent = await db.list_recent_created_events(limit=20)
        if not recent:
            await update.message.reply_text("אין אירועים למחוק.")
            return
        if search:
            for ev in recent:
                if search in ev["title"].lower():
                    event_row = ev
                    break
        if not event_row:
            event_row = recent[0]

    try:
        cal.delete_event(
            calendar_id=event_row["calendar_id"],
            event_id=event_row["google_event_id"],
        )
    except Exception as e:
        logger.exception("Failed to delete calendar event")
        await update.message.reply_text(f"שגיאה במחיקת האירוע: {e}")
        return

    await _smart_reply(
        update, context,
        f"✅ האירוע *{event_row['title']}* נמחק מהיומן.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def _action_list_events(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    intent: dict[str, Any],
    payload_message: Any,
) -> None:
    settings = get_settings()
    db = _db(context)
    cal = _calendar(context)

    range_ = intent.get("range", "today")
    tz = pytz.timezone(settings.timezone)
    now = datetime.now(tz)
    if range_ == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        label = "היום"
    elif range_ == "tomorrow":
        start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        label = "מחר"
    else:  # week
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
        label = "השבוע"

    items: list[tuple[datetime, str]] = []

    # Calendar events (if configured)
    if cal.configured:
        calendar_nickname = intent.get("calendar_nickname")
        if calendar_nickname:
            cal_row = await db.get_calendar(calendar_nickname)
            calendar_id = cal_row["google_id"] if cal_row else settings.google_default_calendar
        else:
            default = await db.get_default_calendar()
            calendar_id = default["google_id"] if default else settings.google_default_calendar
        try:
            events = cal.list_events(calendar_id=calendar_id, time_min=start, time_max=end)
            for ev in events:
                s = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")
                title = ev.get("summary", "(ללא כותרת)")
                try:
                    dt = datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(tz)
                except Exception:
                    continue
                items.append((dt, f"📅 {dt.strftime('%d/%m %H:%M')} — {title}"))
        except Exception as e:
            logger.exception("Failed to list calendar events")
            await update.message.reply_text(f"שגיאה בקריאת היומן: {e}")

    # Reminders in the same range — always include (the bot owns these)
    reminders = await db.list_open_reminders()
    for r in reminders:
        try:
            rdt = datetime.fromisoformat(r["remind_at"])
            if rdt.tzinfo is None:
                rdt = tz.localize(rdt)
            else:
                rdt = rdt.astimezone(tz)
        except Exception:
            continue
        if start <= rdt < end:
            items.append((rdt, f"⏰ {rdt.strftime('%d/%m %H:%M')} — {r['text']}"))

    if not items:
        msg = f"אין לך כלום {label}."
        if not cal.configured:
            msg += " (Google Calendar לא מוגדר — רואה רק תזכורות שיצרנו פה)"
        await _smart_reply(update, context, msg)
        return

    items.sort(key=lambda x: x[0])
    lines = [f"*{label}:*"] + [ln for _, ln in items]
    if not cal.configured:
        lines.append("_רק תזכורות — Google Calendar לא מוגדר._")
    await _smart_reply(update, context, "\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def _action_summarize_group(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    intent: dict[str, Any],
    payload_message: Any,
) -> None:
    db = _db(context)
    claude = _claude(context)
    group_id = intent.get("group_id")
    if not group_id:
        await update.message.reply_text("איזו קבוצה לסכם?")
        return
    group = await db.get_group_by_id(int(group_id))
    if not group:
        await update.message.reply_text("הקבוצה לא נמצאה.")
        return

    # Try to fetch recent messages from the group via the bot API.
    # NOTE: Bot API can only see messages it received after being added.
    # As a fallback, we summarize the last items from our own send-history for that group.
    history_rows = await db.get_recent_history(limit=200)
    relevant = [
        f"{h['sent_at']}: {h['content_preview']}"
        for h in history_rows
        if h["group_id"] == group["id"]
    ][:50]
    summary = await claude.summarize_messages(group["name"], relevant)
    await _smart_reply(update, context, f"*סיכום — {group['name']}*\n\n{summary}", parse_mode=ParseMode.MARKDOWN)


async def _action_show_history(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    intent: dict[str, Any],
    payload_message: Any,
) -> None:
    db = _db(context)
    limit = int(intent.get("limit") or 10)
    rows = await db.get_recent_history(limit=limit)
    if not rows:
        await update.message.reply_text("אין היסטוריה.")
        return
    lines = ["*היסטוריית שליחות:*\n"]
    for r in rows:
        ts = r["sent_at"][:16].replace("T", " ")
        lines.append(f"• {ts} → *{r['group_name']}* ({r['content_type']}): {r['content_preview'][:80]}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def _action_delete_last_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    intent: dict[str, Any],
    payload_message: Any,
) -> None:
    db = _db(context)
    last = await db.get_last_history()
    if not last or not last.get("sent_message_id"):
        await update.message.reply_text("אין הודעה אחרונה למחוק.")
        return
    try:
        await context.bot.delete_message(
            chat_id=last["chat_id"], message_id=last["sent_message_id"]
        )
        await db.delete_history_entry(last["id"])
        await _smart_reply(
            update, context,
            f"✅ ההודעה האחרונה נמחקה מקבוצת *{last['group_name']}*",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        await update.message.reply_text(f"לא הצלחתי למחוק: {e}")


async def _action_list_groups(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    intent: dict[str, Any],
    payload_message: Any,
) -> None:
    from bot.handlers.groups import cmd_groups
    await cmd_groups(update, context)


async def _action_add_contact(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    intent: dict[str, Any],
    payload_message: Any,
) -> None:
    db = _db(context)
    nickname = intent.get("nickname")
    email = intent.get("email")
    full_name = intent.get("full_name")
    if not nickname or not email:
        await update.message.reply_text("חסרים פרטים. שימוש: \"איש קשר <כינוי> <email>\"")
        return
    await db.add_contact(nickname=nickname, email=email, full_name=full_name)
    await _smart_reply(update, context, f"✅ נוסף איש קשר: {nickname} ({email})")


async def _action_list_contacts(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    intent: dict[str, Any],
    payload_message: Any,
) -> None:
    db = _db(context)
    rows = await db.list_contacts()
    if not rows:
        await update.message.reply_text("אין אנשי קשר.")
        return
    lines = ["*אנשי קשר:*\n"]
    for c in rows:
        full = f" ({c['full_name']})" if c.get("full_name") else ""
        lines.append(f"• *{c['nickname']}* — {c['email']}{full}")
    await _smart_reply(update, context, "\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def _action_delete_contact(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    intent: dict[str, Any],
    payload_message: Any,
) -> None:
    db = _db(context)
    nickname = intent.get("nickname")
    if not nickname:
        await update.message.reply_text("ציין כינוי איש קשר.")
        return
    ok = await db.delete_contact(nickname)
    await _smart_reply(update, context, "✅ נמחק." if ok else "לא נמצא.")


async def _action_help(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    intent: dict[str, Any],
    payload_message: Any,
) -> None:
    settings = get_settings()
    await update.message.reply_text(
        HELP_TEXT.format(bot_name=settings.bot_name),
        parse_mode=ParseMode.MARKDOWN,
    )


async def _action_create_telegram_group(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    intent: dict[str, Any],
    payload_message: Any,
) -> None:
    """Stage 1: ask for confirmation. Actual creation happens in the callback."""
    db = _db(context)
    name = (intent.get("name") or "").strip()
    description = (intent.get("description") or "").strip() or None

    if not name:
        await update.message.reply_text("איזה שם תרצה לקבוצה?")
        return

    tg_user = _tg_user(context)
    if not tg_user.configured:
        await update.message.reply_text(
            "כדי ליצור קבוצה אני צריך גם פרטי Userbot (TELEGRAM_API_ID/HASH ב-.env). "
            "ראה docs/setup.md סעיף 6."
        )
        return

    # Rate limit
    count = await db.count_groups_created_last_24h()
    if count >= MAX_GROUPS_PER_DAY:
        await update.message.reply_text(
            f"⚠️ הגעת למקסימום של {MAX_GROUPS_PER_DAY} קבוצות חדשות ב-24 שעות. "
            f"זה מנגנון בטיחות. נסה שוב מחר."
        )
        return

    # Stash pending request in user_data — confirmation callback uses it
    pending_id = str(payload_message.message_id)
    context.user_data.setdefault("pending_group_creations", {})[pending_id] = {
        "name": name,
        "description": description,
    }

    desc_line = f"\nתיאור: _{description}_" if description else ""
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ צור", callback_data=f"creategroup:ok:{pending_id}"),
            InlineKeyboardButton("❌ ביטול", callback_data=f"creategroup:no:{pending_id}"),
        ]
    ])
    await update.message.reply_text(
        f"לפתוח קבוצת טלגרם חדשה ופרטית בשם:\n*{name}*{desc_line}\n\n"
        f"רק שנינו נהיה בקבוצה. ({count}/{MAX_GROUPS_PER_DAY} נוצרו ב-24 שעות האחרונות)",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )


async def create_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle confirm/cancel buttons for group creation."""
    settings = get_settings()
    query = update.callback_query
    await query.answer()
    if query.from_user.id != settings.telegram_owner_id:
        return

    data = query.data or ""
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "creategroup":
        return
    decision, pending_id = parts[1], parts[2]

    pending_map = context.user_data.get("pending_group_creations") or {}
    pending = pending_map.pop(pending_id, None)
    if not pending:
        await query.edit_message_text("הבקשה הזו לא בתוקף יותר.")
        return

    if decision == "no":
        await query.edit_message_text("בוטל. לא נוצרה קבוצה.")
        return

    # decision == "ok" → create the group
    db = _db(context)
    tg_user = _tg_user(context)
    bot_username = context.application.bot_data.get("bot_username")
    if not bot_username:
        me = await context.bot.get_me()
        bot_username = me.username
        context.application.bot_data["bot_username"] = bot_username

    # Re-check rate limit at the moment of execution
    count = await db.count_groups_created_last_24h()
    if count >= MAX_GROUPS_PER_DAY:
        await query.edit_message_text(
            f"⚠️ הגעת למקסימום של {MAX_GROUPS_PER_DAY} קבוצות חדשות ב-24 שעות."
        )
        return

    name = pending["name"]
    description = pending.get("description")
    await query.edit_message_text(f"יוצר קבוצה *{name}*…", parse_mode=ParseMode.MARKDOWN)

    try:
        chat_id, title = await tg_user.create_group_with_bot(name=name, bot_username=bot_username)
    except Exception as e:
        logger.exception("Failed to create Telegram group")
        await query.edit_message_text(f"❌ שגיאה ביצירת הקבוצה: {e}")
        return

    try:
        gid = await db.add_group(
            chat_id=chat_id,
            name=name,
            description=description,
        )
    except Exception as e:
        logger.exception("Group created in Telegram but failed to register in DB")
        await query.edit_message_text(
            f"⚠️ הקבוצה נוצרה בטלגרם אבל לא נרשמה ב-DB: {e}\n"
            f"chat_id={chat_id}. תוכל להוסיף ידנית עם /addgroup בתוך הקבוצה."
        )
        return

    await query.edit_message_text(
        f"✅ הקבוצה *{title}* נוצרה ונרשמה (id={gid}).\n"
        f"מעכשיו תוכל לכתוב לי \"שלח ל{name}: ...\" ואני אנתב את ההודעה לשם.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def _action_chat(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    intent: dict[str, Any],
    payload_message: Any,
) -> None:
    """Conversational reply — Claude drafted the text. Speak it back if input was voice."""
    reply = intent.get("reply") or intent.get("reason") or "אני פה. מה תרצה?"
    use_voice = bool(context.user_data.get("reply_with_voice"))
    tts = context.application.bot_data.get("tts")

    if use_voice and tts and tts.enabled:
        import tempfile
        from pathlib import Path
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            out_path = Path(tmp.name)
        try:
            await tts.synthesize(reply, out_path)
            with out_path.open("rb") as f:
                await update.message.reply_voice(voice=f)
        except Exception:
            logger.exception("TTS failed; falling back to text")
            await update.message.reply_text(reply)
        finally:
            try:
                out_path.unlink(missing_ok=True)
            except Exception:
                pass
    else:
        await update.message.reply_text(reply)
