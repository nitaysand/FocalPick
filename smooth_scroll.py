# © 2026 נתאי שנדורפי (Nitay Sandorffy). MIT License.
"""
Smooth mouse-wheel scrolling for Tk canvases and text boxes.

Tk scrolls a canvas in big jumps (a tenth of the window by default) and a text box line by line,
which looks like a low refresh rate. Here a wheel notch only adds to a distance still to travel, and a short
timer covers that distance in small pixel steps that slow down towards the end.
"""
__author__ = "נתאי שנדורפי"
__copyright__ = "© 2026 נתאי שנדורפי. MIT License."

NOTCH = 60          # pixels per wheel notch
TICK_MS = 12        # time between small steps
EASE = 0.28         # share of the remaining distance covered in each step
WINDOW = 0.30       # seconds: notches within this time count as "fast scrolling"
BOOST = 0.55        # extra distance per notch for every additional notch inside the window
MAX_MULT = 6.0      # fast scrolling never goes more than this many times faster than slow scrolling


import time


class SmoothScroller:
    def __init__(self, widget):
        self.w = widget
        self.is_canvas = widget.winfo_class() == "Canvas"
        if self.is_canvas:
            widget.configure(yscrollincrement=1)        # 1 pixel per "unit": the view can stop anywhere
        self.pending = 0.0
        self.job = None
        self.recent = []                                # times of the latest notches

    def notches(self, n):
        """n > 0 scrolls up, n < 0 scrolls down (the sign of a wheel delta)."""
        now = time.monotonic()
        self.recent = [t for t in self.recent if now - t < WINDOW]
        mult = min(MAX_MULT, 1 + BOOST * len(self.recent))   # the faster the wheel turns, the longer each notch travels
        self.recent.append(now)
        self.pending -= n * NOTCH * mult
        if self.job is None:
            self._tick()

    def _move(self, px):
        if self.is_canvas:
            self.w.yview_scroll(px, "units")
        else:
            self.w.yview_scroll(px, "pixels")

    def _tick(self):
        self.job = None
        if abs(self.pending) < 1:
            self.pending = 0.0
            return
        step = self.pending * EASE
        step = int(step) if abs(step) >= 1 else (1 if step > 0 else -1)
        self.pending -= step
        try:
            before = self.w.yview()
            self._move(step)
            after = self.w.yview()
        except Exception:                               # the widget was destroyed while scrolling
            self.pending = 0.0
            return
        if after == before:                             # already at the top or the bottom
            self.pending = 0.0
            return
        self.job = self.w.after(TICK_MS, self._tick)
