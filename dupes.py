#!/usr/bin/env python3
"""
dupes.py - find duplicate photos in a folder. It only reports; it never moves or deletes anything.

Two kinds of duplicates:
  exact   the very same file, copied more than once (same size and same content)
  near    the same picture saved again: resized, re-compressed, or exported from another program

A burst of shots, or several photos from the same angle, is NOT a duplicate. For two files to count
as "near" they must look almost pixel-for-pixel the same AND have the same capture time (when both
files carry one). Two frames of a burst differ in time, so they are never matched, however similar.

Usage:
    python dupes.py "D:\\Photos" --recursive
    python dupes.py "D:\\Photos" --out "D:\\dupes_report" --no-near

Output (in --out, default: _duplicates inside the folder):
    duplicates.csv   one row per file in every group, with a suggestion of which one to keep
    report.html      the same, with thumbnails (open in a browser)

Suggestion of which to keep: the largest picture, then the largest file, then the first by name.
"""
__copyright__ = "© 2026 נתאי שנדורפי. MIT License."
import argparse
import base64
import csv
import hashlib
import html
import io
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import i18n
from i18n import tr
from PIL import Image, ImageOps

try:                                   # HEIC (iPhone) needs the optional pillow-heif package
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIC_EXT = {".heic", ".heif"}
except Exception:
    HEIC_EXT = set()
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"} | HEIC_EXT
RAW_EXT = {".cr3", ".cr2", ".crw", ".nef", ".arw", ".dng", ".raf", ".orf", ".rw2", ".pef", ".srw"}
OUT_DIR_NAME = "_duplicates"
MEAN_DIFF_MAX = 2.0            # average difference, out of 255, between two "same" pictures
P95_DIFF_MAX = 10.0            # and 95% of the pixels must differ by less than this
ASPECT_TOL = 0.01              # same shape, within 1%
BUCKET_MAX = 150               # a bucket with more files than this is not searched (e.g. all-black pictures)


# ---------------------------------------------------------------- reading files
def find_files(root, recursive):
    out = []
    it = root.rglob("*") if recursive else root.glob("*")
    for p in it:
        if OUT_DIR_NAME in p.parts or not p.is_file():
            continue
        if p.suffix.lower() in IMAGE_EXT or p.suffix.lower() in RAW_EXT:
            out.append(p)
    return sorted(out, key=lambda p: str(p).lower())


def file_hash(path, chunk=1 << 20):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def capture_stamp(im):
    """Capture time including fractions of a second, as text. Empty when the file has none."""
    try:
        ex = im.getexif()
        sub = ex.get_ifd(0x8769)
        t = sub.get(36867) or sub.get(36868) or ex.get(306)
        if not t:
            return ""
        return f"{str(t).strip()}.{str(sub.get(37521, '')).strip()}"
    except Exception:
        return ""


def describe(path):
    """Small fingerprint of a picture: shape, time, a 64-bit hash, and a 32x32 grey copy."""
    with Image.open(path) as im:
        stamp = capture_stamp(im)
        orig = im.size
        im.draft("RGB", (160, 160))                      # fast decode at reduced size for JPEG
        im = ImageOps.exif_transpose(im).convert("L")
        w, h = im.size
        a = np.asarray(im.resize((9, 8), Image.BILINEAR), dtype=np.float32)
        bits = (a[:, 1:] > a[:, :-1]).flatten()
        hv = 0
        for b in bits:
            hv = (hv << 1) | int(b)
        g = np.asarray(im.resize((32, 32), Image.BILINEAR), dtype=np.float32)
    return {"w": orig[0], "h": orig[1], "aspect": w / h if h else 0, "stamp": stamp, "hash": hv, "grey": g}


def picture_distance(a, b):
    """How far apart two pictures look (mean difference out of 255), or None when they are not the same picture."""
    if abs(a["aspect"] - b["aspect"]) > ASPECT_TOL * max(a["aspect"], b["aspect"], 1e-9):
        return False
    if a["stamp"] and b["stamp"] and a["stamp"] != b["stamp"]:
        return None                                       # shot at different moments: never a duplicate
    d = np.abs(a["grey"] - b["grey"])
    m = float(d.mean())
    return m if m <= MEAN_DIFF_MAX and float(np.percentile(d, 95)) <= P95_DIFF_MAX else None


def same_picture(a, b):
    return picture_distance(a, b) is not None


