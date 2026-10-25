#!/usr/bin/env python3
# © 2026 נתאי שנדורפי (Nitay Sandorffy). MIT License.
"""
Stage 1 of the portfolio workflow.

What it does:
  1. Scans a folder tree for JPEG files only (RAW files are ignored).
  2. Optionally keeps only photos shot on the cameras you name with --cameras (read from EXIF).
  3. Scores sharpness and darkness, and flags blurry / dark photos.
  4. Writes small thumbnails (keeps the folder structure) + a report.csv.
  5. Builds numbered contact sheets from the photos that passed,
     ready to upload to an AI chat for rating.

Install once:   pip install pillow numpy
Check cameras:  python photo_triage.py "D:\\Photos" --list-cameras
Run:            python photo_triage.py "D:\\Photos" --out "D:\\triage"
Only some cameras / skip some folders:
                python photo_triage.py "D:\\Photos" --out "D:\\triage" --cameras "R6 Mark II,250D" --exclude raw-copies
"""
__author__ = "נתאי שנדורפי"
__copyright__ = "© 2026 נתאי שנדורפי. MIT License."
import argparse
import csv
import os
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

# These are your own photos, so disable Pillow's "decompression bomb" warning
# (it triggers on very large images such as panoramas).
Image.MAX_IMAGE_PIXELS = None

# ---------------------------------------------------------------- settings
# Camera filter: pass --cameras "name1,name2" to keep only photos whose EXIF "Model" contains
# one of the names (case-insensitive). Leave it empty to accept every camera.
# Canon uses different model names in different regions, so a few aliases are built in:
CAMERA_ALIASES = {
    "r6 mark ii": ["r6m2"], "r6m2": ["r6 mark ii"],
    "600d": ["rebel t3i", "kiss x5"],
    "250d": ["rebel sl3", "200d ii", "kiss x10"],
}

# Folders whose NAME contains one of these words are skipped completely (with everything inside).
# Empty by default; set it with --exclude (for example to skip folders that hold camera-made
# JPEG copies of RAW files).
EXCLUDE_FOLDER_WORDS = []

ANALYSIS_SIZE = 1024      # long edge used for scoring (keeps thresholds comparable)
THUMB_SIZE = 800          # long edge of saved thumbnails
SHEET_COLS, SHEET_ROWS = 4, 3
CELL_W, CELL_H = 480, 360

# Defaults - calibrate these on your own photos using report.csv
BLUR_THRESHOLD = 40.0     # sharpness below this -> "blurry"
DARK_MEAN_MAX = 45.0      # average brightness (0-255) below this ...
DARK_P99_MAX = 100.0      # ... AND the brightest 1% of pixels below this -> "dark"
                          # (silhouettes / sunsets keep a bright spot, so they pass)


# ---------------------------------------------------------------- helpers
def get_camera(img):
    """Return the EXIF camera model string, or '' if missing."""
    try:
        model = img.getexif().get(0x0110, "")  # 0x0110 = Model
        return str(model).strip()
    except Exception:
        return ""


def camera_allowed(model, wanted):
    """A label for the camera if it is accepted, else None. With no filter every camera is accepted."""
    if not wanted:
        return model or "(unknown)"
    m = model.lower()
    for w in wanted:
        terms = [w.lower()] + CAMERA_ALIASES.get(w.lower(), [])
        if any(t in m for t in terms):
            return w
    return None


def parse_cameras(text):
    return [c.strip() for c in re.split(r"[,;]", text or "") if c.strip()]


def laplacian(gray):
    """4-neighbour Laplacian (edge detector) using plain numpy."""
    g = gray.astype(np.float32)
    return (-4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1]
            + g[1:-1, :-2] + g[1:-1, 2:])


def sharpness_score(gray):
    """
    Variance of the Laplacian, measured per tile on an 8x8 grid.
    The score is the average of the 3 sharpest tiles.
    Why not the whole image: portraits and macro shots have a deliberately
    blurry background, and the sharp subject (an eye, a flower) may cover
    only a few tiles. We only need SOME region to be sharp. A photo where
    no region is sharp scores low.
    """
    lap = laplacian(gray)
    h, w = lap.shape
    n = 8
    tiles = [lap[i * h // n:(i + 1) * h // n, j * w // n:(j + 1) * w // n].var()
             for i in range(n) for j in range(n)]
    return float(np.mean(sorted(tiles)[-3:]))


def brightness_scores(gray):
    return float(gray.mean()), float(np.percentile(gray, 99))


def find_jpegs(root, skip_dir, exclude_words):
    """Walk the tree, pruning the output folder and any excluded folder names."""
    words = [w.lower() for w in exclude_words]
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if Path(dirpath, d).resolve() != skip_dir
            and not any(w in d.lower() for w in words)
        ]
        for name in filenames:
            if name.lower().endswith((".jpg", ".jpeg")):
                yield Path(dirpath, name)


def get_font(size):
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


