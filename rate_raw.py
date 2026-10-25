#!/usr/bin/env python3
# © 2026 נתאי שנדורפי (Nitay Sandorffy). MIT License.
"""
RAW culling assistant.

Works on RAW files only. For every RAW it reads the JPEG preview that the camera
embedded in the file (fast, no RAW conversion), groups similar shots taken one
after another, and asks Gemini to rank each group and score every photo ONLY on
things you cannot fix in editing: composition, camera angle, basic light, and the moment.
(Exposure, white balance, colour, noise are deliberately ignored.)
Then it picks the session highlights ("gems").

Output goes to a separate folder, your RAW files are never touched
(unless you explicitly use --write-xmp, see below):
    report.html   open in a browser: highlights first, then each group ranked
    ratings.csv   the same data for Excel
    previews\\     the preview JPEGs used (also what the report shows)

Install once:   pip install pillow numpy rawpy
Key (each new cmd window):   set GEMINI_API_KEY=your_key

USAGE
  One folder (a session you are editing):
      python rate_raw.py "E:\\Photos\\2026-10-05_session"
  Check the grouping first, without using any AI quota:
      python rate_raw.py "E:\\Photos\\2026-10-05_session" --prepare-only
  Lightroom catalog (close Lightroom first, or copy the .lrcat file):
      python rate_raw.py --catalog "D:\\LR\\catalog.lrcat" --since 2026-10-01
      python rate_raw.py --catalog "D:\\LR\\catalog.lrcat" --collection "Session Oct"
      python rate_raw.py --catalog "D:\\LR\\catalog.lrcat" --folder-contains 2026-10-05

OPTIONAL: --write-xmp  writes star ratings into .xmp sidecar files next to the RAWs
(gem = 5, other top highlights = 4, best of each group = 3). In Lightroom:
select the photos -> Metadata -> Read Metadata from Files. Existing non-zero
ratings are kept unless you add --overwrite-ratings. A .bak copy is made of any
sidecar that already exists.

Your taste: create a text file taste.txt next to this script (or use --taste FILE)
with a few lines about what you like. It is added to the AI instructions.

PRIVACY: on the free tier Google may use what you send to improve its products.
"""
__author__ = "נתאי שנדורפי"
__copyright__ = "© 2026 נתאי שנדורפי. MIT License."
import argparse
import base64
import csv
import hashlib
import html
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

import random
import ensemble
import llm_providers as llm
import photo_triage as tri

try:                                   # HEIC/HEIF (iPhone photos) needs the optional pillow-heif package
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIC_OK = True
except Exception:
    HEIC_OK = False
from i18n import tr
import i18n

Image.MAX_IMAGE_PIXELS = None

# ---------------------------------------------------------------- settings
# Changing the AI instructions? Bump this: old cached ratings are then ignored and the groups are rated again.
PROMPT_VERSION = "v3-structured|"

LOGO_INNER = '<rect width="200" height="200" rx="46" fill="#14213D"/><path d="M103.40,78.00 L162.81,112.30 A64 64 0 0 0 144.67,54.17 Z" fill="#F5B83D"/><path d="M120.75,91.94 L120.75,160.54 A64 64 0 0 0 162.03,115.77 Z" fill="#F4F7FB"/><path d="M117.35,113.94 L57.95,148.24 A64 64 0 0 0 117.35,161.60 Z" fill="#F4F7FB"/><path d="M96.60,122.00 L37.19,87.70 A64 64 0 0 0 55.33,145.83 Z" fill="#F4F7FB"/><path d="M79.25,108.06 L79.25,39.46 A64 64 0 0 0 37.97,84.23 Z" fill="#F4F7FB"/><path d="M82.65,86.06 L142.05,51.76 A64 64 0 0 0 82.65,38.40 Z" fill="#F4F7FB"/>'   # the app logo, used in the report header

RAW_EXT = {".cr3", ".cr2", ".crw", ".nef", ".nrw", ".arw", ".dng", ".raf",
           ".orf", ".rw2", ".pef", ".srw"}
# ordinary picture files, for photographers who also shoot JPEG or use the phone (opt-in: --include-other)
OTHER_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif", ".webp"}
SECONDS_BETWEEN_CALLS = 7
PREVIEW_SIZE = 1280
FLAG_NAMES = {
    "soft_focus": "פוקוס פספס",
    "motion_blur": "טשטוש תנועה",
    "eyes_closed": "עיניים עצומות",
    "subject_cut_off": "נושא חתוך",
    "bad_timing": "תזמון חלש",
    "distraction": "הסחת דעת",
}

CRITERIA = """The photographer shoots RAW and edits everything afterwards in Lightroom. You see the camera's embedded JPEG previews, downscaled, so judge each image as a whole and do not hunt for pixel-level flaws.

Your job is to help the photographer decide which frames are worth keeping. Judge ONLY what cannot be fixed in editing:
- COMPOSITION: framing, subject placement, balance, leading lines, layers/depth, distractions at the edges or behind the subject, separation of the subject from the background. A slightly tilted horizon or a crop that could be tightened later is NOT a flaw.
- ANGLE / VIEWPOINT: the camera position and perspective the photographer chose: height (low, eye level, high), angle to the subject (front, three-quarter, side, rear), distance, and the perspective that results. Judge whether the viewpoint suits the subject and adds impact. A distinctive, well-chosen angle that shows the subject at its best (for example a low three-quarter angle for a car, or eye level or slightly below for a portrait) is a major plus; a flat, default or unflattering angle is a real minus. The angle cannot be changed afterwards, so it counts as much as composition. (Small straightening or re-cropping does not count here.)
- LIGHT (basic): direction and quality of the light, how it shapes the subject, shadow/highlight patterns, atmosphere, subject/background separation by light, rim light or backlight when it helps.
- MOMENT: expression, gesture, timing, position of moving subjects (people, cars in motion). The peak instant matters.
- IMPACT: does the frame make you stop and look? A correct but ordinary, flat or merely documentary frame is an average frame (5). Distinctive, emotional or striking frames earn the high scores.
- CRITICAL TECHNICAL (report as flags, and lower the score only when it really ruins the frame): missed focus on the main subject, unintended motion blur, eyes closed or an awkward expression, subject cut off badly.

IGNORE COMPLETELY: overall exposure/brightness, white balance and colour cast, saturation, contrast level, noise, dust spots, and anything else Lightroom can correct. The preview's processing is not meaningful. Intentional silhouettes, low-key, high-key, motion blur and shallow depth of field are artistic choices, not flaws.

Judge the photograph, not its subject: an exciting subject does not make a good photo, and a modest subject can make a great one. Do not be influenced by where a photo appears in the list: the order is random.

Flags: add one only when it is clearly visible at this size; an empty list is normal.
soft_focus = the main subject (the eyes, for a person) is clearly out of focus while something else is sharp. motion_blur = unintended blur of the subject or camera shake. eyes_closed = a person's eyes shut or caught mid-blink. subject_cut_off = a head, limb or the subject cut by the frame edge in a bad place. bad_timing = the peak instant was missed (awkward mid-gesture, half-stride, someone blocking the subject). distraction = something in the frame that pulls the eye away from the subject.

Photographer's taste notes (priorities to apply on top of the above; if they say to ignore something, ignore it): {TASTE}

Allowed flags: soft_focus, motion_blur, eyes_closed, subject_cut_off, bad_timing, distraction."""

GENRES = {
    "street": "Genre: street photography. The decisive moment, gesture and interplay between people and place matter most; "
              "layering, light and shadow shapes, and a clean frame at the instant of peak interest. Reward candid, unposed moments. "
              "Do not penalize grain, slight softness or imperfect focus when the moment is strong.",
    "events": "Genre: events and people (weddings, parties, gatherings). Genuine expressions and emotional moments matter most. "
              "Penalize closed eyes, mid-blink, awkward mouths, half-turned faces and people blocking the main subject. "
              "Prefer the shot where the main people look their best and natural.",
    "sport": "Genre: sports and action. Peak action and a decisive instant matter most: the apex of the movement, the ball or contact point, "
             "visible effort and emotion. The main athlete must be sharp and in a clear position. Penalize missed focus, "
             "awkward half-movements and clutter that hides the athlete. Intentional panning blur can be good.",
    "landscape": "Genre: landscape and nature. Composition and depth matter most: foreground interest, leading lines, layering, "
                 "a clear point of focus, and a calm or striking balance. The quality of the light (golden hour, mist, dramatic sky) "
                 "is a major factor. Penalize empty skies, cluttered edges and a lack of a main subject.",
    "portrait": "Genre: portrait. The subject's eyes, expression and connection with the camera matter most; sharp focus on the eyes, "
                "flattering angle and light on the face, and a background that separates the subject cleanly. Penalize closed eyes, "
                "awkward expression and distracting objects around the head.",
    "cars": "Genre: cars. Viewpoint and light on the bodywork matter most: a low three-quarter angle, clear lines, "
            "reflections that shape the car, and a background that does not compete. Penalize distracting objects behind the car "
            "and awkward framing that cuts off the wheels or corners.",
}

