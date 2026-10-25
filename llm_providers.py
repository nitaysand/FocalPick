#!/usr/bin/env python3
# © 2026 נתאי שנדורפי (Nitay Sandorffy). MIT License.
"""
חיבור למספר ספקי AI דרך ממשק אחד. הקובץ הזה משמש את rate_raw.py ו-ai_rate.py,
וחייב להיות איתם באותה תיקייה.

ספקים: Google Gemini, OpenAI, Anthropic (Claude), xAI (Grok), Mistral, Groq,
OpenRouter, Together AI, Fireworks AI, Ollama (מקומי), LM Studio (מקומי),
ושרת אחר שתואם OpenAI (עם כתובת משלך).

כל ההודעות בין הכלים לספק עוברות בפורמט פנימי אחד:
    [{"text": "..."}, {"inline_data": {"mime_type": "image/jpeg", "data": "<base64>"}}, ...]
וכאן הוא מתורגם לפורמט שכל ספק דורש.
"""
__author__ = "נתאי שנדורפי"
__copyright__ = "© 2026 נתאי שנדורפי. MIT License."
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path


class ApiError(Exception):
    def __init__(self, code, msg):
        super().__init__(f"HTTP {code}: {msg}")
        self.code = code


class TooManyImages(ApiError):
    """The model accepts fewer images per request than we sent. `limit` is how many it accepts."""
    def __init__(self, code, msg, limit):
        super().__init__(code, msg)
        self.limit = limit


_LIMIT_PATTERNS = [r"up to (\d+) images?", r"(?:maximum|max) (?:of )?(\d+) images?", r"at most (\d+) images?",
                   r"no more than (\d+) images?", r"(\d+) images? (?:per request|maximum|max)\b",
                   r"limit(?:ed)? (?:of|to) (\d+) images?"]


def _is_daily_limit(msg):
    low = msg.lower()
    return any(k in low for k in ("per day", "per-day", "perday", "daily", "requests per day", "tokens per day"))


def _images_limit(code, msg):
    low = msg.lower()
    if code in (400, 413, 422) and "image" in low:
        for pat in _LIMIT_PATTERNS:
            m = re.search(pat, low)
            if m:
                return int(m.group(1))
    return None


