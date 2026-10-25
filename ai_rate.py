#!/usr/bin/env python3
# © 2026 נתאי שנדורפי (Nitay Sandorffy). MIT License.
"""
Stage 2 of the portfolio workflow: AI rating with the Gemini API (free tier).

Works on the output folder of photo_triage.py (the one with report.csv and sheets\\).
No extra packages needed beyond Pillow (already installed).

Setup (once, in the same Command Prompt window you run the script from):
    set GEMINI_API_KEY=your_key_here
  (key: https://aistudio.google.com -> "Get API key". No credit card.)

Commands:
    python ai_rate.py models  "C:\\triage"            list models your key can use
    python ai_rate.py rate    "C:\\triage" --limit 2   PASS 1: rate contact sheets (test on 2 first)
    python ai_rate.py rate    "C:\\triage"             PASS 1: all sheets (resumable)
    python ai_rate.py refine  "C:\\triage"             PASS 2: re-rate the best at higher resolution,
                                                       copy the finalists' ORIGINAL files to finalists\\

Everything is saved as it goes. If you hit the daily quota or the connection drops,
just run the same command again later and it continues where it stopped.

PRIVACY: on the free tier Google may use what you send to improve its products.
The AI sees small copies of your photos (including photos of people).
"""
__author__ = "נתאי שנדורפי"
__copyright__ = "© 2026 נתאי שנדורפי. MIT License."
import argparse
import base64
import csv
import io
import i18n
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from PIL import Image, ImageOps

import llm_providers as llm

Image.MAX_IMAGE_PIXELS = None

# ---------------------------------------------------------------- settings
# Model IDs change often. Run "models" to see what is available to your key.

PER_SHEET = 12            # must match photo_triage.py (4 x 3)
SECONDS_BETWEEN_CALLS = 7  # free tier is ~10 requests/minute
PASS2_BATCH = 4           # photos per request in pass 2
PASS2_SIZE = 1600         # long edge sent in pass 2

PASS1_PROMPT = """You are a demanding photo editor selecting images for the portfolio website of a photographer who shoots cars, portraits of people, and occasionally landscapes and animals.

The attached image is a contact sheet. Each photo has a yellow number in its top-left corner. Return one entry for EVERY numbered photo.

Judge each one AS A PHOTOGRAPH, not by its subject. A cool car or a friend's face does not make a good photo. Consider:
- light (quality, direction, mood) and color
- composition (framing, balance, background, distractions)
- camera angle and viewpoint: height, angle to the subject, distance and the perspective that results. A distinctive angle that shows the subject at its best (for example a low three-quarter angle for a car, eye level or slightly below for a portrait) is a major plus; a flat, default or unflattering angle is a real minus, and it counts as much as composition
- the moment / expression (for people) or the presence and attitude (for cars)
- whether it would stop a stranger scrolling through a portfolio
Intentional silhouettes, low-key exposure, motion and shallow depth of field are artistic choices, not flaws.
The photos are small, so judge overall impact, not fine detail.

Scoring, 1-10. BE HARSH. Most snapshots are 2-5. A documentary shot of a car or of friends is 4 or lower unless it is also a striking image.
6 = decent, 7 = strong, 8 = portfolio-worthy, 9-10 = exceptional (give very rarely).

Return ONLY a JSON array, no other text:
[{"id": <number shown>, "category": "car" | "person" | "landscape" | "animal" | "other", "score": <1-10>, "note": "<max 12 words in LANGNAME: the main reason>"}]"""

PASS2_PROMPT = """You are a demanding photo editor making the FINAL selection for a photographer's portfolio website (cars, portraits, some landscape and animals).
These photos already passed a first screening. Now be stricter: only the very best belong in a portfolio.

Below are {n} photos, each introduced by a line "Photo id N:". Judge each AS A PHOTOGRAPH (light, color, composition, camera angle and viewpoint, moment/expression, impact, technical quality such as sharpness where it matters). Intentional silhouettes, low-key exposure and shallow depth of field are choices, not flaws.

Score 1-10 using the full range. 8 = would genuinely strengthen a professional portfolio, 9-10 = exceptional. At most about one in five should reach 8. People photos must be truly outstanding as images, not just nice memories. Car photos must be striking images, not just good-looking cars.

Return ONLY a JSON array, no other text:
[{{"id": <number>, "category": "car" | "person" | "landscape" | "animal" | "other", "score": <1-10>, "verdict": "<one sentence in LANGNAME: why it works or what holds it back>"}}]"""


