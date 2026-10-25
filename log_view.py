# © 2026 נתאי שנדורפי (Nitay Sandorffy). MIT License.
"""
log_view.py - the running log in the main window: a read-only Tk text box that shows Hebrew correctly.

Lines with Hebrew are wrapped here (in logical order), turned into visual order and drawn right-aligned
(see bidi_visual.py for why), so any part of a line can be selected and copied. What is copied is always the
real, logical text, never the visual one. Lines without Hebrew are drawn as they are.

    log = RtlLog(text_widget, font, rtl=True)
    log.append("text...")     text may end in the middle of a line; the open line is redrawn as it grows
    log.text()                the whole log, as plain logical text
    log.selection()           what is selected, as plain logical text
    log.clear()
"""
__author__ = "נתאי שנדורפי"
import tkinter.font as tkfont

import bidi_visual as bv


class RtlLog:
    def __init__(self, widget, rtl=True):
        self.t = widget
        self.rtl = rtl
        self.font = tkfont.Font(root=widget, font=widget.cget("font"))
        self.lines = []            # logical lines; the last one may still be open (no line break yet)
        self.open = False
        self.rows = []             # one record per line of the text box: (kind, logical line index, map, start, end)
        self.first_row = []        # logical line index -> first row of the text box
        self.last_width = 0
        self._job = None
        widget.tag_configure("rtl", justify="right")
        widget.tag_configure("ltr", justify="left")
        widget.bind("<Configure>", self._on_configure, add="+")

    # ---- size
    def width(self):
        w = self.t.winfo_width()
        if w <= 1:
            return 600
        pad = int(self.t.cget("padx")) + int(self.t.cget("borderwidth")) + int(self.t.cget("highlightthickness"))
        return max(120, w - 2 * pad - 6)

    def _on_configure(self, _e):
        w = self.width()
        if abs(w - self.last_width) < 8:
            return
        self.last_width = w
        if self._job:
            self.t.after_cancel(self._job)
        self._job = self.t.after(250, self.redraw)

    # ---- drawing
    def _draw(self, start):
        """(Re)draw logical lines start.. at the end of the text box."""
        if start < len(self.first_row):
            row = self.first_row[start]
            self.t.delete(f"{row + 1}.0", "end-1c")
            del self.rows[row:]
            del self.first_row[start:]
        width = self.width()
        self.last_width = width
        for i in range(start, len(self.lines)):
            self.first_row.append(len(self.rows))
            line = self.lines[i]
            if self.rtl and bv.has_rtl(line):
                for vis, mp, a, b in bv.wrap_visual(line, width, self.font.measure):
                    self.t.insert("end", vis + "\n", "rtl")
                    self.rows.append(("rtl", i, mp, a, b))
            else:
                self.t.insert("end", line + "\n", "ltr")
                self.rows.append(("ltr", i, None, 0, len(line)))

    def redraw(self):
        self._job = None
        at_end = self.t.yview()[1] >= 0.999
        self.t.delete("1.0", "end")
        self.rows.clear()
        self.first_row.clear()
        self._draw(0)
        if at_end:
            self.t.see("end")

    def append(self, text):
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if not text:
            return
        parts = text.split("\n")
        start = len(self.lines) - 1 if (self.open and self.lines) else len(self.lines)
        if self.open and self.lines:
            self.lines[-1] += parts[0]
        else:
            self.lines.append(parts[0])
        self.lines.extend(parts[1:])
        self.open = parts[-1] != ""
        if not self.open and len(parts) > 1:
            self.lines.pop()                       # the text ended with a line break: no open line
        self._draw(start)
        self.t.see("end")

    def clear(self):
        self.t.delete("1.0", "end")
        self.lines, self.rows, self.first_row, self.open = [], [], [], False

    # ---- reading back
    def text(self):
        return "\n".join(self.lines)

    def selection(self):
        """The selected text, as logical text. Pieces of one wrapped line are joined with a space."""
        try:
            first, last = self.t.index("sel.first"), self.t.index("sel.last")
        except Exception:
            return ""
        (l0, c0), (l1, c1) = (tuple(map(int, first.split("."))), tuple(map(int, last.split("."))))
        out, prev_line = [], None
        for n in range(l0, l1 + 1):
            if n - 1 >= len(self.rows):
                break
            kind, li, mp, a, b = self.rows[n - 1]
            vis_len = len(self.t.get(f"{n}.0", f"{n}.end"))
            lo = c0 if n == l0 else 0
            hi = c1 if n == l1 else vis_len
            if kind == "rtl":
                idx = bv.logical_from_selection(mp, lo, hi)
                piece = "".join(self.lines[li][k] for k in idx)
            else:
                piece = self.lines[li][lo:hi]
            if out:
                out.append(" " if (prev_line == li and kind == "rtl") else "\n")
            out.append(piece)
            prev_line = li
        return "".join(out)

    def select_all(self):
        self.t.tag_add("sel", "1.0", "end-1c")
