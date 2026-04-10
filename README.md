<div dir="rtl" lang="he">

# סוכן טלגרם אישי

סוכן טלגרם אישי בארכיטקטורה כפולה:
- **Bot API** — ניתוב הודעות, ניהול קבוצות, תזכורות, יומן ואנשי קשר
- **Userbot** — סריקה יומית של צ'אטים וסידור תיקיות אוטומטי

המפרט המלא: [docs/spec.md](docs/spec.md)

---

## התקנה מהירה

### 1. דרישות מקדימות
- Python 3.11+
- חשבון טלגרם
- חשבון Anthropic (Claude API)
- חשבון OpenAI (Whisper) — או שימוש בתמלול חינמי
- חשבון Google (Calendar API)

### 2. שכפול והתקנה

```bash
git clone <repo-url>
cd telegram-agent
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

### 3. הגדרת משתני סביבה

העתק `.env.example` ל-`.env` ומלא את הערכים. ראו [docs/setup.md](docs/setup.md) למדריך מפורט איך להשיג כל מפתח.

### 4. הרצה

```bash
# הבוט (Bot API)
python -m bot.main

# Userbot (תהליך נפרד)
python -m userbot.main
```

---

## מבנה הפרויקט

```
telegram-agent/
├── bot/                 # רכיב 1 - Bot API
│   ├── main.py          # נקודת כניסה
│   ├── config.py        # טעינת קונפיגורציה
│   ├── db.py            # SQLite + סכמה
│   ├── handlers/        # מטפלי הודעות ופקודות
│   ├── services/        # שירותים (Claude, Whisper, Calendar)
│   └── utils/           # כלים משותפים
├── userbot/             # רכיב 2 - Userbot (Telethon)
│   └── main.py
├── data/                # מסד נתונים ולוגים (לא ב-git)
├── docs/                # תיעוד
├── .env.example         # תבנית משתני סביבה
├── requirements.txt
└── README.md
```

---

## רישיון

פרטי — שימוש אישי בלבד.

</div>