# kind: gemini | openai (the OpenAI-style /chat/completions) | anthropic
PROVIDERS = {
    "gemini": dict(label="Google Gemini", kind="gemini",
                   base="https://generativelanguage.googleapis.com/v1beta",
                   env=["GEMINI_API_KEY", "GOOGLE_API_KEY"],
                   models=["gemini-3.5-flash-lite", "gemini-3-flash-preview", "gemini-2.5-flash-lite",
                           "gemini-2.5-flash", "gemini-3.5-flash"],
                   delay=7, max_images=16, key_required=True,
                   note="יש שכבה חינמית עם מגבלות יומיות (aistudio.google.com)."),
    "openai": dict(label="OpenAI", kind="openai", base="https://api.openai.com/v1",
                   env=["OPENAI_API_KEY"], models=["gpt-4o-mini"],
                   delay=2, max_images=10, key_required=True,
                   note="בדרך כלל בתשלום לפי שימוש. אפשר לטעון את רשימת המודלים הנוכחית."),
    "anthropic": dict(label="Anthropic (Claude)", kind="anthropic", base="https://api.anthropic.com/v1",
                      env=["ANTHROPIC_API_KEY"], models=["claude-haiku-4-5-20251001", "claude-sonnet-5-5"],
                      delay=2, max_images=20, key_required=True,
                      note="בדרך כלל בתשלום לפי שימוש (console.anthropic.com)."),
    "xai": dict(label="xAI (Grok)", kind="openai", base="https://api.x.ai/v1",
                env=["XAI_API_KEY"], models=[], delay=2, max_images=10, key_required=True,
                note="Grok של איילון מאסק (x.ai). לא להתבלבל עם Groq. בדרך כלל בתשלום. כדאי ללחוץ 'הצג מודלים זמינים' ולבחור מודל שמבין תמונות."),
    "mistral": dict(label="Mistral", kind="openai", base="https://api.mistral.ai/v1",
                    env=["MISTRAL_API_KEY"], models=["mistral-small-latest"],
                    delay=2, max_images=8, key_required=True,
                    note="ייתכן שיש שכבה חינמית עם מגבלות. כדאי לבדוק באתר."),
    "groq": dict(label="Groq", kind="openai", base="https://api.groq.com/openai/v1",
                 env=["GROQ_API_KEY"], models=[], delay=3, max_images=5, key_required=True,
                 note="Groq (groq.com, החברה של שבבי ה-LPU), לא Grok של xAI. ייתכן שיש שכבה חינמית עם מגבלות. מוגבל ל-5 תמונות בבקשה. בחר מודל שמבין תמונות."),
    "openrouter": dict(label="OpenRouter", kind="openai", base="https://openrouter.ai/api/v1",
                       env=["OPENROUTER_API_KEY"],
                       models=["google/gemma-4-31b-it:free", "google/gemma-4-26b-a4b-it:free",
                               "nvidia/nemotron-nano-12b-v2-vl:free",
                               "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"],
                       delay=4, max_images=8, key_required=True, free_daily=50, free_suffix=":free",
                       note="שער למודלים רבים. מודלים עם הסיומת :free הם חינמיים, אבל מוגבלים ל-20 בקשות בדקה ול-50 ביום "
                            "(1,000 ביום אחרי רכישה חד-פעמית של 10 דולר בקרדיטים). רשימת המודלים החינמיים משתנה, אז כדאי "
                            "ללחוץ 'הצג מודלים זמינים'. חלק מהמודלים החינמיים עלולים לשמור או לאמן על מה שנשלח."),
    "together": dict(label="Together AI", kind="openai", base="https://api.together.xyz/v1",
                     env=["TOGETHER_API_KEY"], models=[], delay=2, max_images=8, key_required=True,
                     note="בדרך כלל בתשלום. בחר מודל שמבין תמונות מהרשימה."),
    "fireworks": dict(label="Fireworks AI", kind="openai", base="https://api.fireworks.ai/inference/v1",
                      env=["FIREWORKS_API_KEY"], models=[], delay=2, max_images=8, key_required=True,
                      note="בדרך כלל בתשלום. בחר מודל שמבין תמונות מהרשימה."),
    "ollama": dict(label="Ollama (רץ במחשב שלך)", kind="openai", base="http://localhost:11434/v1",
                   env=[], models=["llama3.2-vision"], delay=0, max_images=4, key_required=False,
                   local=True, note="חינם ופרטי, רץ במחשב שלך. צריך להתקין את Ollama ולהוריד מודל ראייה. "
                                    "איטי בלי כרטיס מסך חזק."),
    "lmstudio": dict(label="LM Studio (רץ במחשב שלך)", kind="openai", base="http://localhost:1234/v1",
                     env=[], models=[], delay=0, max_images=4, key_required=False, local=True,
                     note="חינם ופרטי, רץ במחשב שלך. טען מודל ראייה והפעל את השרת המקומי ב-LM Studio."),
    "custom": dict(label="אחר (שרת תואם OpenAI)", kind="openai", base="",
                   env=["AI_API_KEY"], models=[], delay=2, max_images=8, key_required=False,
                   note="לשרת משלך או לספק שלא ברשימה. חובה למלא כתובת בסיס, למשל https://.../v1"),
}
ORDER = ["gemini", "openai", "anthropic", "xai", "mistral", "groq", "openrouter", "together",
         "fireworks", "ollama", "lmstudio", "custom"]

# ---------------------------------------------------------------- provider data kept in files anyone can edit
# Free tiers, limits and model names change all the time, so they live in providers.json (next to this file),
# and each user can add their own changes in ~/.photo_tools_providers.json. Both are optional:
# the table above is the fallback. A file can change a provider's fields, add a provider, or set "order".
_FIELD_TYPES = {"label": str, "kind": str, "base": str, "note": str, "env": list, "models": list,
                "delay": (int, float), "max_images": int, "key_required": bool, "local": bool,
                "free_daily": int, "free_suffix": str}
_KINDS = ("gemini", "openai", "anthropic")


def _data_files():
    here = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return [here / "providers.json", Path.home() / ".photo_tools_providers.json"]


def _clean(entry):
    """Only well-formed fields are accepted, so a typo in a data file cannot break the tools."""
    out = {}
    for k, v in entry.items():
        want = _FIELD_TYPES.get(k)
        if want is None or (isinstance(v, bool) and want is not bool) or not isinstance(v, want):
            continue
        if k in ("env", "models") and not all(isinstance(x, str) for x in v):
            continue
        if k == "kind" and v not in _KINDS:
            continue
        out[k] = v
    return out


