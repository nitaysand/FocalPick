"""
בדיקת כיווניות. מריצים: python bidi_test.py
מציג את אותם משפטים בכמה שיטות. צלם מסך ושלח, ונבחר את השיטה שמוצגת נכון.
"""
import tkinter as tk
from tkinter import ttk
import tkinter.font as tkfont

import bidi_text

SAMPLES = [
    "כתובת השרת, נדרשת רק בספק 'אחר'",
    "ציון 8 (קומפוזיציה 6, אור 7)",
    "רק לבדוק איך התמונות מתקבצות, בלי בינה מלאכותית ובלי מפתח API",
    "מתחילים: rate_raw --catalog C:\\Users\\nitay\\סטף.lrcat --similarity 0.10",
    "ו-21 קבצים חסרים בדיסק RAW, בקטלוג נמצאו 0 קבצי RAW.",
    "כתובת ברירת מחדל: https://generativelanguage.googleapis.com/v1beta (aistudio.google.com)",
]
LONG = ("בוחר מכל קבוצת צילומים דומים את התמונה הטובה ביותר (עד 8 תמונות בקבוצה), ומסמן את הצילומים הבולטים "
        "של הסשן. הדירוג שופט קומפוזיציה, זווית צילום ואור, ומתעלם ממה שאפשר לתקן ב-Lightroom.")

RLM, RLE, PDF, RLI, PDI = "\u200f", "\u202b", "\u202c", "\u2067", "\u2069"
STRATS = [
    ("A  רגיל, בלי טיפול", lambda t, w, f: t),
    ("B  סימן RLM בתחילת השורה, השיטה הנוכחית", lambda t, w, f: RLM + t),
    ("C  הטמעה ימין לשמאל, RLE", lambda t, w, f: RLE + t + PDF),
    ("D  בידוד ימין לשמאל, RLI", lambda t, w, f: RLI + t + PDI),
    ("E  סידור עצמי ונעילת כיוון", lambda t, w, f: bidi_text.visual(t, w, f)),
]


def main():
    root = tk.Tk()
    root.title("בדיקת כיווניות")
    root.geometry("980x900")
    font = tkfont.Font(family="Segoe UI", size=10)
    canvas = tk.Canvas(root)
    sb = ttk.Scrollbar(root, command=canvas.yview)
    canvas.configure(yscrollcommand=sb.set)
    sb.pack(side="left", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    f = ttk.Frame(canvas)
    canvas.create_window((0, 0), window=f, anchor="nw")
    f.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-3 if e.delta > 0 else 3, "units"))
    r = 0
    for name, fn in STRATS:
        ttk.Label(f, text=name, font=("Segoe UI", 10, "bold")).grid(row=r, column=0, sticky="w", padx=8, pady=(10, 2))
        r += 1
        for s in SAMPLES:
            ttk.Label(f, text=fn(s, None, None), anchor="e", justify="right", font=font).grid(
                row=r, column=0, sticky="e", padx=8)
            r += 1
        ttk.Label(f, text=fn(LONG, 420, font), justify="right", font=font,
                  wraplength=0 if name.startswith("E") else 420).grid(row=r, column=0, sticky="e", padx=8, pady=4)
        r += 1
    f.columnconfigure(0, weight=1)
    root.mainloop()


if __name__ == "__main__":
    main()