GROUP_PROMPT = """You are an experienced photo editor helping a photographer cull a shoot.

""" + CRITERIA + """

{CONTEXT}

Each photo is introduced by a line "Photo N:" (N is only a label).

Scale for composition, angle, light and overall (1-10, halves such as 6.5 are allowed):
1-2 = a failed frame, 3-4 = weak, 5 = ordinary and correct (most frames), 6 = good, 7 = strong, 8 = excellent, 9-10 = exceptional (very rarely).
Use the whole range and do not give every frame the same score. In a typical shoot most frames fall between 4 and 6, about one in six reaches 7 or more, and 9 or more is a rare event.
"overall" is your holistic judgment of the frame as a keeper: composition, angle, light, moment and impact together, not an average. A serious flaw (missed focus on the subject, the main person's eyes closed, the subject badly cut off) lowers it by 1 to 3 points even when the rest is good.

Work in this order: for each photo first write a short "look" (what the subject is, what is happening, the strongest point and the weakest point), and only then give its scores.
In "note" write ONE short sentence in {LANGUAGE} (max 15 words): the main reason for the score, or what separates this frame from the others. Everything else is in English.

Return ONLY JSON of this shape, no other text:
{"differences": "<similar shots only, else empty: 1-2 sentences on what really differs between the frames (expression, eyes, pose, timing, sharpness of the subject, framing, background)>", "photos": [{"n": <number>, "look": "<max 25 words>", "composition": <1-10>, "angle": <1-10>, "light": <1-10>, "overall": <1-10>, "rank": <rank within this request, 1 = best, or null>, "flags": [<allowed flags>], "note": "<one sentence in {LANGUAGE}>"}]}"""

SIMILAR_CONTEXT = ("These {N} photos were taken one after another of the same scene, with small differences. "
                   "The photographer will keep the best frame and probably drop the rest, so the ranking matters most. "
                   "First find what actually differs between the frames. Then rank from best (rank 1) to worst in this order of importance: "
                   "(1) a frame with a critical flaw (closed eyes, missed focus, subject blocked) cannot be rank 1 if another frame is free of it; "
                   "(2) the better moment and expression; (3) composition and angle; (4) light. "
                   "Every photo must get a different rank, and the scores must reflect the gaps: frames that are practically equal may be half a point apart, "
                   "a clearly better frame should be at least one point higher. Rank 1 is not automatically a good photo: "
                   "if all the frames are mediocre, rank 1 still gets a mediocre score.")
SINGLES_CONTEXT = ("These {N} photos are unrelated to each other (different scenes). "
                   "Do not rank them against each other: set rank to null and judge each on its own, on the absolute scale below.")

HIGHLIGHT_PROMPT = """You are an experienced photo editor. The photographer finished a shoot session; below are the {N} strongest candidates from the session, each introduced by a line "Photo N:" (N is only a label; the order is random).

""" + CRITERIA + """

Compare the candidates against each other and rank ALL of them from best (1) to worst, with a different rank for each. Judge each one as a photograph that stands on its own, not as a record of the day.
If two candidates are nearly the same scene, rank the better one clearly higher; do not let both take high places unless each would stand on its own in a selection.
Set "gem" to true ONLY for photos that are truly exceptional: ones the photographer would print, show proudly and protect from deletion, and that clearly stand out from the rest of the session. It is fine to mark few or none.
In "reason" write ONE short sentence in {LANGUAGE} (max 15 words) on what makes the photo strong, or why it ranks where it does.

Return ONLY JSON of this shape, no other text:
{"photos": [{"n": <number>, "rank": <1..N>, "gem": <true|false>, "reason": "<one sentence in {LANGUAGE}>"}]}"""


ApiError = llm.ApiError


# ---------------------------------------------------------------- RAW previews
def fix_orientation(im, flip=0, raw_orientation=0):
    """Rotate the preview upright: EXIF orientation of the preview, else LibRaw's flip,
    else the orientation stored in the RAW's own metadata."""
    if im.getexif().get(0x0112):
        return ImageOps.exif_transpose(im)
    if flip in (5, 6) and im.width > im.height:   # sensor is landscape, picture is portrait
        return im.transpose(Image.Transpose.ROTATE_90 if flip == 5 else Image.Transpose.ROTATE_270)
    if raw_orientation in (6, 8) and im.width > im.height:
        return im.transpose(Image.Transpose.ROTATE_270 if raw_orientation == 6
                            else Image.Transpose.ROTATE_90)
    return im


# --- pure-Python fallback (no native libraries): find the JPEGs inside the RAW file
def jpeg_end(data, pos):
    """Return the end offset of the JPEG that starts at pos, by walking its segments."""
    n = len(data)
    i = pos + 2
    while i + 4 <= n:
        if data[i] != 0xFF:
            return None
        m = data[i + 1]
        if m == 0xFF:
            i += 1
            continue
        if m == 0xD9:
            return i + 2
        if m == 0x01 or 0xD0 <= m <= 0xD7:
            i += 2
            continue
        i += 2 + ((data[i + 2] << 8) | data[i + 3])
        if m == 0xDA:                      # start of scan: skip the entropy-coded data
            j = i
            while True:
                j = data.find(b"\xff", j)
                if j == -1 or j + 1 >= n:
                    return None
                nb = data[j + 1]
                if nb == 0xFF:
                    j += 1
                elif nb == 0 or 0xD0 <= nb <= 0xD7:
                    j += 2
                else:
                    break
            i = j
    return None


def find_embedded_jpegs(data):
    """List (start, end) of every complete JPEG in the file, largest first."""
    found, pos, last_end = [], 0, 0
    while True:
        pos = data.find(b"\xff\xd8\xff", pos)
        if pos == -1:
            break
        if pos < last_end:                 # inside a JPEG we already found (e.g. EXIF thumbnail)
            pos += 3
            continue
        end = jpeg_end(data, pos)
        if end:
            found.append((pos, end))
            last_end = end
            pos = end
        else:
            pos += 3
    found.sort(key=lambda x: -(x[1] - x[0]))
    return found


def cr3_metadata(data):
    """Orientation and capture time from the CMT1/CMT2 boxes of a Canon CR3."""
    head = data[:3_000_000]
    meta = {"orientation": 0, "time": None}
    for tag in (b"CMT1", b"CMT2"):
        i = head.find(tag)
        if i < 4:
            continue
        size = int.from_bytes(head[i - 4:i], "big")
        tiff = head[i + 4:i - 4 + size]
        try:
            ex = Image.Exif()
            ex.load(b"Exif\x00\x00" + tiff)
        except Exception:
            continue
        if ex.get(0x0112):
            meta["orientation"] = int(ex.get(0x0112))
        v = ex.get(0x9003) or ex.get_ifd(0x8769).get(0x9003) or ex.get(0x0132)
        if v and not meta["time"]:
            try:
                meta["time"] = datetime.strptime(str(v).strip()[:19], "%Y:%m:%d %H:%M:%S")
            except ValueError:
                pass
    return meta


def scan_preview(path):
    data = path.read_bytes()
    for start, end in find_embedded_jpegs(data):
        if end - start < 20_000:
            break
        try:
            im = Image.open(io.BytesIO(data[start:end]))
            im.load()
        except Exception:
            continue
        orient = cr3_metadata(data)["orientation"] if path.suffix.lower() == ".cr3" else 0
        return fix_orientation(im, 0, orient)
    raise RuntimeError("לא נמצאה תמונת JPEG בתוך הקובץ")


_NOTED = {"fallback": False}


