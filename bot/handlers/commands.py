"""Slash command handlers: /start, /help, /id, /groups, /reminders, /contacts, /history."""
from __future__ import annotations

import logging
from datetime import datetime

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.config import get_settings
from bot.utils.auth import owner_only

logger = logging.getLogger(__name__)


HELP_TEXT = """\
*שלום! אני {bot_name}, העוזר האישי שלך.* 🤖

*מה אני יודע לעשות:*

📨 *ניתוב הודעות*
שלח לי טקסט/תמונה/קובץ/הודעה קולית — אני אזהה לאיזו קבוצה זה הולך ואשלח.
דוגמה: "תשלח לקבוצת עבודה: לבדוק חוזה"

🗂️ *ניהול קבוצות*
• /groups — רשימת קבוצות
• /addgroup — הוספת קבוצה חדשה (הוסף אותי לקבוצה ושלח כאן את הפקודה)
• "מחק קבוצה X"
• "תראה לי את קבוצת X"

⏰ *תזכורות*
• "תזכיר לי מחר ב-9 לבדוק חוזה"
• /reminders — רשימת תזכורות פתוחות
• "מחק תזכורת מספר 3"

📅 *יומן*
• "קבע פגישה מחר ב-10 עם דן ואופק"
• "מה יש לי היום ביומן?"
• /calendars — רשימת יומנים מוגדרים

👥 *אנשי קשר*
• "איש קשר דן dan@email.com"
• /contacts — רשימת אנשי קשר

📝 *סיכום חכם*
• "סכם לי את קבוצת עבודה"

📜 *לוג ומחיקה*
• /history — היסטוריית שליחות אחרונות
• "מחק את ההודעה האחרונה ששלחתי"

🆔 *פקודות שירות*
• /id — להציג את ה-Telegram ID שלך
• /help — להציג את העזרה הזו
"""


@owner_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_settings()
    await update.message.reply_text(
        f"שלום! אני {settings.bot_name}. שלח /help כדי לראות מה אני יודע לעשות."
    )


@owner_only
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_settings()
    await update.message.reply_text(
        HELP_TEXT.format(bot_name=settings.bot_name),
        parse_mode=ParseMode.MARKDOWN,
    )


@owner_only
async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Returns the user's Telegram ID."""
    user = update.effective_user
    chat = update.effective_chat
    text = (
        f"User ID: `{user.id}`\n"
        f"Username: @{user.username}\n"
        f"Chat ID: `{chat.id}`\n"
        f"Chat type: {chat.type}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