ApiError = llm.ApiError


# ---------------------------------------------------------------- API
def call_gemini(model, key, parts, retries=5):
    """Name kept for compatibility: sends the request to whichever provider is configured."""
    return llm.call(model, key, parts, retries)


def extract_json_list(text):
    """Find the JSON array in a model reply. Tolerates code fences, <think> blocks and stray brackets."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    text = re.sub(r"```(?:json)?", "", text).strip()
    dec = json.JSONDecoder()
    pos = text.find("[")
    while pos != -1:
        try:
            obj, _ = dec.raw_decode(text[pos:])
            if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
                return obj
        except ValueError:
            pass
        pos = text.find("[", pos + 1)
    raise ValueError("no JSON array in reply")



def parse_json_list(text):
    clean = []
    for it in extract_json_list(text):
        try:
            clean.append({
                "id": int(it["id"]),
                "category": str(it.get("category", "other")).lower(),
                "score": float(it["score"]),
                "note": str(it.get("note") or it.get("verdict") or "")[:300],
            })
        except (KeyError, TypeError, ValueError):
            continue
    return clean


def jpeg_part(img_or_path, max_side=None):
    if isinstance(img_or_path, (str, Path)):
        im = Image.open(img_or_path)
        if max_side:
            im.draft("RGB", (max_side, max_side))
        im = ImageOps.exif_transpose(im).convert("RGB")
    else:
        im = img_or_path
    if max_side:
        im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return {"inline_data": {"mime_type": "image/jpeg",
                            "data": base64.b64encode(buf.getvalue()).decode()}}


# ---------------------------------------------------------------- data helpers
def atomic_write(path, text):
    """Write a file so that stopping the program mid-write can never leave a half-written file."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_json(path, default=None):
    """Read a JSON file; return `default` if it is missing or damaged."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def load_report(folder):
    with open(folder / "report.csv", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def get_key(args):
    key = args.key or llm.env_key()
    if not key and llm.info()["key_required"]:
        env = (llm.info()["env"] or ["AI_API_KEY"])[0]
        sys.exit(f"חסר מפתח API עבור {llm.info()['label']}. בחלון הזה כתוב:  set {env}=המפתח_שלך")
    return key


def explain_api_error(e):
    print(llm.explain_error(e))


def guard_stale(folder):
    """If the triage report changed (photo numbers differ), move old AI results aside."""
    import hashlib
    import shutil
    rows = load_report(folder)
    h = hashlib.sha1("|".join(f"{r['id']}:{r['path']}" for r in rows).encode()).hexdigest()
    marker = folder / "ai_report_hash.txt"
    old = marker.read_text().strip() if marker.exists() else None
    if old is not None and old != h:
        stale = [p for p in (folder / "ai_raw", folder / "ai_pass2.jsonl",
                             folder / "ai_scores.csv", folder / "finalists.csv") if p.exists()]
        if stale:
            arch = folder / f"old_results_{time.strftime('%Y%m%d_%H%M%S')}"
            arch.mkdir()
            for p in stale:
                shutil.move(str(p), str(arch / p.name))
            print("שים לב: תוצאות הניפוי השתנו מאז הדירוג הקודם (מספרי התמונות לא תואמים), "
                  f"אז העברתי את הדירוגים הישנים אל {arch.name} והתחלתי דירוג חדש.")
    marker.write_text(h)


# ---------------------------------------------------------------- pass 1
def merge_pass1(folder):
    report = {int(r["id"]): r for r in load_report(folder)}
    rows = []
    for raw in sorted((folder / "ai_raw").glob("sheet_*.json")):
        for it in (read_json(raw, []) or []):
            r = report.get(it["id"])
            if not r:
                continue
            rows.append({"id": it["id"], "score": it["score"], "category": it["category"],
                         "note": it["note"], "sheet": raw.stem, "camera": r["camera"],
                         "path": r["path"], "thumb_path": r["thumb_path"]})
    rows.sort(key=lambda x: -x["score"])
    write_csv(folder / "ai_scores.csv", rows,
              ["id", "score", "category", "note", "sheet", "camera", "path", "thumb_path"])
    return rows


def cmd_rate(args):
    key = get_key(args)
    folder = args.folder.resolve()
    guard_stale(folder)
    ok = [r for r in load_report(folder) if r["status"] == "ok"]
    sheets = sorted((folder / "sheets").glob("sheet_*.jpg"))
    raw_dir = folder / "ai_raw"
    raw_dir.mkdir(exist_ok=True)
    todo = [(k, s) for k, s in enumerate(sheets) if not (raw_dir / f"{s.stem}.json").exists()]
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(sheets)} דפים בסך הכול, {len(todo)} לדירוג עכשיו. מודל: {args.model}")
    if not llm.confirm_work(len(todo), args.model, SECONDS_BETWEEN_CALLS):
        return

    try:
        for n, (k, sheet) in enumerate(todo, 1):
            ids = [int(r["id"]) for r in ok[k * PER_SHEET:(k + 1) * PER_SHEET]]
            print(f"[{n}/{len(todo)}] {sheet.name} (תמונות {ids[0]}-{ids[-1]})")
            try:
                text = call_gemini(args.model, key,
                                   [{"text": PASS1_PROMPT.replace("LANGNAME", i18n.language_name())}, jpeg_part(sheet)])
                items = [i for i in parse_json_list(text) if i["id"] in ids]
            except ValueError as e:
                print(f"    לא הצלחתי לדרג את הדף ({e}). אנסה שוב בהרצה הבאה")
                continue
            missing = set(ids) - {i["id"] for i in items}
            if missing:
                print(f"    שים לב: לא התקבל דירוג עבור {sorted(missing)}")
            atomic_write(raw_dir / f"{sheet.stem}.json", json.dumps(items, ensure_ascii=False))
            time.sleep(SECONDS_BETWEEN_CALLS)
    except ApiError as e:
        explain_api_error(e)
    finally:
        rows = merge_pass1(folder)
        print(f"\nדורגו עד כה: {len(rows)} תמונות -> {folder / 'ai_scores.csv'}")
        if rows:
            dist = {}
            for r in rows:
                dist[int(r["score"])] = dist.get(int(r["score"]), 0) + 1
            print("התפלגות ציונים:", dict(sorted(dist.items(), reverse=True)))


# ---------------------------------------------------------------- pass 2
def cmd_refine(args):
    key = get_key(args)
    folder = args.folder.resolve()
    guard_stale(folder)
    scores_file = folder / "ai_scores.csv"
    if not scores_file.exists():
        sys.exit("צריך להריץ קודם את שלב ה-rate.")
    with open(scores_file, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    def passes(r, base):
        need = base + (1 if r["category"] == "person" else 0)  # people: one point stricter
        return float(r["score"]) >= need

    cands = [r for r in rows if passes(r, args.min_score)]
    cands.sort(key=lambda r: -float(r["score"]))
    cands = cands[:args.max_candidates]

    cache_file = folder / "ai_pass2.jsonl"
    done = {}
    if cache_file.exists():
        good = []
        for line in cache_file.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
                done[d["id"]] = d
                good.append(line)
            except (ValueError, KeyError, TypeError):
                continue                  # a half-written line from an interrupted run
        atomic_write(cache_file, "\n".join(good) + ("\n" if good else ""))
    todo = [r for r in cands if int(r["id"]) not in done]
    print(f"{len(cands)} תמונות מועמדות (ציון >= {args.min_score}, אנשים >= {args.min_score + 1}); "
          f"{len(todo)} עוד לבדיקה. מודל: {args.model}")
    if not llm.confirm_work(-(-len(todo) // PASS2_BATCH), args.model, SECONDS_BETWEEN_CALLS):
        return

    bs = PASS2_BATCH
    try:
        i = 0
        while i < len(todo):
            batch = todo[i:i + bs]
            ids = [int(r["id"]) for r in batch]
            print(f"[{i // bs + 1}/{(len(todo) + bs - 1) // bs}] תמונות {ids}")
            parts = [{"text": PASS2_PROMPT.format(n=len(batch)).replace("LANGNAME", i18n.language_name())}]
            for r in batch:
                src = Path(r["path"])
                if not src.exists():
                    src = Path(r["thumb_path"])
                parts.append({"text": f"Photo id {r['id']}:"})
                parts.append(jpeg_part(src, PASS2_SIZE))
            try:
                items = [it for it in parse_json_list(call_gemini(args.model, key, parts))
                         if it["id"] in ids]
            except llm.TooManyImages as e:
                if 1 <= e.limit < len(batch):
                    print(f"    המודל מקבל רק עד {e.limit} תמונות בבקשה. מקטין את הקבוצות ל-{e.limit} וממשיך.")
                    bs = e.limit
                    continue
                raise
            except ValueError as e:
                print(f"    לא הצלחתי לבדוק את הקבוצה ({e}). אנסה שוב בהרצה הבאה")
                i += bs
                continue
            with open(cache_file, "a", encoding="utf-8") as f:
                for it in items:
                    f.write(json.dumps(it, ensure_ascii=False) + "\n")
                    done[it["id"]] = it
            i += bs
            time.sleep(SECONDS_BETWEEN_CALLS)
    except ApiError as e:
        explain_api_error(e)

    # ---- results
    by_id = {int(r["id"]): r for r in rows}
    final = []
    for i, it in done.items():
        r = by_id.get(i)
        if not r:
            continue
        final.append({"id": i, "score2": it["score"], "score1": r["score"],
                      "category": it["category"], "verdict": it["note"],
                      "path": r["path"]})
    final.sort(key=lambda x: -x["score2"])
    write_csv(folder / "finalists.csv", final,
              ["id", "score2", "score1", "category", "verdict", "path"])

    out_dir = folder / "finalists"
    out_dir.mkdir(exist_ok=True)
    copied = 0
    for r in final:
        need = args.final_score + (1 if r["category"] == "person" else 0)
        if r["score2"] >= need and Path(r["path"]).exists():
            name = f"{int(r['score2']):02d}_{r['category']}_{r['id']}_{Path(r['path']).name}"
            dst = out_dir / name
            if not dst.exists():
                shutil.copy2(r["path"], dst)
                copied += 1
    n_final = sum(1 for r in final
                  if r["score2"] >= args.final_score + (1 if r["category"] == "person" else 0))
    print(f"\nנבדקו: {len(final)} תמונות -> {folder / 'finalists.csv'}")
    print(f"בגמר (ציון >= {args.final_score}, אנשים >= {args.final_score + 1}): {n_final}. "
          f"הועתקו {copied} קבצים מקוריים חדשים אל {out_dir}")


# ---------------------------------------------------------------- models
def cmd_models(args):
    key = get_key(args)
    try:
        names = llm.list_models(key)
    except ApiError as e:
        explain_api_error(e)
        return
    for n in names:
        print(n)
    if not names:
        print("לא נמצאו מודלים.")


# ---------------------------------------------------------------- main
def main():
    import i18n
    i18n.setup_cli()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__copyright__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("folder", type=Path, help="output folder of photo_triage.py")
        p.add_argument("--provider", default="gemini", choices=llm.ORDER, help="AI provider")
        p.add_argument("--base-url", default=None, help="custom server address (for 'custom', Ollama, LM Studio)")
        p.add_argument("--model", default=None)
        p.add_argument("--key", default=None, help="API key (or use the provider's environment variable)")
        p.add_argument("--delay", type=float, default=None, help="seconds between requests")

    p = sub.add_parser("models"); common(p); p.set_defaults(fn=cmd_models)
    p = sub.add_parser("rate"); common(p)
    p.add_argument("--limit", type=int, default=0, help="only do N sheets in this run")
    p.set_defaults(fn=cmd_rate)
    p = sub.add_parser("refine"); common(p)
    p.add_argument("--min-score", type=float, default=7,
                   help="pass-1 score needed to enter pass 2 (people need +1)")
    p.add_argument("--max-candidates", type=int, default=250)
    p.add_argument("--final-score", type=float, default=8,
                   help="pass-2 score needed to become a finalist (people need +1)")
    p.set_defaults(fn=cmd_refine)

    args = ap.parse_args()
    global SECONDS_BETWEEN_CALLS
    try:
        llm.configure(args.provider, args.base_url)
    except ValueError as e:
        sys.exit(str(e))
    if not args.model:
        args.model = llm.default_model()
    if not args.model and args.cmd != "models":
        sys.exit("צריך לציין מודל (--model). אפשר לראות רשימה בפקודה models.")
    SECONDS_BETWEEN_CALLS = args.delay if args.delay is not None else llm.default_delay()
    args.fn(args)


if __name__ == "__main__":
    main()