def extract_preview(path):
    """Return the RAW's embedded JPEG preview as a PIL image."""
    if path.suffix.lower() in OTHER_EXT:
        with Image.open(path) as im:
            im.load()
            return ImageOps.exif_transpose(im)
    problem = ""
    try:
        import rawpy
        with rawpy.imread(str(path)) as raw:
            t = raw.extract_thumb()
            flip = raw.sizes.flip
            if t.format == rawpy.ThumbFormat.JPEG:
                im = Image.open(io.BytesIO(t.data))
                im.load()
            else:
                im = Image.fromarray(t.data)
        return fix_orientation(im, flip)
    except ImportError as e:
        problem = f"rawpy לא נטען: {e}"
    except Exception as e:
        problem = f"rawpy נכשל: {e}"
    if not _NOTED["fallback"]:
        _NOTED["fallback"] = True
        print("  rawpy לא זמין אצלך, אז אני קורא את הקבצים בשיטה אחרת. היא קצת איטית יותר, אבל עובדת.")
    try:
        return scan_preview(path)
    except Exception as e:
        problem += f" | שיטה פנימית: {e}"
    exe = shutil.which("exiftool")
    if exe:
        for tag in ("-JpgFromRaw", "-PreviewImage", "-ThumbnailImage"):
            data = subprocess.run([exe, "-b", tag, str(path)], capture_output=True).stdout
            if data[:2] == b"\xff\xd8":
                im = Image.open(io.BytesIO(data))
                im.load()
                return fix_orientation(im)
    raise RuntimeError(problem or "לא נמצאה תצוגה מקדימה")


def capture_time(path, catalog_time=None):
    if catalog_time:
        return catalog_time
    try:
        with Image.open(path) as im:
            ex = im.getexif()
            v = ex.get_ifd(0x8769).get(0x9003) or ex.get(0x0132)
            if v:
                return datetime.strptime(str(v).strip()[:19], "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    if path.suffix.lower() == ".cr3":
        try:
            with open(path, "rb") as f:
                t = cr3_metadata(f.read(3_000_000))["time"]
            if t:
                return t
        except Exception:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime)


# ---------------------------------------------------------------- file discovery
def drop_jpeg_of_raw_pairs(files):
    """A JPEG saved next to a RAW with the same name is the same shot: keep only the RAW (no double work)."""
    raw_keys = {(p.parent, p.stem.lower()) for p in files if p.suffix.lower() in RAW_EXT}
    return [p for p in files if p.suffix.lower() in RAW_EXT or (p.parent, p.stem.lower()) not in raw_keys]


def find_raws(folder, recursive, include_other=False, keep_pairs=False):
    """RAW files, and with include_other also JPEG/PNG/TIFF/HEIC. By default a JPEG that sits next to a RAW
    of the same name is skipped, so shooting RAW+JPEG does not make the tool work twice."""
    it = folder.rglob("*") if recursive else folder.glob("*")
    wanted = RAW_EXT | OTHER_EXT if include_other else RAW_EXT
    files = [p for p in it if p.is_file() and p.suffix.lower() in wanted]
    if include_other and not keep_pairs:
        files = drop_jpeg_of_raw_pairs(files)
    return sorted(files, key=lambda p: p.name.lower())


def parse_lr_time(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).split(".")[0].replace("Z", ""))
    except ValueError:
        return None


def catalog_files(lrcat, since, until, folder_contains, collection, include_other=False):
    """Read-only query of a Lightroom Classic catalog (works on a temporary copy)."""
    tmp = Path(tempfile.mkdtemp()) / "cat.lrcat"
    shutil.copy2(lrcat, tmp)
    con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
    try:
        sql = """
          SELECT rf.absolutePath, fo.pathFromRoot, f.baseName, f.extension, i.captureTime
          FROM Adobe_images i
          JOIN AgLibraryFile f ON i.rootFile = f.id_local
          JOIN AgLibraryFolder fo ON f.folder = fo.id_local
          JOIN AgLibraryRootFolder rf ON fo.rootFolder = rf.id_local
        """
        where, params = [], []
        if collection:
            sql += (" JOIN AgLibraryCollectionImage ci ON ci.image = i.id_local"
                    " JOIN AgLibraryCollection c ON ci.collection = c.id_local")
            where.append("c.name = ?")
            params.append(collection)
        if since:
            where.append("i.captureTime >= ?")
            params.append(since)
        if until:
            where.append("i.captureTime < ?")
            params.append(until)
        if folder_contains:
            where.append("(fo.pathFromRoot LIKE ? OR rf.absolutePath LIKE ?)")
            params += [f"%{folder_contains}%"] * 2
        if where:
            sql += " WHERE " + " AND ".join(where)
        rows = con.execute(sql, params).fetchall()
    finally:
        con.close()
    result = {}
    for root, rel, base, ext, ct in rows:
        p = Path(f"{root}{rel}{base}.{ext}")
        if p.suffix.lower() in RAW_EXT or (include_other and p.suffix.lower() in OTHER_EXT):
            result[p] = parse_lr_time(ct)
    return result


# ---------------------------------------------------------------- index + grouping
def build_index(files, out, catalog_times, index, size):
    prev_dir = out / "previews"
    prev_dir.mkdir(parents=True, exist_ok=True)
    for n, p in enumerate(files, 1):
        key = str(p)
        rec = index.get(key)
        if rec and rec.get("size") == p.stat().st_size and (out / rec["preview"]).exists():
            continue
        print(f"  [{n}/{len(files)}] קורא את התצוגה המקדימה של {p.name}")
        try:
            im = extract_preview(p).convert("RGB")
        except Exception as e:
            print(f"    מדלג על {p.name}: {e}")
            continue
        im.thumbnail((size, size))
        name = f"{p.stem}_{hashlib.sha1(key.encode()).hexdigest()[:6]}.jpg"
        im.save(prev_dir / name, quality=88)
        g = np.asarray(im.convert("L").resize((24, 24), Image.BILINEAR), dtype=np.float32)
        sig = (g - g.mean()).round(1).flatten().tolist()
        t = capture_time(p, catalog_times.get(p))
        index[key] = {"preview": f"previews/{name}", "time": t.isoformat(), "sig": sig,
                      "size": p.stat().st_size}


# ---------------------------------------------------------------- local pre-filter (no AI, nothing is sent)
PRE_BLUR = 12.0            # sharpness below this is a clear failure (photo_triage uses 40 as a soft limit)
PRE_BRIGHT_MEAN = 238.0    # average brightness above this ...
PRE_BRIGHT_P1 = 205.0      # ... and even the darkest 1% of pixels above this -> blown out


def image_metrics(path):
    """Sharpness and brightness of a preview, on the same scale photo_triage uses."""
    with Image.open(path) as im:
        im = im.convert("L")
        im.thumbnail((tri.ANALYSIS_SIZE, tri.ANALYSIS_SIZE))
        gray = np.asarray(im)
    mean_b, p99 = tri.brightness_scores(gray)
    return {"sharp": round(tri.sharpness_score(gray), 1), "mean": round(mean_b, 1), "p99": round(p99, 1),
            "p1": round(float(np.percentile(gray, 1)), 1)}


def ensure_metrics(files, out, index):
    """Measure every preview once; the numbers are kept in index.json."""
    todo = [p for p in files if str(p) in index and "q" not in index[str(p)]]
    for n, p in enumerate(todo, 1):
        if n % 50 == 0:
            print(f"  [{n}/{len(todo)}] בודק איכות בסיסית")
        rec = index[str(p)]
        try:
            rec["q"] = image_metrics(out / rec["preview"])
        except (OSError, ValueError):
            rec["q"] = {}


def reject_reason(rec, blur=PRE_BLUR):
    """A reason when the photo is a clear technical failure, otherwise None. Deliberately cautious."""
    q = rec.get("q") or {}
    if not q:
        return None
    if q["mean"] < tri.DARK_MEAN_MAX and q["p99"] < tri.DARK_P99_MAX:
        return "חשוכה מאוד"
    if q["mean"] > PRE_BRIGHT_MEAN and q["p1"] > PRE_BRIGHT_P1:
        return "חשופה יתר על המידה"
    if q["sharp"] < blur:
        return "מטושטשת מאוד"
    return None


def load_taste(args):
    """What the model is told about the photographer's taste: the type of shoot, then the taste file."""
    taste_file = args.taste or Path(__file__).with_name("taste.txt")
    taste = taste_file.read_text(encoding="utf-8").strip() if taste_file.exists() else ""
    if args.genre:
        taste = (GENRES[args.genre] + "\n" + taste).strip()
    return taste


