"""
results_view.py - a gallery of the results, inside the app.

Reads the output folder of any of the tools (a RAW session, or the archive steps) and shows
the photos as a grid you can sort and filter by score. Click a photo to see it large, with the
model's notes.

load_results() knows nothing about the screen, so it can be tested on its own.
"""
import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import bidi_text
import i18n
from i18n import X
from smooth_scroll import SmoothScroller

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:          # no Tk (e.g. when only the data functions are tested)
    tk = ttk = None

try:
    from PIL import Image, ImageTk
except ImportError:           # Pillow is a requirement of the tools, so this is just a safety net
    Image = ImageTk = None

THUMB = 170
MAX_SHOWN = 300               # cells drawn at once; the rest comes with "show more"

FLAG_NAMES = {
    "soft_focus": "פוקוס פספס", "motion_blur": "טשטוש תנועה", "eyes_closed": "עיניים עצומות",
    "subject_cut_off": "נושא חתוך", "bad_timing": "תזמון חלש", "distraction": "הסחת דעת",
}
SORTS = (("score", "ציון, מהגבוה לנמוך"), ("name", "שם הקובץ"), ("group", "לפי קבוצה"))


# ---------------------------------------------------------------- data
def _read_csv(path):
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_results(folder):
    """
    Returns (kind, items). kind is "raw", "finalists", "scores" or None when the folder holds no results.
    Each item: name, path, image (a Path to a small JPEG, or None), score (float or None),
    gem (bool), group (text), lines (list of short notes).
    """
    folder = Path(folder)
    if (folder / "ratings.csv").exists():
        return "raw", _load_raw(folder)
    if (folder / "finalists.csv").exists() or (folder / "ai_scores.csv").exists():
        return _load_archive(folder)
    return None, []


def _load_raw(folder):
    index = _json(folder / "index.json")
    items = []
    for r in _read_csv(folder / "ratings.csv"):
        rec = index.get(r.get("path", ""), {})
        image = folder / rec["preview"] if rec.get("preview") else None
        lines = []
        parts = [f"{label} {r[k]}" for label, k in (("קומפוזיציה", "composition"), ("זווית", "angle"),
                                                    ("אור", "light")) if r.get(k)]
        if parts:
            lines.append("  ".join(parts))
        flags = [FLAG_NAMES.get(f, f) for f in (r.get("flags") or "").split(",") if f]
        if flags:
            lines.append("סימונים: " + ", ".join(flags))
        if r.get("highlight_reason"):
            lines.append(r["highlight_reason"])
        elif r.get("note"):
            lines.append(r["note"])
        group = r.get("group", "")
        if r.get("rank_in_group"):
            lines.append(f"מקום {r['rank_in_group']} בקבוצה {group}")
        items.append({"name": r.get("file", ""), "path": r.get("path", ""), "image": image,
                      "score": _num(r.get("overall")), "gem": bool(r.get("gem")),
                      "group": str(group), "lines": lines,
                      "note": r.get("highlight_reason") or r.get("note") or ""})
    return items


def _load_archive(folder):
    thumbs = {}
    for r in _read_csv(folder / "report.csv"):
        thumbs[r.get("id")] = (r.get("thumb_path"), r.get("camera", ""))
    items = []
    fin = _read_csv(folder / "finalists.csv")
    if fin:
        kind = "finalists"
        for r in fin:
            thumb, cam = thumbs.get(r.get("id"), (None, ""))
            lines = [x for x in (r.get("category"), r.get("verdict")) if x]
            if r.get("score1"):
                lines.append(f"ציון בדף המגע: {r['score1']}")
            items.append(_archive_item(r, thumb, _num(r.get("score2")), lines, r.get("verdict", "")))
    else:
        kind = "scores"
        for r in _read_csv(folder / "ai_scores.csv"):
            thumb = r.get("thumb_path") or thumbs.get(r.get("id"), (None, ""))[0]
            lines = [x for x in (r.get("category"), r.get("note")) if x]
            items.append(_archive_item(r, thumb, _num(r.get("score")), lines, r.get("note", "")))
    return kind, items


def _archive_item(r, thumb, score, lines, note=""):
    path = r.get("path", "")
    return {"name": Path(path).name if path else str(r.get("id", "")), "path": path,
            "image": Path(thumb) if thumb else None, "score": score, "gem": False,
            "group": r.get("sheet", ""), "lines": lines, "note": note}


def sort_items(items, how, min_score=0, only_gems=False):
    out = [i for i in items if (i["score"] or 0) >= min_score and (i["gem"] or not only_gems)]
    if how == "name":
        out.sort(key=lambda i: i["name"].lower())
    elif how == "group":
        out.sort(key=lambda i: (i["group"], -(i["score"] or 0), i["name"].lower()))
    else:
        out.sort(key=lambda i: (not i["gem"], -(i["score"] if i["score"] is not None else -1), i["name"].lower()))
    return out