def load_provider_files(files=None):
    """Applies the data files on top of the built-in table. Returns a list of warnings (also printed)."""
    warnings = []
    for path in (files if files is not None else _data_files()):
        try:
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            warnings.append(f"לא הצלחתי לקרוא את {path.name}: {e}")
            continue
        for name, entry in (data.get("providers") or {}).items():
            if not isinstance(entry, dict) or not re.fullmatch(r"[a-z0-9_-]{2,30}", str(name)):
                warnings.append(f"{path.name}: דילגתי על ספק לא תקין ({name})")
                continue
            clean = _clean(entry)
            if name in PROVIDERS:
                PROVIDERS[name].update(clean)
            elif {"label", "kind", "base"} <= clean.keys():
                PROVIDERS[name] = {"env": [], "models": [], "delay": 2, "max_images": 8, "key_required": True,
                                   "note": "", **clean}
                ORDER.append(name)
            else:
                warnings.append(f"{path.name}: הספק {name} חדש וחסרים בו label, kind או base, ולכן דילגתי עליו")
        order = data.get("order")
        if isinstance(order, list):
            known = [n for n in order if n in PROVIDERS]
            ORDER[:] = known + [n for n in ORDER if n not in known]
    for w in warnings:
        print(w, file=sys.stderr)
    return warnings


load_provider_files()


_cfg = {"provider": "gemini", "base": None}


def configure(provider="gemini", base_url=None):
    if provider not in PROVIDERS:
        raise ValueError(f"ספק לא מוכר: {provider}. האפשרויות: {', '.join(ORDER)}")
    _cfg["provider"] = provider
    _cfg["base"] = (base_url or "").strip() or None
    if provider == "custom" and not _cfg["base"]:
        raise ValueError("בספק 'אחר' חובה למלא כתובת בסיס (למשל https://.../v1)")


@contextmanager
def using(provider, base_url=None):
    """Temporarily talk to another provider (used when a second or third model checks the first one's work)."""
    old = dict(_cfg)
    configure(provider, base_url)
    try:
        yield
    finally:
        _cfg.update(old)


def info(provider=None):
    return PROVIDERS[provider or _cfg["provider"]]


def base_url():
    return (_cfg["base"] or info()["base"]).rstrip("/")


def default_delay():
    return info()["delay"]


def max_images():
    return info()["max_images"]


def default_model():
    m = info()["models"]
    return m[0] if m else ""


# The GUI sets this to a function(text) -> bool that asks the user whether to go on.
# From the command line it stays None and the estimate is only printed.
confirm_hook = None


# ---- what this tool has sent lately, so the estimate can say how much of a daily quota is probably left.
# It only counts requests sent by this tool, and it learns the daily limit from the last time a provider refused.
USAGE_FILE = Path.home() / ".photo_tools_usage.json"
DAY = 24 * 3600


def _usage_key(model):
    return f"{_cfg['provider']}|{model}"


def _load_usage():
    try:
        return json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_usage(data):
    try:
        tmp = USAGE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(USAGE_FILE)
    except OSError:
        pass                                  # the estimate is a convenience, never a reason to stop the work


def _sent_last_day(rec, now):
    return [t for t in rec.get("sent", []) if now - t < DAY]


def record_request(model):
    if info().get("local"):
        return
    now, data = time.time(), _load_usage()
    rec = data.setdefault(_usage_key(model), {})
    rec["sent"] = _sent_last_day(rec, now) + [now]
    _save_usage(data)


def record_daily_limit(model):
    """A provider said the daily quota is over: remember how many requests this tool had sent in the last day."""
    if info().get("local"):
        return
    now, data = time.time(), _load_usage()
    rec = data.setdefault(_usage_key(model), {})
    n = len(_sent_last_day(rec, now))
    if n >= 3:
        rec["limit_hit"] = {"n": n, "at": now}
    _save_usage(data)


def quota_estimate(model):
    """(sent in the last 24 hours, known daily limit or None, requests probably left or None)."""
    now = time.time()
    rec = _load_usage().get(_usage_key(model), {})
    used = len(_sent_last_day(rec, now))
    hit = rec.get("limit_hit")
    if not hit or now - hit.get("at", 0) > 30 * DAY:
        return used, None, None
    return used, hit["n"], max(0, hit["n"] - used)