def taste_salt(taste):
    """Part of every result's key: another taste or type of shoot means the rating has to be redone."""
    return "|t" + hashlib.sha1(taste.encode("utf-8")).hexdigest()[:8] if taste else ""


def language_name():
    """Name of the language the model should write its notes in: the language chosen for the program."""
    return i18n.language_name()


def lang_salt():
    """Notes are written in the program's language, so results rated in another language are not reused.
    Hebrew adds nothing, which keeps the keys of the original language as they were."""
    return "" if i18n.LANG == "he" else "|" + i18n.LANG


FAR_STRICT = 0.8     # non-adjacent shots must look more alike than adjacent ones, since time does not vouch for them


def merge_far(groups, distance, limit, far, max_group):
    """Join groups of shots that are not next to each other in time but show the same scene.
    Two groups join when they started at most `far` seconds apart, their averages look alike and so does
    at least one pair of photos (one from each); the closest pairs go first and a joined group never exceeds max_group."""
    groups = [list(g) for g in groups]
    while True:
        means = [np.mean([i["sig"] for i in g], axis=0) for g in groups]
        best = None
        for a in range(len(groups)):
            ta = groups[a][0]["time"]
            for b in range(a + 1, len(groups)):
                gap = (groups[b][0]["time"] - ta).total_seconds()
                if gap > far:
                    break
                if len(groups[a]) + len(groups[b]) > max_group:
                    continue
                d = distance(means[a], means[b])
                if d > limit:
                    continue
                near = min(distance(x["sig"], y["sig"]) for x in groups[a] for y in groups[b])
                if near > limit:
                    continue
                if best is None or d < best[0]:
                    best = (d, a, b)
        if best is None:
            return groups
        _, a, b = best
        merged = sorted(groups[a] + groups[b], key=lambda x: (x["time"], x["name"].lower()))
        groups[a] = merged
        del groups[b]


def make_units(files, index, gap, sim, max_group, salt="", far=0):
    """Split the files (in shooting order) into groups of similar consecutive shots.
    far > 0: afterwards, groups that look alike and were shot at most `far` seconds apart are joined, even when other
    shots lie between them (a scene that was left and come back to)."""
    items = []
    for p in files:
        rec = index.get(str(p))
        if rec:
            items.append({"path": p, "name": p.name, "time": datetime.fromisoformat(rec["time"]),
                          "sig": np.array(rec["sig"], dtype=np.float32), "preview": rec["preview"]})
    items.sort(key=lambda x: (x["time"], x["name"].lower()))

    def norm(sig):
        """Signature scaled to unit contrast, so a brighter or flatter version of the same frame still matches."""
        sd = float(sig.std())
        return sig / sd if sd > 1e-3 else sig * 0

    def distance(a, b):
        """0 = the same picture, about 1 = unrelated pictures."""
        return float(np.abs(norm(a) - norm(b)).mean()) / 1.13

    groups, cur = [], []
    for it in items:
        if cur:
            prev = cur[-1]
            dt = (it["time"] - prev["time"]).total_seconds()
            # close to the previous shot AND to the first one AND to the average of the group so far,
            # so a long chain of small changes cannot drift into a different scene
            d_prev = distance(it["sig"], prev["sig"])
            d_first = distance(it["sig"], cur[0]["sig"])
            d_mean = distance(it["sig"], np.mean([c["sig"] for c in cur], axis=0))
            if dt > gap or d_prev > sim or d_first > sim * 1.5 or d_mean > sim * 1.25 or len(cur) >= max_group:
                groups.append(cur)
                cur = []
        cur.append(it)
    if cur:
        groups.append(cur)
    if far and far > 0:
        groups = merge_far(groups, distance, sim * FAR_STRICT, far, max_group)

    units, singles = [], []
    for g in groups:
        if len(g) >= 2:
            units.append({"kind": "similar", "items": g})
        else:
            singles.append(g[0])
    for i in range(0, len(singles), max_group):
        chunk = singles[i:i + max_group]
        units.append({"kind": "singles", "items": chunk})
    units.sort(key=lambda u: (u["items"][0]["time"], u["items"][0]["name"].lower()))
    for n, u in enumerate(units, 1):
        u["id"] = n
        u["key"] = hashlib.sha1((PROMPT_VERSION + salt + lang_salt() + u["kind"] + "|" + "|".join(sorted(i["name"] for i in u["items"]))
                                 ).encode()).hexdigest()[:10]
    return units


# ---------------------------------------------------------------- Gemini
def call_gemini(model, key, parts, retries=5):
    """Name kept for compatibility: sends the request to whichever provider is configured."""
    return llm.call(model, key, parts, retries)


def parse_json_list(text):
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



def img_part(out, rel):
    data = (out / rel).read_bytes()
    return {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(data).decode()}}


def num(v, lo=1, hi=10):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return None


def rank_int(v):
    n = num(v, 1, 99)
    return int(n) if n is not None else None


def explain_api_error(e):
    print(llm.explain_error(e))


def shown_order(n, seed):
    """A fixed shuffle of 0..n-1 for this seed, so the first and last photo get no extra attention and every
    reviewer sees a different order, while a re-run shows the same one."""
    order = list(range(n))
    random.Random(seed).shuffle(order)
    return order


def rate_unit(unit, out, taste, model, key, hints=None, role="a"):
    """hints: {photo name: text} to show next to a photo, e.g. what earlier reviewers scored (off by default).
    role: which reviewer this is ("a", "b", "c"): each one is shown the photos in its own order."""
    items = unit["items"]
    ctx = (SIMILAR_CONTEXT if unit["kind"] == "similar" else SINGLES_CONTEXT).replace("{N}", str(len(items)))
    prompt = (GROUP_PROMPT.replace("{CONTEXT}", ctx).replace("{LANGUAGE}", language_name())
              .replace("{TASTE}", taste or "none provided"))
    seed = (unit.get("key") or "|".join(i["name"] for i in items)) + role
    shown = [items[i] for i in shown_order(len(items), seed)]
    parts = [{"text": prompt}]
    for n, it in enumerate(shown, 1):
        extra = f" ({hints[it['name']]})" if hints and it["name"] in hints else ""
        parts.append({"text": f"Photo {n}:{extra}"})
        parts.append(img_part(out, it["preview"]))
    rows = parse_json_list(call_gemini(model, key, parts))
    res = {}
    for r in rows:
        try:
            n = int(r["n"])
        except (KeyError, TypeError, ValueError):
            continue
        if not 1 <= n <= len(shown):
            continue
        flags = [f for f in (r.get("flags") or []) if f in FLAG_NAMES]
        res[shown[n - 1]["name"]] = {
            "overall": num(r.get("overall")), "composition": num(r.get("composition")), "angle": num(r.get("angle")),
            "light": num(r.get("light")), "rank": rank_int(r.get("rank")),
            "flags": flags, "note": str(r.get("note") or "")[:200]}
    return res


def rate_highlights(cands, out, taste, model, key):
    prompt = (HIGHLIGHT_PROMPT.replace("{N}", str(len(cands))).replace("{LANGUAGE}", language_name())
              .replace("{TASTE}", taste or "none provided"))
    shown = [cands[i] for i in shown_order(len(cands), "|".join(c["name"] for c in cands))]
    parts = [{"text": prompt}]
    for n, c in enumerate(shown, 1):
        parts.append({"text": f"Photo {n}:"})
        parts.append(img_part(out, c["preview"]))
    res = {}
    for r in parse_json_list(call_gemini(model, key, parts)):
        try:
            n = int(r["n"])
        except (KeyError, TypeError, ValueError):
            continue
        if 1 <= n <= len(shown):
            res[shown[n - 1]["name"]] = {"hl_rank": rank_int(r.get("rank")),
                                         "gem": bool(r.get("gem")),
                                         "hl_reason": str(r.get("reason") or "")[:200]}
    return res


# ---------------------------------------------------------------- double check (a second model, and a judge)
def checker_config(args, role):
    """(provider, base url, model, key) for the second model ("second") or the judge ("judge"); None if not asked for."""
    model = getattr(args, f"{role}_model")
    if not model:
        return None
    given = getattr(args, f"{role}_provider")
    prov = given or args.provider
    base = getattr(args, f"{role}_base_url") if given else args.base_url
    key = getattr(args, f"{role}_key") or (args.key if prov == args.provider else None)
    with llm.using(prov, base):
        key = key or llm.env_key()
        if not key and llm.info()["key_required"]:
            env = (llm.info()["env"] or ["AI_API_KEY"])[0]
            sys.exit(f"חסר מפתח API עבור {llm.info()['label']} (הבדיקה הכפולה). כתוב:  set {env}=המפתח_שלך")
    return {"provider": prov, "base": base, "model": model, "key": key}


