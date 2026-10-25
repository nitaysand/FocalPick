<p align="center"><img src="assets/logo-icon.svg" alt="logo" width="120"></p>

# FocalPick · כלי מיון ודירוג תמונות

<div dir="rtl">

כלים בפייתון שעוזרים לצלם לבחור תמונות, בעזרת מודל AI שמסתכל על התמונות. כל הזכויות שמורות לנתאי שנדורפי ©.

## מה יש כאן

| כלי | מה הוא עושה |
|---|---|
| `rate_raw.py` | **סשן צילום (RAW):** מקבץ צילומים דומים, מדרג כל קבוצה לפי קומפוזיציה, זווית צילום, אור ורגע (ומתעלם מחשיפה, צבע ואיזון לבן, שאפשר לתקן בעריכה), ומסמן את הבולטות של הסשן. יוצר דוח HTML וגיליון CSV, ואפשר לכתוב כוכבים לליטרום (קבצי XMP). |
| `photo_triage.py` | **ניפוי ארכיון (JPEG):** מוציא תמונות מטושטשות וחשוכות, אפשר להגביל למצלמות מסוימות, ומכין דפי מגע. |
| `ai_rate.py` | **דירוג ארכיון:** נותן ציון לדפי המגע ובודק מקרוב את הטובות. |
| `dupes.py` | **כפילויות:** מוצא קבצים זהים בדיוק ואותה תמונה בגודל או בדחיסה אחרים. צילומי רצף לא נחשבים כפילות. רק מדווח, ולא מוחק. |
| `photo_tools_gui.py` | **ממשק גרפי** לכלים. |
| `bidi_text.py`, `bidi_visual.py`, `log_view.py` | סידור נכון של עברית מעורבת באנגלית ובמספרים בחלון (Windows), כולל בחירה והעתקה של חלק משורה ביומן. |
| `results_view.py` | גלריית התוצאות בתוך הממשק: מיון, סינון לפי ציון, הגדלה. |
| `tests/` | בדיקות אוטומטיות: `python -m unittest discover tests -v`. |
| `win_dnd.py` | גרירת תיקיות וקבצים מ-Explorer לחלון (Windows, בלי ספריות נוספות). |
| `assets/` | הלוגו (SVG, PNG ו-ICO) ודף מותג. |
| `llm_providers.py` | חיבור למספר ספקי AI: Google Gemini, OpenAI, Anthropic, xAI, Mistral, Groq, OpenRouter, Together, Fireworks, Ollama, LM Studio ושרת תואם OpenAI. |

המודל מספק **המלצה**, לא פסק דין. הבחירה הסופית שלך.

## התקנה

דרוש Python 3.9 ומעלה.

```
pip install -r requirements.txt
```

(אופציונלי: `pip install rawpy`. הכלים עובדים גם בלעדיו. לקריאת קבצי HEIC מהטלפון: `pip install pillow-heif`.)

**בדיקת התאמה לטעם שלך.** הלשונית "התאמה לטעם שלך" (או `python agreement.py <תיקיית תוצאות> --catalog <קטלוג>`) משווה בין דירוג ה-AI לבין הכוכבים ודגלי ה-Pick שנתת בליטרום לאותן תמונות, ומציגה אחוזי התאמה, והאם ה-AI בחר כטובה ביותר בקבוצה את מה שבחרת גם אתה. תמונות בלי כוכבים נחשבות כלא נבחרות, ולכן כדאי להריץ על סשן שסיימת לברור בעצמך. לא כותבים לליטרום ולא שולחים כלום. אם הכלי כתב כוכבים לקטלוג, ההשוואה חסרת משמעות.

**קבצים שאינם RAW.** כברירת מחדל סשן הצילום עובד על קבצי RAW בלבד. אפשר לסמן "לכלול גם קבצים שאינם RAW" (בשורת הפקודה: `--include-other`) כדי לכלול גם JPEG, PNG, TIFF ו-HEIC. קובץ JPEG ששמור ליד RAW באותו שם ידולג, כדי שצילום ב-RAW+JPEG לא יידרג פעמיים (`--keep-pairs` מבטל את הכלל). כוכבים לליטרום נכתבים רק לקבצי RAW.

**macOS.** הכלים עובדים עם Python מ-python.org (כולל Tk). להפעלה: `python3 photo_tools_gui.py` או לחיצה כפולה על `start_gui.command`. אין קובץ EXE ל-Mac, גרירת קבצים לחלון עובדת רק ב-Windows, ומפתח ה-API נשמר בקובץ ההגדרות ולא באחסון מאובטח. הממשק לא נבדק על Mac עדיין.

## הפעלה

הממשק הגרפי:

```
python photo_tools_gui.py
```

