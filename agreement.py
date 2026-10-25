"""
agreement.py - how much do the AI ratings agree with YOUR choices?

Takes the results folder of a photo session run (rate_raw.py: it holds ratings.csv) and the Lightroom catalog
where you already rated the same photos by hand, and compares them. Nothing is sent anywhere and nothing is
changed: the catalog is only read (from a temporary copy).

What counts as "chosen by you": a Pick flag, or at least --min-stars stars (default 3). Photos without
stars count as not chosen, so run it on a session where you finished your own selection.

IMPORTANT: if you let the tool write stars to Lightroom (--write-xmp) and Lightroom imported them, those
stars are the AI's own, and the comparison means nothing. Use photos you rated before running the tool.

Run:
    python agreement.py "D:\\rating\\session" --catalog "D:\\LR\\catalog.lrcat"

Writes agreement/report.html and agreement/agreement.csv inside the results folder.

Copyright (c) 2026 נתאי שנדורפי (Nitay Sandorffy). MIT License.
"""
import argparse
import csv
import html
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import i18n
from i18n import tr

__copyright__ = "© 2026 נתאי שנדורפי. MIT License."


def norm(path):
    """One spelling for a path, so the CSV and the catalog can be matched (slashes, upper/lower case)."""
    return str(path).replace("\\", "/").casefold()