def _duration(seconds):
    m = int(round(seconds / 60))
    if m < 2:
        return "פחות משתי דקות"
    if m < 90:
        return f"כ-{m} דקות"
    h = m / 60
    return f"כ-{h:.1f} שעות".replace(".0", "")


def _job_lines(n_requests, model, delay):
    """The estimate lines for one provider (the one that is configured right now), and whether they warn."""
    d = default_delay() if delay is None else delay
    lines = []
    over = False
    daily = info().get("free_daily")
    suffix = info().get("free_suffix")
    if daily and suffix and str(model).endswith(suffix) and n_requests > daily:
        days = -(-n_requests // daily)
        lines.append(f"במודל חינמי כזה מותר בערך {daily} בקשות ביום, ולכן העבודה תתפרס על {days} ימים. "
                     "מה שהושלם נשמר, ואפשר להמשיך מחר באותה פקודה.")
        over = True
    used, limit, left = quota_estimate(model)
    if limit and not info().get("local"):
        lines.append(f"בפעם הקודמת שהמכסה היומית נגמרה, זה קרה אחרי כ-{limit} בקשות. "
                     f"ב-24 השעות האחרונות הכלי שלח {used}, כלומר נשארו בערך {left}. זו הערכה בלבד, כי היא לא רואה שימוש מחוץ לכלי.")
        if n_requests > left:
            lines.append("העבודה הזו גדולה מזה, ולכן סביר שתיעצר באמצע. מה שהושלם נשמר, ואפשר להמשיך אחר כך.")
            over = True
    if str(info().get("note", "")).startswith("בדרך כלל בתשלום") and not info().get("local"):
        lines.append("הספק הזה בדרך כלל בתשלום לפי שימוש. הכלי לא מחשב עלות, אז כדאי לבדוק את המחיר באתר הספק.")
    return lines, over, n_requests * (d + 8)


def confirm_work(n_requests, model="", delay=None, extra=None):
    """Print how big the job is. In the GUI, also ask before a big one. Returns False if the user says no.

    `extra` lists more jobs for other providers (a second model that checks the first, and a judge for
    disagreements): dicts with provider, base, model, n, delay and what. They are shown together,
    and the question is always asked, because the photos are then sent to more than one provider."""
    if n_requests <= 0:
        return True
    lines, over, seconds = _job_lines(n_requests, model, delay)
    head = f"העבודה הזו כוללת כ-{n_requests} בקשות לספק. בקצב הנוכחי היא תיקח {_duration(seconds)}."
    total, any_remote = n_requests, not info().get("local")
    if extra:
        head = f"{info()['label']} ({model}): כ-{n_requests} בקשות."
    out = [head] + lines
    for ex in extra or []:
        with using(ex["provider"], ex.get("base")):
            l2, o2, s2 = _job_lines(ex["n"], ex["model"], ex.get("delay"))
            label = info()["label"]
            remote = not info().get("local")
        out.append("")
        out.append(f"{ex['what']}: {label} ({ex['model']}), כ-{ex['n']} בקשות.")
        if ex.get("rough"):
            out.append("(הערכה גסה, תלוי בכמות המחלוקות.)")
        out += l2
        over = over or o2
        seconds += s2
        total += ex["n"]
        any_remote = any_remote or remote
    if extra:
        out.append("")
        out.append(f"בסך הכול כ-{total} בקשות, והזמן המשוער {_duration(seconds)}.")
        if any_remote:
            out.append("התמונות יישלחו לכל הספקים שמופיעים כאן, כל אחד לפי תפקידו. בדוק שזה מקובל עליך.")
        over = over or any_remote
    text = "\n".join(out)
    print(text)
    if confirm_hook and (over or total >= 30):
        if not confirm_hook(text):
            print("הפעולה בוטלה לפני שהתחילה. שום דבר לא נשלח.")
            return False
    return True


def env_key(provider=None):
    for name in info(provider)["env"] + ["AI_API_KEY"]:
        if os.environ.get(name):
            return os.environ[name]
    return ""


def key_for_request(key):
    """Local servers need no key, but some clients insist on a non-empty value."""
    if key:
        return key
    if not info()["key_required"]:
        return "none"
    return ""


# Some providers (Groq, for one) sit behind Cloudflare, which blocks Python's default
# "Python-urllib" identity with HTTP 403 / "error code: 1010". A plain custom name avoids that.
USER_AGENT = "focalpick/1.0"


def _headers(kind, key):
    h = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": USER_AGENT}
    if kind == "gemini":
        h["x-goog-api-key"] = key
    elif kind == "anthropic":
        h["x-api-key"] = key
        h["anthropic-version"] = "2023-06-01"
    else:
        h["Authorization"] = f"Bearer {key}"
    return h


def _build(kind, model, parts):
    if kind == "gemini":
        return "/models/%s:generateContent" % model, {
            "contents": [{"parts": parts}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}}
    content = []
    for p in parts:
        if "text" in p:
            content.append({"type": "text", "text": p["text"]})
        else:
            d = p["inline_data"]
            if kind == "anthropic":
                content.append({"type": "image", "source": {
                    "type": "base64", "media_type": d["mime_type"], "data": d["data"]}})
            else:
                content.append({"type": "image_url", "image_url": {
                    "url": f"data:{d['mime_type']};base64,{d['data']}"}})
    if kind == "anthropic":
        return "/messages", {"model": model, "max_tokens": 4096,
                             "messages": [{"role": "user", "content": content}]}
    return "/chat/completions", {"model": model,
                                 "messages": [{"role": "user", "content": content}]}


def _extract(kind, data):
    if kind == "gemini":
        cands = data.get("candidates") or []
        if not cands:
            raise ValueError(f"no answer (blocked?): {data.get('promptFeedback')}")
        parts = cands[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if kind == "anthropic":
        blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        if not blocks:
            raise ValueError(f"no answer: stop_reason={data.get('stop_reason')}")
        return "".join(blocks)
    choices = data.get("choices") or []
    if not choices:
        raise ValueError(f"no answer: {str(data)[:200]}")
    content = choices[0].get("message", {}).get("content")
    if isinstance(content, list):
        content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
    if not content:
        raise ValueError(f"empty answer: finish_reason={choices[0].get('finish_reason')}")
    return content


def call(model, key, parts, retries=5):
    """Send one request to the configured provider; return the reply text."""
    pi = info()
    kind = pi["kind"]
    path, body = _build(kind, model, parts)
    req = urllib.request.Request(base_url() + path, data=json.dumps(body).encode("utf-8"),
                                 headers=_headers(kind, key_for_request(key)))
    timeout = 900 if pi.get("local") else 240
    data = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.load(r)
            break
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:400]
            if e.code == 429 and _is_daily_limit(msg):
                record_daily_limit(model)
                raise ApiError(e.code, msg)          # waiting a minute will not help
            if e.code in (429, 500, 502, 503, 504, 529) and attempt < retries - 1:
                wait = 65 if e.code == 429 else 20
                print(f"    השרת החזיר {e.code}. מחכה {wait} שניות ומנסה שוב ({attempt + 1}/{retries - 1})...")
                reason = " ".join(msg.split())[:200]
                if reason:
                    print(f"    הסיבה לפי השרת: {reason}")
                time.sleep(wait)
                continue
            lim = _images_limit(e.code, msg)
            if lim is not None:
                raise TooManyImages(e.code, msg, lim)
            raise ApiError(e.code, msg)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt < retries - 1:
                print(f"    בעיית רשת ({e}), מנסה שוב בעוד 20 שניות...")
                time.sleep(20)
                continue
            raise ApiError(0, str(e))
    record_request(model)
    return _extract(kind, data)


LAST_DETAILS = {}      # model name -> short facts the provider gave about it, from the last list_models() call


def _per_million(v):
    try:
        return f"{float(v) * 1_000_000:g}"
    except (TypeError, ValueError):
        return None


def _model_facts(kind, m):
    """The facts a provider's model list gives about one model, as one short line (best effort)."""
    bits = []
    if kind == "gemini":
        if m.get("displayName"):
            bits.append(m["displayName"])
        if m.get("inputTokenLimit"):
            bits.append(f"input limit {m['inputTokenLimit']} tokens")
        if m.get("outputTokenLimit"):
            bits.append(f"output limit {m['outputTokenLimit']} tokens")
        return ", ".join(bits)
    if kind == "anthropic":
        return m.get("display_name", "")
    ctx = m.get("context_window") or m.get("context_length") or (m.get("top_provider") or {}).get("context_length")
    if ctx:
        bits.append(f"context {ctx}")
    pr = m.get("pricing")
    if isinstance(pr, dict):
        a, b = _per_million(pr.get("prompt")), _per_million(pr.get("completion"))
        if a is not None and b is not None:
            bits.append(f"price per million tokens: in {a}, out {b}")
    modal = (m.get("architecture") or {}).get("input_modalities")
    if modal:
        bits.append("inputs: " + "/".join(modal))
    if m.get("owned_by"):
        bits.append(f"by {m['owned_by']}")
    if m.get("active") is False:
        bits.append("inactive")
    return ", ".join(bits)


def list_models(key, free_only=False):
    """Names of the models this key can use (best effort; formats differ per provider).
    What the provider says about each model is kept in LAST_DETAILS."""
    LAST_DETAILS.clear()
    pi = info()
    kind = pi["kind"]
    if kind == "gemini":
        url = base_url() + "/models?pageSize=200"
    elif kind == "anthropic":
        url = base_url() + "/models?limit=100"
    else:
        url = base_url() + "/models"
    req = urllib.request.Request(url, headers=_headers(kind, key_for_request(key)))
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        raise ApiError(e.code, e.read().decode("utf-8", "replace")[:300])
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise ApiError(0, str(e))
    names = []
    if kind == "gemini":
        for m in data.get("models", []):
            n = m.get("name", "").replace("models/", "")
            if "generateContent" in m.get("supportedGenerationMethods", []) and n.startswith("gemini"):
                names.append(n)
                LAST_DETAILS[n] = _model_facts(kind, m)
    elif kind == "anthropic":
        names = [m["id"] for m in data.get("data", []) if "id" in m]
        for m in data.get("data", []):
            if "id" in m:
                LAST_DETAILS[m["id"]] = _model_facts(kind, m)
    else:
        items = data.get("data") if isinstance(data, dict) else data
        for m in items or []:
            mid = m.get("id") or m.get("name")
            if not mid:
                continue
            modal = (m.get("architecture") or {}).get("input_modalities")   # OpenRouter tells us
            if modal is not None and "image" not in modal:
                continue
            if free_only and isinstance(m.get("pricing"), dict):
                pr = m["pricing"]
                zero = all(str(pr.get(k, "0")).strip() in ("0", "0.0", "0.00", "0.000000") for k in ("prompt", "completion"))
                if not (zero or str(mid).endswith(":free")):
                    continue
            names.append(mid)
            LAST_DETAILS[mid] = _model_facts(kind, m)
    return sorted(set(names))


def explain_error(e):
    """Hebrew explanation for an ApiError, with the right provider name."""
    name = info()["label"]
    lines = [f"\nנעצר: {e}"]
    if e.code == 429 and _is_daily_limit(str(e)):
        lines.append("נגמרה המכסה היומית של המודל הזה. מה שנעשה עד כאן נשמר. אפשר להמשיך מחר באותה פקודה, "
                     "או לעבור למודל או לספק אחר (המכסות נפרדות בין מודלים).")
    elif e.code == 429:
        lines.append("כנראה נגמרה המכסה (לדקה או ליום), או שהגעת למגבלת הקצב. "
                     "מה שנעשה עד כאן נשמר. אפשר להריץ שוב מאוחר יותר, והעבודה תמשיך מאותה נקודה.")
    elif isinstance(e, TooManyImages):
        lines.append(f"המודל מקבל רק עד {e.limit} תמונות בבקשה, והשיטה הזו צריכה יותר. כדאי לבחור מודל אחר.")
    elif e.code in (400, 404, 422):
        lines.append("ייתכן ששם המודל התיישן, שהמודל לא מבין תמונות, או שהכתובת לא נכונה. "
                     "אפשר ללחוץ 'הצג מודלים זמינים' (או להריץ את הפקודה models) ולבחור מודל אחר.")
    elif e.code == 403 and "1010" in str(e):
        lines.append(f"השרת של {name} חסם את הבקשה לפי הזהות של התוכנה (שגיאה 1010 של Cloudflare). "
                     "זה לא קשור למפתח שלך. אם זה קורה גם בגרסה העדכנית של הכלי, כדאי לדווח על כך למפתח.")
    elif e.code in (401, 403):
        lines.append(f"{name} דחה את המפתח. כדאי לבדוק שהוא הועתק נכון, ושהוא מתאים לספק שבחרת.")
    elif e.code == 402:
        lines.append("נראה שחסר יתרה בחשבון אצל הספק.")
    elif e.code == 0:
        lines.append("לא הצלחתי להתחבר. בדוק חיבור לאינטרנט, או (בשרת מקומי) שהשרת באמת רץ ושהכתובת נכונה.")
    return "\n".join(lines)
