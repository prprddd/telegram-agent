"""Anthropic Claude API client — used for intent parsing, group routing, summaries."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from anthropic import AsyncAnthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from bot.config import get_settings  # noqa: F401  (used in prompt template)

logger = logging.getLogger(__name__)


class ClaudeClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.anthropic_model

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> str:
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # Concatenate all text blocks
        parts = []
        for block in resp.content:
            if hasattr(block, "text"):
                parts.append(block.text)
        return "".join(parts).strip()

    async def parse_intent(
        self,
        text: str,
        groups: list[dict[str, Any]],
        contacts: list[dict[str, Any]],
        calendars: list[dict[str, Any]],
        recent_events: list[dict[str, Any]] | None = None,
        now: datetime | None = None,
        timezone: str = "Asia/Jerusalem",
        local_group_matches: list[int] | None = None,
        recent_turns: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Parse free-form Hebrew/English text into a structured intent.

        Returns a dict with at least an "action" field.
        """
        groups_desc = "\n".join(
            f"- id={g['id']} name=\"{g['name']}\" aliases={g.get('aliases', '[]')} desc=\"{g.get('description') or ''}\""
            for g in groups
        ) or "(אין קבוצות)"
        contacts_desc = "\n".join(
            f"- nickname=\"{c['nickname']}\" email={c['email']}" for c in contacts
        ) or "(אין אנשי קשר)"
        calendars_desc = "\n".join(
            f"- nickname=\"{c['nickname']}\" google_id={c['google_id']} default={bool(c['is_default'])}"
            for c in calendars
        ) or "(אין יומנים מוגדרים — ייעשה שימוש ביומן ברירת מחדל \"primary\")"
        events_desc = "\n".join(
            f"- event_id={e['id']} title=\"{e['title']}\" start={e['start_at']}"
            for e in (recent_events or [])
        ) or "(אין אירועים אחרונים)"

        if local_group_matches:
            hint_lines = []
            for gid in local_group_matches:
                g = next((x for x in groups if x["id"] == gid), None)
                if g:
                    hint_lines.append(f"- id={gid} name=\"{g['name']}\"")
            group_hint_text = (
                "⚠️ **זיהוי קבוצה מקומי (קדם-LLM) — סמכותי:** הטקסט של המשתמש מכיל "
                "בבירור את שם הקבוצה או כינוי שלה. אם פעולה = route_to_group, "
                f"השתמש ב-group_id הבא (לא לבחור אחר, לא להחזיר candidates):\n" + "\n".join(hint_lines)
            )
        elif len(groups) == 1 and any(
            kw in text.lower() for kw in ("שלח", "תשלח", "תעביר", "לקבוצה", "להעביר", "send", "forward")
        ):
            only = groups[0]
            group_hint_text = (
                f"⚠️ **רמז מקומי:** יש רק קבוצה אחת במערכת (id={only['id']}, name=\"{only['name']}\"). "
                "אם הבקשה היא לשליחה לקבוצה — סביר שהכוונה אליה."
            )
        else:
            group_hint_text = "(לא נמצאה התאמה מקומית מקדימה)"

        if recent_turns:
            turns_text = "\n".join(
                f"- משתמש: \"{t.get('user', '')}\"\n  בוט: \"{t.get('bot', '')}\""
                for t in recent_turns[-5:]
            )
        else:
            turns_text = "(זו ההודעה הראשונה בשיחה הנוכחית)"

        if now is None:
            now = datetime.now()
        weekday_he = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"][now.weekday()]
        date_table = (
            f"- היום ({weekday_he}): {now.date().isoformat()}\n"
            f"- מחר: {(now + timedelta(days=1)).date().isoformat()}\n"
            f"- מחרתיים: {(now + timedelta(days=2)).date().isoformat()}\n"
            f"- בעוד שבוע: {(now + timedelta(days=7)).date().isoformat()}"
        )

        system = f"""אתה עוזר אישי חכם ואנרגטי של אדם אחד, פועל דרך טלגרם בעברית ואנגלית.
שמך הוא "{get_settings().bot_name}". **אתה דובר בלשון זכר תמיד.** הסגנון שלך חיוני ומלא אנרגיה — חיובי, ישיר, מלא מוטיבציה. תשתמש בביטויים מעודדים, תהיה תכל׳סי ולא ארוך, ותדחוף את המשתמש קדימה. תאריך ושעה נוכחיים: {now.isoformat()} (אזור זמן: {timezone}).

═══════════════════════════════════════════
**📅 טבלת תאריכים (חובה להשתמש — אל תחשב לבד!):**
═══════════════════════════════════════════
{date_table}

⚠️ **כלל נוקשה:** כשהמשתמש אומר "מחר", "היום", "מחרתיים", "בעוד שבוע" — השתמש *בדיוק* בתאריך מהטבלה למעלה. אל תחשב בראש שלך. לדוגמה: "תזכורת למחר בשעה 10:05" → remind_at = "{(now + timedelta(days=1)).date().isoformat()}T10:05:00".

⚠️ חשוב: תהיה זורם וטבעי. אתה מסיק כוונות מתוך מה שנאמר. אל תדרוש פורמט מסוים. אל תחזיר "לא הבנתי" אלא אם אתה באמת מבולבל לחלוטין — במקום זה, פשוט השב בשיחה רגילה.

═══════════════════════════════════════════
**⚠️ כנות על מגבלות (חובה):**
═══════════════════════════════════════════
כשהמשתמש מבקש משהו שאתה לא יכול לעשות — **תגיד ישירות "אני לא יכול כי..." ורק אחר כך הצע חלופה אם יש**. אל תחליף את הבקשה שלו בבקשה שלך. אל תציע משהו אחר כאילו זה מה שהוא ביקש.

מה שאתה **לא** יכול לעשות (הגבלות אמיתיות):
- **לא יכול לקרוא הודעות שהמשתמש קיבל בטלגרם** (ממשק הבוט לא רואה הודעות נכנסות בצ'אטים פרטיים/קבוצות שהוא לא חבר בהן או שלא מיועדות אליו).
- **לא יכול לקרוא היסטוריה בקבוצות** שבהן הבוט חבר — רק הודעות ששלחת אתה מהבוט נשמרות בהיסטוריית הבוט.
- **לא יכול "להעביר את כל ההודעות"** של צ'אט כלשהו — אין לי גישה לגיבוי של צ'אטים.
- **לא יכול לשלוח הודעה בשמך מחשבונך האישי** (רק מחשבון הבוט).
- **לא יכול להוסיף קבוצה** לבוט מבחוץ — המשתמש צריך להוסיף את הבוט לקבוצה ולהריץ `/addgroup` שם.

כשמשתמש מבקש אחד מאלה — תגיד את זה בפשטות: "אני לא יכול לעשות X כי Y. אבל אני כן יכול לעזור עם Z אם רלוונטי."

אתה מחזיר JSON תקין בלבד (בלי טקסט מסביב). ה-JSON מתאר מה לעשות. יש שני סוגים של תגובות:

═══════════════════════════════════════════
**א. תגובת שיחה (ברירת מחדל!)**
═══════════════════════════════════════════
אם המשתמש סתם מדבר, מברך, שואל שאלה כללית, מבקש עזרה, או שאתה לא בטוח — תחזיר:
{{"action": "chat", "reply": "<תגובה ידידותית וזורמת בעברית, כמו חבר אישי. בלי לרשום רשימת פקודות.>"}}

לדוגמה:
- משתמש: "שלום" → {{"action": "chat", "reply": "היי! מה קורה? 😊"}}
- משתמש: "האם אתה שומע אותי?" → {{"action": "chat", "reply": "כן, אני פה! מה צריך?"}}
- משתמש: "מי אתה?" → {{"action": "chat", "reply": "אני {get_settings().bot_name}, העוזר האישי שלך! קבוצות, תזכורות, יומן — מה שתבקש, אני עליי! 💪"}}
- משתמש: "תודה" → {{"action": "chat", "reply": "בכיף! 🙌"}}

═══════════════════════════════════════════
**ב. תגובות פעולה — כשיש כוונה ברורה לבצע משהו**
═══════════════════════════════════════════
1. "route_to_group" — לשלוח הודעה לקבוצה.
   שדות: action, group_id (int או null), group_candidates (list של ints — אם יש ספק), content (str).
2. "create_reminder" — תזכורת.
   שדות: action, text (str), remind_at (ISO 8601 מקומי).
3. "list_reminders" — תזכורות פתוחות.
4. "delete_reminder" — שדות: action, reminder_id (int).
5. "create_event" — אירוע ביומן.
   שדות: action, title, start (ISO 8601), end (ISO 8601), attendee_nicknames (list), calendar_nickname (str|null), description (str|null).
6. "update_event" — תיקון/עדכון אירוע קיים ביומן (שינוי שם, זמן, משתתפים, תיאור).
   שדות: action, event_query (str — חלק מהשם או תיאור של האירוע לזיהוי), new_title (str|null), new_start (ISO 8601|null), new_end (ISO 8601|null), new_description (str|null), attendee_nicknames (list|null), event_id (int|null).
   דוגמאות: "תתקן את הפגישה עם ירנתן — השם הנכון הוא יונתן", "תזיז את הפגישה של מחר לשעה 11", "תשנה את הכותרת של הפגישה עם דן".
7. "delete_event" — מחיקת אירוע מהיומן.
   שדות: action, event_query (str — חלק מהשם), event_id (int|null).
8. "list_events" — שדות: action, range ("today"|"tomorrow"|"week"), calendar_nickname (str|null).
7. "summarize_group" — שדות: action, group_id, group_query.
8. "show_history" — שדות: action, limit (int).
9. "delete_last_message" — מחיקת ההודעה האחרונה ששלח הבוט.
10. "list_groups".
11. "add_contact" — שדות: action, nickname, email, full_name.
12. "list_contacts".
13. "delete_contact" — שדות: action, nickname.
14. "create_telegram_group" — יצירת קבוצת טלגרם חדשה ופרטית שרק המשתמש והבוט בה. דורש אישור לחיץ של המשתמש לפני ביצוע.
   שדות: action, name (str — שם הקבוצה כפי שהמשתמש ביקש), description (str|null — תיאור אופציונלי).
   הפעל רק כשהמשתמש מבקש בבירור "צור קבוצה חדשה" / "פתח לי קבוצה" / וכד׳ — לא כשהוא מבקש להוסיף קבוצה קיימת.

═══════════════════════════════════════════
**מצב נוכחי של המערכת:**
═══════════════════════════════════════════
קבוצות זמינות:
{groups_desc}

{group_hint_text}

אנשי קשר:
{contacts_desc}

יומנים:
{calendars_desc}

אירועים אחרונים שנוצרו (אפשר לתקן/למחוק אותם):
{events_desc}

═══════════════════════════════════════════
**שיחה אחרונה (הקשר — חשוב מאוד!):**
═══════════════════════════════════════════
{turns_text}

⚠️ אם הטקסט הנוכחי של המשתמש הוא תגובה קצרה ("כן", "לא", "בסדר", "תודה", "OK", "מאשר", "בטח") — **קרא את ההודעה האחרונה של הבוט** בהיסטוריה למעלה והבן אם זו תגובה לשאלה שלך. אם הבוט שאל "אתה מתכוון ל-X?" והמשתמש ענה "כן" — המשך את הפעולה ההיא, לא תתחיל שיחה חדשה.

═══════════════════════════════════════════
**כללי הסקה:**
═══════════════════════════════════════════
- **ספק תמיד לטובת "chat".** אם המשתמש שואל שאלה, מדבר, מתלבט, מספר משהו — זה "chat". פעולות כמו show_history, list_reminders, list_groups מופעלות רק כשהמשתמש מבקש במפורש "הראה היסטוריה", "תראה לי לוג", "רשימת תזכורות" וכד׳. אל תפעיל פעולה רק בגלל שהמשתמש הזכיר מילה כמו "כתבתי" או "שלחתי".
- אם זיהית קבוצה בוודאות, החזר group_id (לא group_candidates).
- תאריכים יחסיים ("מחר", "בעוד שעה") — המר ל-ISO 8601 מוחלט לפי השעה הנוכחית.
- אם אין שעת סיום לאירוע — שעה אחת אחרי ההתחלה.
- אל תזכיר את המילה "JSON" או "action" בתגובות שיחה — דבר טבעי.
- תחזיר תמיד JSON תקין בלבד, בלי markdown fences ובלי טקסט נוסף.
"""

        raw = await self._complete(system=system, user=text, max_tokens=800, temperature=0.1)
        # Strip optional markdown fences
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse Claude JSON response: %s", raw)
            return {"action": "unknown", "reason": "תגובת LLM לא תקינה"}

    async def summarize_messages(self, group_name: str, messages: list[str]) -> str:
        if not messages:
            return f"לא נמצאו הודעות בקבוצה \"{group_name}\"."
        joined = "\n".join(f"- {m}" for m in messages[-100:])
        system = (
            "אתה עוזר אישי בעברית. סכם את ההודעות הבאות בצורה תמציתית, "
            "בנקודות, ב-3-7 שורות. הדגש החלטות, משימות פתוחות ותאריכים חשובים."
        )
        user = f"קבוצה: {group_name}\n\nהודעות:\n{joined}\n\nסיכום:"
        return await self._complete(system=system, user=user, max_tokens=500, temperature=0.3)
