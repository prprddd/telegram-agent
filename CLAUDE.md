<div dir="rtl" lang="he">

# הוראות לקלוד — פרויקט telegram-agent

## מה הפרויקט

סוכן טלגרם אישי (single-user) עבור dsema. ארכיטקטורה כפולה:
- **Bot API** — ניתוב הודעות לקבוצות, תזכורות, Google Calendar, תמלול קולי, ספר אנשי קשר
- **Userbot (Telethon)** — תהליך נפרד, סריקה יומית של צ׳אטים לתיקיית "שאר הצ׳אטים"

**משתמש יחיד.** כל ההנדלרים מוגנים ב-`@owner_only` ומשווים ל-`settings.telegram_owner_id`.

**שפה:** עברית (עם תמיכה באנגלית). כל מסמכי הפרויקט בעברית עטופים ב-`<div dir="rtl" lang="he">`. גם הודעות למשתמש.

**מפרט מלא:** [docs/spec.md](docs/spec.md) — קרא שם לפני החלטות ארכיטקטוניות.
**הגדרה מהתחלה:** [docs/setup.md](docs/setup.md) — המדריך למשתמש.

---

## הנחיות תקשורת עם המשתמש

- **עברית פשוטה, בלי ז׳רגון טכני.** המשתמש לא מפתח. אל תדבר על `config.py`, `pydantic`, `async` — דבר על "הגדרות", "מה הבוט יודע לעשות". אם חייבים מונח טכני, הסבר אותו.
- **אל תציג לו בחירות ארכיטקטוניות** כמו אם לכתוב רכיב אחד או שניים. תחליט לבד, תבנה, ואם יש דיוק ששובר התנהגות — תציג בצורה פשוטה.
- **אנלוגיות טובות** (רכב/מנוע, בית/חדרים) עובדות טוב איתו.
- אם הוא אומר "לא הבנתי" — זה שלך. תעצור, תפשט, ותסביר מחדש בלי קוד.

---

## מצב נוכחי של הקוד (נכון ל-2026-04-10)

### ✅ קיים

**מסמכים:** `README.md`, `docs/spec.md`, `docs/setup.md` — כולם בעברית מלאה.

**קונפיגורציה:** `.env` מלא עם מפתחות אמיתיים (Telegram Bot Token, Owner ID 1707367947, Anthropic, OpenAI). `data/google_credentials.json` קיים. Userbot (API ID/Hash) **ריק עדיין**.

**תשתית פרויקט:** `requirements.txt`, `Procfile`, `railway.toml`, `runtime.txt`, `.gitignore`, `.venv/` מותקן.

**קוד שכתוב ויציב:**
- `bot/utils/auth.py` — דקורטור `@owner_only`
- `bot/utils/logging_setup.py` — `setup_logging(level)`
- `bot/services/transcriber.py` — `Transcriber` class (OpenAI Whisper async)
- `bot/services/calendar_client.py` — `CalendarClient` class (Google Calendar v3, OAuth desktop flow)
- `bot/handlers/commands.py` — `cmd_start`, `cmd_help`, `cmd_id`
- `bot/handlers/groups.py` — `cmd_groups`, `cmd_addgroup`, `cmd_removegroup`
- `bot/handlers/reminders.py` — `schedule_reminder`, `restore_reminders` (משתמש ב-PTB JobQueue)
- `userbot/main.py` — תהליך עצמאי, Telethon, סריקה יומית לפי `USERBOT_SCAN_TIME`

### ❌ חסר — "המנוע" של הבוט

**שלושת הקבצים האלה הם bottleneck — בלעדיהם שום דבר לא רץ:**

