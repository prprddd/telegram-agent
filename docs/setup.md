<div dir="rtl" lang="he">

# מדריך התקנה — שלב אחר שלב

המדריך הזה לוקח אותך מ-0 ל-בוט עובד. עבור על הסעיפים בסדר.

---

## 0. דרישות מקדימות

- **Python 3.11 או חדש יותר** — בדוק עם `python --version`
- **חשבון טלגרם** פעיל
- **חשבון Google** עם Calendar API
- **חשבון Anthropic** (חיוב מופעל) — ל-Claude API
- **חשבון OpenAI** (חיוב מופעל) — ל-Whisper תמלול. *אופציונלי, אם לא תרצה הודעות קוליות*
- **כרטיס אשראי** — רוב ה-APIs דורשים אמצעי תשלום

---

## 1. צור את הבוט ב-BotFather

1. פתח את טלגרם וחפש את `@BotFather`
2. שלח `/newbot`
3. בחר שם תצוגה (למשל "העוזר האישי שלי")
4. בחר username שמסתיים ב-`bot` (למשל `dsema_assistant_bot`)
5. **העתק את הטוקן** שמתקבל — נראה ככה: `1234567890:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`
6. שמור אותו לרגע — תכניס אותו ל-`.env` בהמשך

הגדרות מומלצות (אופציונלי) דרך BotFather:
- `/setdescription` — תיאור הבוט
- `/setuserpic` — תמונת פרופיל
- `/setprivacy` — שמור על "Enabled" (ברירת מחדל) — הבוט לא יקרא הודעות בקבוצות שלא מיועדות לו
- `/setcommands` — רשימת הפקודות שיופיעו אוטומטית:
  ```
  start - התחלה
  help - עזרה
  id - הצג את ה-ID שלי
  groups - רשימת קבוצות
  addgroup - הוספת קבוצה (להריץ בתוך הקבוצה)
  removegroup - הסרת קבוצה
  ```

---

## 2. השג את ה-Telegram User ID שלך

הבוט הוא single-user — הוא יענה רק לך.

1. חפש בטלגרם את `@userinfobot` ושלח לו `/start`
2. הוא יחזיר לך את ה-ID שלך (מספר ארוך, למשל `123456789`)
3. שמור את המספר — נכנס ל-`.env` כ-`TELEGRAM_OWNER_ID`

(לחלופין, אחרי שתפעיל את הבוט שלך, שלח לו `/id` והוא יחזיר את ה-ID — אבל ב-`.env` תצטרך להזין אותו ידנית.)

---

## 3. השג Anthropic API Key

1. היכנס ל-https://console.anthropic.com/
2. צור חשבון או התחבר
3. **Settings → Billing** — הוסף אמצעי תשלום והפקד 5$ (מינימום)
4. **Settings → API Keys → Create Key**
5. תן לו שם (למשל "telegram-bot")
6. **העתק את המפתח מיד** — הוא לא יוצג שוב. נראה ככה: `sk-ant-api03-...`
7. שמור — נכנס ל-`.env` כ-`ANTHROPIC_API_KEY`

הערה: המפרט מציין מודל ברירת מחדל `claude-sonnet-4-6`. אם זה לא זמין לך עדיין, ערוך את `ANTHROPIC_MODEL` ב-`.env`.

---

## 4. השג OpenAI API Key (לתמלול)

*אופציונלי — דלג אם לא תשתמש בהודעות קוליות.*

1. היכנס ל-https://platform.openai.com/
2. צור חשבון או התחבר
3. **Settings → Billing** — הוסף אמצעי תשלום והפקד 5$
4. **API keys → Create new secret key**
5. תן לו שם (למשל "telegram-whisper")
6. **העתק את המפתח מיד** — נראה ככה: `sk-proj-...`
7. שמור — נכנס ל-`.env` כ-`OPENAI_API_KEY`

---

## 5. הגדר Google Calendar API

זה הסעיף הארוך ביותר — קח אוויר.

### 5.1 צור פרויקט ב-Google Cloud

1. היכנס ל-https://console.cloud.google.com/
2. למעלה, ליד הלוגו, לחץ על תפריט הפרויקטים → **New Project**
3. שם: `telegram-agent` (או מה שתרצה)
4. צור — חכה כמה שניות

### 5.2 הפעל את Google Calendar API

1. בתפריט הצדדי: **APIs & Services → Library**
2. חפש "Google Calendar API"
3. לחץ עליו → **Enable**

### 5.3 הגדר OAuth Consent Screen

1. **APIs & Services → OAuth consent screen**
2. בחר **External** → Create
3. App name: `telegram-agent`
4. User support email: המייל שלך
5. Developer contact: המייל שלך
6. **Save and Continue**
7. **Scopes** — דלג (Save and Continue)
8. **Test users → Add Users** → הוסף את המייל שלך
9. **Save and Continue** → **Back to Dashboard**

### 5.4 צור OAuth Client ID

1. **APIs & Services → Credentials**
2. **Create Credentials → OAuth client ID**
3. Application type: **Desktop app**
4. שם: `telegram-agent-desktop`
5. **Create**
6. בחלון שנפתח — **Download JSON**
7. שמור את הקובץ בתור `data/google_credentials.json` בתיקיית הפרויקט

### 5.5 אישור ראשוני