UI_FONT = "Segoe UI" if sys.platform == "win32" else ("Helvetica Neue" if sys.platform == "darwin" else "DejaVu Sans")


def show_in_folder(path, open_path):
    """Select the file in Explorer; if it is gone, open its folder."""
    p = Path(path)
    if sys.platform == "win32" and p.exists():
        try:
            subprocess.Popen(["explorer", f"/select,{p}"])
            return
        except OSError:
            pass
    elif sys.platform == "darwin" and p.exists():
        try:
            subprocess.Popen(["open", "-R", str(p)])      # reveal in Finder
            return
        except OSError:
            pass
    open_path(p.parent if p.parent.exists() else p)


# ---------------------------------------------------------------- window
class ResultsWindow:
    """The photos are drawn as items of one canvas (not as a tree of small widgets), so fast scrolling never leaves
    smeared pictures behind, and only the thumbnails that are in view are loaded."""

    def __init__(self, parent, folder, theme, R, open_path, scale=1.0, data=None):
        self.parent, self.theme, self.R, self.open_path = parent, theme, R, open_path
        self.kind, self.items = data or load_results(folder)
        self.folder = Path(folder)
        self.photos = {}                       # thumbnails, kept alive
        self.shown = []
        self.limit = MAX_SHOWN
        self.cols = 0
        self.thumb = int(THUMB * scale)
        self.cell_w = self.thumb + 20
        self.cell_h = self.thumb + int(112 * scale)
        self.scale = scale
        self.img_items = {}                    # cell number -> canvas item of its picture
        self.load_job = self.resize_job = None
        self.top = tk.Toplevel(parent)
        self.top.title(R("תוצאות"))
        self.top.geometry(f"{int(980 * scale)}x{int(700 * scale)}")
        self.top.minsize(int(560 * scale), int(360 * scale))
        self.top.configure(background=theme["bg"])
        import tkinter.font as tkfont
        self.f_score = tkfont.Font(root=self.top, family=UI_FONT, size=11, weight="bold")
        self.f_name = tkfont.Font(root=self.top, family=UI_FONT, size=8)
        self.f_note = tkfont.Font(root=self.top, family=UI_FONT, size=8)
        self.build()
        self.top.after(50, self.refresh)

    # ---- layout
    def build(self):
        R, P = self.R, self.theme
        bar = ttk.Frame(self.top)
        bar.pack(side="top", fill="x", padx=10, pady=8)
        self.sort_var = tk.StringVar(value=i18n.tr(SORTS[0][1]))
        self.min_var = tk.StringVar(value="0")
        self.gem_var = tk.BooleanVar(value=False)
        ttk.Label(bar, text=R("מיון")).pack(side=X("right"), padx=(0, 4))
        sb = ttk.Combobox(bar, textvariable=self.sort_var, values=[i18n.tr(n) for _, n in SORTS], state="readonly",
                          width=18, justify=X("right"))
        sb.pack(side=X("right"), padx=(0, 14))
        ttk.Label(bar, text=R("ציון מינימלי")).pack(side=X("right"), padx=(0, 4))
        mb = ttk.Combobox(bar, textvariable=self.min_var, values=[str(i) for i in range(0, 10)], state="readonly",
                          width=4, justify="center")
        mb.pack(side=X("right"), padx=(0, 14))
        if any(i["gem"] for i in self.items):
            ttk.Checkbutton(bar, text=R("רק בולטות הסשן"), variable=self.gem_var,
                            style="RTL.TCheckbutton", command=self.refresh).pack(side=X("right"), padx=(0, 14))
        self.count = ttk.Label(bar, text="", style="Hint.TLabel")
        self.count.pack(side=X("left"))
        for c in (sb, mb):
            c.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        body = ttk.Frame(self.top)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.canvas = tk.Canvas(body, highlightthickness=0, background=P["bg"])
        self.vs = ttk.Scrollbar(body, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.on_scroll)
        self.vs.pack(side=X("left"), fill="y")
        self.canvas.pack(side=X("left"), fill="both", expand=True)
        self.canvas.bind("<Configure>", self.on_resize)
        self.smooth = SmoothScroller(self.canvas)
        self.top.bind("<MouseWheel>", self.on_wheel)
        self.top.bind("<Button-4>", lambda e: self.smooth.notches(1))
        self.top.bind("<Button-5>", lambda e: self.smooth.notches(-1))
        self.top.bind("<Escape>", lambda e: self.top.destroy())

    def on_wheel(self, e):
        self.smooth.notches(1 if e.delta > 0 else -1)

    def on_scroll(self, a, b):
        self.vs.set(a, b)
        if self.load_job is None:
            self.load_job = self.top.after(30, self.load_visible)

    def on_resize(self, e):
        cols = max(1, e.width // self.cell_w)
        if cols != self.cols:
            if self.resize_job:
                self.top.after_cancel(self.resize_job)
            self.resize_job = self.top.after(120, self.render)      # draw again once the resizing settles
        else:
            self.center()

    # ---- content
    def refresh(self):
        how = next((k for k, n in SORTS if i18n.tr(n) == self.sort_var.get()), "score")
        self.shown = sort_items(self.items, how, int(self.min_var.get() or 0), self.gem_var.get())
        self.limit = MAX_SHOWN
        self.render()

    def center(self):
        """Keep the grid in the middle when the width changes by less than a column."""
        width = self.canvas.winfo_width()
        x = max(0, (width - self.cols * self.cell_w) // 2)
        self.canvas.xview_moveto(0)
        self.canvas.configure(scrollregion=(-x, 0, width - x, self.total_h))

    def render(self, keep_y=None):
        R = self.R
        self.resize_job = None
        self.canvas.delete("all")
        self.img_items = {}
        total = len(self.items)
        if not total:
            self.count.configure(text=R("לא נמצאו תוצאות בתיקייה הזו." if self.kind is None else "אין תמונות להצגה."))
        else:
            self.count.configure(text=R(f"מוצגות {len(self.shown)} מתוך {total}"))
        batch = self.shown[:self.limit]
        width = max(self.canvas.winfo_width(), self.cell_w)
        self.cols = max(1, width // self.cell_w)
        rows = (len(batch) + self.cols - 1) // self.cols
        self.total_h = rows * self.cell_h + (60 if len(self.shown) > self.limit else 8)
        P, th = self.theme, self.thumb
        note_w = self.cell_w - 20
        for n, it in enumerate(batch):
            row, col = divmod(n, self.cols)
            if i18n.rtl():
                col = self.cols - 1 - col                    # right-to-left: the first photo is at the top right
            x0, y0 = col * self.cell_w + 4, row * self.cell_h + 4
            x1, y1 = x0 + self.cell_w - 8, y0 + self.cell_h - 8
            cx = (x0 + x1) // 2
            tag = f"c{n}"
            self.canvas.create_rectangle(x0, y0, x1, y1, fill=P["surface"], outline="", tags=(tag, "cell"))
            score = "" if it["score"] is None else f"{it['score']:.0f}"
            self.canvas.create_text(cx, y0 + th + 20, text=("★ " if it["gem"] else "") + score, font=self.f_score,
                                    fill=P["accent"] if it["gem"] else P["fg"], tags=(tag,))
            self.canvas.create_text(cx, y0 + th + 40, text=it["name"], font=self.f_name, fill=P["muted"], tags=(tag,))
            note = (it.get("note") or "").strip()
            if note:
                if len(note) > 90:
                    note = note[:88].rsplit(" ", 1)[0] + "…"
                shown = bidi_text.wrap_text(note, note_w, self.f_note, i18n.rtl())
                self.canvas.create_text(cx, y0 + th + 52, text=shown, font=self.f_note, fill=P["muted"],
                                        anchor="n", justify="center", tags=(tag,))
            self.canvas.tag_bind(tag, "<Button-1>", lambda e, k=n: self.detail(k))
            self.canvas.tag_bind(tag, "<Enter>", lambda e: self.canvas.configure(cursor="hand2"))
            self.canvas.tag_bind(tag, "<Leave>", lambda e: self.canvas.configure(cursor=""))
        if len(self.shown) > self.limit:
            more = min(MAX_SHOWN, len(self.shown) - self.limit)
            b = ttk.Button(self.canvas, text=R(f"הצג עוד {more}"), command=self.more)
            self.canvas.create_window(width // 2, rows * self.cell_h + 28, window=b)
        self.center()
        self.canvas.yview_moveto(0 if keep_y is None else min(1.0, keep_y / max(1, self.total_h)))
        self.load_visible()

    def more(self):
        self.limit += MAX_SHOWN
        self.render(keep_y=self.canvas.canvasy(0))

    def load_visible(self):
        """Load the thumbnails of the rows in view (and one row around them), nothing else."""
        self.load_job = None
        batch = self.shown[:self.limit]
        if not batch:
            return
        top = self.canvas.canvasy(0)
        bottom = top + self.canvas.winfo_height()
        first = max(0, int(top // self.cell_h) - 1)
        last = int(bottom // self.cell_h) + 1
        P, th = self.theme, self.thumb
        for n in range(first * self.cols, min(len(batch), (last + 1) * self.cols)):
            if n in self.img_items:
                continue
            row, col = divmod(n, self.cols)
            if i18n.rtl():
                col = self.cols - 1 - col
            cx = col * self.cell_w + 4 + (self.cell_w - 8) // 2
            cy = row * self.cell_h + 4 + th // 2 + 8
            img = self.photo(batch[n])
            tag = f"c{n}"
            if img:
                item = self.canvas.create_image(cx, cy, image=img, tags=(tag,))
            else:
                item = self.canvas.create_text(cx, cy, text=self.R("אין תצוגה"), fill=P["muted"], tags=(tag,))
            self.img_items[n] = item

    def photo(self, it):
        p = it["image"]
        if not p or Image is None:
            return None
        key = str(p)
        if key not in self.photos:
            try:
                im = Image.open(p).convert("RGB")
                im.thumbnail((self.thumb, self.thumb))
                self.photos[key] = ImageTk.PhotoImage(im)
            except (OSError, ValueError):
                self.photos[key] = None
        return self.photos[key]

    # ---- one photo, large
    def detail(self, k):
        self.cur = k
        if not hasattr(self, "dw") or not self.dw.winfo_exists():
            P = self.theme
            self.dw = tk.Toplevel(self.top)
            self.dw.configure(background=P["bg"])
            self.dw.geometry(f"{int(900 * self.scale)}x{int(760 * self.scale)}")
            self.dw.minsize(int(480 * self.scale), int(420 * self.scale))
            self.dw.bind("<Escape>", lambda e: self.dw.destroy())
            self.dw.bind("<Left>", lambda e: self.step(1))      # right-to-left: left = next
            self.dw.bind("<Right>", lambda e: self.step(-1))
            # the buttons and the text are packed first, at the bottom, so a large picture can never push them out
            bb = ttk.Frame(self.dw)
            bb.pack(side="bottom", fill="x", padx=10, pady=8)
            ttk.Button(bb, text=self.R("הצג בתיקייה"), command=lambda: show_in_folder(
                self.shown[self.cur]["path"], self.open_path)).pack(side=X("right"), padx=4)
            ttk.Button(bb, text=self.R("העתק נתיב"), command=self.copy_path).pack(side=X("right"), padx=4)
            ttk.Button(bb, text=self.R("הבאה"), command=lambda: self.step(1)).pack(side=X("left"), padx=4)
            ttk.Button(bb, text=self.R("הקודמת"), command=lambda: self.step(-1)).pack(side=X("left"), padx=4)
            import tkinter.font as tkfont
            self.f_detail = tkfont.Font(root=self.dw, family=UI_FONT, size=10)
            self.dtxt = tk.Label(self.dw, background=P["bg"], foreground=P["fg"], font=self.f_detail,
                                 justify=X("right"), anchor=X("e"))
            self.dtxt.pack(side="bottom", fill="x", padx=14, pady=(0, 4))
            self.dimg = tk.Label(self.dw, background=P["bg"])
            self.dimg.pack(side="top", fill="both", expand=True, padx=8, pady=8)
            self.dimg.bind("<Configure>", lambda e: self.schedule_detail())
            self.detail_job = None
        self.dw.lift()
        self.dw.focus_set()
        it = self.shown[k]
        self.dw.title(it["name"])
        self.dsrc = None
        if it["image"] and Image is not None:
            try:
                self.dsrc = Image.open(it["image"]).convert("RGB")
            except (OSError, ValueError):
                pass
        self.draw_detail()

    def schedule_detail(self):
        if self.detail_job:
            self.dw.after_cancel(self.detail_job)
        self.detail_job = self.dw.after(100, self.draw_detail)

    def draw_detail(self):
        self.detail_job = None
        if not self.dw.winfo_exists():
            return
        it = self.shown[self.cur]
        w, h = max(100, self.dimg.winfo_width() - 8), max(100, self.dimg.winfo_height() - 8)
        self.dphoto = None
        if self.dsrc is not None:
            im = self.dsrc.copy()
            im.thumbnail((w, h))                               # the picture fits the space that is left
            self.dphoto = ImageTk.PhotoImage(im)
        self.dimg.configure(image=self.dphoto or "", text="" if self.dphoto else self.R("אין תצוגה"),
                            foreground=self.theme["muted"])
        head = ("★ בולטת. " if it["gem"] else "") + ("" if it["score"] is None else f"ציון {it['score']:.0f}.  ")
        text = i18n.tr(head + it["name"]) + "\n" + "\n".join(i18n.tr(x) for x in it["lines"])
        shown = bidi_text.wrap_text(text, max(240, self.dw.winfo_width() - 60), self.f_detail, i18n.rtl())
        self.dtxt.configure(text=shown)

    def step(self, d):
        k = self.cur + d
        if 0 <= k < len(self.shown):
            self.detail(k)

    def copy_path(self):
        self.top.clipboard_clear()
        self.top.clipboard_append(self.shown[self.cur]["path"])