1. **`bot/config.py`** — חייב לחשוף `get_settings()` שמחזיר אובייקט pydantic-settings עם השדות הבאים (מוגדר מהקוד הקיים):

   ```
   telegram_bot_token: str
   telegram_owner_id: int
   anthropic_api_key: str
   anthropic_model: str
   openai_api_key: str | None
   whisper_model: str
   tts_model: str
   tts_voice: str
   google_credentials_file: Path
   google_token_file: Path
   google_default_calendar: str
   telegram_api_id: int | None
   telegram_api_hash: str | None
   telethon_session_name: str
   userbot_other_folder: str
   userbot_scan_time: str
   timezone: str
   database_path: Path
   log_level: str
   bot_name: str
   ```

   `get_settings()` חייב להיות cached (LRU או lazy) — נקרא בהרבה מקומות.

2. **`bot/db.py`** — `Database` class async (מבוסס `aiosqlite`). חייב לחשוף:

   ```
   async init()                          # יוצר טבלאות
   async list_groups() -> list[dict]     # id, name, description, chat_id
   async add_group(chat_id, name, description) -> int
   async remove_group(id_or_name) -> bool
   async list_open_reminders() -> list[dict]  # id, text, remind_at
   async mark_reminder_fired(id)
   ```

   טבלאות מינימליות: `groups`, `reminders`, `history` (לוג שליחות), `contacts` (מיפוי כינוי→מייל).

3. **`bot/main.py`** — נקודת כניסה (`python -m bot.main`). צריך:
   - לקרוא `setup_logging`
   - ליצור `Database`, לקרוא `db.init()`, לשמור ב-`application.bot_data["db"]`
   - לרשום את ההנדלרים מ-`commands.py` ו-`groups.py`
   - לקרוא `restore_reminders(app)` ב-startup
   - `Application.run_polling()`

### הערות ארכיטקטוניות

- **כל הקוד הקיים מייבא `from bot.config import get_settings`** ו-`from bot.db import Database`. האינטרפייס מוגדר בפועל — שמור עליו.
- **הבוט ה-"חכם" (LLM router)** — ניתוב בשפה חופשית, חילוץ תזכורות, יצירת אירועי יומן — **עדיין לא נבנה.** זו הפאזה השנייה. הפאזה הראשונה היא בוט בסיסי שעובד עם פקודות בלבד.
- **הנחת ברירת מחדל למודל Claude:** `claude-sonnet-4-6` (מה שמוגדר ב-`.env`). אם לא זמין — נפל חזרה ל-`claude-sonnet-4-5`.

---

## מה עשינו בסשן של 2026-04-10

המשתמש ציין שסשן קודם "נעלם". הסשן הנוכחי היה בעיקר **מיפוי מצב** אחרי איבוד הקונטקסט:

1. אימתתי שהקוד שלם — שום דבר לא נמחק.
2. זיהיתי את שלושת הקבצים החסרים (`config.py`, `db.py`, `main.py`).
3. חילצתי את האינטרפייסים שהקוד הקיים כבר מניח עליהם (לעיל).
4. הצגתי למשתמש שתי אפשרויות להמשך: בוט בסיסי (פקודות בלבד) או בוט חכם מלא (עם LLM router). המשתמש עדיין לא החליט.

**עדיין לא נכתבה שורת קוד חדשה בסשן הזה.**

---

## כללי עבודה בפרויקט הזה

- **RTL בכל מסמכי פרויקט עברית:** עטוף ב-`<div dir="rtl" lang="he">...</div>`, אל תדביק עברית ולועזית בלי רווח.
- **`.env` ב-gitignore** — מכיל מפתחות אמיתיים. אל תעלה. אל תדפיס את תוכנו בסיכומי סטטוס.
- **אל תיצור קבצי docs חדשים** אלא אם המשתמש ביקש. יש מספיק תיעוד.
- **PTB v21.6 + JobQueue** — לתזכורות. אל תביא APScheduler ישירות.
- **aiosqlite** (לא sqlite3 סנכרוני) — הקוד ב-`userbot/main.py` כבר משתמש בו.
- **`owner_only`** על כל הנדלר חדש של הבוט.

</div>