# ---------------------------------------------------------------- reading the inputs
def read_ratings(folder):
    """The rows of ratings.csv, plus the photos the pre-filter skipped (rejected.csv) and the preview paths."""
    f = folder / "ratings.csv"
    if not f.is_file():
        raise FileNotFoundError("בתיקייה הזו אין קובץ ratings.csv. צריך לבחור את תיקיית התוצאות של סשן צילום שדורג.")
    with open(f, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    skipped = []
    rj = folder / "rejected.csv"
    if rj.is_file():
        with open(rj, newline="", encoding="utf-8-sig") as fh:
            skipped = list(csv.DictReader(fh))
    try:
        index = json.loads((folder / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        index = {}
    return rows, skipped, index


def catalog_choices(lrcat):
    """{normalized path: (stars, pick)} for every photo in the catalog. Works on a temporary copy."""
    tmp = Path(tempfile.mkdtemp()) / "cat.lrcat"
    try:
        shutil.copy2(lrcat, tmp)
        con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        try:
            rows = con.execute("""
                SELECT rf.absolutePath, fo.pathFromRoot, f.baseName, f.extension, i.rating, i.pick
                FROM Adobe_images i
                JOIN AgLibraryFile f ON i.rootFile = f.id_local
                JOIN AgLibraryFolder fo ON f.folder = fo.id_local
                JOIN AgLibraryRootFolder rf ON fo.rootFolder = rf.id_local""").fetchall()
        finally:
            con.close()
    except sqlite3.DatabaseError as e:
        raise ValueError(f"לא הצלחתי לקרוא את הקטלוג ({e}). ייתכן שזה לא קטלוג של Lightroom Classic.")
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)
    return {norm(f"{root}{rel}{base}.{ext}"): (int(rating or 0), int(pick or 0))
            for root, rel, base, ext, rating, pick in rows}


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- the statistics (plain Python, no extra packages)
def ranks(values):
    """Ranks starting at 1; equal values share the average rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def auc(pos, neg):
    """Chance that a photo you chose got a higher AI score than one you did not. 0.5 = a coin toss, 1 = perfect."""
    if not pos or not neg:
        return None
    r = ranks(list(pos) + list(neg))
    return (sum(r[:len(pos)]) - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def spearman(a, b):
    if len(a) < 3 or len(set(a)) < 2 or len(set(b)) < 2:
        return None
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den if den else None


def compare(rows, skipped, choices, min_stars):
    """Match the AI results to your choices and compute the agreement numbers."""
    items, unmatched, unrated_by_ai = [], 0, 0
    for r in rows:
        key = norm(r.get("path", ""))
        if key not in choices:
            unmatched += 1
            continue
        score = to_float(r.get("overall"))
        if score is None:
            unrated_by_ai += 1
            continue
        stars, pick = choices[key]
        items.append({"file": r["file"], "path": r["path"], "score": score, "stars": stars, "pick": pick,
                      "kept": pick == 1 or stars >= min_stars, "group": r.get("group", ""),
                      "kind": r.get("group_type", ""), "rank": to_float(r.get("rank_in_group")),
                      "hl": to_float(r.get("highlight_rank")), "gem": bool(r.get("gem")), "skipped": False})
    for r in skipped:                      # the pre-filter kept these away from the AI: for the AI they count as the lowest score
        key = norm(r.get("path", ""))
        if key in choices:
            stars, pick = choices[key]
            items.append({"file": r["name"], "path": r["path"], "score": 0.0, "stars": stars, "pick": pick,
                          "kept": pick == 1 or stars >= min_stars, "group": "", "kind": "", "rank": None,
                          "hl": None, "gem": False, "skipped": True, "reason": r.get("reason", "")})
    kept = [i for i in items if i["kept"]]
    rest = [i for i in items if not i["kept"]]
    res = {"items": items, "n": len(items), "n_kept": len(kept), "unmatched": unmatched, "unrated_by_ai": unrated_by_ai,
           "auc": auc([i["score"] for i in kept], [i["score"] for i in rest])}
    # the AI's top photos, as many as you chose
    ranked = sorted(items, key=lambda i: -i["score"])
    k = len(kept)
    res["topk_hits"] = sum(1 for i in ranked[:k] if i["kept"]) if k else 0
    res["topk_base"] = k / len(items) if items else 0
    # inside groups of similar shots: is the AI's favourite one of the photos you chose?
    groups = {}
    for i in items:
        if i["kind"] == "similar":
            groups.setdefault(i["group"], []).append(i)
    g_total = g_hit = 0
    base = 0.0
    for members in groups.values():
        chosen = [m for m in members if m["kept"]]
        best = [m for m in members if m["rank"] == 1]
        if len(members) >= 2 and chosen and best:
            g_total += 1
            g_hit += 1 if best[0]["kept"] else 0
            base += len(chosen) / len(members)
    res.update(groups=g_total, groups_hit=g_hit, groups_base=base / g_total if g_total else 0)
    # the session highlights the AI picked
    hl = [i for i in items if i["hl"]]
    res["hl_total"] = len(hl)
    res["hl_kept"] = sum(1 for i in hl if i["kept"])
    # how well the stars themselves are ordered (only photos you gave stars to)
    rated = [i for i in items if i["stars"] > 0 and not i["skipped"]]
    res["spearman"] = spearman([i["stars"] for i in rated], [i["score"] for i in rated])
    res["n_rated"] = len(rated)
    res["missed"] = sorted([i for i in kept], key=lambda i: i["score"])[:12]
    res["false_alarms"] = sorted(rest, key=lambda i: -i["score"])[:12]
    res["skipped_kept"] = [i for i in kept if i["skipped"]]
    return res


# ---------------------------------------------------------------- words
def verdict(res):
    a = res["auc"]
    if a is None:
        return "אין מספיק נתונים להערכה: צריך גם תמונות שבחרת וגם תמונות שלא."
    if res["n_kept"] < 15:
        return "יש מעט מדי תמונות שבחרת, ולכן התוצאה לא יציבה. כדאי לנסות על סשן גדול יותר."
    if a >= 0.80:
        return "התאמה טובה: הדירוג של ה-AI מבדיל היטב בין מה שבחרת למה שלא."
    if a >= 0.65:
        return "התאמה בינונית: הדירוג נותן כיוון, אבל כדאי לעבור גם על מה שדורג נמוך. אפשר לשפר עם קובץ הטעם האישי."
    return "התאמה חלשה: הדירוג כמעט לא מתאים לבחירות שלך. כדאי לנסות מודל אחר, לתאר את הטעם שלך בקובץ הטעם, או לא להסתמך עליו."


def summary_lines(res, min_stars):
    pct = lambda a, b: round(100 * a / b) if b else 0
    L = [tr("נבדקו {0} תמונות שמופיעות גם בתוצאות וגם בקטלוג. מהן {1} שבחרת (דגל Pick או לפחות {2} כוכבים).")
         .format(res["n"], res["n_kept"], min_stars)]
    if res["unmatched"]:
        L.append(tr("{0} תמונות מהתוצאות לא נמצאו בקטלוג ולכן לא נספרו.").format(res["unmatched"]))
    if res["unrated_by_ai"]:
        L.append(tr("{0} תמונות עוד לא דורגו על ידי ה-AI ולכן לא נספרו.").format(res["unrated_by_ai"]))
    if res["auc"] is not None:
        L.append(tr("יכולת ההפרדה (AUC): {0}. 0.50 = כמו הטלת מטבע, 1.00 = מושלם.").format(f"{res['auc']:.2f}"))
    if res["n_kept"]:
        L.append(tr("מתוך {0} התמונות שה-AI דירג הכי גבוה, {1} ({2}%) הן תמונות שבחרת. בבחירה אקראית היית מצפה לכ-{3}%.")
                 .format(res["n_kept"], res["topk_hits"], pct(res["topk_hits"], res["n_kept"]),
                         round(100 * res["topk_base"])))
    if res["groups"]:
        L.append(tr("בקבוצות של צילומים דומים: ה-AI בחר כטובה ביותר תמונה שבחרת גם אתה ב-{0} מתוך {1} קבוצות ({2}%). בבחירה אקראית: כ-{3}%.")
                 .format(res["groups_hit"], res["groups"], pct(res["groups_hit"], res["groups"]),
                         round(100 * res["groups_base"])))
    if res["hl_total"]:
        L.append(tr("מתוך {0} הבולטות שה-AI בחר, בחרת גם אתה {1}.").format(res["hl_total"], res["hl_kept"]))
    if res["skipped_kept"]:
        L.append(tr("{0} תמונות שבחרת נפסלו בסינון המקדים. אם זה קורה הרבה, כדאי להריץ עם סף טשטוש נמוך יותר.")
                 .format(len(res["skipped_kept"])))
    if res["spearman"] is not None:
        L.append(tr("בין התמונות שנתת להן כוכבים ({0}), מתאם הדירוג (Spearman) הוא {1}.")
                 .format(res["n_rated"], f"{res['spearman']:.2f}"))
    L.append(tr(verdict(res)))
    return L


# ---------------------------------------------------------------- output
def write_reports(out, res, index, results_dir, min_stars):
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "agreement.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["file", "your_stars", "your_pick", "chosen_by_you", "ai_score", "group", "rank_in_group",
                    "highlight_rank", "skipped_by_prefilter", "path"])
        for i in sorted(res["items"], key=lambda i: -i["score"]):
            w.writerow([i["file"], i["stars"], i["pick"], "yes" if i["kept"] else "", i["score"], i["group"],
                        "" if i["rank"] is None else int(i["rank"]), "" if i["hl"] is None else int(i["hl"]),
                        "yes" if i["skipped"] else "", i["path"]])
    e = html.escape
    rtl = i18n.rtl()

    def card(i):
        prev = (index.get(i["path"]) or {}).get("preview")
        img = f'<img loading="lazy" src="../{e(prev)}">' if prev else ""
        mark = ("★" * i["stars"]) + (" Pick" if i["pick"] == 1 else "")
        return (f'<div class="c">{img}<div class="n">{e(i["file"])}</div>'
                f'<div>{e(tr("ה-AI"))}: <b>{i["score"]:.0f}</b> · {e(tr("אתה"))}: {e(mark or "–")}</div></div>')

    parts = [f"""<!doctype html><html lang="{i18n.LANG}" dir="{"rtl" if rtl else "ltr"}"><meta charset="utf-8">
<title>{e(tr("התאמה לטעם שלך"))}</title><style>
body{{background:#161616;color:#eee;font-family:Segoe UI,Arial,sans-serif;margin:0;padding:24px}}
h1{{font-size:22px}} h2{{margin-top:32px;border-bottom:1px solid #444;padding-bottom:6px}} li{{margin:6px 0}}
.row{{display:flex;flex-wrap:wrap;gap:12px}} .c{{width:220px;background:#2a2a2a;border-radius:6px;padding:6px;font-size:13px}}
.c img{{width:100%;height:160px;object-fit:contain;background:#111;display:block;border-radius:4px}}
.n{{font-family:Consolas,monospace;font-size:12px;color:#aaa;direction:ltr;text-align:left;margin:4px 0}}
.foot{{margin-top:40px;color:#777;font-size:12px;text-align:center}}
</style><body><h1>{e(tr("התאמה לטעם שלך"))}</h1>
<p>{e(tr("האם הדירוג של ה-AI מתאים לבחירות שלך? ההשוואה היא בין התוצאות של הכלי לבין הכוכבים והדגלים שנתת בליטרום."))}</p><ul>"""]
    parts += [f"<li>{e(line)}</li>" for line in summary_lines(res, min_stars)]
    parts.append("</ul>")
    parts.append(f"<p>{e(tr('אם כתבת כוכבים מהכלי לליטרום והם יובאו, הכוכבים האלה הם של ה-AI עצמו וההשוואה חסרת משמעות.'))}</p>")
    if res["missed"]:
        parts.append(f"<h2>{e(tr('תמונות שבחרת וה-AI דירג נמוך'))}</h2><div class='row'>"
                     + "".join(card(i) for i in res["missed"]) + "</div>")
    if res["false_alarms"]:
        parts.append(f"<h2>{e(tr('תמונות שה-AI דירג גבוה ולא בחרת'))}</h2><div class='row'>"
                     + "".join(card(i) for i in res["false_alarms"]) + "</div>")
    parts.append(f'<p class="foot">{e(tr("נוצר בכלי מיון ודירוג תמונות"))} · {e(tr("כל הזכויות שמורות לנתאי שנדורפי"))} ©</p></body>')
    (out / "report.html").write_text("\n".join(parts), encoding="utf-8")


def main():
    i18n.setup_cli()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__copyright__)
    ap.add_argument("results", type=Path, help="results folder of a photo session run (holds ratings.csv)")
    ap.add_argument("--catalog", type=Path, required=True, help="Lightroom Classic catalog (.lrcat) with your own ratings")
    ap.add_argument("--min-stars", type=int, default=3, help="stars that count as chosen by you (default %(default)s)")
    ap.add_argument("--out", type=Path, default=None, help="report folder (default: agreement inside the results folder)")
    args = ap.parse_args()
    if not args.results.is_dir():
        sys.exit(f"התיקייה לא נמצאה: {args.results}")
    if not args.catalog.is_file():
        sys.exit(f"הקטלוג לא נמצא: {args.catalog}")
    try:
        rows, skipped, index = read_ratings(args.results)
        choices = catalog_choices(args.catalog)
    except (FileNotFoundError, ValueError) as e:
        sys.exit(str(e))
    res = compare(rows, skipped, choices, args.min_stars)
    if not res["n"]:
        sys.exit("לא נמצאה אף תמונה שמופיעה גם בתוצאות וגם בקטלוג. בדוק שזה הקטלוג שבו דירגת את אותן תמונות.")
    out = (args.out or args.results / "agreement").resolve()
    write_reports(out, res, index, args.results, args.min_stars)
    print()
    for line in summary_lines(res, args.min_stars):
        print(line)
    print(f"\nהדוח (לפתוח בדפדפן): {out / 'report.html'}")
    print(f"גיליון לאקסל:     {out / 'agreement.csv'}")


if __name__ == "__main__":
    main()