באמצעות הקובץ הזה, בפעם הראשונה שהבוט יצטרך גישה ליומן, הוא יפתח דפדפן ויבקש ממך לאשר. אחרי האישור — הטוקן יישמר ב-`data/google_token.json` ולא תצטרך לאשר שוב.

---

## 6. השג Telegram API ID + Hash (ל-Userbot בלבד)

*אופציונלי — דלג אם לא תשתמש ב-Userbot לסידור צ'אטים.*

1. היכנס ל-https://my.telegram.org/auth
2. התחבר עם מספר הטלפון שלך (יישלח קוד בטלגרם)
3. **API development tools**
4. צור אפליקציה חדשה:
   - App title: `telegram-agent`
   - Short name: `tgagent`
   - URL: ריק
   - Platform: Desktop
   - Description: `personal automation`
5. **Create application**
6. שמור את:
   - `api_id` — מספר
   - `api_hash` — מחרוזת ארוכה

> ⚠️ **אל תפרסם את הערכים האלה לעולם.** זה גישה מלאה לחשבון הטלגרם שלך.

נכנסים ל-`.env` כ-`TELEGRAM_API_ID` ו-`TELEGRAM_API_HASH`.

---

## 7. התקן את הפרויקט מקומית

```bash
cd C:\Users\dsema\projects\telegram-agent

python -m venv .venv
.venv\Scripts\activate

pip install --upgrade pip
pip install -r requirements.txt
```

---

## 8. צור את קובץ ה-`.env`

```bash
copy .env.example .env
```

ערוך את `.env` במחשב (Notepad/VSCode) ומלא את כל הערכים שאספת בסעיפים 1-6.

מינימום לעבודה בסיסית:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_OWNER_ID`
- `ANTHROPIC_API_KEY`

לתמלול: `OPENAI_API_KEY`

ליומן: ודא ש-`data/google_credentials.json` קיים.

ל-Userbot: `TELEGRAM_API_ID` + `TELEGRAM_API_HASH`.

---

## 9. הרץ את הבוט בפעם הראשונה

```bash
.venv\Scripts\activate
python -m bot.main
```

אתה אמור לראות:
```
[INFO] bot.main: Starting bot polling...
[INFO] bot.main: Bot startup complete.
```

עכשיו פתח את הבוט שלך בטלגרם (חפש את ה-username שיצרת ב-BotFather) ושלח `/start`.

אם הוא עונה — מצוין! אם הוא אומר "אין לך גישה" — בדוק שוב את `TELEGRAM_OWNER_ID`.

---

## 10. הוסף את הקבוצה הראשונה

1. צור קבוצה חדשה בטלגרם
2. הוסף את הבוט שלך לקבוצה (כחבר רגיל)
3. בתוך הקבוצה — שלח `/addgroup work עבודה — צוות הפיתוח`
4. הבוט יענה ויאשר
5. עכשיו בצ'אט פרטי איתו, שלח: "תשלח לעבודה: בדיקה ראשונה" — והוא ישלח לקבוצה.

---

## 11. הרץ את ה-Userbot (אופציונלי)

תהליך נפרד, חלון Terminal נוסף:

```bash
.venv\Scripts\activate
python -m userbot.main
```

בפעם הראשונה הוא יבקש ממך:
1. את מספר הטלפון
2. קוד שמגיע בטלגרם
3. אם יש Two-Factor — סיסמה

אחרי האימות, הוא ייצור קובץ session ויסרוק אוטומטית בשעה שהגדרת ב-`USERBOT_SCAN_TIME`.

---

## 12. פריסה ל-Railway (אופציונלי)

1. דחוף את הקוד ל-GitHub (private repo)
2. https://railway.app/ → New Project → Deploy from GitHub
3. בחר את ה-repo
4. **Variables** → הוסף את כל המשתנים מ-`.env` (פרט לקבצים)
5. ל-`google_credentials.json` — השתמש ב-Railway's File Mounts או הצפנה לפי המדריך שלהם
6. הפרויקט יתחיל אוטומטית. הלוגים זמינים ב-dashboard.

לחלופין: Render.com — תהליך דומה.

---

## פתרון תקלות

| תקלה | פתרון |
|---|---|
| `pydantic_settings.BaseSettings ValidationError` | חסר משתנה ב-`.env`. קרא את ההודעה — היא תגיד מי |
| `Unauthorized: invalid token` | `TELEGRAM_BOT_TOKEN` לא נכון |
| הבוט עונה "אין לך גישה" | `TELEGRAM_OWNER_ID` לא תואם ל-ID שלך |
| `anthropic.AuthenticationError` | `ANTHROPIC_API_KEY` לא נכון או החשבון בלי credit |
| תמלול לא עובד | `OPENAI_API_KEY` חסר או החשבון בלי credit |
| Calendar לא נוצר | `data/google_credentials.json` חסר או OAuth לא הושלם |
| Userbot crash | מחק את קובץ ה-`.session` ב-`data/` והרץ שוב |

---

## אבטחה — חובה לקרוא

- **לעולם אל תעלה את `.env` ל-git.** הוא ב-`.gitignore` כברירת מחדל.
- **לעולם אל תעלה את `data/google_credentials.json` או `data/google_token.json`.**
- **לעולם אל תפרסם את ה-Telegram API Hash שלך.**
- אם חשדת שמפתח דלף — צור חדש מיד וההישן השבת.

</div>