def checker_dir(out, role, cfg):
    tag = hashlib.sha1(f"{cfg['provider']}|{cfg['model']}".encode()).hexdigest()[:6]
    d = out / f"groups_{role}" / tag
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_dir(dirp, units):
    res = {}
    for u in units:
        data = read_json(dirp / f"{u['key']}.json") if (dirp / f"{u['key']}.json").exists() else None
        if isinstance(data, dict):
            res.update(data)
    return res


def judge_jobs(units, a, b, gap):
    """The pieces the judge is asked about: (file stem, sub-unit, [names]) for every disputed group."""
    jobs = []
    for u, names in ensemble.find_disputes(units, a, b, gap):
        stem = hashlib.sha1((u["key"] + "|" + ",".join(sorted(names))).encode()).hexdigest()[:16]
        sub = {"id": u["id"], "kind": u["kind"], "key": stem, "items": [i for i in u["items"] if i["name"] in names]}
        jobs.append((stem, sub, names))
    return jobs


def load_judge(dirp, jobs):
    res = {}
    for stem, _sub, _names in jobs:
        f = dirp / f"{stem}.json"
        data = read_json(f) if f.exists() else None
        if isinstance(data, dict):
            res.update(data)
    return res


def run_second_model(units, out, cfg, dirp, taste):
    """Rate the groups the first model rated, with the second model. Returns False if it had to stop."""
    todo = [u for u in units if (out / "groups" / f"{u['key']}.json").exists()
            and not (dirp / f"{u['key']}.json").exists()]
    if not todo:
        return True
    with llm.using(cfg["provider"], cfg["base"]):
        delay = llm.default_delay()
        print(f"\nבדיקה כפולה: {len(todo)} קבוצות לדירוג במודל השני ({llm.info()['label']}, {cfg['model']})")
        for n, u in enumerate(todo, 1):
            print(f"[{n}/{len(todo)}] קבוצה {u['id']} (מודל שני)")
            try:
                res = rate_unit(u, out, taste, cfg["model"], cfg["key"], role="b")
            except ValueError as e:
                print(f"    המודל השני לא הצליח לדרג את הקבוצה ({e}). הקבוצה תישאר עם הדירוג של המודל הראשון")
                continue
            except ApiError as e:
                explain_api_error(e)
                print("הבדיקה הכפולה נעצרה. מה שהושלם נשמר, ואפשר להמשיך בהרצה הבאה. הדירוג ימשיך להתבסס על המודל הראשון בקבוצות שנשארו.")
                return False
            atomic_write(dirp / f"{u['key']}.json", json.dumps(res, ensure_ascii=False))
            time.sleep(delay)
    return True


def run_judge(units, out, cfg, dirp, taste, a, b, gap, sees):
    """Ask the third model about the disputed photos and groups only."""
    jobs = judge_jobs(units, a, b, gap)
    todo = [j for j in jobs if not (dirp / f"{j[0]}.json").exists()]
    print(f"\nמחלוקות בין שני המודלים: {len(jobs)} קבוצות או קבוצות-משנה" + (f", מתוכן {len(todo)} עוד לא הוכרעו" if todo else ""))
    if not todo:
        return True
    with llm.using(cfg["provider"], cfg["base"]):
        delay = llm.default_delay()
        print(f"המכריע ({llm.info()['label']}, {cfg['model']}) בודק רק אותן" + (", כשהוא רואה את הציונים הקודמים" if sees else ", בלי לראות את הציונים הקודמים"))
        for n, (stem, sub, names) in enumerate(todo, 1):
            print(f"[{n}/{len(todo)}] הכרעה בקבוצה {sub['id']}")
            hints = None
            if sees:
                hints = {nm: f"earlier reviewers scored it {a[nm]['overall']:.0f} and {b[nm]['overall']:.0f}"
                         for nm in names if nm in a and nm in b and a[nm].get("overall") is not None
                         and b[nm].get("overall") is not None}
            try:
                res = rate_unit(sub, out, taste, cfg["model"], cfg["key"], hints, role="c")
            except ValueError as e:
                print(f"    המכריע לא הצליח ({e}). בקבוצה הזו תיקבע התוצאה לפי הממוצע")
                continue
            except ApiError as e:
                explain_api_error(e)
                print("ההכרעה נעצרה. מה שהושלם נשמר, ואפשר להמשיך בהרצה הבאה.")
                return False
            atomic_write(dirp / f"{stem}.json", json.dumps(res, ensure_ascii=False))
            time.sleep(delay)
    return True


# ---------------------------------------------------------------- merge + reports
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


def load_results(out, units):
    results = {}
    for u in units:
        f = out / "groups" / f"{u['key']}.json"
        if not f.exists():
            continue
        data = read_json(f)
        if not isinstance(data, dict):
            continue                      # damaged file: that group is simply rated again
        for name, rec in data.items():
            rec.update({"unit": u["id"], "kind": u["kind"]})
            results[name] = rec
    return results


def pick_candidates(units, results, n_cands):
    c = []
    for u in units:
        rated = [(results[i["name"]], i) for i in u["items"] if i["name"] in results
                 and results[i["name"]].get("overall") is not None]
        if not rated:
            continue
        if u["kind"] == "similar":
            rec, it = max(rated, key=lambda x: x[0]["overall"])
            c.append(it)
        else:
            c += [it for rec, it in rated if rec["overall"] >= 6]
    c.sort(key=lambda it: -results[it["name"]]["overall"])
    return c[:n_cands]


