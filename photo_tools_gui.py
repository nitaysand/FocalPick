#!/usr/bin/env python3
# © 2026 נתאי שנדורפי (Nitay Sandorffy). MIT License.
"""
ממשק גרפי לכלי מיון ודירוג התמונות.

חייב להיות באותה תיקייה עם:  rate_raw.py   photo_triage.py   ai_rate.py
הפעלה:  python photo_tools_gui.py
"""
__author__ = "נתאי שנדורפי"
__copyright__ = "© 2026 נתאי שנדורפי. MIT License."
import ctypes
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, simpledialog, ttk



def _import_failed(err):
    """A friendly message instead of a traceback when a library cannot be loaded (usually Windows blocking a DLL)."""
    text = str(err)
    blocked = any(k in text.lower() for k in ("application control", "blocked", "smart app control", "dll load failed"))
    if blocked:
        msg = ("Windows חסם טעינת רכיב של התוכנה (בדרך כלל ספריית התמונות Pillow), ולכן היא לא יכולה להיפתח.\n\n"
               "הפירוש: 'שליטה באפליקציות' (Smart App Control או App Control) לא מכיר את הקובץ הלא חתום.\n"
               "מה אפשר לעשות:\n"
               "1. להריץ עם גרסת פייתון יציבה יותר (3.12 או 3.13) ולהתקין בה את Pillow:  py -3.12 -m pip install --force-reinstall pillow numpy\n"
               "2. או לכבות את Smart App Control (אבטחת Windows > בקרת אפליקציות ודפדפן). זה מוריד שכבת הגנה, ובחלק מהגרסאות "
               "של Windows אי אפשר להפעיל אותו שוב בקלות, אז זו החלטה שלך.\n\n"
               "Windows blocked a component (usually Pillow). Run with Python 3.12/3.13 and reinstall pillow, "
               "or turn off Smart App Control.\n\n" + text[:300])
    else:
        msg = "חסר רכיב שהתוכנה צריכה:\n" + text[:400] + "\n\nלהתקנה:  pip install pillow numpy rawpy"
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("FocalPick", msg)
        root.destroy()
    except Exception:
        print(msg, file=sys.stderr)
    sys.exit(1)


try:
    import ai_rate
    import bidi_text
    import i18n
    from i18n import X, tr
    import agreement
    import dupes
    import help_view
    import log_view
    import llm_providers as llm
    import photo_triage
    import rate_raw
    import results_view
    import secret_store
    import win_dnd
    from smooth_scroll import SmoothScroller
except ImportError as _err:
    _import_failed(_err)

GENRE_LABELS = {"": "ללא, דירוג כללי", "street": "רחוב", "events": "אירועים ואנשים", "sport": "ספורט ותנועה",
                "landscape": "נוף וטבע", "portrait": "פורטרט", "cars": "רכבים"}
APP_NAME = "FocalPick"
APP_VERSION = "1.0"
# Fill these in once the GitHub project and the Sponsors page exist: the matching button then appears in the About window.
REPO_URL = "https://github.com/nitaysand/FocalPick"          # e.g. "https://github.com/<user>/focalpick"
SPONSOR_URL = ""       # e.g. "https://github.com/sponsors/<user>"
SETTINGS_FILE = Path.home() / ".photo_tools_gui.json"
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
UI_FONT = "Segoe UI" if IS_WIN else ("Helvetica Neue" if IS_MAC else "DejaVu Sans")
# Windows virtual-key codes: they stay the same whatever keyboard layout is active
VK = {67: "c", 86: "v", 88: "x", 65: "a", 90: "z", 89: "y"}
SHORTCUT_KEYS = ("c", "v", "x", "a", "z", "y")

HEB_RE = re.compile(r"[\u0590-\u05FF]")


def R(text):
    """Text for a label, in the current language. In Hebrew every line gets a right-to-left base direction
    (see bidi_text.py)."""
    text = i18n.tr(text)
    return bidi_text.rtl_text(text) if i18n.rtl() else text


class mb:
    """Message boxes with the same right-to-left treatment. Looks the real function up at call time."""
    @staticmethod
    def _call(name, title, message, **kw):
        return getattr(messagebox, name)(i18n.tr(title), R(message), **kw)

    showinfo = staticmethod(lambda t, m, **k: mb._call("showinfo", t, m, **k))
    showwarning = staticmethod(lambda t, m, **k: mb._call("showwarning", t, m, **k))
    askyesno = staticmethod(lambda t, m, **k: mb._call("askyesno", t, m, **k))
    askokcancel = staticmethod(lambda t, m, **k: mb._call("askokcancel", t, m, **k))


# ---------------------------------------------------------------- colours (light / dark)
PALETTES = {
    "light": dict(bg="#f4f6fa", surface="#ffffff", fg="#1b2130", muted="#5b6478", border="#c6cddb",
                  field="#ffffff", btn="#e5e9f1", btn_hot="#d7dde9", sel="#cddcf8", sel_fg="#101828",
                  disabled="#9aa2b2", accent="#14213D", accent_hot="#26396a", accent_fg="#ffffff",
                  check="#14213D", changed="#9a5b00"),
    "dark": dict(bg="#171c28", surface="#1f2536", fg="#e7eaf3", muted="#9ba4b9", border="#3a425a",
                 field="#121620", btn="#2a3247", btn_hot="#364059", sel="#35508c", sel_fg="#ffffff",
                 disabled="#6c7489", accent="#F5B83D", accent_hot="#ffcb66", accent_fg="#14213D",
                 check="#F5B83D", changed="#F5B83D"),
}
THEME = {"dark": False, **PALETTES["light"]}        # the palette currently in use (read by the right-click menu)
THEME_CHOICES = (("system", "לפי המחשב"), ("light", "בהיר"), ("dark", "כהה"))


def system_is_dark():
    """True when the operating system is set to a dark appearance."""
    try:
        if IS_WIN:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
        if sys.platform == "darwin":
            r = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                               capture_output=True, text=True, timeout=2)
            return "dark" in r.stdout.lower()
        r = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                           capture_output=True, text=True, timeout=2)
        return "dark" in r.stdout.lower()
    except Exception:
        return False


def set_titlebar_dark(root, dark):
    """Dark title bar on Windows 10/11 (does nothing elsewhere)."""
    if not IS_WIN:
        return
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        val = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):          # 20 = Windows 11 / newer Windows 10, 19 = older builds
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                break
    except Exception:
        pass



ICON_PNG_B64 = {
    32: "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAABmJLR0QA/wD/AP+gvaeTAAAE6ElEQVRYhb2Xe1BUZRiHn2935bJoCrIQgyAQIwlFVs4wmjgYGqiY5SClqehAauqU4AXUybQpwAuoTIYpctnSMjFkuGQhWE7qONpokyImWOLoCLvs5oztoszu6Q/EcdsLhxny/e987+97f8/uec/7nSN4LPxCYhOsCpYiSeNA+AGCgQkrcFuSqJdU1nxDy6nLvQkBEBIS53FPWIqBdwbI0FV0C0larfvrl0IAJYDKO6jsCZn3eAox1dNnZIfZ2HZeaEImJEpCfP+EzB+P+0qLFKmSFGIJUv92jgoPIfq5CDS+PgDo9Aaamlu5eu06FotVbhl3i0qsEb6hse2AX1/qp/01zHt7Btt3lVD5zW5ejB5tp+k0GDlSVc/+8graO/RyIG4oAF9XCiEE7y6czYm6ctIWJLusNtzHm8WLUjhRpyVtQTJC9PkQjVABCmdZN7dBFG7bQOKUiQCYzV19FezZ5z6IkcGBeHp6YDKZXUkVKqcZhcLGXG6cPnuBj/N2c6vtOpnTwPcpyCgDyUmfOQVIT03ul3nbzdvkFRRz7MefSBkPB9Ng+JCe3O9tsL+hHwAB/hoyViyUZWwydbG39BBFxV/zQtADatZBVJCtZvUMqD4PHXdlAqQvmo2np4dLY0mSqKyuJ3f7XtysBgrmw/SXwFHfqd0hPR5yvrPPOWzApMQ4l+YXLjYxM2UZmdl56PQGfAZDgLdj896YFQMKB3nhGxpr1x5hoUF8mLWMSRNjbNbN5i5GvzzNoYEQ8PpYWDcLAoY5hkj4BJpv2SxJdv/A5EnjiRkbTdqyDcxLW0NLa5vTX2VTSYKqc/DqJiisg65ue82zgfZrdgDhYcHkbl5F9eE9POjuZuqb6WzO+4x79/6RBbJu7Qdoz/gQvwlqfrXNaYbIAOiNqNHhfKvdyc6t66k/fppJ01KpOPpDnwDJbyTw87GvSJ6TSuaXbqQUwOWbzvV2AHqD0eZ6emIcx2tKmT9nJrn5X/QJAKBWe7ByeSqNdeWMiEwgKReyD0BruwyA5qvX7UQeHu68/958GmrLmTk9Xs6MByAwwJ/83CwOlBRwQRdG4yUZAE3Nreg7DQ4LBvhr2LVtAxUHCnk+ctSj9eioCDZmL3cKMi5mDCVFOQ5zdgBWq5XKaidzk54BdOeODoPxLn6a4eRsyuw5nsdEOt0DUFXjuKbDJiwuO+zw5Lt8pYWUBStZuTaH16a8QmNtGXNTklAqnfYyACaTmRLtEfkA7R168gtLH113Goxkb9zOjNlLGfrUEBpqy/goewWDB3u5NO6NLTv2odM7vq1OT8P92gqiIsPRd/5NYZEWP40PJZ9/Stx/pmNfUVXbgPZgldO8UwBJksjIykWt9iQ7czFz30pCpVT2y/xozXHWrN+K5Oxl4CGAFRcDyWzu4s+2mzy4341KLQ/AZDKzZcc+tAerXJoDVqXae2Q6MNSV6uJvVzhceQyL1UpwUABeXmo7zZ12PYcq6nBzG0RGVi5nzl6Uw9oufMMm7EESS+SooedVLWJUKBHhoWh8vRFCoNMbuXTlD6613JBbBgAJKoRf+PhnrBZlE+DWr90DEJJCxCs6Wk63SkLKeOLmEqWdrScblQBmY9s5r2HBRoSYzMPvxf/d3MuwFJ3OYnOq+ATHRgqFWCWENBkIHEAYK9AuwSkUoqiz9WRjb+JfzxSvBPEAD/UAAAAASUVORK5CYII=",
    64: "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",
    128: "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",
}


# ---------------------------------------------------------------- Windows niceties
def enable_dpi_awareness():
    """Without this, Windows stretches the window on a scaled display (125%, 150%) and the text looks blurry."""
    if not IS_WIN:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def keep_awake(on):
    """Stops Windows from going to sleep while a long job runs (applies to the calling thread)."""
    if not IS_WIN:
        return
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001 if on else 0x80000000)
    except Exception:
        pass


def notify_done(root):
    """A short sound and a taskbar flash, but only when the window is not in front."""
    try:
        if root.focus_displayof() is not None:
            return
    except (tk.TclError, KeyError):
        pass
    if IS_WIN:
        try:
            import winsound
            winsound.MessageBeep()
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id())

            class FLASHWINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("hwnd", ctypes.c_void_p), ("dwFlags", ctypes.c_uint),
                            ("uCount", ctypes.c_uint), ("dwTimeout", ctypes.c_uint)]
            info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 3 | 12, 3, 0)   # flash until the window is in front
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
        except Exception:
            pass
    else:
        root.bell()


def fmt_eta(seconds):
    m = int(round(seconds / 60))
    if seconds < 60:
        return "פחות מדקה"
    if m < 90:
        return f"כ-{m} דקות"
    h, mm = divmod(m, 60)
    return f"כ-{h} שעות" + (f" ו-{mm} דקות" if mm else "")


