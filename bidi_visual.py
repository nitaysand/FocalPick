# © 2026 נתאי שנדורפי (Nitay Sandorffy). MIT License.
"""
bidi_visual.py - Hebrew (and Arabic) lines turned into VISUAL order, for Tk text boxes on Windows.

Why: a Tk text box draws its text in separate pieces (a new piece starts wherever a tag, the cursor or the
selection starts), and Windows reorders every piece on its own with a left-to-right base direction. A line
with the selection in its middle then comes out scrambled, and a wrapped line loses its direction.

What this module does instead: it runs the Unicode bidirectional algorithm itself, so the text can be put into
the box already in the order in which it is to be seen, and it puts an invisible left-to-right mark after every
Hebrew letter. Every Hebrew letter is then a run of its own between two left-to-right characters, so Windows has
nothing left to reorder, whatever way the text is cut into pieces. Selecting only part of a line is safe too.

    to_visual(text)  ->  (visual string, map)
        map[i] is the index in `text` of the i-th character of the visual string, or None for an added mark.
    wrap_visual(text, width, measure)  ->  list of (visual string, map, logical start, logical end)
    has_rtl(text)

The algorithm is the standard one (UAX #9) for a paragraph whose base direction is right-to-left: rules W1-W7,
N0-N2, I1-I2, L1, L2 and L4. Embeddings and isolates are not supported: those control characters are removed.
"""
import re
import unicodedata

LRM = "‎"
_CONTROLS = re.compile("[‎‏‪-‮⁦-⁩]")
_PAIRS = {"(": ")", "[": "]", "{": "}"}
_CLOSE = {v: k for k, v in _PAIRS.items()}
_MIRROR = {"(": ")", ")": "(", "[": "]", "]": "[", "{": "}", "}": "{", "<": ">", ">": "<",
           "«": "»", "»": "«", "‹": "›", "›": "‹"}
_NI = {"B", "S", "WS", "ON"}
_RTL_CLASSES = {"R", "AL"}


def has_rtl(text):
    return any(unicodedata.bidirectional(c) in _RTL_CLASSES for c in text)


def strip_marks(text):
    return _CONTROLS.sub("", text)


def _resolve(text):
    """Embedding level (1 or 2) of every character, for a right-to-left paragraph."""
    n = len(text)
    orig = [unicodedata.bidirectional(c) for c in text]
    t = list(orig)
    sos = "R"
    # W1: a combining mark takes the type of the character before it
    for i in range(n):
        if t[i] == "NSM":
            t[i] = t[i - 1] if i else sos
    # W2: a European digit after an Arabic letter is an Arabic digit
    last = sos
    for i in range(n):
        if t[i] in ("L", "R", "AL"):
            last = t[i]
        elif t[i] == "EN" and last == "AL":
            t[i] = "AN"
    # W3
    t = ["R" if x == "AL" else x for x in t]
    # W4: a single separator between two numbers of the same kind
    for i in range(1, n - 1):
        if t[i] == "ES" and t[i - 1] == "EN" and t[i + 1] == "EN":
            t[i] = "EN"
        elif t[i] == "CS" and t[i - 1] == t[i + 1] and t[i - 1] in ("EN", "AN"):
            t[i] = t[i - 1]
    # W5: terminators next to a European digit
    i = 0
    while i < n:
        if t[i] == "ET":
            j = i
            while j < n and t[j] == "ET":
                j += 1
            if (i > 0 and t[i - 1] == "EN") or (j < n and t[j] == "EN"):
                for k in range(i, j):
                    t[k] = "EN"
            i = j
        else:
            i += 1
    # W6
    t = ["ON" if x in ("ES", "ET", "CS") else x for x in t]
    # W7: a European digit after a left-to-right letter is a left-to-right letter
    last = sos
    for i in range(n):
        if t[i] in ("L", "R"):
            last = t[i]
        elif t[i] == "EN" and last == "L":
            t[i] = "L"

    def strong(x):
        return "R" if x in ("R", "EN", "AN") else ("L" if x == "L" else None)

    # N0: paired brackets
    stack, pairs = [], []
    for i, ch in enumerate(text):
        if t[i] != "ON":
            continue
        if ch in _PAIRS:
            stack.append((i, _PAIRS[ch]))
        elif ch in _CLOSE:
            for k in range(len(stack) - 1, -1, -1):
                if stack[k][1] == ch:
                    pairs.append((stack[k][0], i))
                    del stack[k:]
                    break
    for o, c in sorted(pairs):
        inside = {strong(x) for x in t[o + 1:c]} - {None}
        if not inside:
            continue
        if "R" in inside:                         # the embedding direction (right-to-left) is inside
            d = "R"
        else:                                     # only the opposite direction inside: the context decides
            before = sos
            for k in range(o - 1, -1, -1):
                if strong(t[k]):
                    before = strong(t[k])
                    break
            d = "L" if before == "L" else "R"
        t[o] = t[c] = d
    # N1 / N2: neutrals between two strong characters of one direction take it, else the embedding direction
    i = 0
    while i < n:
        if t[i] in _NI:
            j = i
            while j < n and t[j] in _NI:
                j += 1
            a = strong(t[i - 1]) if i else "R"
            b = strong(t[j]) if j < n else "R"
            d = a if a == b else "R"
            for k in range(i, j):
                t[k] = d
            i = j
        else:
            i += 1
    # I1 / I2 for base level 1
    return [1 if x == "R" else 2 for x in t], orig


