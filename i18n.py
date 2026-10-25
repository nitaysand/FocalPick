"""
i18n.py - interface languages.

The program's own texts are written in Hebrew. A language file in lang/<code>.json maps each Hebrew text to the
same text in that language:  {"_name": "English", "_rtl": false, "strings": {"<hebrew>": "<translation>"}}.
A text with parts that change (numbers, names) is written with {0}, {1}... in both languages, and matched as a
template, so a finished line such as "נמצאו 12 קבצי RAW" is still found.

    tr(text)           the text in the current language (unchanged when there is no translation)
    set_lang(code)     choose the language; "he" needs no file
    rtl()              True for a right-to-left language (Hebrew)
    X(word)            mirror a direction word ("left", "e", "ne"...) when the language reads left to right
    col(i, span=1)     mirror a column of a 3-column form
    available()        {code: name} of the languages found

Adding a language: copy lang/en.json to lang/<code>.json, translate the values, set "_name" and "_rtl".
"""
import json
import os
import re
import sys
from pathlib import Path

LANG = "he"
NAME = "Hebrew"
GUI = False                 # the GUI translates what it shows itself; the console tools must then stay quiet
_exact, _templates = {}, []
_SLOT = re.compile(r"\{[^{}]*\}")
_CONTROLS = re.compile("[‎‏‪-‮⁦-⁩]")
_FLIP = {"left": "right", "right": "left", "e": "w", "w": "e", "ne": "nw", "nw": "ne", "se": "sw", "sw": "se",
         "en": "wn", "wn": "en", "es": "ws", "ws": "es"}
_rtl = True
MISSES = set()              # texts with no translation, for finding gaps (see PHOTO_TOOLS_I18N_DEBUG)


def lang_dirs():
    here = Path(__file__).resolve().parent
    dirs = [here / "lang", here / "lang" / "lang"]
    if getattr(sys, "_MEIPASS", None):
        dirs.append(Path(sys._MEIPASS) / "lang")
    dirs.append(Path.home() / ".photo_tools_lang")      # a user's own language files
    dirs.append(here)                                   # a language file left next to the program (must hold "strings")
    return dirs


def _files():
    found = {}
    for d in lang_dirs():
        if d.is_dir():
            for f in sorted(d.glob("*.json")):
                if d.name != "lang" and f.name != "en.json" and not f.stem.startswith("lang_"):
                    continue                            # in the program folder only en.json or lang_<code>.json count
                found[f.stem.replace("lang_", "", 1)] = f
    return found


def available():
    names = {"he": "עברית"}
    for code, f in _files().items():
        try:
            names[code] = json.loads(f.read_text(encoding="utf-8")).get("_name", code)
        except (OSError, ValueError):
            pass
    return names


def _template(he):
    """Regex for a Hebrew text with {n} slots, or None when it has none or is too loose to be safe."""
    parts = _SLOT.split(he)
    if len(parts) < 2 or sum(len(p.strip()) for p in parts) < 3:
        return None
    if not re.search("[֐-׿]", "".join(parts)):
        return None
    return re.compile("^" + "(.*?)".join(re.escape(p) for p in parts) + "$", re.S)


def set_lang(code):
    global LANG, _exact, _templates, _rtl
    global NAME
    LANG, _exact, _templates, _rtl, NAME = "he", {}, [], True, "Hebrew"
    if code == "he":
        return
    f = _files().get(code)
    if not f:
        return
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    LANG, _rtl = code, bool(data.get("_rtl", False))
    NAME = str(data.get("_name") or code)
    for he, tgt in (data.get("strings") or {}).items():
        if not isinstance(tgt, str) or not tgt:
            continue
        he, tgt = he.strip("\n"), tgt.strip("\n")             # line breaks around a text are not part of it
        if not he or not tgt:
            continue
        slots = _SLOT.findall(he)
        if slots:
            rx = _template(he)
            if rx:
                _templates.append((sum(len(p) for p in _SLOT.split(he)), rx, slots, tgt))
        else:
            _exact[he] = tgt
    _templates.sort(key=lambda t: -t[0])               # the most specific template first


def language_name():
    """English-readable name of the current language, for telling an AI model which language to write in."""
    return NAME


def rtl():
    return _rtl


def X(word):
    return word if _rtl else _FLIP.get(word, word)


def col(i, span=1, total=3):
    return i if _rtl else total - i - span


def _fill(slots, tgt, groups):
    """Put the captured pieces into the translation (the pieces are translated too, e.g. a duration)."""
    pieces = [tr(g) for g in groups]
    if all(s == "{}" for s in slots):                   # positional
        it = iter(pieces)
        return re.sub(r"\{\}", lambda m: next(it, ""), tgt)
    by_slot = {}
    for s, p in zip(slots, pieces):
        by_slot.setdefault(s, p)
    return _SLOT.sub(lambda m: by_slot.get(m.group(0), m.group(0)), tgt)


def _one(text):
    if text in _exact:
        return _exact[text]
    for _, rx, slots, tgt in _templates:
        m = rx.match(text)
        if m:
            return _fill(slots, tgt, m.groups())
    return None


_HEB = re.compile("[֐-׿]")


def tr(text):
    """The text in the current language. Direction marks are removed first."""
    if LANG == "he" or not text or not _HEB.search(text):
        return text
    text = _CONTROLS.sub("", text)
    core = text.strip("\n")
    if core != text:
        lead = text[:len(text) - len(text.lstrip("\n"))]
        return lead + tr(core) + text[len(text.rstrip("\n")):]
    hit = _one(text)
    if hit is not None:
        return hit
    if "\n" in text:                                    # a few lines printed together: translate line by line
        return "\n".join(tr(line) for line in text.split("\n"))
    stripped = text.strip()
    if stripped != text:                                # keep the surrounding spaces
        hit = _one(stripped)
        if hit is not None:
            lead = text[:len(text) - len(text.lstrip())]
            return lead + hit + text[len(text.rstrip()):]
    if os.environ.get("PHOTO_TOOLS_I18N_DEBUG"):
        MISSES.add(text)
    return text


def system_language():
    """'he' on a Hebrew Windows, otherwise 'en'."""
    try:
        if sys.platform == "win32":
            import ctypes
            if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x0D:
                return "he"
        else:
            import locale
            loc = (locale.getlocale()[0] or os.environ.get("LANG", "")).lower()
            if loc.startswith(("he", "iw")):
                return "he"
    except Exception:
        pass
    return "en"


def saved_language():
    """The language chosen in the GUI, else PHOTO_TOOLS_LANG, else the computer's."""
    code = os.environ.get("PHOTO_TOOLS_LANG")
    if not code:
        try:
            code = json.loads((Path.home() / ".photo_tools_gui.json").read_text(encoding="utf-8")).get("lang")
        except (OSError, ValueError):
            code = None
    return code or system_language()


class _Translating:
    """Wraps stdout/stderr of a console tool and translates each finished line."""
    def __init__(self, stream):
        self.stream, self.buf = stream, ""

    def write(self, s):
        self.buf += s
        done = ""
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            done += tr(line) + "\n"
        if done:
            self.stream.write(done)
        return len(s)

    def flush(self):
        if self.buf and not self.buf.endswith("\r"):
            self.stream.write(tr(self.buf))
            self.buf = ""
        self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def setup_cli():
    """Called at the start of a console tool: choose the language and translate what it prints."""
    if GUI:
        return
    set_lang(saved_language())
    if LANG != "he":
        sys.stdout = _Translating(sys.stdout)
        sys.stderr = _Translating(sys.stderr)