שורת פקודה, סשן צילום (קודם בדיקת קיבוץ בלי AI, אחר כך דירוג):

```
python rate_raw.py "D:\Photos\session" --out "D:\rating\session" --prepare-only
python rate_raw.py "D:\Photos\session" --out "D:\rating\session" --provider gemini --key YOUR_KEY
```

אפשר גם להגדיר את המפתח במשתנה סביבה (למשל `GEMINI_API_KEY`) ולא בשורת הפקודה. כל כלי מציג את כל האפשרויות עם `-h`.
ההרצה ניתנת להמשך: אם נעצרה (מכסה, רשת), מריצים את אותה פקודה והיא ממשיכה מאותה נקודה.

## ספקי AI, מכסות ופרטיות

- נדרש **מודל שמבין תמונות**. שמות המודלים משתנים מהר, ולכן בממשק יש כפתור "הצג מודלים זמינים".
- לחלק מהספקים יש שכבה חינמית עם מגבלות (למשל Gemini, חלק ממודלי OpenRouter עם הסיומת `:free`, ו-Groq). המגבלות משתנות, ויש לבדוק באתרים שלהם.
- **התמונות נשלחות לספק שבחרת** (תצוגות מקדימות או עותקים קטנים, לא הקבצים המקוריים). בשכבות חינמיות הספק עשוי להשתמש בתוכן לשיפור המוצרים שלו. אל תשלח תמונות שאין לך זכות או רצון לשלוח. מודל מקומי (Ollama, LM Studio) לא שולח דבר החוצה.
- הכלים לא שומרים מפתחות בקבצים, אלא אם סימנת זאת במפורש בממשק.
- פירוט מלא על מה נשלח, מה נשמר ומה באחריותך: [`PRIVACY.md`](PRIVACY.md).
- נתוני הספקים (מכסות, מודלים) נמצאים בקובץ `providers.json`, וניתן לעדכן אותם בלי לגעת בקוד. אפשר גם להוסיף קובץ אישי `.photo_tools_providers.json` בתיקיית המשתמש.

## מגבלות ידועות

- הממשק בעברית בלבד.
- מראה בהיר או כהה: ברירת המחדל לפי הגדרת המחשב, ואפשר להחליף בתיבה "מראה" בפינה השמאלית העליונה.
- נבדק בעיקר עם קבצי Canon (CR3 ו-CR2) ועם Gemini. ספקים אחרים נבדקו מול שרת בדיקה מדומה, ולא מול כל ספק אמיתי.
- החלק של ליטרום (קריאת קטלוג וכתיבת XMP) נבדק על נתונים מדומים בלבד. מומלץ לנסות על עותק, ולגבות את הקטלוג.
- Windows עם Smart App Control עלול לחסום קבצי EXE שלא חתומים דיגיטלית (וגם ספריות כמו rawpy). הכלים עובדים בלעדיהם: מריצים אותם עם `python`.
- הכלי נכתב בסיוע AI. השימוש באחריותך.

## תרומה לפרויקט

מוזמנים לתרום ידע (מכסות ספקים, תיקוני ניסוח, קבצי טעם לדוגמה) וקוד. הפרטים ותנאי התרומה ב-[`CONTRIBUTING.md`](CONTRIBUTING.md).

## רישיון

© נתאי שנדורפי. מופץ ברישיון MIT: מותר להשתמש, להעתיק, לשנות ולהפיץ, בתנאי שנשמרת הודעת זכויות היוצרים. ראה `LICENSE`.

</div>

---

## English (short)

A set of Python tools that help photographers cull and rate photos using an AI vision model: group similar RAW shots and rank them on composition, camera angle and light (ignoring what is easy to fix in editing), find the session highlights, and optionally write star ratings to Lightroom XMP sidecars. Includes a GUI (Hebrew and English, pick the language at the top) and support for many AI providers (Gemini, OpenAI, Anthropic, xAI, Mistral, Groq, OpenRouter, Together, Fireworks, Ollama, LM Studio, any OpenAI-compatible server).

Requires Python 3.9+; `pip install -r requirements.txt`; run `python photo_tools_gui.py`.
Photos (previews or small copies) are sent to the provider you choose. Free tiers may use submitted content to improve their products.

**Languages.** The interface, console output and HTML reports follow the language chosen in the GUI (or `PHOTO_TOOLS_LANG=en` for the command-line tools). To add a language, copy `lang/en.json` to `lang/<code>.json` (or to `~/.photo_tools_lang/` for personal use), set `_name` and `_rtl`, and translate the values. Keep `{n}`-style placeholders unchanged. Run `python -m unittest discover tests` to check them.

Copyright (c) 2026 Nitay Sandorffy. Released under the MIT License. See `LICENSE`.