def write_csv_report(out, units, results, index_paths):
    fields = ["file", "group", "group_type", "rank_in_group", "overall", "composition", "angle", "light",
              "flags", "note", "highlight_rank", "gem", "highlight_reason", "path",
              "score_model_1", "score_model_2", "score_judge", "disputed", "decided_by"]
    rows = []
    for u in units:
        for it in u["items"]:
            r = results.get(it["name"], {})
            rows.append({
                "file": it["name"], "group": u["id"], "group_type": u["kind"],
                "rank_in_group": r.get("rank") if u["kind"] == "similar" else "",
                "overall": r.get("overall", ""), "composition": r.get("composition", ""), "angle": r.get("angle", ""),
                "light": r.get("light", ""), "flags": ",".join(r.get("flags", [])),
                "note": r.get("note", ""), "highlight_rank": r.get("hl_rank", ""),
                "gem": "yes" if r.get("gem") else "", "highlight_reason": r.get("hl_reason", ""),
                "path": str(it["path"]),
                "score_model_1": "" if r.get("score_a") is None else r["score_a"],
                "score_model_2": "" if r.get("score_b") is None else r["score_b"],
                "score_judge": "" if r.get("score_c") is None else r["score_c"],
                "disputed": "yes" if r.get("disputed") or r.get("group_disputed") else "",
                "decided_by": r.get("decided", "")})
    with open(out / "ratings.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def card(it, r, extra_class="", badge=""):
    e = html.escape
    flags = "".join(f'<span class="flag">{e(tr(FLAG_NAMES.get(f, f)))}</span>' for f in r.get("flags", []))
    scores = ""
    if r.get("overall") is not None:
        spans = "".join(f"<span>{label} {r[k]:.0f}</span>"
                        for label, k in ((tr("קומפוזיציה"), "composition"), (tr("זווית"), "angle"), (tr("אור"), "light"))
                        if r.get(k))
        scores = f'<div class="scores"><b>{r["overall"]:.0f}</b>{spans}</div>'
    ens = ""
    if r.get("score_a") is not None and r.get("score_b") is not None:
        parts = [f'{tr("מודל 1")} {r["score_a"]:.0f}', f'{tr("מודל 2")} {r["score_b"]:.0f}']
        if r.get("score_c") is not None:
            parts.append(f'{tr("מכריע")} {r["score_c"]:.0f}')
        hot = r.get("disputed") or r.get("group_disputed")
        tag = ""
        if r.get("decided") == "undecided":
            tag = f' <span class="flag">{tr("לא הוכרע")}</span>'
        elif hot:
            tag = f' <span class="flag">{tr("במחלוקת")}</span>'
        ens = f'<div class="ens">{" · ".join(parts)}{tag}</div>'
    note = r.get("hl_reason") or r.get("note") or ""
    return (f'<div class="card {extra_class}"><a href="{e(it["preview"])}" target="_blank">'
            f'<img loading="lazy" src="{e(it["preview"])}"></a>'
            f'<div class="info">{badge}<div class="name">{e(it["name"])}</div>{scores}{ens}'
            f'<div>{flags}</div><p>{e(note)}</p></div></div>')


REPORT_INTRO = ("ירוק = הטוב ביותר בקבוצה. זהב = \"פגז\". הציונים מתעלמים מחשיפה, איזון לבן וצבע, ומתייחסים לקומפוזיציה, אור ורגע. "
                "לחיצה על תמונה פותחת אותה בגדול. חפש את שם הקובץ בליטרום (Library Filter > Text > File Name).")


def write_html_report(out, units, results, title, rejected=None, double_check=None):
    by_name = {it["name"]: it for u in units for it in u["items"]}
    hl = sorted((n for n, r in results.items() if r.get("hl_rank")), key=lambda n: results[n]["hl_rank"])
    fav = urllib.parse.quote('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">' + LOGO_INNER + '</svg>')
    h = [f"""<!doctype html><html lang="{i18n.LANG}" dir="{"rtl" if i18n.rtl() else "ltr"}"><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
body{{background:#161616;color:#eee;font-family:Segoe UI,Arial,sans-serif;margin:0;padding:24px}}
h1{{font-size:22px}} h2{{margin-top:36px;border-bottom:1px solid #444;padding-bottom:6px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}}
.card{{background:#222;border-radius:8px;overflow:hidden;border:2px solid transparent}}
.card.best{{border-color:#4caf50}} .card.gem{{border-color:#ffc107}}
.card img{{width:100%;height:260px;object-fit:contain;background:#111;display:block}} .info{{padding:8px 10px}}
.name{{font-family:Consolas,monospace;font-size:13px;color:#aaa;direction:ltr;text-align:left}}
.ens{{color:#9ab;font-size:12px;margin:2px 0}} .scores{{margin:4px 0}} .scores b{{font-size:20px;margin-left:10px}} .scores span{{margin-left:8px;color:#bbb;font-size:13px}}
.flag{{background:#7a2e2e;border-radius:4px;padding:1px 6px;font-size:12px;margin-left:4px}}
.badge{{display:inline-block;background:#4caf50;color:#000;border-radius:4px;padding:1px 7px;font-size:12px;margin-left:6px}}
.badge.gem{{background:#ffc107}} p{{margin:4px 0;color:#ccc;font-size:14px}}
.foot{{margin-top:40px;color:#777;font-size:12px;text-align:center}}
</style><link rel="icon" href="data:image/svg+xml,{fav}"><body><h1><svg viewBox="0 0 200 200" width="38" height="38" style="vertical-align:middle;margin-left:10px">{LOGO_INNER}</svg>{html.escape(title)}</h1>
</body-intro>"""]
    h[0] = h[0].replace("</body-intro>", "<p>" + html.escape(tr(REPORT_INTRO)) + "</p>" +
                        (f"<p>{html.escape(double_check)}</p>" if double_check else ""))
    if hl:
        h.append(f"<h2>{tr('הבולטות של הסשן')}</h2><div class='grid'>")
        for n in hl:
            r = results[n]
            gem = r.get("gem")
            badge = (f'<span class="badge {"gem" if gem else ""}">'
                     f'{"💎 " + tr("פגז") + " · " if gem else ""}{tr("מקום {n}").replace("{n}", str(int(r["hl_rank"])))}</span>')
            h.append(card(by_name[n], r, "gem" if gem else "", badge))
        h.append("</div>")
    h.append(f"<h2>{tr('קבוצות')}</h2>")
    for u in units:
        title_u = (tr(f"קבוצה {u['id']} · {len(u['items'])} תמונות דומות") if u["kind"] == "similar"
                   else tr(f"קבוצה {u['id']} · תמונות בודדות ({len(u['items'])})"))
        h.append(f"<h3>{title_u}</h3><div class='grid'>")
        items = list(u["items"])
        if u["kind"] == "similar":
            items.sort(key=lambda it: results.get(it["name"], {}).get("rank") or 99)
        for i, it in enumerate(items):
            r = results.get(it["name"], {})
            best = u["kind"] == "similar" and r.get("rank") == 1
            badge = '<span class="badge">' + tr("הכי טוב בקבוצה") + '</span>' if best else ""
            h.append(card(it, r, "best" if best else "", badge))
        h.append("</div>")
    if rejected:
        h.append(f"<h2>{html.escape(tr(f'דולגו מראש, בלי בינה מלאכותית ({len(rejected)})'))}</h2>"
                 "<p>" + html.escape(tr("תמונות שנראות כטעות טכנית ברורה. הן לא נשלחו לדירוג. אם אחת מהן בכל זאת חשובה, "
                                        "הרץ שוב עם ביטול הסינון המקדים.")) + "</p><div class='grid'>")
        for r in rejected:
            h.append(f'<div class="card"><a href="{html.escape(r["preview"])}" target="_blank">'
                     f'<img loading="lazy" src="{html.escape(r["preview"])}"></a>'
                     f'<div class="info"><div class="name">{html.escape(r["name"])}</div>'
                     f'<span class="flag">{html.escape(tr(r["reason"]))}</span></div></div>')
        h.append("</div>")
    h.append('<p class="foot">' + html.escape(tr("נוצר בכלי מיון ודירוג תמונות")) + " · " + html.escape(tr("כל הזכויות שמורות לנתאי שנדורפי")) + " ©</p>")
    h.append("</body></html>")
    atomic_write(out / "report.html", "\n".join(h))


# ---------------------------------------------------------------- XMP (optional)
XMP_TEMPLATE = """<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmp:Rating="{R}"/>
 </rdf:RDF>
</x:xmpmeta>
"""


def write_xmp_rating(raw_path, stars, overwrite):
    """Set xmp:Rating in the sidecar, leaving everything else in it untouched."""
    xmp = raw_path.with_suffix(".xmp")
    if not xmp.exists():
        xmp.write_text(XMP_TEMPLATE.replace("{R}", str(stars)), encoding="utf-8")
        return "נוצרו"
    text = xmp.read_text(encoding="utf-8")
    attr = re.search(r'xmp:Rating="(\d+)"', text)
    elem = re.search(r"<xmp:Rating>(\d+)</xmp:Rating>", text)
    cur = int((attr or elem).group(1)) if (attr or elem) else 0
    if cur > 0 and not overwrite:
        return "נשמר דירוג קיים"
    bak = xmp.with_suffix(".xmp.bak")
    if not bak.exists():
        shutil.copy2(xmp, bak)
    if attr:
        text = text[:attr.start()] + f'xmp:Rating="{stars}"' + text[attr.end():]
    elif elem:
        text = text[:elem.start()] + f"<xmp:Rating>{stars}</xmp:Rating>" + text[elem.end():]
    else:
        m = re.search(r"<rdf:Description\b", text)
        if not m:
            return "דולג (מבנה סיידקאר לא צפוי)"
        ns = "" if "xmlns:xmp=" in text else ' xmlns:xmp="http://ns.adobe.com/xap/1.0/"'
        text = text[:m.end()] + f'{ns} xmp:Rating="{stars}"' + text[m.end():]
    xmp.write_text(text, encoding="utf-8")
    return "עודכנו"


def plan_stars(units, results, top_n):
    plan = {}
    for u in units:
        for it in u["items"]:
            r = results.get(it["name"])
            if not r:
                continue
            stars = 0
            if r.get("gem"):
                stars = 5
            elif r.get("hl_rank") and r["hl_rank"] <= top_n:
                stars = 4
            elif u["kind"] == "similar" and r.get("rank") == 1:
                stars = 3
            elif u["kind"] == "singles" and (r.get("overall") or 0) >= 7:
                stars = 3
            if stars:
                plan[it["path"]] = stars
    return plan


# ---------------------------------------------------------------- main
def main():
    i18n.setup_cli()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__copyright__)
    ap.add_argument("source", nargs="?", type=Path, help="folder with RAW files")
    ap.add_argument("--recursive", action="store_true", help="include sub-folders")
    ap.add_argument("--include-other", action="store_true",
                    help="also rate JPEG, PNG, TIFF and HEIC files, not only RAW (a JPEG next to a RAW of the same name is skipped)")
    ap.add_argument("--keep-pairs", action="store_true",
                    help="with --include-other: also rate a JPEG that has a RAW of the same name")
    ap.add_argument("--catalog", type=Path, help="Lightroom Classic catalog (.lrcat)")
    ap.add_argument("--since", help="catalog: capture date from, e.g. 2026-10-01")
    ap.add_argument("--until", help="catalog: capture date before, e.g. 2026-10-08")
    ap.add_argument("--collection", help="catalog: collection name")
    ap.add_argument("--folder-contains", help="catalog: text that must appear in the folder path")
    ap.add_argument("--out", type=Path, help="output folder (default: _rating inside the photo folder)")
    ap.add_argument("--provider", default="gemini", choices=llm.ORDER, help="AI provider")
    ap.add_argument("--base-url", default=None, help="custom server address (for 'custom', Ollama, LM Studio)")
    ap.add_argument("--delay", type=float, default=None, help="seconds between requests")
    ap.add_argument("--model", default=None)
    ap.add_argument("--highlight-model", default=None, help="model for the highlights step (default: --model)")
    ap.add_argument("--second-provider", default=None, choices=llm.ORDER,
                    help="double check: a second provider whose model rates the same photos")
    ap.add_argument("--second-base-url", default=None)
    ap.add_argument("--second-model", default=None, help="double check: the second model (turns the double check on)")
    ap.add_argument("--second-key", default=None)
    ap.add_argument("--judge-provider", default=None, choices=llm.ORDER,
                    help="double check: a third provider that settles the disagreements (optional)")
    ap.add_argument("--judge-base-url", default=None)
    ap.add_argument("--judge-model", default=None)
    ap.add_argument("--judge-key", default=None)
    ap.add_argument("--dispute-gap", type=float, default=ensemble.DEFAULT_GAP,
                    help="two models are in dispute about a photo when their scores differ by this much (default %(default)s)")
    ap.add_argument("--judge-sees-scores", action="store_true",
                    help="show the judge what the first two models scored (by default it rates blind, which keeps it independent)")
    ap.add_argument("--key", default=None)
    ap.add_argument("--taste", type=Path, default=None, help="text file describing your taste")
    ap.add_argument("--genre", choices=sorted(GENRES), default=None,
                    help="kind of shoot, so the rating fits it: " + ", ".join(sorted(GENRES)))
    ap.add_argument("--gap", type=float, default=120, help="seconds between shots that start a new group")
    ap.add_argument("--similarity", type=float, default=0.30,
                    help="how different consecutive shots may look before a new group starts (lower = more groups)")
    ap.add_argument("--far-gap", type=float, default=1800,
                    help="seconds: shots of the same scene up to this far apart are grouped even when other shots lie "
                         "between them (0 = only consecutive shots)")
    ap.add_argument("--max-group", type=int, default=8)
    ap.add_argument("--highlights", type=int, default=0,
                    help="how many top highlights get 4+ stars with --write-xmp (0 = about 4%% of the photos, at least 3)")
    ap.add_argument("--candidates", type=int, default=0, help="photos compared in the highlights step (0 = 12, or fewer if the provider takes fewer images per request)")
    ap.add_argument("--limit", type=int, default=0, help="only rate N groups in this run")
    ap.add_argument("--no-prefilter", action="store_true",
                    help="send every photo to the AI, including clear failures (very dark, blown out, very blurry)")
    ap.add_argument("--prefilter-blur", type=float, default=PRE_BLUR,
                    help="sharpness below this counts as very blurry and is skipped (default %(default)s)")
    ap.add_argument("--prepare-only", action="store_true", help="only build previews, groups and report (no AI)")
    ap.add_argument("--write-xmp", action="store_true")
    ap.add_argument("--overwrite-ratings", action="store_true")
    args = ap.parse_args()
    global SECONDS_BETWEEN_CALLS
    try:
        llm.configure(args.provider, args.base_url)
    except ValueError as e:
        sys.exit(str(e))
    if not args.model:
        args.model = llm.default_model()
    if not args.model and not args.prepare_only:
        sys.exit("צריך לציין מודל (--model) עבור הספק שבחרת. אפשר לראות רשימה בפקודה: "
                 f"python ai_rate.py models <תיקייה> --provider {args.provider}")
    SECONDS_BETWEEN_CALLS = args.delay if args.delay is not None else llm.default_delay()
    cap = llm.max_images()
    if args.max_group > cap:
        print(f"הספק {llm.info()['label']} מקבל עד {cap} תמונות בבקשה, אז מקטין את גודל הקבוצה ל-{cap}.")
        args.max_group = cap
    second = checker_config(args, "second") if not args.prepare_only else None
    judge = checker_config(args, "judge") if second else None
    for cfg in (second, judge):
        if cfg:
            with llm.using(cfg["provider"], cfg["base"]):
                other = llm.max_images()
                label = llm.info()["label"]
            if args.max_group > other:
                print(f"הספק {label} מקבל עד {other} תמונות בבקשה, אז מקטין את גודל הקבוצה ל-{other} כדי שיתאים לכל המודלים.")
                args.max_group = other
    if not args.candidates:
        args.candidates = 12
    if args.candidates > cap:
        args.candidates = cap

    # ---- which files
    catalog_times = {}
    if args.catalog:
        if not args.catalog.is_file():
            sys.exit(f"הקטלוג לא נמצא: {args.catalog}")
        catalog_times = catalog_files(args.catalog, args.since, args.until,
                                      args.folder_contains, args.collection, args.include_other)
        files = sorted(catalog_times, key=lambda p: p.name.lower())
        if args.include_other and not args.keep_pairs:
            files = drop_jpeg_of_raw_pairs(files)
        missing = [p for p in files if not p.exists()]
        files = [p for p in files if p.exists()]
        print(f"בקטלוג נמצאו {len(files)} " + ("קבצי תמונה" if args.include_other else "קבצי RAW") + (f", ו-{len(missing)} קבצים חסרים בדיסק" if missing else ""))
        out = args.out or Path(f"rating_{args.catalog.stem}")
        title = f"Rating: {args.catalog.stem}"
    else:
        if not args.source or not args.source.is_dir():
            sys.exit("צריך לציין תיקיית תמונות, או להשתמש ב---catalog.")
        files = find_raws(args.source, args.recursive, args.include_other, args.keep_pairs)
        out = args.out or (args.source / "_rating")
        title = f"Rating: {args.source.name}"
    if not files:
        sys.exit("לא נמצאו קבצי תמונה." if args.include_other else "לא נמצאו קבצי RAW.")
    out = out.resolve()
    (out / "groups").mkdir(parents=True, exist_ok=True)
    if args.include_other:
        n_other = sum(1 for p in files if p.suffix.lower() in OTHER_EXT)
        print(f"נמצאו {len(files)} קבצי תמונה, מהם {n_other} שאינם RAW. התוצאות יישמרו ב: {out}")
        if not HEIC_OK and any(p.suffix.lower() in (".heic", ".heif") for p in files):
            print("יש קבצי HEIC, אבל הרכיב pillow-heif לא מותקן ולכן הם ידולגו. להתקנה:  pip install pillow-heif")
    else:
        print(f"נמצאו {len(files)} קבצי RAW. התוצאות יישמרו ב: {out}")

    # ---- previews + grouping
    index_file = out / "index.json"
    index = read_json(index_file, {})
    build_index(files, out, catalog_times, index, PREVIEW_SIZE)
    rejected = []
    if not args.no_prefilter:
        ensure_metrics(files, out, index)
    atomic_write(index_file, json.dumps(index))
    if not args.no_prefilter:
        keep = []
        for p in files:
            rec = index.get(str(p))
            why = reject_reason(rec, args.prefilter_blur) if rec else None
            if why:
                rejected.append({"name": p.name, "path": str(p), "preview": rec["preview"], "reason": why,
                                 **{k: rec["q"].get(k, "") for k in ("sharp", "mean", "p99")}})
            else:
                keep.append(p)
        if rejected:
            counts = {}
            for r in rejected:
                counts[r["reason"]] = counts.get(r["reason"], 0) + 1
            detail = ", ".join(f"{n} {why}" for why, n in counts.items())
            print(f"דילגתי מראש על {len(rejected)} תמונות שנראות כטעות ברורה ({detail}). "
                  "הן לא נשלחות לדירוג, והרשימה בקובץ rejected.csv ובדוח.")
            with open(out / "rejected.csv", "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=["name", "reason", "sharp", "mean", "p99", "path", "preview"])
                w.writeheader()
                w.writerows(rejected)
        files = keep
        if not files:
            sys.exit("כל התמונות נפסלו בסינון המקדים. אם זה לא נראה לך, הרץ עם ביטול הסינון המקדים.")
    if not args.highlights:
        args.highlights = min(args.candidates, max(3, round(len(files) * 0.04)))
    limits_file = out / "image_limits.json"
    limits = read_json(limits_file, {})
    lk = f"{args.provider}|{args.model}"
    if limits.get(lk) and args.max_group > limits[lk]:
        print(f"ידוע לי שהמודל {args.model} מקבל עד {limits[lk]} תמונות בבקשה, אז הקבוצות יהיו קטנות יותר.")
        args.max_group = limits[lk]
        args.candidates = min(args.candidates, limits[lk])
    taste = load_taste(args)
    units = make_units(files, index, args.gap, args.similarity, args.max_group, taste_salt(taste), args.far_gap)
    n_sim = sum(1 for u in units if u["kind"] == "similar")
    print(f"חולקו ל-{len(units)} קבוצות ({n_sim} של צילומים דומים, {len(units) - n_sim} של תמונות בודדות)")

    # ---- AI
    dir_b = checker_dir(out, "b", second) if second else None
    dir_c = checker_dir(out, "c", judge) if judge else None

    def current_results():
        """The ratings so far: the first model's, or with a double check the merged ratings of all the models."""
        first = load_results(out, units)
        if not second:
            return first
        b = load_dir(dir_b, units)
        c = load_judge(dir_c, judge_jobs(units, first, b, args.dispute_gap)) if judge else {}
        return ensemble.combine(units, first, b, c, args.dispute_gap)

    results = current_results()
    if not args.prepare_only:
        key = args.key or llm.env_key()
        if not key and llm.info()["key_required"]:
            env = (llm.info()["env"] or ["AI_API_KEY"])[0]
            sys.exit(f"חסר מפתח API עבור {llm.info()['label']}. כתוב:  set {env}=המפתח_שלך   "
                     "(או השתמש ב---prepare-only)")
        asked = False
        while True:
            todo = [u for u in units if not (out / "groups" / f"{u['key']}.json").exists()]
            if args.limit:
                todo = todo[:args.limit]
            print(f"{len(todo)} קבוצות לדירוג עכשיו. מודל: {args.model}")
            if not asked:
                asked = True
                extra = []
                if second:
                    n_b = sum(1 for u in units if not (dir_b / f"{u['key']}.json").exists()
                              and ((out / "groups" / f"{u['key']}.json").exists() or u in todo))
                    with llm.using(second["provider"], second["base"]):
                        d_b = llm.default_delay()
                    extra.append({"provider": second["provider"], "base": second["base"], "model": second["model"],
                                  "n": n_b, "delay": d_b, "what": "בדיקה כפולה, המודל השני"})
                    if judge:
                        with llm.using(judge["provider"], judge["base"]):
                            d_c = llm.default_delay()
                        extra.append({"provider": judge["provider"], "base": judge["base"], "model": judge["model"],
                                      "n": max(1, -(-n_b * 15 // 100)), "delay": d_c, "what": "המכריע במחלוקות",
                                      "rough": True})
                if not llm.confirm_work(len(todo) + 1, args.model, SECONDS_BETWEEN_CALLS, extra or None):
                    return
            try:
                for n, u in enumerate(todo, 1):
                    print(f"[{n}/{len(todo)}] קבוצה {u['id']} ({'דומות' if u['kind'] == 'similar' else 'בודדות'}, {len(u['items'])} תמונות)")
                    try:
                        res = rate_unit(u, out, taste, args.model, key)
                    except ValueError as e:
                        print(f"    לא הצלחתי לדרג את הקבוצה ({e}). אנסה שוב בהרצה הבאה")
                        continue
                    atomic_write(out / "groups" / f"{u['key']}.json", json.dumps(res, ensure_ascii=False))
                    time.sleep(SECONDS_BETWEEN_CALLS)

                if second:
                    ok = run_second_model(units, out, second, dir_b, taste)
                    if ok and judge:
                        first, b = load_results(out, units), load_dir(dir_b, units)
                        run_judge(units, out, judge, dir_c, taste, first, b, args.dispute_gap, args.judge_sees_scores)
                    elif ok:
                        print("לא נבחר מכריע, ולכן במחלוקת הציון הסופי הוא הממוצע, והקבוצות שבהן המודלים חלוקים יסומנו.")

                results = current_results()
                all_rated = all((out / "groups" / f"{u['key']}.json").exists() for u in units)
                cands = pick_candidates(units, results, args.candidates)
                if all_rated and len(cands) >= 3:
                    hkey = hashlib.sha1((PROMPT_VERSION + lang_salt() + taste_salt(taste) + "|".join(c["name"] for c in cands)).encode()).hexdigest()[:10]
                    hfile = out / "groups" / f"highlights_{hkey}.json"
                    if read_json(hfile) is None:
                        print(f"שלב הבולטות: משווה את {len(cands)} המועמדות החזקות ביותר")
                        hres = rate_highlights(cands, out, taste, args.highlight_model or args.model, key)
                        atomic_write(hfile, json.dumps(hres, ensure_ascii=False))
                    for name, rec in read_json(hfile, {}).items():
                        if name in results:
                            results[name].update(rec)
                elif not all_rated:
                    print("את הבולטות אבחר רק אחרי שכל הקבוצות ידורגו. אפשר להריץ שוב.")
                break
            except llm.TooManyImages as e:
                if e.limit < 2 or (e.limit >= args.max_group and e.limit >= args.candidates):
                    explain_api_error(e)
                    results = current_results()
                    break
                print(f"\nהמודל {args.model} מקבל רק עד {e.limit} תמונות בבקשה. "
                      f"מקטין את גודל הקבוצות ל-{e.limit} וממשיך.")
                limits[lk] = e.limit
                atomic_write(limits_file, json.dumps(limits))
                args.max_group = min(args.max_group, e.limit)
                args.candidates = min(args.candidates, e.limit)
                units = make_units(files, index, args.gap, args.similarity, args.max_group, taste_salt(taste), args.far_gap)
                results = {}
                continue
            except ApiError as e:
                explain_api_error(e)
                results = current_results()
                break

    # ---- reports
    dc_text = None
    if second:
        two, hot, judged, undecided = ensemble.summary(results)
        dc_text = tr("בדיקה כפולה") + ": " + tr("{0} תמונות דורגו בשני מודלים, {1} במחלוקת, {2} הוכרעו על ידי מכריע, {3} לא הוכרעו.").replace(
            "{0}", str(two)).replace("{1}", str(hot)).replace("{2}", str(judged)).replace("{3}", str(undecided))
        print("\n" + dc_text)
    write_csv_report(out, units, results, None)
    write_html_report(out, units, results, title, rejected, dc_text)
    rated = sum(1 for r in results.values() if r.get("overall") is not None)
    gems = sum(1 for r in results.values() if r.get("gem"))
    print(f"\nדורגו {rated} מתוך {sum(len(u['items']) for u in units)} תמונות. פגזים: {gems}")
    print(f"הדוח (לפתוח בדפדפן): {out / 'report.html'}")
    print(f"גיליון לאקסל:     {out / 'ratings.csv'}")

    # ---- XMP
    if args.write_xmp:
        plan = plan_stars(units, results, args.highlights)
        done, not_raw = {}, 0
        for p, stars in plan.items():
            if Path(p).suffix.lower() not in RAW_EXT:      # Lightroom reads no sidecar for JPEG; a shared name would also clash
                not_raw += 1
                continue
            msg = write_xmp_rating(p, stars, args.overwrite_ratings)
            done[msg] = done.get(msg, 0) + 1
        print(f"\nכוכבים בקובצי XMP: {done or 'אין מה לכתוב'}")
        if not_raw:
            print(f"{not_raw} קבצים שאינם RAW לא קיבלו כוכבים, כי ליטרום לא קורא להם קובץ נלווה. אפשר לדרג אותם ידנית לפי הדוח.")
        print("בליטרום: סמן את התמונות -> Metadata -> Read Metadata from Files.")


if __name__ == "__main__":
    main()