class Tooltip:
    """A small explanation that appears when the mouse rests on a widget."""
    def __init__(self, widget, text, delay=550):
        self.widget, self.text, self.delay = widget, text, delay
        self.tip, self.job = None, None
        widget.bind("<Enter>", self.schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")
        widget.bind("<Destroy>", self.hide, add="+")

    def schedule(self, _event=None):
        self.hide()
        self.job = self.widget.after(self.delay, self.show)

    def show(self):
        self.job = None
        try:
            self.tip = tw = tk.Toplevel(self.widget)
            tw.wm_overrideredirect(True)
            tw.attributes("-topmost", True)
            font = tkfont.Font(font=(UI_FONT, 9))
            px = int(380 * max(1.0, self.widget.winfo_fpixels("1i") / 96.0))
            lab = tk.Label(tw, text=bidi_text.wrap_text(i18n.tr(self.text), px, font, i18n.rtl()), justify=X("right"), anchor=X("e"),
                           background=THEME["surface"], foreground=THEME["fg"], padx=10, pady=6,
                           borderwidth=1, relief="solid", font=(UI_FONT, 9))
            lab.pack()
            tw.update_idletasks()
            w, h = tw.winfo_reqwidth(), tw.winfo_reqheight()
            sw, sh = tw.winfo_screenwidth(), tw.winfo_screenheight()
            x = self.widget.winfo_pointerx() + 14
            y = self.widget.winfo_pointery() + 18
            if x + w > sw - 8:
                x = self.widget.winfo_pointerx() - w - 14
            if y + h > sh - 8:
                y = self.widget.winfo_pointery() - h - 10
            tw.wm_geometry(f"+{max(0, x)}+{max(0, y)}")
        except tk.TclError:
            self.tip = None

    def hide(self, _event=None):
        if self.job:
            try:
                self.widget.after_cancel(self.job)
            except tk.TclError:
                pass
            self.job = None
        if self.tip:
            try:
                self.tip.destroy()
            except tk.TclError:
                pass
            self.tip = None


# explanations shown when the mouse rests on a field
TIPS = {
    "rr_source": "התיקייה עם קבצי ה-RAW של הסשן. הכלי רק קורא אותם, ולא משנה ולא מוחק כלום.",
    "rr_catalog": "קובץ הקטלוג של ליטרום, עם הסיומת lrcat. הכלי קורא אותו בעותק זמני ולא משנה אותו.",
    "rr_since": "רק תמונות שצולמו מתאריך זה והלאה, בצורה שנה-חודש-יום. ריק = בלי הגבלה.",
    "rr_until": "רק תמונות שצולמו עד התאריך הזה, כולל. ריק = בלי הגבלה.",
    "rr_collection": "רק תמונות שנמצאות באוסף (Collection) בליטרום ששמו כך. אפשר לכתוב חלק מהשם.",
    "rr_foldertext": "רק תמונות מתיקיות בקטלוג ששמן מכיל את הטקסט הזה. אפשר לכתוב חלק מהשם.",
    "rr_out": "המקום שבו יישמרו הדוח, הדירוגים והעותקים הקטנים. אם משאירים ריק, הכלי בוחר מקום בעצמו.",
    "rr_genre": "סוג הצילום משנה מה נחשב טוב: למשל ברחוב הרגע חשוב יותר מחדות, בספורט שיא התנועה וחדות הנושא. כך הדירוג מתאים יותר לסשן. לא חובה, ואפשר לשלב עם קובץ הטעם.",
    "rr_taste": "קובץ טקסט קצר שמתאר מה אתה אוהב בתמונה, כדי שהדירוג יתאים לטעם שלך. לא חובה.",
    "ag_results": "התיקייה שנוצרה בסשן הצילום ובה הקובץ ratings.csv. אם משאירים ריק, נלקחת תיקיית התוצאות של הסשן שמוגדרת בלשונית סשן הצילום.",
    "ag_stars": "תמונה שקיבלה ממך לפחות כמות כוכבים כזו, או דגל Pick, נחשבת לבחירה שלך. תמונות בלי כוכבים נחשבות לתמונות שלא בחרת, ולכן כדאי להריץ את הבדיקה על סשן שסיימת לברור בו בעצמך. אם הכלי כתב כוכבים לליטרום, הכוכבים האלה הם של הבינה המלאכותית והבדיקה לא תהיה אמינה.",
    "rr_other": "כברירת מחדל הכלי עובד רק על קבצי RAW. כשמסומן הוא יעבוד גם על JPEG, PNG, TIFF ו-HEIC. אם צילמת RAW וגם JPEG, קובץ JPEG שיש לו RAW באותו שם ידולג, כך שאותה תמונה לא תידרג פעמיים. כוכבים נכתבים לליטרום רק לקבצי RAW. קבצי HEIC דורשים התקנה של pillow-heif.",
    "rr_recursive": "לכלול גם את כל תתי-התיקיות של התיקייה שבחרת.",
    "rr_prepare": "רק מקבץ את התמונות ומראה את הקבוצות, בלי לשלוח כלום לבינה המלאכותית. מומלץ להתחיל כך, כדי לוודא שהקיבוץ הגיוני.",
    "rr_xmp": "כותב את הדירוג לליטרום כקובץ קטן ליד כל תמונה. בליטרום: Metadata, ואז Read Metadata from Files.",
    "rr_overwrite": "כשמסומן, גם תמונות שכבר יש להן כוכבים בליטרום יקבלו כוכבים חדשים. אחרת הן לא ייגעו. זמין רק כשכתיבת הכוכבים מסומנת.",
    "rr_limit": "כמה קבוצות לדרג בהרצה הזו. שימושי לניסוי קטן או למכסה יומית מוגבלת. 0 = את כולן.",
    "rr_sim": "כמה שתי תמונות צריכות להיות דומות כדי להיחשב אותה סדרה. נמוך = מחמיר יותר, ולכן קבוצות קטנות יותר. ברירת המחדל 0.30.",
    "rr_gap": "אם עברו יותר שניות מהתמונה הקודמת, מתחילה קבוצה חדשה. ברירת המחדל 120.",
    "rr_fargap": "תמונות של אותה סצנה שצולמו בהפרש של עד כמה שניות יקובצו יחד גם אם בניהן צולמו תמונות אחרות (למשל חזרת לאותו מקום). 0 = רק תמונות עוקבות. ברירת המחדל 1800 (חצי שעה).",
    "rr_maxgroup": "מקסימום תמונות בקבוצה אחת. קבוצה גדולה יותר מתחלקת. ריק = אוטומטי: הכלי מכיר את המגבלה של כל ספק, ואם מודל מסוים מקבל פחות תמונות הוא לומד את זה מהשגיאה ומקטין את הקבוצות לבד.",
    "rr_cands": "כמה מהתמונות הטובות ביותר ייבדקו שוב זו מול זו, כדי לבחור את בולטות הסשן. ריק = אוטומטי (עד 12, ולא יותר ממה שהספק מקבל בבקשה).",
    "rr_hls": "כמה מהבולטות יקבלו 4 כוכבים ומעלה בליטרום. ריק = כ-4% מהתמונות בסשן, לפחות 3.",
    "tr_source": "התמונות הישנות שרוצים לסרוק, כולל תתי-תיקיות. רק קבצי JPEG.",
    "ar_folder": "התיקייה שבה נשמרות תוצאות הניפוי: עותקים קטנים, דפי מגע ודוח. שלבים 2 ו-3 קוראים ממנה.",
    "tr_blur": "תמונה עם ציון חדות נמוך מהסף נחשבת מטושטשת. נמוך = מקל יותר, כלומר פחות תמונות יסוננו. ברירת המחדל 40.",
    "tr_exclude": "תיקיות ששמן מכיל אחת מהמילים האלה לא ייסרקו. מפרידים בין מילים ברווח.",
    "tr_cameras": "רק תמונות מהמצלמות האלה, לפי שם הדגם. מפרידים בפסיק. ריק = כל המצלמות.",
    "tr_listcams": "במקום לעבד, מציג כמה תמונות יש מכל דגם מצלמה. שימושי כדי לדעת מה לכתוב בשדה המצלמות.",
    "ar_limit": "כמה דפי מגע לדרג בהרצה הזו. 0 = את כולם.",
    "ar_min": "כדי להיבדק מקרוב, תמונה צריכה לפחות את הציון הזה בשלב 2. בתמונות עם אנשים הסף גבוה ב-1.",
    "ar_final": "ציון בבדיקה מקרוב שמכניס תמונה לתיקיית הגמר. בתמונות עם אנשים הסף גבוה ב-1.",
    "ar_max": "מקסימום תמונות לבדיקה מקרוב בהרצה אחת.",
    "key": "המפתח נשלח רק לספק שבחרת. אל תשתף אותו, ואל תצלם מסך שבו הוא נראה.",
    "model": "המודל שיסתכל על התמונות, יש לבחור במודל שיודע להבין תמונות (ניתן לברר פרטים ברשת). הכפתור משמאל מרענן את הרשימה למודלים העדכניים שהספק מציע.",
    "hl_model": "אפשר לבחור מודל חזק יותר רק לשלב בחירת הבולטות. ריק = אותו מודל.",
    "copy_models": "מעתיק ללוח את רשימת המודלים של הספק (אחרי 'הצג מודלים זמינים'), יחד עם שאלה מוכנה, כדי להדביק בצ'אטבוט ולוודא איזה מהם חינמי ומה המכסות. הרשימה עצמה לא אומרת מה חינמי, חוץ מ-OpenRouter.",
    "base_url": "כתובת השרת. נדרשת בספק 'אחר', ואפשר לשנות אותה ב-Ollama וב-LM Studio אם השרת לא רץ בכתובת הרגילה.",
    "delay": "הפסקה בין בקשות, כדי לא לחרוג ממגבלת הקצב של הספק. ריק = ברירת המחדל של הספק.",
    "only_free": "ב-OpenRouter, מסנן את רשימת המודלים כך שיוצגו רק החינמיים.",
    "rr_prefilter": "לפני השליחה לבינה המלאכותית, הכלי בודק במחשב שלך ומדלג רק על טעויות טכניות ברורות: תמונה חשוכה מאוד, חשופה מאוד או מטושטשת מאוד. זה חוסך מכסה וזמן. התמונות שדולגו מופיעות בדוח, ושום דבר לא נמחק.",
    "rr_preblur": "תמונה שמדד החדות שלה נמוך מהמספר הזה נחשבת מטושטשת מאוד, ולכן לא נשלחת לדירוג. זו לא סקאלה של 1 עד 100, ואין לה תקרה: תמונה חדה מקבלת בדרך כלל הרבה יותר מהסף. נמוך יותר = זהיר יותר, כלומר פחות תמונות נפסלות. 0 = לא פוסלים בגלל טשטוש בכלל. ברירת המחדל היא 12, ובניפוי הארכיון הסף הרגיל הוא 40.",
    "dp_near": "מחפש גם את אותה תמונה שנשמרה שוב בגודל או בדחיסה אחרים. צילומי רצף ותמונות מאותה זווית לא נחשבים כפילות, כי הזמן שבו צולמו שונה.",
    "save_key": ("שומר את המפתח באחסון הסיסמאות של Windows, מוצפן ומשויך לחשבון המשתמש שלך. "
                 "כשמבטלים את הסימון, המפתח נמחק משם." if secret_store.available() else
                 "שומר את המפתח בקובץ ההגדרות במחשב הזה. נוח, אבל מי שיגיע לקובץ יראה אותו."),
}
# settings that "Restore defaults" resets, and that are highlighted once changed (paths and the AI connection are not)
RESET_KEYS = ("rr_prefilter", "rr_preblur", "dp_near", "dp_recursive", "rr_recursive", "rr_other", "ag_stars", "rr_prepare", "rr_xmp", "rr_overwrite", "rr_since", "rr_until", "rr_collection",
              "rr_foldertext", "rr_limit", "rr_sim", "rr_gap", "rr_fargap", "rr_maxgroup", "rr_cands", "rr_hls",
              "tr_blur", "tr_exclude", "tr_cameras", "tr_listcams", "ar_limit", "ar_min", "ar_final", "ar_max",
              "delay", "only_free")


class StopRun(BaseException):
    """Raised inside the worker thread when the user presses Stop."""


class QWriter:
    """Receives everything the tools print and hands it to the window."""
    def __init__(self, q):
        self.q = q

    def write(self, s):
        if s:
            self.q.put(s)
        return len(s)

    def flush(self):
        pass

    def isatty(self):
        return False


# ---------------------------------------------------------------- keyboard shortcuts + right-click menu
def make_undoable(widget, var):
    """Simple undo/redo history for an entry that is bound to a StringVar."""
    hist, redo, busy = [var.get()], [], [False]

    def changed(*_):
        if busy[0]:
            return
        cur = var.get()
        if cur != hist[-1]:
            hist.append(cur)
            redo.clear()
            if len(hist) > 200:
                del hist[0]

    def apply(value):
        busy[0] = True
        var.set(value)
        busy[0] = False
        try:
            widget.icursor("end")
        except tk.TclError:
            pass

    def undo():
        if len(hist) > 1:
            redo.append(hist.pop())
            apply(hist[-1])

    def redo_():
        if redo:
            hist.append(redo.pop())
            apply(hist[-1])

    var.trace_add("write", changed)
    widget._undo, widget._redo = undo, redo_


def do_action(w, key):
    if key in ("c", "a") and hasattr(w, "_pick_copy"):      # the log and the guide pick whole lines themselves
        (w._pick_copy if key == "c" else w._pick_all)()
        return
    if key == "c":
        w.event_generate("<<Copy>>")
        if getattr(w, "_readonly", False):          # the log carries direction marks: copy clean text
            try:
                clean = bidi_text.strip(w.clipboard_get())
                w.clipboard_clear()
                w.clipboard_append(clean)
            except tk.TclError:
                pass
    elif key == "x" and not getattr(w, "_readonly", False):
        w.event_generate("<<Cut>>")
    elif key == "v" and not getattr(w, "_readonly", False):
        w.event_generate("<<Paste>>")
    elif key == "a":
        if isinstance(w, tk.Text):
            w.tag_add("sel", "1.0", "end-1c")
        else:
            w.selection_range(0, "end")
            w.icursor("end")
    elif key == "z" and hasattr(w, "_undo"):
        w._undo()
    elif key == "y" and hasattr(w, "_redo"):
        w._redo()


def key_from_event(event):
    key = VK.get(event.keycode) if IS_WIN else None
    if key is None and len(event.keysym) == 1:
        key = event.keysym.lower()
    return key if key in SHORTCUT_KEYS else None


def on_ctrl_key(event):
    """Ctrl+C / V / X / A / Z / Y on any keyboard layout (including Hebrew)."""
    key = key_from_event(event)
    if key:
        do_action(event.widget, key)
    return "break"


def on_right_click(event):
    w = event.widget
    w.focus_set()
    is_text = isinstance(w, tk.Text)
    m = tk.Menu(w, tearoff=0, background=THEME["surface"], foreground=THEME["fg"],
                activebackground=THEME["sel"], activeforeground=THEME["sel_fg"], borderwidth=1, relief="flat")
    if not is_text:
        m.add_command(label=tr("בטל"), command=lambda: do_action(w, "z"))
        m.add_command(label=tr("חזור"), command=lambda: do_action(w, "y"))
        m.add_separator()
        m.add_command(label=tr("גזור"), command=lambda: do_action(w, "x"))
    m.add_command(label=tr("העתק"), command=lambda: do_action(w, "c"))
    if not is_text:
        m.add_command(label=tr("הדבק"), command=lambda: do_action(w, "v"))
    m.add_command(label=tr("בחר הכול"), command=lambda: do_action(w, "a"))
    try:
        m.tk_popup(event.x_root, event.y_root)
    finally:
        m.grab_release()
    return "break"


def install_editing_support(root):
    for cls in ("TEntry", "TCombobox", "Text"):
        root.bind_class(cls, "<Control-Key>", on_ctrl_key)
        for k in SHORTCUT_KEYS:
            root.bind_class(cls, f"<Control-{k}>", on_ctrl_key)
            root.bind_class(cls, f"<Control-{k.upper()}>", on_ctrl_key)
        root.bind_class(cls, "<Button-3>", on_right_click)
        if IS_MAC:                                      # a Mac right click is Button-2, or Control + click
            root.bind_class(cls, "<Button-2>", on_right_click)
            root.bind_class(cls, "<Control-Button-1>", on_right_click)
    # a read-only Text does not take focus on click by itself, so Ctrl+C would never reach it
    root.bind_class("Text", "<Button-1>", lambda e: e.widget.focus_set(), add="+")


def restart_command():
    """(args, keyword arguments) that start this program again as a completely separate process.

    A one-file EXE unpacks itself into a temporary folder and deletes it on exit. A copy started from inside
    it inherits the same folder from the environment, so closing the first copy pulled the files out from
    under the second ("Failed to remove temporary directory", "Failed to import encodings module").
    Clearing those variables makes the new copy unpack its own files, and on Windows it also starts detached.
    """
    frozen = getattr(sys, "frozen", False)
    args = [sys.executable] + (sys.argv[1:] if frozen else sys.argv)
    kw = {"close_fds": True}
    if frozen:
        env = {k: v for k, v in os.environ.items() if k != "_MEIPASS2" and not k.startswith("_PYI_")}
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        kw["env"] = env
    if sys.platform == "win32":
        kw["creationflags"] = 0x00000008 | 0x00000200      # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    return (args,), kw


class FilterCombobox(ttk.Combobox):
    """A combo box you can type in to search. While you type, a small list under the field shows only the
    matching entries (anywhere in the name); Up and Down move in it, Enter picks, Escape closes.
    The list never takes the keyboard, so typing carries on, which the built-in drop-down does not allow."""
    MAX_ROWS = 10

    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        self._pop = None
        self._lb = None
        self.bind("<KeyRelease>", self._typed, add="+")
        self.bind("<Down>", self._move_down, add="+")
        self.bind("<Up>", self._move_up, add="+")
        self.bind("<Return>", self._pick, add="+")
        self.bind("<Escape>", self._close, add="+")
        self.bind("<FocusOut>", lambda e: self.after(150, self._close), add="+")
        self.bind("<Button-1>", self._arrow, add="+")

    def _arrow(self, e):
        """The arrow opens this list (all the entries, with the current one marked) instead of the built-in drop-down,
        which would take the keyboard and end the search."""
        try:
            on_arrow = self.identify(e.x, e.y) == "downarrow"
        except tk.TclError:
            on_arrow = False
        if not on_arrow or str(self.cget("state")) == "disabled":
            return None
        if self._open():
            self._close()
        else:
            self.focus_set()
            self._show(everything=True)
        return "break"

    def _matches(self):
        text = self.get().strip().lower()
        values = [str(v) for v in self.cget("values") if str(v)]
        return [v for v in values if text in v.lower()] if text else values

    def _typed(self, event):
        if event.keysym in ("Up", "Down", "Return", "Escape", "Tab", "Shift_L", "Shift_R", "Control_L", "Control_R",
                            "Alt_L", "Alt_R", "Left", "Right", "Home", "End", "ISO_Left_Tab"):
            return
        self._show()

    def _show(self, everything=False):
        found = [str(v) for v in self.cget("values") if str(v)] if everything else self._matches()
        if not found:
            self._close()
            return
        if self._pop is None or not self._pop.winfo_exists():
            self._pop = tk.Toplevel(self)
            self._pop.wm_overrideredirect(True)
            self._lb = tk.Listbox(self._pop, exportselection=False, activestyle="none", borderwidth=1,
                                  relief="solid", highlightthickness=0, font=(UI_FONT, 10),
                                  background=THEME["field"], foreground=THEME["fg"],
                                  selectbackground=THEME["sel"], selectforeground=THEME["sel_fg"])
            self._sb = ttk.Scrollbar(self._pop, command=self._lb.yview)
            self._lb.configure(yscrollcommand=self._sb.set)
            self._lb.pack(side="left", fill="both", expand=True)
            self._lb.bind("<ButtonRelease-1>", self._click)
        self._lb.delete(0, "end")
        for v in found:
            self._lb.insert("end", v)
        self._lb.configure(height=min(self.MAX_ROWS, len(found)))
        if len(found) > self.MAX_ROWS:
            self._sb.pack(side="right", fill="y")
        else:
            self._sb.pack_forget()
        cur = self.get()
        if everything and cur in found:                        # mark and show the entry that is chosen now
            i = found.index(cur)
            self._lb.selection_set(i)
            self._lb.see(i)
        self.update_idletasks()
        self._pop.geometry(f"{self.winfo_width()}x{self._lb.winfo_reqheight()}+{self.winfo_rootx()}+{self.winfo_rooty() + self.winfo_height()}")
        self._pop.lift()

    def _close(self, _e=None):
        if self._pop is not None:
            try:
                self._pop.destroy()
            except tk.TclError:
                pass
        self._pop = self._lb = None

    def _open(self):
        return self._pop is not None and self._pop.winfo_exists()

    def _step(self, d):
        if not self._open():
            return False
        cur = self._lb.curselection()
        i = (cur[0] + d) if cur else (0 if d > 0 else self._lb.size() - 1)
        i = max(0, min(self._lb.size() - 1, i))
        self._lb.selection_clear(0, "end")
        self._lb.selection_set(i)
        self._lb.see(i)
        return True

    def _move_down(self, e):
        return "break" if self._step(1) else None

    def _move_up(self, e):
        return "break" if self._step(-1) else None

    def _choose(self, value):
        self.set(value)
        self.icursor("end")
        self._close()
        self.event_generate("<<ComboboxSelected>>")

    def _pick(self, e):
        if self._open() and self._lb.curselection():
            self._choose(self._lb.get(self._lb.curselection()[0]))
            return "break"
        self._close()

    def _click(self, e):
        i = self._lb.nearest(e.y)
        if 0 <= i < self._lb.size():
            self._choose(self._lb.get(i))
        self.focus_set()


# ---------------------------------------------------------------- scrollable area
class ScrollFrame(ttk.Frame):
    """A frame that gets a scrollbar when its content is taller than the window."""
    def __init__(self, parent):
        super().__init__(parent)
        bg = ttk.Style().lookup("TFrame", "background") or "#f0f0f0"
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, background=bg)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side=X("left"), fill="y")
        self.canvas.pack(side=X("left"), fill="both", expand=True)
        self.inner = ttk.Frame(self.canvas)
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.win, width=e.width))
        self.smooth = SmoothScroller(self.canvas)

    def scroll(self, steps):
        """steps < 0 scrolls up, as in the old unit-based call: three steps are one wheel notch."""
        if self.inner.winfo_reqheight() > self.canvas.winfo_height():
            self.smooth.notches(-steps / 3)


