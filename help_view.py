"""
help_view.py - the built-in guide: a window that shows photo_tools_guide.html inside the program.

The guide is a normal HTML file (also readable in a browser). This module reads it, leaves out the parts
that are only for the command line (anything marked class="cli") and shows the rest, one chapter at a time,
with a list of chapters on the side. There is one guide per language: photo_tools_guide.html (Hebrew) and
lang/guide_<code>.html for the others; if a language has no guide, the Hebrew one is shown.

Text is drawn one paragraph at a time with a single style per line (no bold or colour in the middle of a
line), because Tk draws each differently-styled piece of a line on its own, which would scramble the order
of a right-to-left line.

Copyright (c) 2026 נתאי שנדורפי (Nitay Sandorffy). MIT License.
"""
import re
import sys
import tkinter as tk
from html.parser import HTMLParser
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk

import bidi_text
import i18n
import line_select
from smooth_scroll import SmoothScroller

HERE = Path(__file__).resolve().parent
_SKIP_TAGS = {"head", "style", "script", "title", "svg"}
_BLOCK_END = {"p", "li", "h2", "h3", "pre"}


# ---------------------------------------------------------------- reading the guide
class _Guide(HTMLParser):
    """Turns the guide into chapters: [(title, [(kind, text), ...])]. Kinds: p, h3, li, pre, note, warn."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chapters, self.blocks = [], []
        self.title = None
        self.rtl = True
        self.buf = []
        self.kind = None
        self.hide = None            # [tag, depth] while inside an element marked class="cli"
        self.skip = 0
        self.lists = []             # open lists: ["ol", counter] or ["ul", 0]
        self.boxes = []             # open <div class="note|warn"> boxes
        self.cells = []
        self.in_row = False
        self.header_row = False
        self.in_pre = False

    # -- helpers
    def flush(self):
        text = "".join(self.buf)
        self.buf = []
        kind, self.kind = self.kind, None
        if not kind:
            return
        if kind == "pre":
            text = text.strip("\n")
        else:
            text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return
        if self.boxes and kind in ("p", "li"):
            kind = self.boxes[-1]
        self.blocks.append((kind, text))

    def start_chapter(self, title):
        self.end_chapter()
        self.title = title

    def end_chapter(self):
        self.flush()
        if self.blocks or self.title:
            self.chapters.append((self.title or "", self.blocks))
        self.blocks = []

    # -- parser events
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.rtl = (a.get("dir", "rtl") == "rtl")
        if self.hide:
            if tag == self.hide[0]:
                self.hide[1] += 1
            return
        if "cli" in (a.get("class") or "").split():
            self.flush()
            self.hide = [tag, 1]
            return
        if tag in _SKIP_TAGS:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "h2":
            self.flush()
            self.kind = "chapter"
        elif tag == "h3":
            self.flush()
            self.kind = "h3"
        elif tag == "p":
            self.flush()
            self.kind = "p"
        elif tag in ("ul", "ol"):
            self.flush()
            self.lists.append([tag, 0])
        elif tag == "li":
            self.flush()
            self.kind = "li"
            if self.lists:
                self.lists[-1][1] += 1
                self.buf.append(f"{self.lists[-1][1]}. " if self.lists[-1][0] == "ol" else "• ")
        elif tag == "pre":
            self.flush()
            self.kind = "pre"
            self.in_pre = True
        elif tag == "div":
            cls = (a.get("class") or "").split()
            self.flush()
            self.boxes.append("warn" if "warn" in cls else "note" if "note" in cls else None)
            if self.boxes[-1]:
                self.kind = self.boxes[-1]
        elif tag == "tr":
            self.flush()
            self.cells, self.in_row, self.header_row = [], True, False
        elif tag in ("td", "th"):
            self.flush()
            self.kind = "cell"
            self.header_row = self.header_row or tag == "th"
        elif tag == "br":
            self.buf.append("\n" if self.in_pre else " ")

    def handle_endtag(self, tag):
        if self.hide:
            if tag == self.hide[0]:
                self.hide[1] -= 1
                if self.hide[1] == 0:
                    self.hide = None
            return
        if tag in _SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == "h2":
            text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
            self.buf, self.kind = [], None
            self.start_chapter(text)
        elif tag in _BLOCK_END:
            self.flush()
            self.in_pre = tag != "pre" and self.in_pre
        elif tag in ("ul", "ol"):
            self.flush()
            if self.lists:
                self.lists.pop()
        elif tag in ("td", "th"):
            self.cells.append(re.sub(r"\s+", " ", "".join(self.buf)).strip())
            self.buf, self.kind = [], None
        elif tag == "tr":
            cells = [c for c in self.cells if c]
            if cells and not self.header_row:
                head, rest = cells[0], cells[1:]
                self.blocks.append(("li", "• " + head + (": " + " · ".join(rest) if rest else "")))
            self.in_row = False
        elif tag == "div" and self.boxes:
            self.flush()
            self.boxes.pop()

    def handle_data(self, data):
        if self.hide or self.skip:
            return
        if self.kind:
            self.buf.append(data)
        elif data.strip() and self.boxes and self.boxes[-1]:
            self.kind = self.boxes[-1]
            self.buf.append(data)


def parse_guide(html_text):
    """(chapters, rtl): the guide without its command-line parts."""
    g = _Guide()
    g.feed(html_text)
    g.end_chapter()
    chapters = [(t, b) for t, b in g.chapters if b]
    return chapters, g.rtl


def guide_file(lang):
    """The guide for this language, else the Hebrew one. None when no guide file is found."""
    dirs = i18n.lang_dirs() + [HERE] + ([Path(sys._MEIPASS)] if getattr(sys, "_MEIPASS", None) else [])
    if lang != "he":
        for d in dirs:
            f = d / f"guide_{lang}.html"
            if f.is_file():
                return f
    for d in dirs:
        f = d / "photo_tools_guide.html"
        if f.is_file():
            return f
    return None


def load_guide(lang=None):
    f = guide_file(lang or i18n.LANG)
    if not f:
        return [], True
    return parse_guide(f.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- the window
class NavList(tk.Text):
    """The chapter list. Long titles wrap onto several lines instead of being cut off, and each line is drawn on
    its own so Hebrew keeps its order. Click a title or use Up and Down."""
    WIDTH_PX = 260

    def __init__(self, parent, palette, font_name, rtl, titles):
        self.P, self.rtl_doc, self.titles, self.current = palette, rtl, titles, None
        self.font = tkfont.Font(font=(font_name, 10))
        super().__init__(parent, width=1, wrap="none", relief="flat", borderwidth=0, highlightthickness=1,
                         highlightbackground=palette["border"], background=palette["field"], foreground=palette["fg"],
                         font=self.font, cursor="arrow", padx=8, pady=6, spacing1=3, spacing3=3, takefocus=1,
                         exportselection=False, insertwidth=0)
        self.configure(width=max(24, int(self.WIDTH_PX / max(1, self.font.measure("0")))))
        just = "right" if rtl else "left"
        self.tag_configure("item", justify=just)
        self.tag_configure("cur", background=palette["sel"], foreground=palette["sel_fg"])
        self.bind("<Button-1>", self._click)
        self.bind("<Up>", lambda e: self._step(-1))
        self.bind("<Down>", lambda e: self._step(1))
        self.bind("<Key>", lambda e: "break")
        self.bind("<MouseWheel>", lambda e: (self.yview_scroll(-1 if e.delta > 0 else 1, "units"), "break")[1])
        self.bind("<Configure>", self._refit)
        self._width = 0
        self._fill()

    def _fill(self):
        px = max(120, (self._width or self.WIDTH_PX) - 24)
        self.configure(state="normal")
        self.delete("1.0", "end")
        for i, title in enumerate(self.titles):
            for line in bidi_text.wrap_lines(title, px, self.font, max_chars=40):
                shown = bidi_text.RLE + line + bidi_text.PDF if self.rtl_doc and bidi_text.has_hebrew(line) else line
                self.insert("end", shown + "\n", ("item", f"i{i}"))
        self.configure(state="disabled")
        if self.current is not None:
            self._mark()

    def _refit(self, e):
        if abs(e.width - self._width) > 6:
            self._width = e.width
            self.after(120, self._fill)

    def _mark(self):
        self.tag_remove("cur", "1.0", "end")
        rng = self.tag_ranges(f"i{self.current}")
        if rng:
            self.tag_add("cur", rng[0], rng[-1])
            self.see(rng[0])

    def _click(self, e):
        self.focus_set()
        for tag in self.tag_names(f"@{e.x},{e.y}"):
            if tag.startswith("i") and tag[1:].isdigit():
                self.selection_set(int(tag[1:]))
                self.event_generate("<<ListboxSelect>>")
                break
        return "break"

    def _step(self, d):
        i = 0 if self.current is None else max(0, min(len(self.titles) - 1, self.current + d))
        self.selection_set(i)
        self.event_generate("<<ListboxSelect>>")
        return "break"

    # the few Listbox methods the guide window uses
    def selection_set(self, i):
        self.current = i
        self._mark()

    def selection_clear(self, *_):
        self.current = None
        self.tag_remove("cur", "1.0", "end")

    def curselection(self):
        return () if self.current is None else (self.current,)


class GuideWindow:
    def __init__(self, parent, theme, R, ui_font, scale=1.0):
        self.parent, self.theme, self.R, self.ui_font = parent, theme, R, ui_font
        self.chapters, self.doc_rtl = load_guide()
        self.top = tk.Toplevel(parent)
        self.top.title(R("מדריך"))
        self.top.geometry(f"{int(1000 * scale)}x{int(720 * scale)}")
        self.top.minsize(int(620 * scale), int(380 * scale))
        self.top.configure(background=theme["bg"])
        self.current = 0
        self.job = None
        self.build()
        if self.chapters:
            self.nav.selection_set(0)
            self.show(0)
        else:
            self.text.configure(state="normal")
            self.text.insert("end", R("לא נמצא קובץ המדריך. הוא אמור להיות ליד התוכנה, בשם photo_tools_guide.html."))
            self.text.configure(state="disabled")
        self.top.bind("<Escape>", lambda e: self.top.destroy())

    def build(self):
        P, R = self.theme, self.R
        ui_rtl = i18n.rtl()
        body = ttk.Frame(self.top)
        body.pack(fill="both", expand=True, padx=8, pady=8)
        side = i18n.X("right")
        self.nav = NavList(body, P, self.ui_font, self.doc_rtl, [t or R("מבוא") for t, _ in self.chapters])
        self.nav.pack(side=side, fill="y", padx=(8, 0) if ui_rtl else (0, 8))
        self.nav.bind("<<ListboxSelect>>", self.on_pick)
        self.vsb = ttk.Scrollbar(body)
        self.vsb.pack(side=i18n.X("left"), fill="y")
        self.text = tk.Text(body, wrap="none", relief="flat", borderwidth=0, highlightthickness=1,
                            highlightbackground=P["border"], background=P["field"], foreground=P["fg"],
                            padx=18, pady=12, cursor="arrow", font=(self.ui_font, 10),
                            yscrollcommand=self.vsb.set, spacing1=2, spacing3=2)
        self.vsb.configure(command=self.text.yview)
        self.text.pack(side=i18n.X("left"), fill="both", expand=True)
        self.text.bind("<Key>", self.on_key)
        line_select.install(self.text, lambda: (P["sel"], P["sel_fg"]))
        self.smooth = SmoothScroller(self.text)
        self.text.bind("<MouseWheel>", lambda e: (self.smooth.notches(1 if e.delta > 0 else -1), "break")[1])
        self.text.bind("<Button-4>", lambda e: (self.smooth.notches(1), "break")[1])
        self.text.bind("<Button-5>", lambda e: (self.smooth.notches(-1), "break")[1])
        self.text.bind("<Configure>", self.on_resize)
        dark = bool(P.get("dark"))
        just = "right" if self.doc_rtl else "left"
        base = tkfont.Font(font=(self.ui_font, 10))
        self.font = base
        self.text.tag_configure("p", justify=just)
        self.text.tag_configure("li", justify=just, lmargin1=24, lmargin2=24, rmargin=24, spacing1=3)
        if self.doc_rtl:
            self.text.tag_configure("li", lmargin1=0, lmargin2=0)
        self.text.tag_configure("chapter", justify=just, font=(self.ui_font, 15, "bold"), foreground=P["accent"],
                                spacing3=10)
        self.text.tag_configure("h3", justify=just, font=(self.ui_font, 11, "bold"), spacing1=12, spacing3=4)
        mono = "Consolas" if sys.platform == "win32" else "Menlo" if sys.platform == "darwin" else "DejaVu Sans Mono"
        self.text.tag_configure("pre", justify=just, font=(mono, 10), background="#2c3347" if dark else "#eceff4",
                                lmargin1=10, lmargin2=10, rmargin=10, spacing1=0, spacing3=0)
        self.text.tag_configure("note", justify=just, background="#2e2a1c" if dark else "#fff8e1",
                                lmargin1=8, lmargin2=8, rmargin=8)
        self.text.tag_configure("warn", justify=just, background="#3a2224" if dark else "#fdecea",
                                lmargin1=8, lmargin2=8, rmargin=8)
        self.mono = tkfont.Font(font=(mono, 10))

    # ---- behaviour
    def on_key(self, event):
        """Read-only, but selecting and copying still work."""
        if event.state & 0x4 and event.keysym.lower() in ("c", "a"):
            return None
        if event.keysym in ("Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next"):
            return None
        return "break"

    def on_pick(self, _event=None):
        sel = self.nav.curselection()
        if sel:
            self.show(sel[0])

    def on_resize(self, _event=None):
        if self.job:
            self.top.after_cancel(self.job)
        self.job = self.top.after(150, lambda: self.show(self.current))

    def show(self, index):
        self.job = None
        self.current = index
        if not self.chapters:
            return
        width = max(200, self.text.winfo_width() - 60)
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        title, blocks = self.chapters[index]
        self.put(title or self.R("מבוא"), "chapter", width, self.font)
        for kind, text in blocks:
            if kind == "pre":
                for line in text.split("\n"):
                    self.put(line, "pre", width, self.mono, wrap=False)
            elif kind in ("note", "warn"):
                self.put(text, kind, width - 20, self.font)
                t.insert("end", "\n")
            else:
                self.put(text, kind, width - (24 if kind == "li" else 0), self.font)
        t.configure(state="disabled")
        t.yview_moveto(0)

    def put(self, text, tag, width, font, wrap=True):
        """One paragraph. Every line is closed off on its own, so each keeps the right base direction."""
        lines = bidi_text.wrap_lines(text, width, font) if wrap else [text]
        for line in lines:
            shown = bidi_text.RLE + line + bidi_text.PDF if self.doc_rtl and bidi_text.has_hebrew(line) else line
            self.text.insert("end", shown + "\n", tag)
        if tag in ("p", "chapter", "pre"):
            self.text.insert("end", "\n" if tag != "pre" else "", tag)
