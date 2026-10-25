<div dir="rtl">

# יומן שינויים

הפורמט מבוסס על [Keep a Changelog](https://keepachangelog.com/he/). עד הגרסה הציבורית הראשונה הכול כאן תחת "לא פורסם".

## לא פורסם

### כלים
- **בדיקה כפולה (`ensemble.py`):** דירוג הסשן בשני מודלים (אפשר מספקים שונים), ומכריע שלישי רק במחלוקות: פער ציונים גדול בתמונה, או בחירה שונה של התמונה הטובה בצילומי רצף. המכריע שופט עיוור כברירת מחדל. הדוח וה-CSV מציגים את הציון של כל מודל ומי הכריע, וחלון האישור מראה לאילו ספקים יישלחו התמונות.
- **חיפוש ברשימת המודלים:** מקלידים חלק משם המודל ורשימה קטנה מציגה רק את ההתאמות, בלי לאבד את ההקלדה.
- **בחירת טקסט בטרמינל ובמדריך:** בוחרים שורות שלמות, כי חיתוך שורה עברית באמצע (על ידי הסמן או הבחירה) גרם ל-Windows לצייר אותה בסדר שגוי. רשימת הפרקים במדריך עוברת לגלישת שורות במקום לחתוך כותרות ארוכות.
- **חלון "מתקדם":** הגדרות שרוב האנשים לא צריכים (רגישות הקיבוץ, פער בשניות, מקסימום בקבוצה, בולטות, סף טשטוש, מודל בולטות, השהיה) עברו לחלון נפרד, ושדות שלא רלוונטיים לספק שנבחר (כתובת שרת, מודלים חינמיים) מוסתרים. מקסימום תמונות, מספר המתחרות ומספר הבולטות הם אוטומטיים כשהשדה ריק. בדיקת ההתאמה לטעם עברה לשם.
- **מדריך מובנה בתוכנה:** כפתור "מדריך" (או F1) פותח את המדריך בחלון, פרק אחרי פרק, בלי החלקים של שורת הפקודה. המדריך זמין בעברית ובאנגלית (`lang/guide_en.html`), וכל שפה נוספת מוסיפים בקובץ `lang/guide_<קוד>.html`.
- **בדיקת התאמה לטעם שלך (`agreement.py`, לשונית חדשה):** משווה את דירוג ה-AI לכוכבים ולדגלי Pick שנתת בליטרום: יכולת הפרדה (AUC), התאמה בראש הדירוג, התאמה בתוך קבוצות של צילומים דומים והבולטות. דוח HTML ו-CSV עם התמונות שפספס. קורא את הקטלוג בעותק זמני בלבד.
- **הערכה לפני הרצה:** הכלי זוכר כמה בקשות שלח ב-24 השעות האחרונות ובאיזה מספר נגמרה המכסה היומית בפעם הקודמת, ומזהיר מראש כשהעבודה עלולה להיעצר באמצע. לספק בתשלום מוצגת הערה על עלות. הנתונים נשמרים רק במחשב (`.photo_tools_usage.json`).
- **קבצים שאינם RAW בסשן:** אפשרות לכלול JPEG, PNG, TIFF ו-HEIC (HEIC דורש `pillow-heif`). JPEG שיש לו RAW באותו שם ידולג, כדי שלא לעבוד פעמיים על אותו צילום. כוכבים נכתבים רק ל-RAW.
- **תאימות ל-Mac (לא נבדקה):** פתיחת קבצים ותיקיות ב-Finder, קליק ימני, גופן מערכת, וקובץ הפעלה `start_gui.command`.
- **ממשק באנגלית (ובסיס לשפות נוספות):** בחירת שפה בראש החלון. הממשק, הפלט, דוחות ה-HTML וכלי שורת הפקודה מתורגמים, והפריסה מתהפכת לשפות שמאל-לימין. שפה חדשה נוספת בקובץ `lang/<קוד>.json`, בלי לגעת בקוד.
- **סשן צילום (`rate_raw.py`):** קיבוץ צילומים דומים, דירוג לפי קומפוזיציה, זווית, אור ורגע, בחירת בולטות, דוח HTML ו-CSV, וכתיבת כוכבים לליטרום (XMP). קריאה מתיקייה או מקטלוג ליטרום.
- **ארכיון (`photo_triage.py`, `ai_rate.py`):** ניפוי תמונות מטושטשות וחשוכות, דפי מגע, דירוג בבדיקה מקרוב.
- **כפילויות (`dupes.py`):** קבצים זהים בדיוק ותמונות כמעט זהות. צילומי רצף לא נחשבים כפילות, כי זמן הצילום שלהם שונה. רק מדווח.
- **סינון מקדים בסשן:** דילוג מקומי, לפני שליחה ל-AI, על טעויות ברורות בלבד: חשוכה מאוד, חשופה מאוד, מטושטשת מאוד. הרשימה נשמרת ב-`rejected.csv` ובדוח.
- **ריבוי ספקי AI (`llm_providers.py`):** 12 ספקים. נתוני הספקים (מכסות, מגבלות) בקובץ `providers.json` שאפשר לעדכן בלי לגעת בקוד, וקובץ אישי נוסף בתיקיית המשתמש.
- הערכת עלות וזמן, ושאלת אישור לפני עבודה גדולה או כזו שחורגת מהמכסה החינמית היומית.

### ממשק
- ממשק גרפי בעברית עם לשוניות: סשן, ארכיון, כפילויות.
- מראה בהיר וכהה, ברירת המחדל לפי המחשב.
- סידור נכון של עברית מעורבת באנגלית ובמספרים (`bidi_text.py`).
- הסברי ריחוף, הדגשת שדה ששונה מברירת המחדל, וכפתור שחזור ברירות מחדל.
- פס התקדמות עם הערכת זמן, מניעת שינה בזמן ריצה, צליל והבהוב בסיום, יומן שאפשר להעתיק ולשמור.
- פרופילים בשם להגדרות הכלים והמודל.
- גרירת תיקיות וקבצים מ-Explorer (Windows).
- גלריית תוצאות: מיון, סינון לפי ציון, הגדלה, והצגה בתיקייה.
- הודעת פרטיות חד-פעמית לפני השליחה הראשונה ל-AI.

### תיעוד ופרויקט
- `README.md`, מדריך מלא (`photo_tools_guide.html`), `PRIVACY.md`, `CONTRIBUTING.md` עם תנאי תרומה, תבניות Issues ו-Pull Request.
- לוגו ודף מותג. סקריפט `build_exe.bat` לבניית EXE.
- בדיקות אוטומטיות בתיקיית `tests/`.

</div>

## Unreleased
- Grouping: shots are compared by shape at equal contrast (so exposure changes do not split a series), and against the first shot and the group average, not only the previous shot, so unrelated photos no longer join one group. Default sensitivity is now 0.30 (a saved 0.10 resets).
- New button 'Copy model list': copies the provider's models, with whatever the provider reports about them, plus a ready question for a chatbot.
- Fixes: Hebrew selection scrambling (own highlight), KeyError 'popdown' with the mouse wheel over a model list.
- Rating instructions rewritten: the model first describes each frame and what differs between similar shots, then scores; clearer scale and spread (fewer 7s), tie-break order for similar shots (flaws, moment, composition, light), precise flag definitions, impact as a criterion, taste notes as priorities. Photos are shown in a shuffled, reproducible order, a different one for each reviewer, to remove first/last-position bias. Results rated with the old instructions are not reused.
- Notes and reasons from the AI are written in the language chosen in the program (also for archive rating).
- Results are now keyed to the taste file and the type of shoot too: changing either re-rates automatically (before, stale results were reused silently).
- Guide updated: type of shoot, copy model list, About, `--genre`, grouping sensitivity.
- Hebrew in the running log is now drawn in visual order (own bidirectional algorithm, `bidi_visual.py`, `log_view.py`): any part of a line can be selected and copied, lines are wrapped correctly, and copying always gives the real text. The guide opens in the browser.
- The arrow of a search box (model lists) opens the searchable list instead of the built-in drop-down.
- New About window text; the window keeps a fixed width.
- The whole interface (text and buttons) shrinks and grows in proportion to the window; the buttons fill the bar.
- Results window: photos are drawn on one canvas and loaded only when in view (no smearing when scrolling fast); each photo shows its note; the large view always shows the text and buttons.
- Mouse-wheel scrolling now accelerates: a slow turn moves 60 px per notch, a fast turn up to 6 times more (all scrolled windows).
- Similar photos that are not next to each other are now grouped: shots of the same scene up to 30 minutes apart (`--far-gap`, Advanced window) join one group even when other shots lie between them. The match is stricter than for consecutive shots. Groups changed this way are rated again.