# ---------------------------------------------------------------- building the command lines
def _num(text, name, kind=float, minimum=None):
    try:
        v = kind(str(text).strip())
    except ValueError:
        raise ValueError(f'בשדה "{name}" צריך להזין מספר')
    if minimum is not None and v < minimum:
        raise ValueError(f'המספר בשדה "{name}" קטן מדי')
    return v


def ai_args(g, need_ai=True, need_model=True):
    """The provider-related part of the command line (shared by rate_raw and ai_rate)."""
    prov = g("provider")
    pinfo = llm.PROVIDERS[prov]
    base = g("base_url").strip()
    if prov == "custom" and not base:
        if not need_ai:
            return []          # only checking the grouping: no provider needed
        raise ValueError('בספק "אחר" צריך למלא כתובת שרת (למשל https://.../v1)')
    a = ["--provider", prov]
    if base:
        a += ["--base-url", base]
    if not need_ai:
        return a
    key = g("key").strip()
    if pinfo["key_required"] and not key:
        raise ValueError(f"צריך מפתח API עבור {pinfo['label']}")
    if key:
        a += ["--key", key]
    model = g("model").strip()
    if need_model:
        if not model:
            raise ValueError("צריך לבחור מודל (אפשר ללחוץ על 'הצג מודלים זמינים')")
        a += ["--model", model]
    if g("delay").strip():
        a += ["--delay", str(_num(g("delay"), "המתנה בין בקשות", float, 0))]
    return a


def build_rate_raw_args(g):
    a = []
    if g("rr_mode") == "catalog":
        if not g("rr_catalog"):
            raise ValueError("צריך לבחור קטלוג ליטרום")
        a += ["--catalog", g("rr_catalog")]
        for k, flag in (("rr_since", "--since"), ("rr_until", "--until"),
                        ("rr_collection", "--collection"), ("rr_foldertext", "--folder-contains")):
            if g(k).strip():
                a += [flag, g(k).strip()]
        out = g("rr_out") or str(Path.home() / "Documents" / f"rating_{Path(g('rr_catalog')).stem}")
    else:
        if not g("rr_source"):
            raise ValueError("צריך לבחור תיקיית צילומים")
        a.append(g("rr_source"))
        if g("rr_recursive"):
            a.append("--recursive")
        out = g("rr_out") or str(Path(g("rr_source")) / "_rating")
    a += ["--out", out]
    if g("rr_other"):
        a.append("--include-other")
    if not g("rr_prefilter"):
        a.append("--no-prefilter")
    else:
        a += ["--prefilter-blur", str(_num(g("rr_preblur"), "סף הטשטוש המקדים", float, 0))]
    if g("rr_prepare"):
        a.append("--prepare-only")
        a += ai_args(g, need_ai=False)
    else:
        a += ai_args(g)
        if g("hl_model").strip():
            a += ["--highlight-model", g("hl_model").strip()]
    if g("rr_taste"):
        a += ["--taste", g("rr_taste")]
    if g("rr_genre"):
        a += ["--genre", g("rr_genre")]
    a += ["--limit", str(_num(g("rr_limit"), "כמה קבוצות לדרג עכשיו", int, 0)),
          "--similarity", str(_num(g("rr_sim"), "רגישות הקיבוץ", float, 0.001)),
          "--gap", str(_num(g("rr_gap"), "פער בשניות בין קבוצות", float, 0)),
          "--far-gap", str(_num(g("rr_fargap"), "חיפוש תמונות דומות רחוקות בזמן", float, 0))]
    for name, flag, title, minimum in (("rr_maxgroup", "--max-group", "מקסימום תמונות בקבוצה", 2),
                                       ("rr_cands", "--candidates", "כמה תמונות מתחרות על הבולטות", 3),
                                       ("rr_hls", "--highlights", "כמה מהבולטות יקבלו 4 כוכבים", 1)):
        if g(name).strip():                           # empty = automatic
            a += [flag, str(_num(g(name), title, int, minimum))]
    if g("rr_xmp"):
        a.append("--write-xmp")
        if g("rr_overwrite"):
            a.append("--overwrite-ratings")
    return a, Path(out)


def build_triage_args(g):
    if not g("tr_source"):
        raise ValueError("צריך לבחור את תיקיית הארכיון")
    out = g("ar_folder") or str(Path.home() / "Documents" / "triage_output")
    a = [g("tr_source"), "--out", out]
    if g("tr_listcams"):
        a.append("--list-cameras")
    a += ["--blur", str(_num(g("tr_blur"), "סף הטשטוש", float, 0))]
    if g("tr_cameras").strip():
        a += ["--cameras", g("tr_cameras").strip()]
    a.append("--exclude")
    a += g("tr_exclude").split()
    return a, Path(out)


def build_dupes_args(g):
    if not g("dp_source"):
        raise ValueError("צריך לבחור את תיקיית התמונות")
    out = g("dp_out") or str(Path.home() / "Documents" / "duplicates_report")
    a = [g("dp_source"), "--out", out]
    if g("dp_recursive"):
        a.append("--recursive")
    if not g("dp_near"):
        a.append("--no-near")
    return a, Path(out)


def build_agreement_args(g):
    res = g("ag_results") or g("rr_out") or (str(Path(g("rr_source")) / "_rating") if g("rr_source") else "")
    if not res or not Path(res).is_dir():
        raise ValueError("צריך לבחור את תיקיית התוצאות של סשן צילום שכבר דורג")
    if not g("rr_catalog"):
        raise ValueError("צריך לבחור את קובץ הקטלוג של ליטרום, שבו דירגת את אותן תמונות")
    stars = _num(g("ag_stars"), "כוכבים שנחשבים לבחירה שלך", int, 1)
    return [res, "--catalog", g("rr_catalog"), "--min-stars", str(stars)], Path(res) / "agreement"


def build_airate_args(g):
    if not g("ar_folder"):
        raise ValueError("צריך לבחור את תיקיית התוצאות מהניפוי. היא נוצרת בשלב 1")
    cmd = g("ar_cmd")
    a = [cmd, g("ar_folder")] + ai_args(g, need_model=(cmd != "models"))
    if cmd == "rate":
        a += ["--limit", str(_num(g("ar_limit"), "כמה דפים לדרג עכשיו", int, 0))]
    if cmd == "refine":
        a += ["--min-score", str(_num(g("ar_min"), "ציון מינימלי להמשך", float, 1)),
              "--final-score", str(_num(g("ar_final"), "ציון להיכנס לגמר", float, 1)),
              "--max-candidates", str(_num(g("ar_max"), "מקסימום תמונות לבדיקה", int, 1))]
    return a, Path(g("ar_folder"))


# ---------------------------------------------------------------- the app
ADDRESS_PROVIDERS = ("custom", "ollama", "lmstudio")     # providers where you may need to type a server address
PER_PROVIDER = ("key", "model", "hl_model", "base_url")
# a profile remembers the tool settings and the model, never paths or the key
PROFILE_KEYS = RESET_KEYS + ("rr_mode", "ar_cmd", "rr_taste", "rr_genre")
# fields that take a dropped folder / a dropped file, and how to call them in the log
DIR_FIELDS = ("rr_source", "tr_source", "ar_folder", "rr_out", "dp_source", "dp_out", "ag_results")
FILE_FIELDS = ("rr_catalog", "rr_taste")
FIELD_TITLES = {"rr_source": "תיקיית הצילומים", "rr_catalog": "קובץ הקטלוג", "rr_out": "תיקיית התוצאות",
                "rr_taste": "קובץ הטעם", "tr_source": "תיקיית הארכיון", "ar_folder": "תיקיית התוצאות",
                "dp_source": "תיקיית הכפילויות", "dp_out": "תיקיית הדוח", "ag_results": "תיקיית התוצאות"}


