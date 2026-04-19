<div dir="rtl" lang="he">

⚠️ בסשן חדש - קרא את סעיף 'סטטוס נוכחי' לפני כל פעולה

# הוראות לקלוד — פרויקט telegram-agent

## מה הפרויקט

סוכן טלגרם אישי (single-user) עבור dsema. ארכיטקטורה כפולה:
- **Bot API** — ניתוב הודעות לקבוצות, תזכורות, Google Calendar, תמלול קולי, ספר אנשי קשר
- **Userbot (Telethon)** — תהליך נפרד, סריקה יומית של צ׳אטים לתיקיית "שאר הצ׳אטים"

**משתמש יחיד.** כל ההנדלרים מוגנים ב-`@owner_only` ומשווים ל-`settings.telegram_owner_id`.

**שפה:** עברית (עם תמיכה באנגלית). מסמכי הפרויקט בעברית (README, docs/*.md) עטופים ב-`<div dir="rtl" lang="he">` — כי שם זה מרונדר כ-HTML. **בצ'אט עם המשתמש — לא לעטוף ב-div.** ה-chat של Claude Code לא מרנדר HTML, וה-tag מופיע כטקסט ליטרלי. עברית ממילא יורדת RTL לבד.

**מפרט מלא:** [docs/spec.md](docs/spec.md) — קרא שם לפני החלטות ארכיטקטוניות.
**הגדרה מהתחלה:** [docs/setup.md](docs/setup.md) — המדריך למשתמש.

---

## הנחיות תקשורת עם המשתמש

- **עברית פשוטה, בלי ז׳רגון טכני.** המשתמש לא מפתח. אל תדבר על `config.py`, `pydantic`, `async` — דבר על "הגדרות", "מה הבוט יודע לעשות". אם חייבים מונח טכני, הסבר אותו.
- **אל תציג לו בחירות ארכיטקטוניות** כמו אם לכתוב רכיב אחד או שניים. תחליט לבד, תבנה, ואם יש דיוק ששובר התנהגות — תציג בצורה פשוטה.
- **אנלוגיות טובות** (רכב/מנוע, בית/חדרים) עובדות טוב איתו.
- אם הוא אומר "לא הבנתי" — זה שלך. תעצור, תפשט, ותסביר מחדש בלי קוד.

---

## סטטוס נוכחי - 2026-04-19 (ערב, אחרי אירוע Conflict)

### ⚠️ תיקונים ב-CLAUDE.md שהיו שגויים בגרסה הקודמת

- **שם השירות ב-Render:** `telegram-agent` (לא `telegram-agent-1` כפי שהיה רשום). Service ID: `srv-d7cetid7vvec7386ip00`.
- **URL הבוט:** `https://telegram-agent-lxjb.onrender.com` (לא `telegram-agent-1.onrender.com`).
- **Branch מתפרס ב-Render:** `master` ✅.
- **Project hierarchy:** `Danou's_Telegram_Agent / Production / telegram-agent`.

### 🟢 מה נעשה היום (סשן 2026-04-19, 7 commits על master)

| Commit | מה | נפרס |
|---|---|---|
| `4fdf75d` | זיהוי קבוצה מקומי + זיכרון שיחה + חוקי כנות | ✅ |
| `5d24938` | prefix ראשוני להודעת קול מטקסט | ✅ |
| `efb438d` | regex יציב ל-prefix הקול + "מה כן יכול" ב-prompt | ✅ |
| `5ed0c9a` | ברירת מחדל TTS = `fable` | ✅ |
| `775cffa` | קטגוריות משימות/קניות/רכישות + reactions + סיכום | ✅ |
| `f8a273b` | docs checkpoint | ✅ |
| `1d1e887` | **הבוט חייב לעלות גם אם MessageReactionHandler נופל בייבוא** | ✅ (Live מ-5:14 PM) |

### 🔴 מצב פתוח — 2 שאלות לא-פתורות שנסשן הבא חייב לעקוב אחריהן

**1. קול הבוט עדיין נשמע כמו `nova` (נשי), לא `fable` (גברי) — לא מוסבר.**
- הקוד ב-master: `tts_voice: str = Field("fable", alias="TTS_VOICE")` ב-[bot/config.py:30](bot/config.py#L30).
- Render מריץ `1d1e887` שכולל את השינוי הזה (אושר בצילום Events).
- המשתמש אישר ש-`TTS_VOICE` **לא קיים** ב-Environment של Render, אז אין override.
- למרות הכל — המשתמש שמע קול נשי. לא הגיוני לפי הקוד.
- השערות לבדוק בסשן הבא:
  - (a) לעשות Manual Deploy עם "Clear build cache & deploy" — אולי Render מריץ תמונה cached מלפני שינוי fable.
  - (b) הוספת log בעת startup שמדפיס את הערך של `settings.tts_voice` — לראות בוודאות מה נטען.
  - (c) לבדוק אם יש `.env` באיזשהו disk ב-Render שמוגדר עם `TTS_VOICE=nova` בצורה נסתרת.

**2. בעבר קרה `telegram.error.Conflict: terminated by other getUpdates request` — אולי יש instance שני.**
- הבוט היה שותק ~7 שעות בגלל זה. תוקן אחרי `Restart` ידני של המשתמש (5:17 PM).
- **לא וידאנו שיש רק instance אחד.** אולי:
  - יש service שני ב-Render (הצילום של Projects overview הראה "Ungrouped Services → telegram-agent-1" *בנוסף* ל-`telegram-agent` שבתוך project Production).
  - או שהמשתמש הריץ את הבוט גם מקומית וזה תופס את ה-polling.
- לבדוק בסשן הבא: `dashboard.render.com` → רשימת services מלאה. אם יש שניים שמשתמשים באותו `TELEGRAM_BOT_TOKEN` — מחיקת אחד פותרת את הקונפליקט הכרוני.

### 🟡 מצב חלקית-מאומת — הפיצ'ר החדש של קטגוריות

- המשתמש שלח "רכישה כיסוי מחברת ממותג / מחברות ממותגות" — לא ראינו בצילום אם הוא הגיע לקבוצה *רכישות*.
- המשתמש שלח "בקול" (מחרוזת ריקה אחרי ה-prefix) — הבוט חזר על התשובה הקודמת בטקסט, לא בקול. ה-regex הנוכחי דורש ":" או "-" אחרי "בקול" → לא נתפס. אולי להרפות את הדרישה.
- **טרם אומת:** `/groups` → מופיעות `משימות`/`קניות`/`רכישות`. האם הן רשומות? לא יודעים.
- **טרם אומת:** הבוט admin בשלוש הקבוצות. בלי זה מעקב reactions לא יעבוד (ראה [memory/reactions_require_admin.md](../../../Users/dsema/.claude/projects/c--CLAUDE-Projects-telegram-agent/memory/reactions_require_admin.md)).

### 🔜 סדר הפעולות לסשן הבא

1. **קודם — לפתור את תעלומת הקול.** המשתמש יבצע Manual Deploy עם `Clear build cache & deploy`, ישלח "דבר איתי: בדיקה", ויגיד אם הקול השתנה.
2. **לבדוק conflict** — בעמוד הראשי של Render לוודא שיש רק service אחד (או למחוק את `telegram-agent-1` הישן אם הוא שורד).
3. **לוודא קטגוריות רשומות** — `/groups` בצ'אט פרטי ואז להריץ שלוש בדיקות end-to-end (שליחה → לייק → סיכום).
4. **רק אז** להוסיף פיצ'רים חדשים (כמו TTS על תזכורות).

### ⚠️ בעיות רקע (לא בוערות)

- **Userbot**: `TELEGRAM_API_ID`/`HASH` ריקים. המשתמש אמר שלא צריך — הוא יפתח קבוצות בעצמו ויצרף את הבוט ידנית.
- **OPENAI_API_KEY ב-Render**: לא מוגדר. תמלול קולי ו-TTS לא יעבדו שם. מלא ב-.env המקומי.
- **Google Calendar ב-Render**: OAuth לא בוצע על Render, `google_token.json` רק מקומית.

---

## כללי עבודה בפרויקט הזה

- **RTL בכל מסמכי פרויקט עברית:** עטוף ב-`<div dir="rtl" lang="he">...</div>`, אל תדביק עברית ולועזית בלי רווח.
- **`.env` ב-gitignore** — מכיל מפתחות אמיתיים. אל תעלה. אל תדפיס את תוכנו בסיכומי סטטוס.
- **אל תיצור קבצי docs חדשים** אלא אם המשתמש ביקש. יש מספיק תיעוד.
- **PTB v21.6 + JobQueue** — לתזכורות. אל תביא APScheduler ישירות.
- **aiosqlite** (לא sqlite3 סנכרוני) — הקוד ב-`userbot/main.py` כבר משתמש בו.
- **`owner_only`** על כל הנדלר חדש של הבוט.

</div>