# ---------------------------------------------------------------- contact sheets
def make_sheets(ok_rows, sheets_dir):
    sheets_dir.mkdir(parents=True, exist_ok=True)
    per_sheet = SHEET_COLS * SHEET_ROWS
    font = get_font(34)
    n_sheets = 0
    for s in range(0, len(ok_rows), per_sheet):
        chunk = ok_rows[s:s + per_sheet]
        sheet = Image.new("RGB", (SHEET_COLS * CELL_W, SHEET_ROWS * CELL_H), (20, 20, 20))
        draw = ImageDraw.Draw(sheet)
        for k, row in enumerate(chunk):
            x, y = (k % SHEET_COLS) * CELL_W, (k // SHEET_COLS) * CELL_H
            with Image.open(row["thumb_path"]) as im:
                im = im.convert("RGB")
                im.thumbnail((CELL_W - 8, CELL_H - 8))
                sheet.paste(im, (x + 4 + (CELL_W - 8 - im.width) // 2,
                                 y + 4 + (CELL_H - 8 - im.height) // 2))
            label = str(row["id"])
            draw.rectangle([x + 4, y + 4, x + 12 + 22 * len(label), y + 44], fill=(0, 0, 0))
            draw.text((x + 8, y + 6), label, fill=(255, 255, 0), font=font)
        n_sheets += 1
        sheet.save(sheets_dir / f"sheet_{n_sheets:03d}.jpg", quality=85)
    return n_sheets


# ---------------------------------------------------------------- main
def main():
    import i18n
    i18n.setup_cli()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__copyright__)
    ap.add_argument("source", type=Path, help="root folder with your photos")
    ap.add_argument("--out", type=Path, default=Path("triage_output"), help="output folder")
    ap.add_argument("--list-cameras", action="store_true",
                    help="only count camera models found in JPEGs, then exit")
    ap.add_argument("--cameras", default="",
                    help='keep only these cameras, comma separated, e.g. "R6 Mark II,250D" (default: all)')
    ap.add_argument("--exclude", nargs="*", default=EXCLUDE_FOLDER_WORDS,
                    help="skip folders whose name contains any of these words (default: none)")
    ap.add_argument("--blur", type=float, default=BLUR_THRESHOLD, help="blur threshold")
    args = ap.parse_args()

    wanted = parse_cameras(args.cameras)
    src = args.source.resolve()
    out = args.out.resolve()
    if not src.is_dir():
        sys.exit(f"התיקייה לא נמצאה: {src}")

    # ---- mode 1: just list camera models
    if args.list_cameras:
        counts = Counter()
        for p in find_jpegs(src, out, args.exclude):
            try:
                with Image.open(p) as im:
                    counts[get_camera(im) or "(בלי נתוני מצלמה)"] += 1
            except Exception:
                counts["(לא נקרא)"] += 1
        for model, n in counts.most_common():
            mark = "  <-- מאושרת" if (wanted and camera_allowed(model, wanted)) else ""
            print(f"{n:6d}  {model}{mark}")
        return

    # ---- mode 2: full run
    thumbs_dir = out / "thumbs"
    sheets_dir = out / "sheets"
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    rows, skipped_camera, errors = [], 0, 0
    next_id = 1
    for n, p in enumerate(find_jpegs(src, out, args.exclude), 1):
        if n % 100 == 0:
            print(f"  עברתי על {n} קבצים...")
        try:
            with Image.open(p) as im:
                cam = camera_allowed(get_camera(im), wanted)
                if cam is None:
                    skipped_camera += 1
                    continue
                im.draft("RGB", (ANALYSIS_SIZE, ANALYSIS_SIZE))  # fast JPEG decode at reduced size
                im = ImageOps.exif_transpose(im).convert("RGB")
                big = im.copy()
                big.thumbnail((ANALYSIS_SIZE, ANALYSIS_SIZE))
                gray = np.asarray(big.convert("L"))
                sharp = sharpness_score(gray)
                mean_b, p99_b = brightness_scores(gray)

                status = "ok"
                if mean_b < DARK_MEAN_MAX and p99_b < DARK_P99_MAX:
                    status = "dark"
                elif sharp < args.blur:
                    status = "blurry"

                thumb_path = ""
                if status == "ok":
                    rel = p.relative_to(src)
                    thumb_path = thumbs_dir / rel.with_suffix(".jpg")
                    thumb_path.parent.mkdir(parents=True, exist_ok=True)
                    t = im.copy()
                    t.thumbnail((THUMB_SIZE, THUMB_SIZE))
                    t.save(thumb_path, quality=85)

                rows.append({
                    "id": next_id, "path": str(p), "camera": cam,
                    "sharpness": round(sharp, 1), "mean_brightness": round(mean_b, 1),
                    "p99_brightness": round(p99_b, 1), "status": status,
                    "thumb_path": str(thumb_path),
                })
                next_id += 1
        except Exception as e:
            errors += 1
            print(f"  לא הצלחתי לקרוא את {p.name}: {e}")

    # ---- report
    report = out / "report.csv"
    fields = ["id", "path", "camera", "sharpness", "mean_brightness",
              "p99_brightness", "status", "thumb_path"]
    with open(report, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    ok_rows = [r for r in rows if r["status"] == "ok"]
    n_sheets = make_sheets(ok_rows, sheets_dir) if ok_rows else 0

    c = Counter(r["status"] for r in rows)
    print("\nסיימתי.")
    print(f"  דילגתי על {skipped_camera} קבצים (מצלמה אחרת או בלי נתוני EXIF)")
    print(f"  ממצלמות מאושרות: {len(rows)}  "
          f"(תקינות {c['ok']}, מטושטשות {c['blurry']}, חשוכות {c['dark']})")
    print(f"  קבצים שלא נקראו: {errors}")
    print(f"  דפי מגע: {n_sheets} -> {sheets_dir}")
    print(f"  דוח: {report}")


if __name__ == "__main__":
    main()