class App:
    def __init__(self, root):
        self.root = root
        root.title("FocalPick")
        try:
            self._icons = [tk.PhotoImage(data=d) for d in ICON_PNG_B64.values()]
            root.iconphoto(True, *self._icons)
        except tk.TclError:
            pass
        self.saved = self.load_settings()
        self.sc = max(1.0, root.winfo_fpixels("1i") / 96.0)         # display scaling (1.0 = 100%)
        h = int(min(800 * self.sc, max(420, root.winfo_screenheight() - 120)))
        root.geometry(self.start_geometry(int(920 * self.sc), h))
        root.minsize(int(640 * self.sc), int(420 * self.sc))
        install_editing_support(root)
        self.style = ttk.Style()
        self.combos = []
        self.row_widgets = {}
        self.defaults = {}
        self.pg_events, self.pg_total = [], 0
        llm.confirm_hook = self.ask_from_worker
        self._bol, self._tag = True, "ltr"
        self._log_pending = ""
        self.dark = False
        self.v = {}
        self.q = queue.Queue()
        self.thread = None
        self.last_out = None
        self.had_error = False
        self.pstate = self.saved.get("providers", {})
        raw = self.saved.get("profiles")
        self.profiles = {str(n): d for n, d in raw.items() if isinstance(d, dict)} if isinstance(raw, dict) else {}
        self.labels = {llm.PROVIDERS[k]["label"]: k for k in llm.ORDER}
        self.fonts = {"base": tkfont.Font(root=root, family=UI_FONT, size=10),
                      "bold": tkfont.Font(root=root, family=UI_FONT, size=10, weight="bold"),
                      "small": tkfont.Font(root=root, family=UI_FONT, size=9),
                      "foot": tkfont.Font(root=root, family=UI_FONT, size=8)}
        self.font_sizes = {"base": 10, "bold": 10, "small": 9, "foot": 8}
        self.ui_factor, self.design_w, self._scale_job = 1.0, 0, None
        self.build_ui()
        self.apply_theme()
        self.append_log("שלום! אחרי הלחיצה על 'הפעל' יוצג כאן מה קורה, שלב אחר שלב.\n")
        self.poll()
        self.dnd = win_dnd.enable_file_drop(root, self.on_drop)
        self.root.after(4000, self.watch_system_theme)
        root.bind("<Return>", self.on_return)
        root.bind("<KP_Enter>", self.on_return)
        root.bind("<Escape>", self.on_escape)
        root.bind("<Configure>", self.on_root_configure, add="+")

    MIN_FACTOR, MAX_FACTOR = 0.85, 1.3

    def apply_factor(self, f):
        """Text size and button margins of the whole interface, as a proportion of the normal size."""
        self.ui_factor = f
        for name, size in self.font_sizes.items():
            self.fonts[name].configure(size=max(7, round(size * f)))
        pad = lambda n: max(2, round(n * f))
        self.style.configure("TButton", padding=(pad(10), pad(4)))
        self.style.configure("Small.TButton", padding=(pad(10), pad(2)))
        self.style.configure("Run.TButton", padding=(pad(20), pad(5)))

    def strip_width(self):
        self.root.update_idletasks()
        return max(self.top_strip.winfo_reqwidth(), self.bottom_bar.winfo_reqwidth()) + 24

    def fit_width(self):
        """Narrower windows shrink the text and the buttons of the whole interface in proportion (down to 85%), wider
        ones enlarge them (up to 130%), so nothing is cut off. The smallest window is the one in which the top strip
        and the button bar still fit at the smallest size."""
        if self.design_w:
            return
        self.apply_factor(1.0)
        self.design_w = self.strip_width()
        self.apply_factor(self.MIN_FACTOR)
        narrowest = self.strip_width()
        self.root.minsize(max(int(520 * self.sc), narrowest), int(420 * self.sc))
        self.apply_factor(1.0)
        self.scale_ui()

    def on_root_configure(self, event):
        if event.widget is not self.root or not self.design_w:
            return
        if self._scale_job:
            self.root.after_cancel(self._scale_job)
        self._scale_job = self.root.after(120, self.scale_ui)

    def scale_ui(self):
        self._scale_job = None
        if not self.design_w:
            return
        f = max(self.MIN_FACTOR, min(self.MAX_FACTOR, self.root.winfo_width() / self.design_w))
        f = round(f * 20) / 20                                   # steps of 5%: no flicker while dragging
        if f != self.ui_factor:
            self.apply_factor(f)

    def start_geometry(self, w, h):
        """Last window size and position, if they still fit on the screen."""
        geo = self.saved.get("geometry", "")
        m = re.fullmatch(r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", geo or "")
        if m:
            gw, gh, gx, gy = int(m[1]), int(m[2]), int(m[3]), int(m[4])
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            if 300 <= gw <= sw and 300 <= gh <= sh and -50 <= gx <= sw - 150 and 0 <= gy <= sh - 100:
                return f"{gw}x{gh}{gx:+d}{gy:+d}"
        return f"{w}x{h}"

    def on_return(self, event):
        # Enter runs only from a text field or from empty space; buttons, boxes and the log keep their own Enter
        if event.widget.winfo_class() not in ("TEntry", "Tk", "Toplevel", "TFrame", "TLabel", "Canvas") \
                or self.run_btn.instate(["disabled"]):
            return
        self.start_run()

    def on_escape(self, _event):
        if self.thread and self.thread.is_alive():
            self.stop_run()

    # ---- variables / settings
    OLD_AUTO = {"rr_maxgroup": "8", "rr_cands": "12", "rr_hls": "5", "rr_sim": "0.10"}     # former defaults: now "automatic" (empty)

    def var(self, name, default="", kind="str"):
        val = self.saved.get(name, default)
        if name in self.OLD_AUTO and str(val).strip() == self.OLD_AUTO[name]:
            val = default
        v = tk.BooleanVar(value=bool(val)) if kind == "bool" else tk.StringVar(value=str(val))
        self.v[name] = v
        self.defaults[name] = bool(default) if kind == "bool" else str(default)
        return v

    def is_changed(self, name):
        cur, d = self.v[name].get(), self.defaults.get(name)
        if isinstance(cur, bool):
            return cur != bool(d)
        a, b = str(cur).strip(), str(d).strip()
        if a == b:
            return False
        try:
            return float(a) != float(b)
        except ValueError:
            return True

    def watch_changed(self, name, widget, base_style):
        """A field whose value differs from the default gets a different colour."""
        def update(*_):
            widget.configure(style=("Changed." + base_style) if self.is_changed(name) else base_style)
        self.v[name].trace_add("write", update)
        update()

    def reset_defaults(self):
        if not mb.askyesno("שחזור ברירות מחדל",
                                   "להחזיר את הגדרות הכלים לברירת המחדל?\n"
                                   "הנתיבים והחיבור לספק לא ישתנו."):
            return
        for name in RESET_KEYS:
            if name in self.v:
                self.v[name].set(self.defaults[name])

    def g(self, name):
        if name == "provider":
            return self.labels.get(self.v["provider_label"].get(), "gemini")
        return self.v[name].get()

    def load_settings(self):
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def capture_provider(self, prov):
        st = self.pstate.setdefault(prov, {})
        for k in PER_PROVIDER:
            st[k] = self.v[k].get()

    def save_settings(self):
        prov = self.g("provider")
        self.capture_provider(prov)
        skip = set(PER_PROVIDER) | {"provider_label"}
        data = {k: v.get() for k, v in self.v.items() if k not in skip}
        data["provider"] = prov
        provs = {}
        for pr, st in self.pstate.items():
            st = dict(st)
            key = st.pop("key", "")
            if self.g("save_key") and key:
                if not secret_store.save(pr, key):       # no secure store here: keep it in the settings file
                    st["key"] = key
            elif secret_store.available() and (not self.g("save_key") or pr == prov):
                secret_store.delete(pr)                  # unticked, or the field was cleared: forget it
            provs[pr] = st
        data["providers"] = provs
        data["profiles"] = self.profiles
        if self.saved.get("privacy_ack"):
            data["privacy_ack"] = True
        try:
            if self.root.state() == "normal":
                data["geometry"] = self.root.geometry()
            elif "geometry" in self.saved:
                data["geometry"] = self.saved["geometry"]
        except tk.TclError:
            pass
        try:
            SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass

    # ---- small UI helpers (right-to-left rows: label on the right)
    def row(self, parent, r, label, widget_factory, browse=None):
        lab = ttk.Label(parent, text=R(label), anchor=X("e"), justify=X("right"))
        lab.grid(row=r, column=i18n.col(2), sticky=X("e"), padx=6, pady=3)
        w = widget_factory(parent)
        w.grid(row=r, column=1, sticky="ew", pady=3)
        widgets = [lab, w]
        if browse:
            b = ttk.Button(parent, text=tr("בחר..."), width=8, command=browse)
            b.grid(row=r, column=i18n.col(0), padx=4)
            widgets.append(b)
        self.row_widgets[(str(parent), r)] = widgets
        parent.columnconfigure(1, weight=1)
        name = getattr(w, "_name", None)
        if name:
            if name in TIPS:
                Tooltip(lab, TIPS[name])
                Tooltip(w, TIPS[name])
            if name in RESET_KEYS:
                self.watch_changed(name, lab, "TLabel")
        return w

    def show_rows(self, parent, rows, visible):
        """Show or hide whole rows of a form (the grid remembers where each widget belongs)."""
        for r in rows:
            for w in self.row_widgets.get((str(parent), r), []):
                if visible:
                    w.grid()
                else:
                    w.grid_remove()

    def entry(self, name, default="", show=None, hebrew=False):
        """Text field. Paths, keys and addresses read left-to-right; pass hebrew=True for free Hebrew text."""
        v = self.var(name, default)

        def make(p):
            e = ttk.Entry(p, textvariable=v, show=show, width=30, justify=X("right") if hebrew else "left")
            make_undoable(e, v)
            e._name = name
            return e
        return make

    def short(self, name, default):
        v = self.var(name, default)

        def make(p):
            e = ttk.Entry(p, textvariable=v, width=10, justify="center")
            make_undoable(e, v)
            e._name = name
            return e
        return make

    def check(self, parent, r, name, text, default=False):
        v = self.var(name, default, "bool")
        cb = ttk.Checkbutton(parent, text=R(text), variable=v, style="RTL.TCheckbutton")
        cb.grid(row=r, column=i18n.col(1, 2), columnspan=2, sticky=X("e"), pady=2, padx=6)
        self.row_widgets[(str(parent), r)] = [cb]
        if name in TIPS:
            Tooltip(cb, TIPS[name])
        if name in RESET_KEYS:
            self.watch_changed(name, cb, "RTL.TCheckbutton")
        return v

    def pick_dir(self, name):
        def f():
            d = filedialog.askdirectory(initialdir=self.g(name) or None)
            if d:
                self.v[name].set(os.path.normpath(d))
        return f

    def pick_file(self, name, types):
        def f():
            p = filedialog.askopenfilename(filetypes=types)
            if p:
                self.v[name].set(os.path.normpath(p))
        return f

    def wrapped(self, lbl, text, margin=12):
        """A label with long Hebrew text: wrapped here, line by line, so each line keeps a right-to-left base."""
        if not hasattr(lbl, "_font"):
            lbl._font = tkfont.Font(font=(UI_FONT, 10))
            lbl._shown = None

            def refit(_e=None):
                w = max(240, lbl.winfo_width() - margin) if lbl.winfo_width() > 1 else int(560 * self.sc)
                shown = bidi_text.wrap_text(i18n.tr(lbl._text), w, lbl._font, i18n.rtl())
                if shown != lbl._shown:
                    lbl._shown = shown
                    lbl.configure(text=shown)
            lbl._refit = refit
            lbl.bind("<Configure>", refit)
        lbl._text = text
        lbl._refit()

    def tab(self, nb, title, hint):
        f = ttk.Frame(nb)
        f.tab_title = R(title)
        lbl = ttk.Label(f, text="", style="Hint.TLabel", anchor=X("e"), justify=X("right"))
        self.wrapped(lbl, hint)
        lbl.pack(fill="x", padx=12, pady=(8, 4))
        inner = ttk.Frame(f)
        inner.pack(fill="x", padx=6, pady=(0, 6))
        return inner

    # ---- layout
    def build_ui(self):
        # a small, quiet copyright line at the very bottom
        ttk.Label(self.root, text=R("כל הזכויות שמורות לנתאי שנדורפי ©"), style="Foot.TLabel").pack(
            side="bottom", pady=(0, 3))
        # bottom bar next, so Run/Stop are always visible even in a small window
        bar = self.bottom_bar = ttk.Frame(self.root)
        bar.pack(side="bottom", fill="x", padx=10, pady=6)
        self.run_btn = ttk.Button(bar, text=tr("הפעל"), style="Run.TButton", command=self.start_run)
        self.run_btn.pack(side=X("right"), padx=4, fill="x", expand=True)
        Tooltip(self.run_btn, "מפעיל את הכלי בלשונית שנבחרה. אפשר גם ללחוץ Enter.")
        self.stop_btn = ttk.Button(bar, text=tr("עצור"), command=self.stop_run, state="disabled")
        Tooltip(self.stop_btn, "עוצר אחרי הפעולה הנוכחית. מה שכבר נעשה נשמר, והרצה חוזרת ממשיכה מאותה נקודה. אפשר גם ללחוץ Esc.")
        self.stop_btn.pack(side=X("right"), padx=4, fill="x", expand=True)
        self.open_btn = ttk.Button(bar, text=tr("פתח את תיקיית התוצאות"), command=self.open_out, state="disabled")
        self.open_btn.pack(side=X("left"), padx=4, fill="x", expand=True)
        self.report_btn = ttk.Button(bar, text=tr("פתח את הדוח"), command=self.open_report, state="disabled")
        self.report_btn.pack(side=X("left"), padx=4, fill="x", expand=True)
        self.gallery_btn = ttk.Button(bar, text=tr("הצג תוצאות בחלון"), command=self.show_results)
        self.gallery_btn.pack(side=X("left"), padx=4, fill="x", expand=True)
        self.help_btn = ttk.Button(bar, text=tr("מדריך"), style="Small.TButton", command=self.show_help)
        self.help_btn.pack(side=X("left"), padx=4, fill="x", expand=True)
        self.adv_btn = ttk.Button(bar, text=tr("מתקדם..."), style="Small.TButton", command=self.show_advanced)
        self.adv_btn.pack(side=X("left"), padx=4, fill="x", expand=True)
        self.root.bind("<F1>", lambda _e: self.show_help())
        Tooltip(self.gallery_btn, "פותח גלריה של התוצאות: אפשר למיין, לסנן לפי ציון ולהגדיל תמונה. "
                                  "אם עוד לא הרצת כלי, תתבקש לבחור תיקיית תוצאות.")

        # appearance switch, in the top corner on the left (the "settings" corner in a right-to-left window)
        top = self.top_strip = ttk.Frame(self.root)
        top.pack(side="top", fill="x", padx=12, pady=(8, 0))
        self.theme_var = self.var("theme", "system")
        names = {k: tr(n) for k, n in THEME_CHOICES}
        self.theme_label = tk.StringVar(value=names.get(self.theme_var.get(), names["system"]))
        box = ttk.Combobox(top, textvariable=self.theme_label, values=[tr(n) for _, n in THEME_CHOICES],
                           state="readonly", width=8, justify=X("right"))
        box.pack(side=X("left"))
        ttk.Label(top, text=R("מראה:"), style="Hint.TLabel").pack(side=X("left"), padx=(0, 6))
        box.bind("<<ComboboxSelected>>", self.on_theme_choice)
        self.combos.append(box)
        self.lang_names = i18n.available()
        self.lang_var = self.var("lang", i18n.LANG)
        self.lang_label = tk.StringVar(value=self.lang_names.get(i18n.LANG, "English"))
        lang_box = ttk.Combobox(top, textvariable=self.lang_label, values=list(self.lang_names.values()),
                                state="readonly", width=7)
        lang_box.pack(side=X("left"), padx=(18, 0))
        lang_box.bind("<<ComboboxSelected>>", self.on_lang_choice)
        self.combos.append(lang_box)
        ttk.Label(top, text=R("שפה:"), style="Hint.TLabel").pack(side=X("left"), padx=(18, 6))
        rb = ttk.Button(top, text=tr("שחזר ברירות מחדל"), style="Small.TButton", command=self.reset_defaults)
        rb.pack(side=X("left"), padx=(18, 0))
        self.about_btn = ttk.Button(top, text=tr("אודות"), style="Small.TButton", command=self.show_about)
        self.about_btn.pack(side=X("left"), padx=(8, 0))
        # profiles: named sets of tool settings, on the right of the strip
        ttk.Label(top, text=R("פרופיל:"), style="Hint.TLabel").pack(side=X("right"), padx=(0, 6))
        self.profile_var = tk.StringVar(value="")
        self.profile_box = ttk.Combobox(top, textvariable=self.profile_var, state="readonly", width=10,
                                        justify=X("right"), values=sorted(self.profiles))
        self.profile_box.pack(side=X("right"))
        self.profile_box.bind("<<ComboboxSelected>>", self.on_profile_pick)
        self.combos.append(self.profile_box)
        Tooltip(self.profile_box, "פרופיל הוא קבוצת הגדרות בשם, למשל 'חתונה' או 'ארכיון ישן'. בחירה בו מחליפה "
                                  "את הגדרות הכלים והמודל. נתיבים ומפתח לא נשמרים בפרופיל.")
        sp = ttk.Button(top, text=tr("שמור כפרופיל..."), style="Small.TButton", command=self.save_profile)
        sp.pack(side=X("right"), padx=(8, 0))
        dp = ttk.Button(top, text=tr("מחק פרופיל"), style="Small.TButton", command=self.delete_profile)
        dp.pack(side=X("right"), padx=(4, 0))
        Tooltip(rb, "מחזיר את הגדרות הכלים (סף, מספרים, סימונים) לברירת המחדל. הנתיבים והחיבור לספק לא משתנים. "
                    "שדה ששונה מברירת המחדל מוצג בצבע אחר.")

        pane = ttk.PanedWindow(self.root, orient="vertical")
        pane.pack(fill="both", expand=True, padx=10, pady=(6, 0))
        self.pane = pane
        # progress strip: shown only while a job runs
        self.prog_frame = ttk.Frame(self.root)
        self.prog_label = ttk.Label(self.prog_frame, text="", style="Hint.TLabel", anchor=X("e"))
        self.prog_label.pack(side=X("right"), padx=(8, 0))
        self.prog_bar = ttk.Progressbar(self.prog_frame, mode="determinate")
        self.prog_bar.pack(side=X("right"), fill="x", expand=True)
        self.sf = ScrollFrame(pane)
        pane.add(self.sf, weight=4)
        lf = ttk.LabelFrame(pane, text=R("מה קורה עכשיו"), labelanchor=X("ne"))
        pane.add(lf, weight=1)

        self.build_ai_frame(self.sf.inner)
        nb = ttk.Notebook(self.sf.inner)
        nb.pack(fill="x", pady=4)
        self.nb = nb
        # tabs run right-to-left: the first one sits on the right
        self.tab_frames = [self.build_rate_raw_tab(nb), self.build_archive_tab(nb), self.build_dupes_tab(nb)]
        self.var("ag_results", "")
        self.var("ag_stars", "3")
        for fr in (reversed(self.tab_frames) if i18n.rtl() else self.tab_frames):
            nb.add(fr.master, text=fr.master.tab_title)
        nb.select(self.tab_frames[0].master)
        nb.bind("<<NotebookTabChanged>>", self.on_tab_changed)
        self.on_tab_changed()
        self.root.after(400, self.fit_width)          # once the theme, fonts and styles have settled

        self.log = tk.Text(lf, height=8, wrap="char", relief="flat", borderwidth=0,
                           highlightthickness=0, padx=8, pady=6, undo=False)
        self.log._readonly = True
        self.rlog = log_view.RtlLog(self.log, rtl=i18n.LANG == "he")       # Hebrew drawn in visual order: see bidi_visual.py
        self.log._pick_copy = self.copy_log_selection
        self.log._pick_all = self.rlog.select_all
        self.log.bind("<<Copy>>", lambda e: (self.copy_log_selection(), "break")[1])
        self.log.bind("<Key>", self.log_key)
        lb = ttk.Frame(lf)
        lb.pack(side="bottom", fill="x", padx=6, pady=(0, 4))
        ttk.Button(lb, text=tr("העתק הכול"), style="Small.TButton", command=self.copy_log).pack(side=X("left"), padx=2)
        ttk.Button(lb, text=tr("שמור יומן..."), style="Small.TButton", command=self.save_log).pack(side=X("left"), padx=2)
        sb = ttk.Scrollbar(lf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side=X("left"), fill="y")
        self.log.pack(side=X("left"), fill="both", expand=True)

        self.root.bind_all("<MouseWheel>", self.on_wheel)
        self.root.bind_all("<Button-4>", lambda e: self.on_wheel(e, 1))
        self.root.bind_all("<Button-5>", lambda e: self.on_wheel(e, -1))
        self.root.bind_class("TCombobox", "<MouseWheel>", self.on_combo_wheel)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_tab_changed(self, _event=None):
        """The AI connection box is hidden on the duplicates tab, which does not use it."""
        try:
            cur = self.root.nametowidget(self.nb.select())
            dupes_tab = cur is self.tab_frames[2].master
        except (tk.TclError, KeyError, AttributeError):
            dupes_tab = False
        if dupes_tab:                                    # duplicates do not use the AI
            self.ai_top.pack_forget()
        elif not self.ai_top.winfo_ismapped():
            self.ai_top.pack(fill="x", pady=6, before=self.nb)

    def on_wheel(self, event, direction=None):
        try:
            w = self.root.winfo_containing(event.x_root, event.y_root)
        except (KeyError, tk.TclError):         # the pointer is over a combo box's own drop-down list, which Tk keeps to itself
            return

        if w is None or str(w).startswith(str(self.log)):
            return
        if not str(w).startswith(str(self.sf)):
            return
        if direction is None:
            direction = 1 if event.delta > 0 else -1
        self.sf.scroll(-3 * direction)

    def on_combo_wheel(self, event):
        # a closed drop-down must not change its value when you scroll the page
        self.on_wheel(event)
        return "break"

    def build_ai_frame(self, parent):
        top = ttk.LabelFrame(parent, text=R("חיבור לבינה המלאכותית, לכל הכלים"), labelanchor=X("ne"))
        self.ai_top = top
        top.pack(fill="x", pady=6)
        saved_prov = self.saved.get("provider", "gemini")
        if saved_prov not in llm.PROVIDERS:
            saved_prov = "gemini"
        pv = tk.StringVar(value=llm.PROVIDERS[saved_prov]["label"])
        self.v["provider_label"] = pv
        prov_box = self.row(top, 0, "ספק", lambda p: ttk.Combobox(
            p, textvariable=pv, values=[llm.PROVIDERS[k]["label"] for k in llm.ORDER],
            state="readonly", justify=X("right")))
        self.combos.append(prov_box)
        self.note = ttk.Label(top, text="", style="Hint.TLabel", anchor=X("e"), justify=X("right"))
        self.note.grid(row=1, column=0, columnspan=3, sticky="ew", padx=8)
        self.wrapped(self.note, "")
        self.key_label_widget = None
        self.row(top, 2, "מפתח API", self.entry("key", "", show="*"))
        self.var("save_key", False, "bool")
        sk = ttk.Checkbutton(top, text=R("זכור את המפתח במחשב הזה" if secret_store.available()
                                  else "זכור את המפתח במחשב הזה, פחות בטוח"), style="RTL.TCheckbutton",
                             variable=self.v["save_key"])
        sk.grid(row=3, column=i18n.col(1, 2), columnspan=2, sticky=X("e"), padx=6)
        Tooltip(sk, TIPS["save_key"])
        mv = self.var("model", "")
        self.model_box = self.row(top, 4, "מודל", lambda p: self._combo(p, mv, "model"))
        self.load_btn = ttk.Button(top, text=tr("הצג מודלים זמינים"), command=self.load_models)
        self.load_btn.grid(row=4, column=i18n.col(0), padx=4)
        self.copy_models_btn = ttk.Button(top, text=tr("העתק רשימת מודלים"), command=self.copy_models)
        self.copy_models_btn.grid(row=3, column=i18n.col(0), padx=4)
        Tooltip(self.copy_models_btn, TIPS["copy_models"])
        self.last_models = None
        self.var("hl_model", "")                    # the separate highlights model is set in the Advanced window
        self.hl_box = None
        self.var("delay", "")                       # so is the pause between requests
        self.row(top, 6, "כתובת השרת", self.entry("base_url", ""))
        self.check(top, 8, "only_free", "להציג ברשימת המודלים רק מודלים חינמיים", True)
        self.apply_provider(saved_prov, first=True)
        self.current_prov = saved_prov
        pv.trace_add("write", self.on_provider_change)

    def genre_picker(self, parent):
        labels = [R(x) for x in GENRE_LABELS.values()]
        self.var("rr_genre", "")
        cur = self.v["rr_genre"]
        shown = tk.StringVar(value=R(GENRE_LABELS.get(cur.get(), GENRE_LABELS[""])))
        box = ttk.Combobox(parent, textvariable=shown, values=labels, state="readonly", width=24, justify=X("right"))
        box._name = "rr_genre"

        def chosen(_e=None):
            for key, lab in GENRE_LABELS.items():
                if R(lab) == shown.get():
                    cur.set(key)
        box.bind("<<ComboboxSelected>>", chosen)
        return box

    def _combo(self, parent, var, name=None):
        c = FilterCombobox(parent, textvariable=var, values=[], justify="left")
        make_undoable(c, var)
        c._name = name
        self.combos.append(c)
        return c

    def on_provider_change(self, *_):
        new = self.g("provider")
        if new == self.current_prov:
            return
        self.capture_provider(self.current_prov)
        self.current_prov = new
        self.apply_provider(new)

    def apply_provider(self, prov, first=False):
        pi = llm.PROVIDERS[prov]
        st = self.pstate.get(prov, {})
        self.v["key"].set(st.get("key") or secret_store.load(prov) or llm.env_key(prov))
        self.v["model"].set(st.get("model") or (pi["models"][0] if pi["models"] else ""))
        self.v["hl_model"].set(st.get("hl_model", ""))
        self.v["base_url"].set(st.get("base_url", ""))
        self.model_box.configure(values=pi["models"])
        if self.hl_box is not None:
            try:
                self.hl_box.configure(values=[""] + pi["models"])
            except tk.TclError:
                self.hl_box = None
        # the server address matters only for a server of your own; the free-models filter only for OpenRouter
        self.show_rows(self.ai_top, (6,), prov in ADDRESS_PROVIDERS)
        self.show_rows(self.ai_top, (8,), prov == "openrouter")
        base = f" כתובת ברירת מחדל: {pi['base']}" if pi["base"] else ""
        self.wrapped(self.note, tr(pi["note"]) + tr(base))

    def build_rate_raw_tab(self, nb):
        f = self.tab(nb, "סשן צילום",
                     "בוחר מכל קבוצת צילומים דומים את התמונה הטובה ביותר, ומסמן את הצילומים הבולטים של הסשן. "
                     "הדירוג שופט קומפוזיציה, זווית צילום, אור ורגע, ומתעלם ממה שאפשר לתקן בעריכה.")
        mode = self.var("rr_mode", "folder")
        self.rr_f = f
        ttk.Label(f, text=R("מקור התמונות"), anchor=X("e")).grid(row=0, column=i18n.col(2), sticky=X("e"), padx=6)
        mf = ttk.Frame(f)
        mf.grid(row=0, column=1, sticky=X("e"))
        # first packed = rightmost, so the order reads right to left: folder, then catalog
        for text, val in (("תיקייה", "folder"), ("קטלוג ליטרום", "catalog")):
            ttk.Radiobutton(mf, text=R(text), variable=mode, value=val, style="RTL.TRadiobutton").pack(
                side=X("right"), padx=8)
        self.row(f, 1, "תיקיית הצילומים", self.entry("rr_source"), self.pick_dir("rr_source"))
        self.row(f, 2, "קובץ הקטלוג של ליטרום", self.entry("rr_catalog"),
                 self.pick_file("rr_catalog", [("Lightroom catalog", "*.lrcat")]))
        self.row(f, 3, "מתאריך, למשל 2026-10-01", self.short("rr_since", ""))
        self.row(f, 4, "עד תאריך", self.short("rr_until", ""))
        self.row(f, 5, "רק מאוסף ליטרום בשם", self.entry("rr_collection", hebrew=True))
        self.row(f, 6, "רק מתיקיות ששמן מכיל", self.entry("rr_foldertext", hebrew=True))
        self.row(f, 7, "לאן לשמור את התוצאות", self.entry("rr_out"), self.pick_dir("rr_out"))
        self.row(f, 8, "קובץ הטעם האישי שלך, לא חובה", self.entry("rr_taste"),
                 self.pick_file("rr_taste", [("Text", "*.txt")]))
        self.row(f, 9, "סוג הצילום, לא חובה: מכוון את הדירוג", self.genre_picker)
        self.check(f, 10, "rr_recursive", "כולל תיקיות משנה")
        self.check(f, 11, "rr_other", "לכלול גם קבצים שאינם RAW (JPEG, HEIC ועוד)")
        self.check(f, 12, "rr_prepare", "רק לבדוק איך התמונות מתקבצות, בלי בינה מלאכותית ובלי מפתח API", True)
        self.check(f, 13, "rr_xmp", "לכתוב כוכבים לליטרום, בקובץ נלווה לכל תמונה")
        xmp_var = self.v["rr_xmp"]
        self.check(f, 14, "rr_overwrite", "לדרוס כוכבים שכבר קיימים")
        self.row(f, 15, "כמה קבוצות לדרג עכשיו, 0 = את כולן", self.short("rr_limit", "0"))
        self.check(f, 16, "rr_prefilter", "לדלג מראש על טעויות ברורות: חשוכה מאוד, חשופה מאוד או מטושטשת מאוד", True)
        # the rest of the grouping and highlight settings live in the "Advanced" window
        for name, default in (("rr_sim", "0.30"), ("rr_gap", "120"), ("rr_fargap", "1800"), ("rr_maxgroup", ""), ("rr_cands", ""),
                              ("rr_hls", ""), ("rr_preblur", "12"), ("ens_gap", "2"), ("judge_model", "")):
            self.var(name, default)
        self.var("ens_sees", False, "bool")
        for name in ("ens_prov", "judge_prov"):
            lab = self.saved.get(name)
            self.var(name, lab if lab in self.labels else llm.PROVIDERS[self.saved.get("provider", "gemini")
                                                                         if self.saved.get("provider") in llm.PROVIDERS else "gemini"]["label"])
        ens_on = self.check(f, 17, "ens_on", "בדיקה כפולה: לדרג גם במודל נוסף, ובמחלוקת גדולה להכריע במודל שלישי")
        self.var("ens_model", "")
        self.row(f, 18, "המודל הנוסף: ספק ושם מודל", self.pair_picker("ens_prov", "ens_model"))

        def update(*_):
            folder = mode.get() == "folder"
            self.show_rows(f, (1, 10), folder)                 # folder path, "include subfolders"
            self.show_rows(f, (2, 3, 4, 5, 6), not folder)    # Lightroom catalog and its filters
            self.row_widgets[(str(f), 7)][0].configure(text=R(
                "לאן לשמור את התוצאות. אם ריק: תיקיית משנה בתוך תיקיית הצילומים" if folder
                else "לאן לשמור את התוצאות. אם ריק: תיקייה חדשה בתיקיית המסמכים"))
            # "overwrite" is always shown, but can only be changed while writing stars is on
            self.row_widgets[(str(f), 14)][0].state(["!disabled"] if xmp_var.get() else ["disabled"])
            self.show_rows(f, (18,), bool(ens_on.get()))
        ens_on.trace_add("write", update)
        mode.trace_add("write", update)
        xmp_var.trace_add("write", update)
        update()
        return f

    def build_dupes_tab(self, nb):
        f = self.tab(nb, "כפילויות",
                     "מוצא קבצים זהים בדיוק, ואותה תמונה ששמורה בגודל או בדחיסה אחרים. "
                     "צילומי רצף ותמונות מאותה זווית אינם כפילות. הכלי רק מדווח, ולא מזיז או מוחק כלום.")
        self.row(f, 0, "תיקיית התמונות", self.entry("dp_source"), self.pick_dir("dp_source"))
        self.row(f, 1, "לאן לשמור את הדוח. אם ריק: תיקיית המסמכים", self.entry("dp_out"), self.pick_dir("dp_out"))
        self.check(f, 2, "dp_recursive", "כולל תיקיות משנה", True)
        self.check(f, 3, "dp_near", "לחפש גם תמונות כמעט זהות, ולא רק קבצים זהים בדיוק", True)
        return f

    def field(self, name, width=10, center=True):
        """An entry bound to a variable that already exists (entry() and short() create the variable)."""
        def make(p):
            e = ttk.Entry(p, textvariable=self.v[name], width=width, justify="center" if center else "left")
            make_undoable(e, self.v[name])
            e._name = name
            return e
        return make

    def peek_key(self, prov):
        """The key for a provider if there is one on screen, saved or in the environment. Never asks."""
        if prov == self.g("provider"):
            return self.g("key").strip()
        return (self.pstate.get(prov, {}).get("key") or secret_store.load(prov) or llm.env_key(prov) or "").strip()

    def pair_picker(self, prov_name, model_name):
        """A provider drop-down and a searchable model box for a second or third model. When the provider is not the
        main one it also gets its own API key (and server address, where one is needed) and a button that lists
        the models that key can use."""
        def make(parent):
            box = ttk.Frame(parent)
            r0, r1, r2 = ttk.Frame(box), ttk.Frame(box), ttk.Frame(box)
            for r in (r0, r1, r2):
                r.pack(fill="x", pady=1)
            labels = [llm.PROVIDERS[k]["label"] for k in llm.ORDER]
            pc = ttk.Combobox(r0, textvariable=self.v[prov_name], values=labels, state="readonly", width=24,
                              justify=X("right"))
            mc = self._combo(r0, self.v[model_name], model_name)
            key_var, base_var = tk.StringVar(), tk.StringVar()      # not in self.v: they must not land in the settings file
            state = {"prov": None}

            def prov_key():
                return self.labels.get(self.v[prov_name].get(), "gemini")

            def refresh(*_):
                try:
                    if not box.winfo_exists():              # the Advanced window was closed
                        return
                except tk.TclError:
                    return
                prov = prov_key()
                info = llm.PROVIDERS[prov]
                other = prov != self.g("provider")
                if state["prov"] != prov or state.get("other") != other:     # show what is already known for it
                    state["prov"], state["other"] = prov, other
                    key_var.set(self.peek_key(prov) if other else "")
                    base_var.set(self.pstate.get(prov, {}).get("base_url", "") if other else "")
                mc.configure(values=list(info["models"]))
                if other and info["key_required"]:
                    key_lab.pack(side=X("right"), padx=(6, 0))
                    key_entry.pack(side=X("right"), fill="x", expand=True)
                else:
                    key_lab.pack_forget()
                    key_entry.pack_forget()
                if other and prov in ADDRESS_PROVIDERS:
                    r2.pack(fill="x", pady=1)
                else:
                    r2.pack_forget()

            key_lab = ttk.Label(r1, text=R("מפתח API:"), style="Hint.TLabel")
            key_entry = ttk.Entry(r1, textvariable=key_var, show="*", width=30)
            make_undoable(key_entry, key_var)
            list_btn = ttk.Button(r1, text=tr("הצג מודלים זמינים"), style="Small.TButton",
                                  command=lambda: self.list_pair_models(prov_key(), key_var.get().strip(),
                                                                         base_var.get().strip(), mc, list_btn))
            list_btn.pack(side=X("left"), padx=(6, 0))
            base_lab = ttk.Label(r2, text=R("כתובת השרת:"), style="Hint.TLabel")
            base_entry = ttk.Entry(r2, textvariable=base_var)
            make_undoable(base_entry, base_var)
            base_lab.pack(side=X("right"), padx=(6, 0))
            base_entry.pack(side=X("right"), fill="x", expand=True)

            def remember(*_):
                prov = state["prov"]
                if prov and prov != self.g("provider"):
                    st = self.pstate.setdefault(prov, {})
                    if key_var.get().strip():
                        st["key"] = key_var.get().strip()
                    if base_var.get().strip():
                        st["base_url"] = base_var.get().strip()
            key_var.trace_add("write", remember)
            base_var.trace_add("write", remember)
            pc.bind("<<ComboboxSelected>>", lambda e: (self.v[model_name].set(""), refresh()))
            trace_id = self.v["provider_label"].trace_add("write", lambda *_: refresh())
            box.bind("<Destroy>", lambda e: e.widget is box and self.v["provider_label"].trace_remove("write", trace_id))
            pc.pack(side=X("right"), padx=(6, 0))
            mc.pack(side=X("right"), fill="x", expand=True)
            self.combos.append(pc)
            refresh()
            return box
        return make

    def list_pair_models(self, prov, key, base, combo, button):
        """Fill the model box of a second or third model with the models its provider offers."""
        if self.thread and self.thread.is_alive():
            mb.showinfo("רגע", "אי אפשר לטעון מודלים בזמן שהכלי רץ.")
            return
        info = llm.PROVIDERS[prov]
        key = key or self.peek_key(prov)
        if info["key_required"] and not key:
            mb.showwarning("אין מפתח", "צריך להזין קודם מפתח API.")
            return
        button.configure(state="disabled")

        def work():
            try:
                with llm.using(prov, base or (self.g("base_url").strip() if prov == self.g("provider") else None)):
                    names = llm.list_models(key)
                self.q.put(("PAIRMODELS", (combo, button, names, info["label"])))
            except ValueError as e:
                self.q.put(f"\n{e}\n")
                self.q.put(("PAIRMODELS", (combo, button, None, info["label"])))
            except llm.ApiError as e:
                self.q.put(llm.explain_error(e) + "\n")
                self.q.put(("PAIRMODELS", (combo, button, None, info["label"])))
            except Exception as e:
                self.q.put(f"\nלא הצלחתי לטעון את רשימת המודלים: {e}\n")
                self.q.put(("PAIRMODELS", (combo, button, None, info["label"])))
        threading.Thread(target=work, daemon=True).start()

    def key_for_provider(self, prov):
        """The API key to use for another provider: the one on screen, a saved one, or ask for it."""
        if prov == self.g("provider"):
            return self.g("key").strip()
        info = llm.PROVIDERS[prov]
        key = self.peek_key(prov)
        if not key and info["key_required"]:
            key = (simpledialog.askstring(
                "מפתח API", f"צריך מפתח API עבור {info['label']} (לבדיקה הכפולה):", show="*", parent=self.root) or "").strip()
            if not key:
                raise ValueError(f"צריך מפתח API עבור {info['label']}")
            self.pstate.setdefault(prov, {})["key"] = key
        return key

    def add_double_check(self, argv):
        """Add the second model (and the judge) to the command line of a photo-session run."""
        if not self.g("ens_on") or self.g("rr_prepare"):
            return argv
        main_prov, main_model = self.g("provider"), self.g("model").strip()
        argv = list(argv)
        for role, prov_var, model_var, title in (("second", "ens_prov", "ens_model", "המודל הנוסף"),
                                                 ("judge", "judge_prov", "judge_model", "המכריע")):
            model = self.g(model_var).strip()
            if not model:
                if role == "second":
                    raise ValueError("בדיקה כפולה: צריך לבחור גם את המודל הנוסף (או לבטל את הסימון).")
                continue
            prov = self.labels.get(self.g(prov_var), main_prov)
            if role == "second" and prov == main_prov and model == main_model:
                raise ValueError("בדיקה כפולה: המודל הנוסף זהה למודל הראשי. בחר מודל אחר.")
            base = (self.g("base_url").strip() if prov == main_prov else self.pstate.get(prov, {}).get("base_url", "")).strip()
            if prov == "custom" and not base:
                raise ValueError(f"בדיקה כפולה ({title}): בספק 'אחר' צריך למלא כתובת שרת.")
            argv += [f"--{role}-provider", prov, f"--{role}-model", model]
            if base:
                argv += [f"--{role}-base-url", base]
            key = self.key_for_provider(prov)
            if key:
                argv += [f"--{role}-key", key]
        argv += ["--dispute-gap", str(_num(self.g("ens_gap"), "פער הציונים שנחשב מחלוקת", float, 0.5))]
        if self.g("ens_sees"):
            argv.append("--judge-sees-scores")
        return argv

    def show_advanced(self):
        """Settings most people never touch, plus the check of how well the AI matches your own choices."""
        win = getattr(self, "_adv", None)
        try:
            if win is not None and win.winfo_exists():
                win.deiconify()
                win.lift()
                return
        except tk.TclError:
            pass
        top = tk.Toplevel(self.root)
        self._adv = top
        top.title(R("מתקדם"))
        top.configure(background=THEME["bg"])
        top.transient(self.root)
        top.bind("<Escape>", lambda e: top.destroy())

        def section(title, hint=None):
            box = ttk.LabelFrame(top, text=R(title), labelanchor=X("ne"))
            box.pack(fill="x", padx=10, pady=(8, 2))
            if hint:
                lbl = ttk.Label(box, text="", style="Hint.TLabel", anchor=X("e"), justify=X("right"))
                self.wrapped(lbl, hint)
                lbl.grid(row=0, column=0, columnspan=3, sticky="ew", padx=8, pady=(2, 4))
            return box

        a = section("דירוג סשן צילום",
                    "ברירות המחדל מתאימות לרוב הסשנים. שדה ריק = הכלי מחליט לבד, לפי הספק והמודל ולפי גודל הסשן.")
        self.row(a, 1, "רגישות הקיבוץ: נמוך = קבוצות קטנות יותר", self.field("rr_sim"))
        self.row(a, 2, "פער בשניות שבו מתחילה קבוצה חדשה", self.field("rr_gap"))
        self.row(a, 3, "תמונות דומות רחוקות בזמן: עד כמה שניות. 0 = כבוי", self.field("rr_fargap"))
        self.row(a, 4, "מקסימום תמונות בקבוצה. ריק = אוטומטי", self.field("rr_maxgroup"))
        self.row(a, 5, "כמה תמונות מתחרות על תואר הבולטות. ריק = אוטומטי", self.field("rr_cands"))
        self.row(a, 6, "כמה בולטות יקבלו 4 כוכבים ומעלה. ריק = אחוז קטן מהסשן", self.field("rr_hls"))
        self.row(a, 7, "סף הטשטוש המקדים. נמוך = זהיר יותר", self.field("rr_preblur"))
        e = section("בדיקה כפולה (כשהיא מסומנת בלשונית סשן צילום)",
                    "שני מודלים מדרגים את אותן תמונות. כשהציונים רחוקים זה מזה, או כשהם בחרו תמונה אחרת מתוך צילומי רצף, "
                    "מודל שלישי מכריע, ורק באותם מקרים. בלי מודל שלישי הציון הסופי הוא הממוצע, והמחלוקות מסומנות.")
        self.row(e, 1, "פער ציונים שנחשב מחלוקת (מתוך 10)", self.field("ens_gap"))
        self.row(e, 2, "המכריע: ספק ושם מודל, לא חובה", self.pair_picker("judge_prov", "judge_model"))
        self.check(e, 3, "ens_sees", "להראות למכריע את הציונים הקודמים (ברירת המחדל: הוא שופט בלי לראות, כדי להישאר עצמאי)")
        b = section("חיבור לספק")
        self.hl_box = self.row(b, 1, "מודל נפרד לבחירת הבולטות, לא חובה", lambda p: self._combo(p, self.v["hl_model"], "hl_model"))
        self.hl_box.configure(values=[""] + llm.PROVIDERS[self.g("provider")]["models"])
        self.row(b, 2, "השהיה בין בקשות בשניות. ריק = ברירת המחדל של הספק", self.field("delay"))
        c = section("התאמה לטעם שלך",
                    "בודק עד כמה הדירוג של הבינה המלאכותית מתאים לבחירות שלך. משווים את תוצאות הכלי לכוכבים ולדגלי Pick "
                    "שנתת בליטרום לאותן תמונות, ומקבלים אחוזי התאמה ורשימה של מה שפספס. "
                    "הבדיקה לא שולחת כלום לשום מקום ולא משנה את הקטלוג.")
        self.row(c, 1, "תיקיית התוצאות של הסשן. אם ריק: התיקייה האחרונה שדורגה", self.field("ag_results", 30, False),
                 self.pick_dir("ag_results"))
        self.row(c, 2, "קובץ הקטלוג של ליטרום", self.field("rr_catalog", 30, False),
                 self.pick_file("rr_catalog", [("Lightroom catalog", "*.lrcat")]))
        self.row(c, 3, "כמה כוכבים נחשבים לבחירה שלך", self.field("ag_stars"))
        bar = ttk.Frame(top)
        bar.pack(fill="x", padx=10, pady=10)
        ttk.Button(bar, text=tr("סגור"), command=top.destroy).pack(side=X("left"))
        ttk.Button(bar, text=tr("הרץ בדיקת התאמה"), command=lambda: (top.destroy(), self.start_run(tab=3))).pack(
            side=X("right"))
        top.update_idletasks()
        top.geometry(f"{max(int(640 * self.sc), top.winfo_reqwidth())}x{top.winfo_reqheight()}")
        self.root.update_idletasks()
        x = self.root.winfo_rootx() + 40
        y = self.root.winfo_rooty() + 40
        top.geometry(f"+{x}+{y}")

    def build_archive_tab(self, nb):
        f = self.tab(nb, "ניפוי ודירוג ארכיון",
                     "עבודה על ארכיון תמונות ישן, בשלושה שלבים לפי הסדר. "
                     "שלב 1 סורק את הארכיון, משאיר רק את המצלמות שבחרת, מסנן תמונות מטושטשות וחשוכות ומכין דפי מגע. "
                     "שלב 2 נותן ציון לכל דף מגע. "
                     "שלב 3 בודק מקרוב את הטובות ביותר ומעתיק אותן לתיקייה נפרדת. "
                     "בתמונות עם אנשים הסף גבוה ב-1.")
        cmd = self.var("ar_cmd", "triage")
        if cmd.get() not in ("triage", "rate", "refine"):
            cmd.set("triage")
        ttk.Label(f, text=R("מה להריץ"), anchor=X("e")).grid(row=0, column=i18n.col(2), sticky=X("ne"), padx=6, pady=3)
        cf = ttk.Frame(f)
        cf.grid(row=0, column=1, sticky=X("e"))
        for text, val in (("שלב 1: ניפוי הארכיון", "triage"), ("שלב 2: דירוג דפי המגע", "rate"),
                          ("שלב 3: בדיקה מקרוב של הטובות ביותר", "refine")):
            ttk.Radiobutton(cf, text=R(text), variable=cmd, value=val, style="RTL.TRadiobutton").pack(
                anchor=X("e"), pady=1)
        self.row(f, 1, "תיקיית הארכיון", self.entry("tr_source"), self.pick_dir("tr_source"))
        self.row(f, 2, "תיקיית התוצאות", self.entry("ar_folder"), self.pick_dir("ar_folder"))
        self.row(f, 3, "סף הטשטוש: נמוך = מקל יותר", self.short("tr_blur", "40"))
        self.row(f, 4, "לדלג על תיקיות ששמן מכיל, מילים מופרדות ברווח", self.entry("tr_exclude", "", hebrew=True))
        self.row(f, 5, "לעבד רק את המצלמות האלה, מופרדות בפסיק. ריק = כולן", self.entry("tr_cameras", ""))
        self.check(f, 6, "tr_listcams", "רק להציג אילו מצלמות נמצאו, בלי לעבד")
        self.row(f, 7, "כמה דפים לדרג עכשיו, 0 = כולם", self.short("ar_limit", "0"))
        self.row(f, 8, "ציון מינימלי להמשך", self.short("ar_min", "7"))
        self.row(f, 9, "ציון להיכנס לגמר", self.short("ar_final", "8"))
        self.row(f, 10, "מקסימום תמונות לבדיקה", self.short("ar_max", "250"))

        def update(*_):
            c = cmd.get()
            self.show_rows(f, (1, 3, 4, 5, 6), c == "triage")
            self.show_rows(f, (7,), c == "rate")
            self.show_rows(f, (8, 9, 10), c == "refine")
            label = {"triage": "לאן לשמור את התוצאות. אם ריק: תיקיית המסמכים",
                     "rate": "תיקיית התוצאות מהניפוי", "refine": "תיקיית התוצאות מהניפוי"}[c]
            self.row_widgets[(str(f), 2)][0].configure(text=R(label))
        cmd.trace_add("write", update)
        update()
        return f

    # ---- models
    def load_models(self):
        if self.thread and self.thread.is_alive():
            mb.showinfo("רגע", "אי אפשר לטעון מודלים בזמן שהכלי רץ.")
            return
        prov = self.g("provider")
        key = self.g("key").strip()
        if llm.PROVIDERS[prov]["key_required"] and not key:
            mb.showwarning("אין מפתח", "צריך להזין קודם מפתח API.")
            return
        try:
            llm.configure(prov, self.g("base_url"))
        except ValueError as e:
            mb.showwarning("חסרים פרטים", str(e))
            return
        free_only = bool(self.g("only_free")) and prov == "openrouter"      # the checkbox is shown only there
        self.load_btn.configure(state="disabled")

        def work():
            try:
                self.q.put(("MODELS", llm.list_models(key, free_only=free_only)))
            except llm.ApiError as e:
                self.q.put(llm.explain_error(e) + "\n")
                self.q.put(("MODELS", None))
            except Exception as e:
                self.q.put(f"\nלא הצלחתי לטעון את רשימת המודלים: {e}\n")
                self.q.put(("MODELS", None))
        threading.Thread(target=work, daemon=True).start()

    def copy_models(self):
        """Copy the model list as a ready question for a chatbot: which of these are free, and what are their limits."""
        prov = self.g("provider")
        info = llm.PROVIDERS[prov]
        if self.last_models and self.last_models[0] == prov:
            names, facts = self.last_models[1], self.last_models[2]
        else:
            names, facts = list(info["models"]), {}
        if not names:
            mb.showinfo("אין רשימה", "אין עדיין רשימת מודלים לספק הזה. לחץ קודם על 'הצג מודלים זמינים'.")
            return
        lines = [tr("רשימת מודלים מהספק {0}, כפי שהתוכנה קיבלה אותה ב-{1}.").replace("{0}", info["label"]).replace("{1}", time.strftime("%Y-%m-%d")),
                 tr("שאלה: על כל אחד מהמודלים, האם הוא מקבל תמונות כקלט, האם הוא חינמי בשכבה החינמית של הספק הזה, ומה המכסות שלו (בקשות לדקה, בקשות ליום, טוקנים). אם הוא בתשלום, מה המחיר בערך. אנא הסתמך על התיעוד הרשמי העדכני, וכתוב במפורש כשאינך בטוח."),
                 tr("אני צריך מודל שמבין תמונות, לדירוג צילומים."), "", tr("המודלים:")]
        for n in names:
            extra = facts.get(n, "")
            lines.append(f"- {n}" + (f"  ({extra})" if extra else ""))
        if not (self.last_models and self.last_models[0] == prov):
            lines += ["", tr("(זו רשימת ברירת המחדל של התוכנה ולא רשימה מהספק. לרשימה מלאה לחץ 'הצג מודלים זמינים'.)")]
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(lines))
        self.append_log("\n" + tr("רשימת המודלים הועתקה ללוח. אפשר להדביק אותה בצ'אטבוט ולבקש לאמת מה חינמי ומה המכסות.") + "\n")

    # ---- running
    def start_run(self, tab=None):
        """tab 3 is the taste check, which lives in the Advanced window and has no notebook tab."""
        if self.thread and self.thread.is_alive():
            return
        if tab is None:
            tab = [fr.master for fr in self.tab_frames].index(self.root.nametowidget(self.nb.select()))
        try:
            if tab == 0:
                argv, out = build_rate_raw_args(self.g)
                argv = self.add_double_check(argv)
                module, label = rate_raw, "rate_raw"
            elif tab == 2:
                argv, out = build_dupes_args(self.g)
                module, label = dupes, "dupes"
            elif tab == 3:
                argv, out = build_agreement_args(self.g)
                module, label = agreement, "agreement"
            elif self.g("ar_cmd") == "triage":
                argv, out = build_triage_args(self.g)
                module, label = photo_triage, "photo_triage"
                self.v["ar_folder"].set(str(out))      # the next steps continue from this folder
            else:
                argv, out = build_airate_args(self.g)
                module, label = ai_rate, "ai_rate"
        except ValueError as e:
            mb.showwarning("חסרים פרטים", str(e))
            return
        if self.uses_ai(tab) and not self.privacy_ok():
            return
        self.save_settings()
        self.last_out = out
        self.had_error = False
        self.clear_log()
        shown = [("***" if (i > 0 and argv[i - 1] in ("--key", "--second-key", "--judge-key")) else a)
                 for i, a in enumerate(argv)]
        self.append_log(f"מתחילים: {label} {' '.join(shown)}\n\n")
        self.start_progress()
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.load_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.report_btn.configure(state="disabled")
        self.thread = threading.Thread(target=self.worker, args=(module, label, argv), daemon=True)
        self.thread.start()

    def uses_ai(self, tab):
        """True when this run sends pictures to an AI provider."""
        if tab == 0:
            return not self.g("rr_prepare")
        if tab in (2, 3):
            return False
        return self.g("ar_cmd") in ("rate", "refine")

    def privacy_ok(self):
        """Shown once, before the first time pictures are sent out."""
        if self.saved.get("privacy_ack"):
            return True
        local = llm.info(self.g("provider")).get("local")
        text = ("לפני הריצה הראשונה, כמה מילים על פרטיות:\n\n"
                + ("הספק שבחרת רץ במחשב שלך, ולכן שום דבר לא יוצא ממנו.\n\n" if local else
                   "התמונות נשלחות לספק שבחרת, בגודל קטן ולא בקבצים המקוריים. הן לא נשלחות אליי, ואני לא אוסף שום מידע. "
                   "בשכבות חינמיות הספק עשוי להשתמש בתוכן כדי לשפר את המוצרים שלו.\n\n")
                + "אתה אחראי לתמונות שאתה שולח, ובמיוחד לתמונות של אנשים אחרים. "
                  "הדירוג הוא המלצה בלבד, והמפתח והעלויות מול הספק באחריותך.\n\n"
                  "הנוסח המלא נמצא בקובץ PRIVACY.md.\n\nלהמשיך?")
        if not mb.askokcancel("פרטיות ואחריות", text):
            return False
        self.saved["privacy_ack"] = True
        return True

    def worker(self, module, label, argv):
        old = (sys.argv, sys.stdout, sys.stderr)
        sys.argv = [label] + argv
        sys.stdout = sys.stderr = QWriter(self.q)
        keep_awake(True)
        try:
            module.main()
        except SystemExit as e:
            if e.code not in (0, None):
                print(e.code)
                self.had_error = True
        except StopRun:
            print("\nעצרת את התהליך. מה שכבר נעשה נשמר, והרצה חוזרת תמשיך מאותה נקודה.")
            self.had_error = True
        except Exception:
            print("\nמשהו השתבש:\n" + traceback.format_exc())
            self.had_error = True
        finally:
            keep_awake(False)
            sys.argv, sys.stdout, sys.stderr = old
            self.q.put(("DONE", None))

    def ask_from_worker(self, text):
        """Called by the tools (in the worker thread) before a big job: shows a yes/no question and waits."""
        done, answer = threading.Event(), [True]
        self.q.put(("ASK", (text + "\n\nלהמשיך?", done, answer)))
        while not done.wait(0.2):
            pass
        return answer[0]

    def stop_run(self):
        if self.thread and self.thread.is_alive():
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(self.thread.ident),
                                                       ctypes.py_object(StopRun))
            self.append_log("\nעוצר... זה עשוי לקחת כמה שניות, עד שהפעולה הנוכחית תסתיים.\n")

    def poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                if isinstance(item, tuple):
                    kind, data = item
                    if kind == "DONE":
                        self.finish()
                    elif kind == "ASK":
                        text, done, answer = data
                        answer[0] = mb.askyesno("לפני שמתחילים", text)
                        done.set()
                    elif kind == "PAIRMODELS":
                        combo, button, names, label = data
                        try:
                            button.configure(state="normal")
                            if names is not None:
                                combo.configure(values=names)
                                self.append_log(f"\nנמצאו {len(names)} מודלים של {label}. אפשר לבחור אחד מהם.\n")
                        except tk.TclError:
                            pass                                   # the window was closed meanwhile
                    elif kind == "MODELS":
                        self.load_btn.configure(state="normal")
                        if data is not None:
                            self.last_models = (self.g("provider"), list(data), dict(llm.LAST_DETAILS))
                            self.model_box.configure(values=data)
                            if self.hl_box is not None:
                                try:
                                    self.hl_box.configure(values=[""] + data)
                                except tk.TclError:
                                    self.hl_box = None
                            self.append_log(f"\nנמצאו {len(data)} מודלים. אפשר לבחור אחד מהם בשדה 'מודל'.\n")
                else:
                    if "\nנעצר:" in item:
                        self.had_error = True
                    self.update_progress(item)
                    self.append_log(item)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    # ---- progress bar
    PROG_RE = re.compile(r"\[(\d+)/(\d+)\]")
    SCAN_RE = re.compile(r"עברתי על (\d+) קבצים")

    def start_progress(self):
        self.pg_events, self.pg_total = [], 0
        self.prog_bar.stop()
        self.prog_bar.configure(mode="indeterminate", value=0)
        self.prog_bar.start(14)
        self.prog_label.configure(text=R("מתחיל..."))
        self.prog_frame.pack(side="bottom", fill="x", padx=14, pady=(2, 2), before=self.pane)

    def update_progress(self, text):
        m = None
        for m in self.PROG_RE.finditer(text):
            pass
        if m:
            n, total = int(m[1]), int(m[2])
            if total <= 0:
                return
            if total != self.pg_total:
                self.pg_total, self.pg_events = total, []
                self.prog_bar.stop()
                self.prog_bar.configure(mode="determinate", maximum=total)
            self.pg_events.append((time.time(), n))
            self.prog_bar.configure(value=n - 1)
            label = tr(f"{n} מתוך {total}")
            ev = self.pg_events[-8:]
            if len(ev) >= 3 and ev[-1][1] > ev[0][1]:
                per_item = (ev[-1][0] - ev[0][0]) / (ev[-1][1] - ev[0][1])
                label += tr(f", נשארו {tr(fmt_eta(per_item * (total - n + 1)))}")
            self.prog_label.configure(text=R(label))
            return
        sm = self.SCAN_RE.search(text)
        if sm:
            self.prog_label.configure(text=R(f"נסרקו {sm[1]} קבצים"))

    def end_progress(self):
        self.prog_bar.stop()
        if self.pg_total:
            self.prog_bar.configure(mode="determinate", maximum=self.pg_total,
                                    value=self.pg_total if not self.had_error else self.prog_bar["value"])
        else:
            self.prog_bar.configure(mode="determinate", maximum=1, value=1 if not self.had_error else 0)
        self.prog_label.configure(text=R("הופסק" if self.had_error else "הושלם"))

    # ---- log helpers
    def copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.rlog.text())

    def save_log(self):
        name = "log_" + time.strftime("%Y-%m-%d_%H-%M") + ".txt"
        path = filedialog.asksaveasfilename(defaultextension=".txt", initialfile=name,
                                            filetypes=[("Text", "*.txt")])
        if path:
            try:
                Path(path).write_text(self.rlog.text(), encoding="utf-8-sig")
            except OSError as e:
                mb.showwarning("לא הצלחתי לשמור", str(e))

    def auto_save_log(self):
        """Keeps a copy of every run next to its results, so there is something to send if something went wrong."""
        if not (self.last_out and Path(self.last_out).is_dir()):
            return
        try:
            with open(Path(self.last_out) / "run_log.txt", "a", encoding="utf-8-sig") as f:
                f.write("\n===== " + time.strftime("%Y-%m-%d %H:%M:%S") + " =====\n")
                f.write(self.rlog.text() + "\n")
        except OSError:
            pass

    def finish(self):
        if self._log_pending:
            self.append_log("\n")
        self.end_progress()
        self.run_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.load_btn.configure(state="normal")
        if self.had_error:
            self.append_log("\nהריצה הופסקה לפני שהסתיימה. הסיבה מוסברת למעלה, ומה שכבר נעשה נשמר.\n")
        else:
            self.append_log("\nזהו, סיימנו.\n")
        if self.last_out and Path(self.last_out).exists():
            self.open_btn.configure(state="normal")
            if (Path(self.last_out) / "report.html").exists():
                self.report_btn.configure(state="normal")
        self.auto_save_log()
        notify_done(self.root)

    # ---- profiles
    def save_profile(self):
        name = simpledialog.askstring("שמירת פרופיל", R("שם לפרופיל:"), parent=self.root,
                                      initialvalue=self.profile_var.get())
        name = (name or "").strip()
        if not name:
            return
        if name in self.profiles and not mb.askyesno("פרופיל קיים", f"כבר יש פרופיל בשם '{name}'. להחליף אותו?"):
            return
        snap = {k: self.v[k].get() for k in PROFILE_KEYS if k in self.v}
        snap["_provider"] = self.g("provider")
        snap["_model"] = self.v["model"].get()
        snap["_hl_model"] = self.v["hl_model"].get()
        self.profiles[name] = snap
        self.profile_box.configure(values=sorted(self.profiles))
        self.profile_var.set(name)
        self.save_settings()
        self.append_log(f"נשמר הפרופיל '{name}'.\n")

    def apply_profile(self, name):
        prof = self.profiles.get(name)
        if not prof:
            return False
        prov = prof.get("_provider")
        if prov in llm.PROVIDERS:
            self.v["provider_label"].set(llm.PROVIDERS[prov]["label"])      # also reloads the provider's own fields
            if prof.get("_model"):
                self.v["model"].set(prof["_model"])
            self.v["hl_model"].set(prof.get("_hl_model", ""))
        for k, val in prof.items():
            if k.startswith("_") or k not in self.v:
                continue
            try:
                self.v[k].set(val)
            except tk.TclError:
                pass
        return True

    def on_profile_pick(self, _event=None):
        name = self.profile_var.get()
        if self.apply_profile(name):
            self.append_log(f"נטען הפרופיל '{name}'.\n")

    def delete_profile(self):
        name = self.profile_var.get()
        if name not in self.profiles:
            mb.showinfo("מחיקת פרופיל", "בחר קודם פרופיל מהרשימה.")
            return
        if not mb.askyesno("מחיקת פרופיל", f"למחוק את הפרופיל '{name}'?"):
            return
        del self.profiles[name]
        self.profile_box.configure(values=sorted(self.profiles))
        self.profile_var.set("")
        self.save_settings()

    # ---- drag and drop
    def plan_drop(self, p, widget):
        """Decide what a dropped file or folder is for. Returns ({field: value}, tab or None) or (None, reason)."""
        p = Path(p)
        name = getattr(widget, "_name", None)
        if name in DIR_FIELDS:
            return {name: str(p if p.is_dir() else p.parent)}, None
        if name in FILE_FIELDS:
            if p.is_dir():
                return None, "לשדה הזה צריך לגרור קובץ ולא תיקייה."
            return {name: str(p)}, None
        suffix = p.suffix.lower()
        if suffix == ".lrcat":
            return {"rr_catalog": str(p), "rr_mode": "catalog"}, 0
        if suffix == ".txt":
            return {"rr_taste": str(p)}, 0
        folder = str(p if p.is_dir() else p.parent)
        try:
            tab = [fr.master for fr in self.tab_frames].index(self.root.nametowidget(self.nb.select()))
        except (tk.TclError, ValueError, KeyError):
            tab = 0
        if tab == 0:
            return {"rr_source": folder, "rr_mode": "folder"}, 0
        if tab == 2:
            return {"dp_source": folder}, 2
        return {("tr_source" if self.g("ar_cmd") == "triage" else "ar_folder"): folder}, 1

    def on_drop(self, paths, x, y):
        if not paths or (self.thread and self.thread.is_alive()):
            return
        try:
            widget = self.root.winfo_containing(x, y)
        except (tk.TclError, KeyError):
            widget = None
        plan, extra = self.plan_drop(paths[0], widget)
        if plan is None:
            self.append_log(extra + "\n")
            return
        for name, value in plan.items():
            self.v[name].set(os.path.normpath(value) if name not in ("rr_mode",) else value)
        if extra is not None:
            self.nb.select(self.tab_frames[extra].master)
        shown = [f"{FIELD_TITLES[n]}: {self.v[n].get()}" for n in plan if n in FIELD_TITLES]
        self.append_log("עודכן בגרירה. " + " | ".join(shown) + "\n")
        if len(paths) > 1:
            self.append_log("נגרר יותר מפריט אחד, ורק הראשון נלקח בחשבון.\n")

    # ---- built-in guide
    ABOUT_TEXT = (
        "FocalPick עוזר לצלמים לעבור על סשן צילום גדול ולבחור מה שווה לשמור. הוא מקבץ צילומי רצף, "
        "מדרג כל תמונה לפי קומפוזיציה, זווית צילום, אור ורגע בעזרת מודל בינה מלאכותית, ומסמן את הבולטות מכל סשן.",
        "הוא לא נוגע בקובצי התמונות עצמם. אם ביקשת, הוא כותב כוכבים לליטרום בקובץ נלווה, ושומר גיבוי של הקובץ הקיים.",
        "התמונות נשלחות, בגודל מוקטן, רק לספק הבינה המלאכותית שבחרת. מפתח ה-API נשמר במחשב שלך, ורק אם סימנת 'זכור את המפתח'.",
        "התוכנה חינמית ונשארת חינמית. אם היא חוסכת לך זמן, אפשר לתמוך בפיתוח שלה, אבל זו רשות בלבד.",
    )
    ABOUT_SMALL = "© נתאי שנדורפי · רישיון MIT. רכיבי צד שלישי כפופים לרישיונות שלהם (ראה THIRD_PARTY_NOTICES.txt)."

    def show_about(self):
        win = getattr(self, "_about", None)
        try:
            if win is not None and win.winfo_exists():
                win.deiconify()
                win.lift()
                return
        except tk.TclError:
            pass
        top = tk.Toplevel(self.root)
        self._about = top
        top.title(R("אודות"))
        top.configure(background=THEME["bg"])
        top.transient(self.root)
        top.resizable(False, False)
        top.bind("<Escape>", lambda e: top.destroy())
        width = int(460 * self.sc)                                   # fixed: the text is wrapped once, to this width
        frame = ttk.Frame(top, padding=(26, 20, 26, 16))
        frame.pack(fill="both", expand=True)
        big = tkfont.Font(family=UI_FONT, size=22, weight="bold")
        ttk.Label(frame, text=APP_NAME, font=big, anchor="center").pack()
        ttk.Label(frame, text=(R("גרסה") + " " + APP_VERSION) if i18n.rtl() else f"{tr('גרסה')} {APP_VERSION}",
                  style="Hint.TLabel", anchor="center").pack(pady=(0, 12))
        body_font = tkfont.Font(family=UI_FONT, size=10)

        def para(text, style=None, font=body_font, pady=4):
            shown = bidi_text.wrap_text(i18n.tr(text), width, font, i18n.rtl())
            kw = {"style": style} if style else {}
            ttk.Label(frame, text=shown, font=font, justify="center", anchor="center", **kw).pack(fill="x", pady=pady)
        for text in self.ABOUT_TEXT:
            para(text)
        links = [(u, t) for u, t in ((REPO_URL, "האתר ב-GitHub"), (SPONSOR_URL, "תמיכה בפרויקט")) if u]
        if links:
            row = ttk.Frame(frame)
            row.pack(pady=(12, 4))
            for url, label in links:
                ttk.Button(row, text=R(label), command=lambda u=url: webbrowser.open(u)).pack(side="left", padx=4)
        para(self.ABOUT_SMALL, style="Hint.TLabel", font=tkfont.Font(family=UI_FONT, size=9), pady=(12, 4))
        ttk.Button(frame, text=R("סגור"), command=top.destroy).pack(pady=(8, 0))
        top.update_idletasks()
        top.geometry(f"+{self.root.winfo_rootx() + 80}+{self.root.winfo_rooty() + 80}")

    def show_help(self):
        """The guide opens in the default browser: it is a real web page there, with correct Hebrew, selection,
        search and printing."""
        f = help_view.guide_file(i18n.LANG)
        if not f:
            mb.showwarning("המדריך לא נמצא", "לא נמצא קובץ המדריך. הוא אמור להיות ליד התוכנה, בשם photo_tools_guide.html.")
            return
        try:
            webbrowser.open(f.resolve().as_uri())
        except Exception:
            mb.showwarning("המדריך", f"לא הצלחתי לפתוח את הדפדפן. אפשר לפתוח ידנית את הקובץ:\n{f}")

    # ---- results gallery
    def show_results(self):
        cands = [self.last_out] + [self.v[n].get().strip() for n in ("rr_out", "ar_folder")]
        folder, data = None, None
        for c in cands:
            if c and Path(c).is_dir():
                d = results_view.load_results(c)
                if d[0]:
                    folder, data = c, d
                    break
        if not folder:
            c = filedialog.askdirectory(title="בחר את תיקיית התוצאות", initialdir=str(Path.home() / "Documents"))
            if not c:
                return
            folder, data = c, results_view.load_results(c)
        if not data[0] or not data[1]:
            mb.showinfo("אין תוצאות", "בתיקייה הזו אין עדיין תוצאות דירוג. הרץ קודם דירוג, או בחר תיקייה אחרת.")
            return
        results_view.ResultsWindow(self.root, folder, THEME, R, self.open_path, self.sc, data)

    # ---- log + open
    READ_KEYS = {"Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next", "Shift_L", "Shift_R",
                 "Control_L", "Control_R"}

    def log_key(self, event):
        """The log is read-only, but stays selectable and copyable: it ignores typing and nothing else."""
        if event.keysym in self.READ_KEYS or event.state & 0x4:
            return None
        return "break"

    def clear_log(self):
        self.rlog.clear()

    def append_log(self, text):
        """Hebrew lines are wrapped and drawn right-aligned in visual order (log_view.py); other lines stay as they are."""
        if i18n.LANG != "he":
            text = self._log_pending + text
            self._log_pending = ""
            if text and not text.endswith(("\n", "\r")):      # wait for the end of the line before translating
                head, _, tail = text.rpartition("\n")
                text, self._log_pending = (head + "\n" if head or text.startswith("\n") else ""), tail
            text = i18n.tr(text)
        self.rlog.append(text)

    def copy_log_selection(self):
        text = self.rlog.selection()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)

    # ---- language
    def on_lang_choice(self, _event=None):
        code = next((c for c, n in self.lang_names.items() if n == self.lang_label.get()), i18n.LANG)
        if code == i18n.LANG:
            return
        if not mb.askyesno("החלפת שפה", "כדי להחליף שפה צריך להפעיל את התוכנה מחדש. להפעיל מחדש עכשיו?"):
            self.lang_label.set(self.lang_names.get(i18n.LANG, ""))
            return
        self.lang_var.set(code)
        self.save_settings()
        try:
            args, kw = restart_command()
            subprocess.Popen(*args, **kw)
            self.root.destroy()
        except OSError:
            mb.showwarning("החלפת שפה", "לא הצלחתי להפעיל מחדש. סגור ופתח את התוכנה ידנית.")

    # ---- appearance (light / dark)
    def on_theme_choice(self, _event=None):
        by_name = {tr(n): k for k, n in THEME_CHOICES}
        self.theme_var.set(by_name.get(self.theme_label.get(), "system"))
        self.apply_theme()
        self.save_settings()

    def watch_system_theme(self):
        """While the choice is 'follow the computer', pick up changes made in the system settings."""
        try:
            if self.theme_var.get() == "system" and system_is_dark() != self.dark:
                self.apply_theme()
        finally:
            self.root.after(4000, self.watch_system_theme)

    def apply_theme(self):
        pref = self.theme_var.get()
        dark = system_is_dark() if pref == "system" else pref == "dark"
        self.dark = dark
        P = PALETTES["dark" if dark else "light"]
        THEME.clear()
        THEME.update(P, dark=dark)
        st = self.style
        st.theme_use("clam")
        st.configure(".", font=self.fonts["base"], background=P["bg"], foreground=P["fg"],
                     fieldbackground=P["field"], bordercolor=P["border"], lightcolor=P["bg"],
                     darkcolor=P["bg"], troughcolor=P["bg"], focuscolor=P["bg"],
                     selectbackground=P["sel"], selectforeground=P["sel_fg"], insertcolor=P["fg"])
        st.map(".", foreground=[("disabled", P["disabled"])])
        st.configure("Hint.TLabel", foreground=P["muted"])
        st.configure("Changed.TLabel", foreground=P["changed"], font=self.fonts["bold"])
        st.configure("Small.TButton", padding=(10, 2), font=self.fonts["small"])
        st.configure("TProgressbar", troughcolor=P["btn"], background=P["accent"], bordercolor=P["border"],
                     lightcolor=P["accent"], darkcolor=P["accent"], thickness=10)
        st.configure("Foot.TLabel", foreground=P["muted"], font=self.fonts["foot"])
        # buttons
        st.configure("TButton", background=P["btn"], foreground=P["fg"], bordercolor=P["border"],
                     lightcolor=P["btn"], darkcolor=P["btn"], padding=(10, 4), relief="flat")
        st.map("TButton", background=[("disabled", P["bg"]), ("pressed", P["btn_hot"]), ("active", P["btn_hot"])])
        st.configure("Run.TButton", background=P["accent"], foreground=P["accent_fg"], bordercolor=P["accent"],
                     lightcolor=P["accent"], darkcolor=P["accent"], font=self.fonts["bold"],
                     padding=(20, 5))
        st.map("Run.TButton", background=[("disabled", P["btn"]), ("pressed", P["accent_hot"]),
                                          ("active", P["accent_hot"])],
               foreground=[("disabled", P["disabled"])], bordercolor=[("disabled", P["border"])])
        # text fields
        for name in ("TEntry", "TCombobox"):
            st.configure(name, fieldbackground=P["field"], foreground=P["fg"], bordercolor=P["border"],
                         lightcolor=P["field"], darkcolor=P["field"], insertcolor=P["fg"], padding=4)
        st.configure("TCombobox", background=P["btn"], arrowcolor=P["fg"])
        st.map("TEntry", bordercolor=[("focus", P["muted"])])
        st.map("TCombobox", fieldbackground=[("readonly", P["field"]), ("disabled", P["bg"])],
               selectbackground=[("readonly", P["field"])], selectforeground=[("readonly", P["fg"])],
               foreground=[("disabled", P["disabled"])], bordercolor=[("focus", P["muted"])],
               background=[("active", P["btn_hot"])])
        self.root.option_add("*TCombobox*Listbox.background", P["field"])
        self.root.option_add("*TCombobox*Listbox.foreground", P["fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", P["sel"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", P["sel_fg"])
        for c in self.combos:               # drop-down lists that already exist
            try:
                self.root.tk.call(f"{c}.popdown.f.l", "configure", "-background", P["field"],
                                  "-foreground", P["fg"], "-selectbackground", P["sel"],
                                  "-selectforeground", P["sel_fg"])
            except tk.TclError:
                pass
        # check boxes and radio buttons: the indicator sits on the right of the text
        for kind in ("Checkbutton", "Radiobutton"):
            label_part = (f"{kind}.focus", {"side": "left", "sticky": "w", "children": [
                (f"{kind}.label", {"sticky": "nswe"})]})
            box_part = (f"{kind}.indicator", {"side": "left", "sticky": ""})
            parts = [label_part, box_part] if i18n.rtl() else [box_part, label_part]   # box on the reading-start side
            st.layout(f"RTL.T{kind}", [(f"{kind}.padding", {"sticky": "nswe", "children": parts})])
            st.configure(f"RTL.T{kind}", background=P["bg"], foreground=P["fg"],
                         indicatorbackground=P["field"], indicatorforeground=P["check"],
                         upperbordercolor=P["muted"], lowerbordercolor=P["muted"],
                         indicatormargin=(6, 1, 0, 1) if i18n.rtl() else (0, 1, 6, 1), padding=2)
            st.configure(f"Changed.RTL.T{kind}", foreground=P["changed"])
            st.map(f"RTL.T{kind}", background=[("active", P["bg"])],
                   indicatorbackground=[("disabled", P["bg"]), ("pressed", P["field"])],
                   indicatorforeground=[("disabled", P["disabled"])])
        # frames, tabs, scrollbars
        st.configure("TLabelframe", background=P["bg"], bordercolor=P["border"], lightcolor=P["bg"],
                     darkcolor=P["bg"])
        st.configure("TLabelframe.Label", background=P["bg"], foreground=P["muted"])
        st.configure("TNotebook", background=P["bg"], bordercolor=P["border"], lightcolor=P["bg"],
                     darkcolor=P["bg"], tabmargins=(0, 4, 0, 0))
        st.configure("TNotebook.Tab", background=P["btn"], foreground=P["muted"], bordercolor=P["border"],
                     lightcolor=P["btn"], darkcolor=P["btn"], padding=(16, 6))
        st.map("TNotebook.Tab", background=[("selected", P["bg"]), ("active", P["btn_hot"])],
               foreground=[("selected", P["fg"])], lightcolor=[("selected", P["bg"])],
               darkcolor=[("selected", P["bg"])])
        st.configure("TScrollbar", background=P["btn"], troughcolor=P["bg"], bordercolor=P["bg"],
                     arrowcolor=P["fg"], lightcolor=P["btn"], darkcolor=P["btn"], gripcount=0)
        st.map("TScrollbar", background=[("active", P["btn_hot"]), ("pressed", P["btn_hot"])])
        st.configure("TPanedwindow", background=P["bg"])
        st.configure("Sash", background=P["bg"], bordercolor=P["bg"], lightcolor=P["bg"],
                     darkcolor=P["bg"], sashthickness=8, gripcount=0)
        # plain tk widgets
        self.root.configure(background=P["bg"])
        self.sf.canvas.configure(background=P["bg"])
        self.log.configure(background=P["field"], foreground=P["fg"], insertbackground=P["fg"],
                           selectbackground=P["sel"], selectforeground=P["sel_fg"])
        set_titlebar_dark(self.root, dark)

    def open_out(self):
        if self.last_out:
            self.open_path(Path(self.last_out))

    def open_report(self):
        p = Path(self.last_out) / "report.html"
        if p.exists():
            self.open_path(p)

    @staticmethod
    def open_path(p):
        try:
            os.startfile(str(p))              # Windows
        except AttributeError:
            try:
                subprocess.Popen(["open" if IS_MAC else "xdg-open", str(p)])
            except OSError:
                webbrowser.open(p.resolve().as_uri())

    def on_close(self):
        self.save_settings()
        self.root.destroy()


def main():
    i18n.GUI = True                       # the window translates the tools' messages itself
    i18n.set_lang(i18n.saved_language())
    enable_dpi_awareness()
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
