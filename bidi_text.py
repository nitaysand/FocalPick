"""
bidi_text.py - Hebrew mixed with English, numbers and punctuation, shown in the right order in Tk.

Tk on Windows draws each line with a left-to-right base direction, so in a line that is mostly Hebrew the
punctuation, numbers and English words land in the wrong places. The fix is to wrap each line in the
Unicode "right-to-left embedding" control characters (RLE ... PDF). Windows then applies the standard
bidirectional algorithm to the line with a right-to-left base, which is what a Hebrew reader expects.

Tk wraps long text by itself, line by line, and the wrapped lines would lose that wrapper. So long
labels are wrapped here, in logical order, and every line gets its own wrapper (wrap_rtl).

    rtl_text(text)             wrap each line that contains Hebrew
    wrap_rtl(text, px, font)   wrap to px pixels (tkinter.font.Font), then rtl_text()
    strip(text)                remove the control characters again (for copying and saving)
"""
import re

RLE, PDF, RLM = "‫", "‬", "‏"
LRE = "‪"
BRAND = "FocalPick"      # the program name stays in English; inside Hebrew it is kept as one left-to-right unit
_CONTROLS = re.compile("[‎‏‪-‮⁦-⁩]")
_HEBREW = re.compile("[֐-׿]")


def has_hebrew(text):
    return bool(_HEBREW.search(text))


def rtl_text(text):
    """Each line that contains Hebrew is drawn with a right-to-left base direction.
    The program name inside such a line is embedded left-to-right, so punctuation or numbers next to it
    cannot reorder it."""
    return "\n".join(RLE + ln.replace(BRAND, LRE + BRAND + PDF) + PDF if has_hebrew(ln) else ln
                     for ln in text.split("\n"))


MAX_CHARS = 90      # a very long Hebrew line was drawn with its two halves swapped on Windows; keep lines short


def wrap_lines(text, width, font, max_chars=MAX_CHARS):
    """Break at spaces so that no line is wider than `width` pixels or longer than `max_chars`. Logical order."""
    lines = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split(" "):
            trial = word if not cur else cur + " " + word
            if cur and (font.measure(trial) > width or len(trial) > max_chars):
                lines.append(cur)
                cur = word
            else:
                cur = trial
        lines.append(cur)
    return lines


def wrap_rtl(text, width, font):
    return rtl_text("\n".join(wrap_lines(text, width, font)))


def wrap_text(text, width, font, rtl=True):
    """Wrap to a pixel width; right-to-left languages also get the direction wrapper on every line."""
    lines = "\n".join(wrap_lines(text, width, font))
    return rtl_text(lines) if rtl else lines


def strip(text):
    return _CONTROLS.sub("", text)