def to_visual(text):
    """The line in the order it is to be seen, with a left-to-right mark after each Hebrew letter, and the map back."""
    text = strip_marks(text)
    if not has_rtl(text):
        return text, list(range(len(text)))
    levels, orig = _resolve(text)
    n = len(text)
    # L1: spaces at the end of the line go back to the paragraph level
    k = n
    while k > 0 and orig[k - 1] in ("WS", "B", "S"):
        k -= 1
        levels[k] = 1
    order = list(range(n))
    top = max(levels)
    for lvl in range(top, 0, -1):                 # L2
        i = 0
        while i < n:
            if levels[order[i]] >= lvl:
                j = i
                while j < n and levels[order[j]] >= lvl:
                    j += 1
                order[i:j] = reversed(order[i:j])
                i = j
            else:
                i += 1
    out, idx = [], []
    for pos in order:
        ch = text[pos]
        if levels[pos] % 2 == 1:                  # L4
            ch = _MIRROR.get(ch, ch)
        out.append(ch)
        idx.append(pos)
        if orig[pos] in _RTL_CLASSES:
            out.append(LRM)
            idx.append(None)
    return "".join(out), idx


def wrap_visual(text, width, measure):
    """Break a logical line at spaces so that each piece, as it is drawn, fits in `width` pixels.
    Returns a list of (visual string, map into the logical line, start, end) where start/end bound the logical piece."""
    text = strip_marks(text)
    vis, mp = to_visual(text)
    if measure(vis) <= width:                      # the common case: one piece
        return [(vis, mp, 0, len(text))]
    words, pos = [], 0
    for part in re.split(r"( +)", text):
        if part:
            words.append((pos, part))
            pos += len(part)
    pieces, cur_start, cur_end = [], 0, 0

    def make(a, b):
        vis, mp = to_visual(text[a:b])
        return vis, [None if m is None else m + a for m in mp], a, b

    def fits(a, b):
        return measure(to_visual(text[a:b])[0]) <= width

    first = True
    for wpos, word in words:
        if word.isspace():
            continue
        wend = wpos + len(word)
        if first:
            cur_start, cur_end, first = 0, wend, False
            if not fits(cur_start, cur_end):
                pieces, cur_start, cur_end = _split_long(text, cur_start, cur_end, width, measure, make, pieces)
            continue
        if fits(cur_start, wend):
            cur_end = wend
        else:
            pieces.append(make(cur_start, cur_end))
            cur_start, cur_end = wpos, wend
            if not fits(cur_start, cur_end):
                pieces, cur_start, cur_end = _split_long(text, cur_start, cur_end, width, measure, make, pieces)
    if first:
        return [make(0, len(text))]
    pieces.append(make(cur_start, cur_end))
    return pieces


def _split_long(text, a, b, width, measure, make, pieces):
    """One word wider than the line: cut it by characters."""
    start = a
    for k in range(a + 1, b + 1):
        if measure(to_visual(text[start:k])[0]) > width and k - 1 > start:
            pieces.append(make(start, k - 1))
            start = k - 1
    return pieces, start, b


def logical_from_selection(text_map, first, last):
    """Characters of the logical line behind visual columns first..last-1, in logical order."""
    got = sorted({m for m in text_map[first:last] if m is not None})
    return got