# ---------------------------------------------------------------- grouping
class DSU:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def find_duplicates(files, near=True, log=print):
    n = len(files)
    dsu = DSU(n)
    sizes = [f.stat().st_size for f in files]
    exact_pairs = 0
    by_size = defaultdict(list)
    for i, s in enumerate(sizes):
        by_size[s].append(i)
    cand = [v for v in by_size.values() if len(v) > 1]
    todo = sum(len(v) for v in cand)
    log(f"בודק אילו קבצים זהים בדיוק ({todo} קבצים באותו גודל)")
    hashes, k = {}, 0
    for v in cand:
        seen = {}
        for i in v:
            k += 1
            if k % 25 == 0:
                log(f"  [{k}/{todo}]")
            try:
                h = file_hash(files[i])
            except OSError as e:
                log(f"  לא הצלחתי לקרוא את {files[i].name}: {e}")
                continue
            hashes[i] = h
            if h in seen:
                dsu.union(i, seen[h])
                exact_pairs += 1
            else:
                seen[h] = i
    near_pairs = 0
    if near:
        idx = [i for i, f in enumerate(files) if f.suffix.lower() in IMAGE_EXT]
        log(f"בודק אילו תמונות כמעט זהות ({len(idx)} קבצים)")
        info, bands = {}, defaultdict(list)
        stamps = {}                                      # capture times present in each group so far
        for n_done, i in enumerate(idx, 1):
            if n_done % 25 == 0 or n_done == len(idx):
                log(f"  [{n_done}/{len(idx)}]")
            try:
                d = describe(files[i])
            except Exception as e:
                log(f"  מדלג על {files[i].name}: {e}")
                continue
            info[i] = d
            if d["stamp"]:
                stamps[i] = {d["stamp"]}
            for b in range(4):                           # four 16-bit slices of the hash
                bands[(b, (d["hash"] >> (16 * b)) & 0xFFFF)].append(i)
        tried, edges = set(), []
        for members in bands.values():
            if len(members) < 2 or len(members) > BUCKET_MAX:
                continue
            for x in range(len(members)):
                for y in range(x + 1, len(members)):
                    a, b = members[x], members[y]
                    if (a, b) in tried or dsu.find(a) == dsu.find(b):
                        continue
                    tried.add((a, b))
                    dist = picture_distance(info[a], info[b])
                    if dist is not None:
                        edges.append((dist, a, b))
        # closest matches first, so a file with no capture time (e.g. a copy sent through a chat app) joins its
        # best match, and cannot then be pulled into a different moment's group
        for dist, a, b in sorted(edges):
            ra, rb = dsu.find(a), dsu.find(b)
            if ra == rb:
                continue
            both = stamps.get(ra, set()) | stamps.get(rb, set())
            if len(both) > 1:
                continue
            dsu.union(a, b)
            stamps[dsu.find(a)] = both
            near_pairs += 1
    groups = defaultdict(list)
    for i in range(n):
        groups[dsu.find(i)].append(i)
    result = []
    for members in groups.values():
        if len(members) < 2:
            continue
        hs = {hashes.get(i) for i in members}
        kind = "exact" if len(hs) == 1 and None not in hs else "near"
        result.append({"kind": kind, "files": members})
    return result


def pixels(path):
    try:
        with Image.open(path) as im:
            return im.size[0] * im.size[1]
    except Exception:
        return 0


def order_members(files, members):
    """Best one first: biggest picture, biggest file, then name."""
    def key(i):
        p = files[i]
        return (-pixels(p), -p.stat().st_size, str(p).lower())
    return sorted(members, key=key)


# ---------------------------------------------------------------- reports
def thumb_b64(path):
    try:
        with Image.open(path) as im:
            im.draft("RGB", (400, 400))
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((220, 220))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=70)
            return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


DUPES_INTRO = ("הכלי רק מדווח, ולא מזיז או מוחק כלום. ההצעה לשמירה היא התמונה הגדולה ביותר בכל קבוצה, ואחריה הקובץ הגדול ביותר. "
               "צילומי רצף או כמה תמונות מאותה זווית לא נחשבים כפילות.")


