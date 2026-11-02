<div dir="rtl">

# פרטיות ואחריות

*הנוסח כאן הוא הסבר בשפה פשוטה ואינו ייעוץ משפטי. הרישיון (`LICENSE`) קובע את תנאי השימוש בקוד.*

## בקצרה

* הכלי רץ **במחשב שלך**. אין שרת של המפתח, ושום מידע לא נשלח אליו. אין איסוף נתונים, ניתוח שימוש או דיווח אוטומטי.
* כשמריצים דירוג בעזרת בינה מלאכותית, **תמונות מוקטנות נשלחות לספק שבחרת** (Google, OpenAI וכן הלאה), עם המפתח שלך ובחשבון שלך.
* בספק שרץ במחשב שלך (Ollama, LM Studio) שום דבר לא יוצא מהמחשב.
* הכלי **לא משנה ולא מוחק את קבצי המקור**. הוא יוצר קבצים חדשים בתיקיית התוצאות, ורק אם ביקשת, כותב כוכבים לקובצי XMP ליד התמונות.

## מה נשלח לספק

* תצוגות מקדימות או עותקים קטנים של התמונות, ודפי מגע (כמה תמונות על דף אחד), ולא הקבצים המקוריים.
* העותקים נוצרים מחדש ולכן **אינם כוללים נתוני EXIF**, כמו מיקום (GPS), דגם מצלמה או תאריך. בהנחיה לספק התמונות מסומנות במספרים ("תמונה 3"), ולא בשמות הקבצים.
* הנחיה בטקסט (מה לבדוק בתמונה), ואם יצרת קובץ טעם אישי, גם את הטקסט שלו.

## מה נשמר במחשב שלך

|מה|איפה|הערות|
|-|-|-|
|הגדרות|`.photo\_tools\_gui.json` בתיקיית המשתמש|מפתח API **לא נשמר בקובץ**. אם סימנת "זכור את המפתח", הוא נשמר באחסון הסיסמאות של Windows (Credential Manager), מוצפן ומשויך לחשבון המשתמש שלך, ונמחק משם כשמבטלים את הסימון. אם האחסון הזה לא זמין (למשל מחוץ ל-Windows), המפתח נשמר בקובץ כטקסט רגיל, ומי שמגיע אליו, או לגיבוי או לסנכרון שלו, רואה אותו|
|ספירת בקשות|`.photo\_tools\_usage.json` בתיקיית המשתמש|זמני השליחה של הבקשות האחרונות לכל ספק ומודל, והמספר שבו נגמרה המכסה בפעם האחרונה. משמש רק להערכה לפני הרצה. אין בו תמונות, שמות קבצים או מפתחות. אפשר למחוק אותו בכל עת|
|תוצאות|בתיקיית התוצאות שבחרת|עותקים קטנים, דפי מגע, דוחות וקבצי CSV. אפשר למחוק את התיקייה בכל עת|
|יומן ריצה|`run\_log.txt` בתיקיית התוצאות|נשאר מקומי. בשליחת יומן לדיווח באג, בדוק שאין בו מידע שאינך רוצה לחשוף|

## אחריותך

* **תמונות של אנשים אחרים:** תמונות הן מידע אישי. שליחתן לספק חיצוני עשויה לדרוש הסכמה או לחייב אותך לפי חוקי הפרטיות במקום שבו אתה פועל. אל תשלח תמונות שאין לך זכות או רצון לשלוח, ובמיוחד של קטינים או של אנשים שביקשו שלא.
* **תנאי הספק:** כל ספק קובע בעצמו מה הוא עושה עם מה שנשלח אליו. הספק עשוי לשמור את התוכן ולהשתמש בו לשיפור המוצרים שלו. כדאי לקרוא את התנאים הספציפים של הספק שלך לפני שמתחילים.
* **מפתח ועלויות:** המפתח הוא סיסמה, ושימוש בו עשוי לעלות כסף או לחרוג ממכסה. הכלי מציג הערכה לפני עבודה גדולה, אבל האחריות על החשבון שלך. אל תשתף את המפתח, ואל תצלם מסך שבו הוא נראה.
* **הדירוג הוא המלצה:** המודל יכול לטעות. הבחירה הסופית שלך.
* **גיבוי:** לפני כתיבת כוכבים לליטרום, גבה את הקטלוג.

## הסרת אחריות

הכלי מסופק "כמות שהוא"  ללא התחייבות מכל סוג. המפתח אינו אחראי לנזק, לאובדן מידע או לעלויות הנובעים משימוש בכלי. פרטים מלאים ב-`LICENSE`.

</div>

\---

## English summary

* The tools run on **your computer**. There is no author server, no data collection, no analytics, and nothing is sent to the author.
* When you run AI rating, **downscaled copies of your photos are sent to the provider you chose**, using your own key and account. With a local provider (Ollama, LM Studio) nothing leaves your machine.
* Images are re-encoded before sending, so **EXIF (including GPS) is not included**, and photos are labelled by number, not by file name.
* Original files are never changed or deleted. XMP sidecars are written only if you ask.
* The API key is stored only if you tick "remember the key": in the Windows Credential Manager (encrypted, tied to your user account), or, where that is not available, as plain text in the settings file.
* You are responsible for the photos you send (especially photos of other people and minors), for the provider's terms, and for the key and its costs. Ratings are suggestions only.
* The software is provided "AS IS", without warranty of any kind. This is a plain-language summary, not legal advice.