def write_reports(out, files, groups):
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for gi, g in enumerate(groups, 1):
        g["order"] = order_members(files, g["files"])
        for rank, i in enumerate(g["order"]):
            p = files[i]
            rows.append({"group": gi, "kind": g["kind"], "suggestion": "keep" if rank == 0 else "copy",
                         "file": p.name, "size_bytes": p.stat().st_size, "pixels": pixels(p), "path": str(p)})
    with open(out / "duplicates.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["group", "kind", "suggestion", "file", "size_bytes", "pixels", "path"])
        w.writeheader()
        w.writerows(rows)
    e = html.escape
    kinds = {"exact": tr("קבצים זהים בדיוק"), "near": tr("אותה תמונה, בגודל או בדחיסה אחרים")}
    d_ = "rtl" if i18n.rtl() else "ltr"
    h = ["""<!doctype html><html lang="@LANG@" dir="@DIR@"><meta charset="utf-8"><title>@T@</title>
<style>
body{background:#161616;color:#eee;font-family:Segoe UI,Arial,sans-serif;margin:0;padding:24px}
h1{font-size:22px} .grp{background:#202020;border-radius:8px;padding:12px;margin:14px 0}
.grp h3{margin:0 0 8px;font-size:15px;color:#ccc} .row{display:flex;flex-wrap:wrap;gap:12px}
.c{width:230px;background:#2a2a2a;border-radius:6px;padding:6px} .c img{width:100%;height:180px;object-fit:contain;background:#111;display:block;border-radius:4px}
.n{font-family:Consolas,monospace;font-size:12px;color:#aaa;direction:ltr;text-align:left;word-break:break-all;margin-top:4px}
.k{display:inline-block;border-radius:4px;padding:1px 7px;font-size:12px;margin-top:4px;background:#4caf50;color:#000}
.k.copy{background:#555;color:#eee} .foot{margin-top:40px;color:#777;font-size:12px;text-align:center}
</style><body><h1>@T@</h1>
<p>@INTRO@</p>"""]
    h[0] = (h[0].replace("@LANG@", i18n.LANG).replace("@DIR@", d_).replace("@T@", tr("כפילויות"))
            .replace("@INTRO@", html.escape(tr(DUPES_INTRO))))
    shown = 0
    for gi, g in enumerate(groups, 1):
        n_files = len(g['order'])
        head = f"{tr(f'קבוצה {gi}')} · {kinds[g['kind']]} · {tr(f'{n_files} קבצים')}"
        h.append(f"<div class='grp'><h3>{head}</h3><div class='row'>")
        for rank, i in enumerate(g["order"]):
            p = files[i]
            img = thumb_b64(p) if shown < 400 and p.suffix.lower() in IMAGE_EXT else ""
            shown += 1
            tag = f"<span class='k'>{tr('לשמור')}</span>" if rank == 0 else f"<span class='k copy'>{tr('עותק')}</span>"
            im = f"<img src='data:image/jpeg;base64,{img}'>" if img else ""
            h.append(f"<div class='c'>{im}{tag}<div class='n'>{e(str(p))}</div></div>")
        h.append("</div></div>")
    h.append("<p class='foot'>" + tr("נוצר בכלי מיון ודירוג תמונות") + " · " + tr("כל הזכויות שמורות לנתאי שנדורפי") + " ©</p></body>")
    (out / "report.html").write_text("\n".join(h), encoding="utf-8")


def main():
    i18n.setup_cli()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__copyright__)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--recursive", action="store_true", help="include sub-folders")
    ap.add_argument("--no-near", action="store_true", help="only exact copies")
    ap.add_argument("--out", type=Path, default=None, help="where to write the report")
    args = ap.parse_args()
    if not args.folder.is_dir():
        sys.exit(f"התיקייה לא נמצאה: {args.folder}")
    out = (args.out or (args.folder / OUT_DIR_NAME)).resolve()
    files = find_files(args.folder, args.recursive)
    print(f"נמצאו {len(files)} קבצי תמונה")
    if len(files) < 2:
        sys.exit("אין מספיק קבצים להשוואה.")
    groups = find_duplicates(files, near=not args.no_near)
    if not groups:
        print("לא נמצאו כפילויות.")
        out.mkdir(parents=True, exist_ok=True)
        write_reports(out, files, [])
        return
    write_reports(out, files, groups)
    extra = sum(len(g["files"]) - 1 for g in groups)
    n_exact = sum(1 for g in groups if g["kind"] == "exact")
    print(f"\nקבוצות כפילויות: {len(groups)}. קבצים זהים בדיוק: {n_exact}. אותה תמונה בגודל או בדחיסה אחרים: {len(groups) - n_exact}.")
    print(f"עותקים מיותרים בסך הכול: {extra}.")
    print("לא הזזתי ולא מחקתי כלום.")
    print(f"הדוח (לפתוח בדפדפן): {out / 'report.html'}")
    print(f"גיליון לאקסל:     {out / 'duplicates.csv'}")


if __name__ == "__main__":
    main()
