"""
Automatic tests for the tools. Run from the project folder:   python -m unittest discover tests -v
No internet, no API key and no Tk window are needed.
"""
import csv
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import agreement          # noqa: E402
import bidi_text          # noqa: E402
import dupes              # noqa: E402
import i18n               # noqa: E402
import llm_providers as llm   # noqa: E402
import ensemble          # noqa: E402
import rate_raw           # noqa: E402
import results_view       # noqa: E402


def textured(seed, size=(1600, 1200)):
    r = np.random.default_rng(seed)
    return Image.fromarray((r.random((12, 16, 3)) * 255).astype("uint8")).resize(size, Image.BICUBIC)


def save_jpeg(im, path, stamp=None, quality=92):
    ex = Image.Exif()
    if stamp:
        ifd = ex.get_ifd(0x8769)
        ifd[36867] = stamp
    im.save(path, "JPEG", quality=quality, exif=ex)


class ProvidersFile(unittest.TestCase):
    def test_json_matches_builtin_table(self):
        data = json.loads((ROOT / "providers.json").read_text(encoding="utf-8"))["providers"]
        self.assertEqual(set(data), set(llm.PROVIDERS))
        for name, fields in data.items():
            for key, value in fields.items():
                self.assertEqual(llm.PROVIDERS[name].get(key), value, f"{name}.{key}")


class Duplicates(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def groups(self):
        files = dupes.find_files(self.d, True)
        found = dupes.find_duplicates(files, True, log=lambda *_: None)
        return sorted(sorted(files[i].name for i in g["files"]) for g in found)

    def test_exact_resized_and_burst(self):
        a = textured(1)
        save_jpeg(a, self.d / "orig.jpg", "2026:10:01 12:00:00")
        shutil.copy(self.d / "orig.jpg", self.d / "copy.jpg")
        save_jpeg(a.resize((800, 600)), self.d / "small.jpg", "2026:10:01 12:00:00", 70)
        save_jpeg(a, self.d / "burst.jpg", "2026:10:01 12:00:01")     # same pixels, another moment
        save_jpeg(textured(2), self.d / "other.jpg", "2026:10:01 12:05:00")
        self.assertEqual(self.groups(), [["copy.jpg", "orig.jpg", "small.jpg"]])

    def test_chat_app_copy_without_exif(self):
        """A copy sent through a chat app: smaller, heavily compressed, no capture time."""
        a = textured(1, (4000, 3000))
        save_jpeg(a, self.d / "orig.jpg", "2026:10:01 12:00:00")
        save_jpeg(a.resize((1600, 1200)), self.d / "chat.jpg", None, 45)
        save_jpeg(textured(3, (4000, 3000)), self.d / "other.jpg", "2026:10:01 12:00:05")
        self.assertEqual(self.groups(), [["chat.jpg", "orig.jpg"]])

    def test_chat_copy_joins_only_its_best_match(self):
        """Two burst frames that look alike, and a timeless copy of the first: the copy must not link the frames."""
        a = textured(1)
        b = a.copy()
        ImageDraw.Draw(b).rectangle((700, 500, 760, 560), fill=(255, 255, 255))   # a tiny change in frame 2
        save_jpeg(a, self.d / "frame1.jpg", "2026:10:01 12:00:00")
        save_jpeg(b, self.d / "frame2.jpg", "2026:10:01 12:00:01")
        save_jpeg(a.resize((800, 600)), self.d / "chat.jpg", None, 50)
        got = self.groups()
        self.assertEqual(len(got), 1)
        self.assertNotIn("frame2.jpg", got[0])

    def test_raw_files_only_exact(self):
        (self.d / "a.CR3").write_bytes(b"abc" * 4000)
        (self.d / "b.CR3").write_bytes(b"abc" * 4000)
        (self.d / "c.CR3").write_bytes(b"abd" * 4000)
        self.assertEqual(self.groups(), [["a.CR3", "b.CR3"]])


class PreFilter(unittest.TestCase):
    def test_reasons(self):
        d = Path(tempfile.mkdtemp())
        try:
            (d / "previews").mkdir()
            r = np.random.default_rng(3)
            sharp = Image.fromarray((r.random((853, 1280, 3)) * 255).astype("uint8"))
            sil = Image.new("RGB", (1280, 853), (10, 10, 12))
            ImageDraw.Draw(sil).ellipse((500, 300, 700, 500), fill=(255, 230, 200))
            cases = {"sharp": sharp, "dark": Image.new("RGB", (1280, 853), (8, 8, 10)),
                     "white": Image.new("RGB", (1280, 853), (250, 250, 248)),
                     "blur": sharp.filter(ImageFilter.GaussianBlur(30)), "silhouette": sil}
            files, index = [], {}
            for name, im in cases.items():
                im.save(d / "previews" / f"{name}.jpg")
                p = Path(f"/x/{name}.CR3")
                files.append(p)
                index[str(p)] = {"preview": f"previews/{name}.jpg"}
            rate_raw.ensure_metrics(files, d, index)
            why = {p.stem: rate_raw.reject_reason(index[str(p)]) for p in files}
            self.assertIsNone(why["sharp"])
            self.assertIsNone(why["silhouette"])          # a bright spot in the dark is not a mistake
            self.assertEqual(why["dark"], "חשוכה מאוד")
            self.assertEqual(why["white"], "חשופה יתר על המידה")
            self.assertEqual(why["blur"], "מטושטשת מאוד")
        finally:
            shutil.rmtree(d, ignore_errors=True)


class Bidi(unittest.TestCase):
    def test_wrapping_only_hebrew_lines(self):
        t = bidi_text.rtl_text("שלום world\nplain line")
        first, second = t.split("\n")
        self.assertTrue(first.startswith(bidi_text.RLE) and first.endswith(bidi_text.PDF))
        self.assertEqual(second, "plain line")

    def test_strip_is_inverse(self):
        s = "מתחילים: rate_raw --catalog C:\\x"
        self.assertEqual(bidi_text.strip(bidi_text.rtl_text(s)), s)


class Results(unittest.TestCase):
    def test_load_raw_and_archive(self):
        d = Path(tempfile.mkdtemp())
        try:
            raw = d / "raw"
            (raw / "previews").mkdir(parents=True)
            Image.new("RGB", (100, 80)).save(raw / "previews" / "p.jpg")
            (raw / "index.json").write_text(json.dumps({"/p/a.CR3": {"preview": "previews/p.jpg"}}))
            with open(raw / "ratings.csv", "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=["file", "group", "rank_in_group", "overall", "composition",
                                                  "angle", "light", "flags", "note", "gem",
                                                  "highlight_reason", "path"])
                w.writeheader()
                w.writerow({"file": "a.CR3", "group": 1, "rank_in_group": 1, "overall": 8, "gem": "yes",
                            "path": "/p/a.CR3"})
            kind, items = results_view.load_results(raw)
            self.assertEqual((kind, len(items), items[0]["gem"], items[0]["score"]), ("raw", 1, True, 8.0))
            self.assertTrue(items[0]["image"].exists())
            self.assertEqual(results_view.load_results(d)[0], None)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_sort_and_filter(self):
        items = [{"name": "a", "score": 5, "gem": False, "group": "1"},
                 {"name": "b", "score": 9, "gem": False, "group": "1"},
                 {"name": "c", "score": 7, "gem": True, "group": "2"}]
        self.assertEqual([i["name"] for i in results_view.sort_items(items, "score")], ["c", "b", "a"])
        self.assertEqual([i["name"] for i in results_view.sort_items(items, "score", 6)], ["c", "b"])
        self.assertEqual([i["name"] for i in results_view.sort_items(items, "name", 0, True)], ["c"])


class OtherFormatsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _jpeg(self, name, size=(400, 300), exif=False):
        im = Image.new("RGB", size, (120, 140, 160))
        ImageDraw.Draw(im).rectangle((50, 50, 200, 200), fill=(250, 250, 250))
        kw = {}
        if exif:
            ex = Image.Exif()
            ex[0x010F] = "SecretCam"
            ex[0x8825] = {1: "N", 2: (32.0, 5.0, 0.0), 3: "E", 4: (34.0, 47.0, 0.0)}     # GPS block
            kw["exif"] = ex
        im.save(self.tmp / name, quality=90, **kw)

    def test_raw_only_by_default_and_pair_rule(self):
        for n in ("a.CR3", "b.CR3"):
            (self.tmp / n).write_bytes(b"x")
        self._jpeg("a.JPG")           # next to a RAW with the same name
        self._jpeg("c.jpg")           # on its own
        names = lambda **kw: [p.name for p in rate_raw.find_raws(self.tmp, False, **kw)]
        self.assertEqual(names(), ["a.CR3", "b.CR3"])
        self.assertEqual(names(include_other=True), ["a.CR3", "b.CR3", "c.jpg"])
        self.assertEqual(names(include_other=True, keep_pairs=True), ["a.CR3", "a.JPG", "b.CR3", "c.jpg"])

    def test_jpeg_goes_through_the_pipeline_without_location_data(self):
        self._jpeg("x.jpg", exif=True)
        files = rate_raw.find_raws(self.tmp, False, include_other=True)
        out = self.tmp / "out"
        index = {}
        rate_raw.build_index(files, out, {}, index, 800)
        rec = index[str(files[0])]
        with Image.open(out / rec["preview"]) as preview:
            self.assertEqual(dict(preview.getexif()), {})             # nothing from the original EXIF is kept
        self.assertNotIn(b"SecretCam", (out / rec["preview"]).read_bytes())


class QuotaEstimateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.old = llm.USAGE_FILE
        llm.USAGE_FILE = self.tmp / "usage.json"
        self.addCleanup(setattr, llm, "USAGE_FILE", self.old)
        llm.configure("gemini")

    def _say(self, n):
        import contextlib
        import io as _io
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            llm.confirm_work(n, "m", 0)
        return buf.getvalue()

    def test_unknown_limit_says_nothing_about_quota(self):
        for _ in range(5):
            llm.record_request("m")
        self.assertNotIn("המכסה היומית נגמרה", self._say(10))

    def test_learns_the_limit_and_warns(self):
        for _ in range(20):
            llm.record_request("m")
        llm.record_daily_limit("m")               # the provider refused after 20 requests
        used, limit, left = llm.quota_estimate("m")
        self.assertEqual((used, limit, left), (20, 20, 0))
        self.assertIn("סביר שתיעצר באמצע", self._say(5))

    def test_local_servers_are_not_tracked(self):
        llm.configure("ollama")
        llm.record_request("m")
        self.assertFalse(llm.USAGE_FILE.exists())


class AgreementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _make(self, ai, mine):
        """ai: {name: (score, group, rank)}; mine: {name: (stars, pick)} - a results folder and a tiny catalog."""
        base_dir = Path(tempfile.mkdtemp(dir=self.tmp))
        res = base_dir / "res"
        res.mkdir()
        with open(res / "ratings.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["file", "group", "group_type", "rank_in_group", "overall", "highlight_rank", "gem", "path"])
            for name, (score, group, rank) in ai.items():
                w.writerow([name, group, "similar", rank, score, "", "", f"C:\\Photos\\{name}"])
        con = sqlite3.connect(base_dir / "c.lrcat")
        con.executescript("""
            CREATE TABLE Adobe_images(id_local INTEGER, rootFile INTEGER, rating REAL, pick REAL);
            CREATE TABLE AgLibraryFile(id_local INTEGER, folder INTEGER, baseName TEXT, extension TEXT);
            CREATE TABLE AgLibraryFolder(id_local INTEGER, rootFolder INTEGER, pathFromRoot TEXT);
            CREATE TABLE AgLibraryRootFolder(id_local INTEGER, absolutePath TEXT);
            INSERT INTO AgLibraryRootFolder VALUES (1, 'C:/Photos/');
            INSERT INTO AgLibraryFolder VALUES (1, 1, '');""")
        for n, (name, (stars, pick)) in enumerate(mine.items(), 1):
            base, ext = name.rsplit(".", 1)
            con.execute("INSERT INTO AgLibraryFile VALUES (?,1,?,?)", (n, base, ext))
            con.execute("INSERT INTO Adobe_images VALUES (?,?,?,?)", (n, n, stars, pick))
        con.commit()
        con.close()
        return res, base_dir / "c.lrcat"

    def _run(self, ai, mine):
        res, cat = self._make(ai, mine)
        rows, skipped, index = agreement.read_ratings(res)
        return agreement.compare(rows, skipped, agreement.catalog_choices(cat), 3)

    def test_perfect_and_reversed(self):
        names = [f"p{i}.CR3" for i in range(10)]
        ai = {n: (90 - i * 8, 1 + i // 5, 1 + i % 5) for i, n in enumerate(names)}
        good = {n: ((4, 0) if i < 4 else (0, 0)) for i, n in enumerate(names)}
        bad = {n: ((0, 0) if i < 6 else (4, 0)) for i, n in enumerate(names)}
        self.assertEqual(self._run(ai, good)["auc"], 1.0)
        self.assertEqual(self._run(ai, bad)["auc"], 0.0)
        r = self._run(ai, good)
        self.assertEqual((r["n"], r["n_kept"], r["topk_hits"]), (10, 4, 4))

    def test_pick_flag_counts_and_unmatched_are_reported(self):
        ai = {"a.CR3": (80, 1, 1), "b.CR3": (40, 1, 2), "z.CR3": (60, 2, 1)}
        mine = {"a.CR3": (0, 1), "b.CR3": (1, 0)}       # a has a Pick flag, z is not in the catalog
        r = self._run(ai, mine)
        self.assertEqual((r["n"], r["n_kept"], r["unmatched"]), (2, 1, 1))

    def test_ranks_with_ties_and_spearman(self):
        self.assertEqual(agreement.ranks([5, 5, 1]), [2.5, 2.5, 1.0])
        self.assertAlmostEqual(agreement.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(agreement.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)
        self.assertIsNone(agreement.spearman([1, 1, 1], [1, 2, 3]))

    def test_reports_are_written(self):
        names = [f"p{i}.CR3" for i in range(6)]
        ai = {n: (90 - i * 10, 1, 1 + i) for i, n in enumerate(names)}
        mine = {n: ((5, 0) if i < 2 else (0, 0)) for i, n in enumerate(names)}
        res_dir, cat = self._make(ai, mine)
        rows, skipped, index = agreement.read_ratings(res_dir)
        res = agreement.compare(rows, skipped, agreement.catalog_choices(cat), 3)
        out = self.tmp / "out"
        agreement.write_reports(out, res, index, res_dir, 3)
        self.assertTrue((out / "report.html").is_file() and (out / "agreement.csv").is_file())


class GuideTests(unittest.TestCase):
    """The guides in the different languages must stay in step with the Hebrew one."""

    @staticmethod
    def _shape(path):
        from html.parser import HTMLParser

        class P(HTMLParser):
            def __init__(self):
                super().__init__()
                self.seq = []

            def handle_starttag(self, tag, attrs):
                self.seq.append((tag, dict(attrs).get("class")))

            def handle_endtag(self, tag):
                self.seq.append("/" + tag)
        p = P()
        p.feed(Path(path).read_text(encoding="utf-8"))
        return p.seq

    def test_english_guide_has_the_same_structure(self):
        he = self._shape(ROOT / "photo_tools_guide.html")
        en = self._shape(ROOT / "lang" / "guide_en.html")
        self.assertEqual(he, en)

    def test_parser_leaves_out_command_line_parts(self):
        try:
            import help_view
        except ImportError:
            self.skipTest("tkinter is not available")
        chapters, rtl = help_view.parse_guide(
            '<html dir="rtl"><h2>1. A</h2><p>text</p><div class="cli"><h2>2. B</h2><p>hidden</p></div>'
            '<h2>3. C</h2><ul><li>x</li></ul></html>')
        self.assertTrue(rtl)
        self.assertEqual([t for t, _ in chapters], ["1. A", "3. C"])
        self.assertNotIn("hidden", str(chapters))


class I18nTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_lang("he")

    def test_hebrew_is_untouched(self):
        i18n.set_lang("he")
        self.assertEqual(i18n.tr("קבוצות"), "קבוצות")

    def test_exact_template_and_nested(self):
        i18n.set_lang("en")
        self.assertEqual(i18n.tr("קבוצות"), "Groups")
        self.assertEqual(i18n.tr("קבוצה 3 · 5 תמונות דומות"), "Group 3 · 5 similar photos")
        self.assertEqual(i18n.tr("\nקבוצות\n"), "\nGroups\n")

    def test_layout_mirroring(self):
        i18n.set_lang("en")
        self.assertFalse(i18n.rtl())
        self.assertEqual(i18n.X("left"), "right")
        self.assertEqual(i18n.col(0), 2)
        i18n.set_lang("he")
        self.assertTrue(i18n.rtl())
        self.assertEqual(i18n.col(0), 0)

    def test_placeholders_match(self):
        data = json.loads((ROOT / "lang" / "en.json").read_text(encoding="utf-8"))["strings"]
        slot = lambda t: sorted(re.findall(r"\{[^{}]*\}", t))
        bad = [k for k, v in data.items() if slot(k) != slot(v)]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()


class RestartAndScrollTests(unittest.TestCase):
    def test_restart_command_is_independent_of_the_old_exe(self):
        """A copy started from a one-file EXE must not share the old copy's temporary folder."""
        import os
        import photo_tools_gui as g
        os.environ["_PYI_APPLICATION_HOME_DIR"] = "x"
        os.environ["_MEIPASS2"] = "y"
        old = getattr(sys, "frozen", None)
        sys.frozen = True
        try:
            args, kw = g.restart_command()
        finally:
            if old is None:
                del sys.frozen
            else:
                sys.frozen = old
            os.environ.pop("_PYI_APPLICATION_HOME_DIR", None)
            os.environ.pop("_MEIPASS2", None)
        self.assertEqual(kw["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")
        self.assertNotIn("_MEIPASS2", kw["env"])
        self.assertFalse(any(k.startswith("_PYI_") for k in kw["env"]))


class EnsembleLogicTests(unittest.TestCase):
    def _unit(self, kind, names):
        return {"id": 1, "kind": kind, "key": "k", "items": [{"name": n} for n in names]}

    def rec(self, overall, rank=None):
        return {"overall": overall, "composition": overall, "angle": overall, "light": overall, "rank": rank,
                "flags": [], "note": ""}

    def test_agreement_is_averaged_and_not_a_dispute(self):
        u = self._unit("singles", ["x"])
        out = ensemble.combine([u], {"x": self.rec(8)}, {"x": self.rec(7)}, {}, gap=2)
        self.assertEqual(out["x"]["overall"], 7.5)
        self.assertFalse(out["x"]["disputed"])
        self.assertEqual(ensemble.find_disputes([u], {"x": self.rec(8)}, {"x": self.rec(7)}, 2), [])

    def test_big_gap_goes_to_the_judge_and_the_median_decides(self):
        u = self._unit("singles", ["x", "y"])
        a, b = {"x": self.rec(8), "y": self.rec(6)}, {"x": self.rec(3), "y": self.rec(6)}
        disputes = ensemble.find_disputes([u], a, b, 2)
        self.assertEqual([(d[0]["id"], d[1]) for d in disputes], [(1, ["x"])])      # only the disputed photo
        out = ensemble.combine([u], a, b, {"x": self.rec(6)}, 2)
        self.assertEqual(out["x"]["overall"], 6)
        self.assertEqual(out["x"]["decided"], "judge")
        self.assertEqual(out["y"]["decided"], "average")

    def test_without_a_judge_the_average_stands_and_the_dispute_is_marked(self):
        u = self._unit("singles", ["x"])
        out = ensemble.combine([u], {"x": self.rec(8)}, {"x": self.rec(3)}, {}, 2)
        self.assertEqual(out["x"]["overall"], 5.5)
        self.assertTrue(out["x"]["disputed"])

    def test_best_of_a_group_is_decided_by_two_of_three(self):
        u = self._unit("similar", ["p", "q", "r"])
        a = {"p": self.rec(8, 1), "q": self.rec(7, 2), "r": self.rec(6, 3)}
        b = {"p": self.rec(6, 3), "q": self.rec(8, 1), "r": self.rec(7, 2)}
        c = {"p": self.rec(7, 2), "q": self.rec(9, 1), "r": self.rec(6, 3)}
        self.assertEqual(len(ensemble.find_disputes([u], a, b, 5)), 1)              # different best shot, even with a high gap
        out = ensemble.combine([u], a, b, c, 5)
        self.assertEqual(out["q"]["rank"], 1)
        self.assertEqual(sorted(r["rank"] for r in out.values()), [1, 2, 3])

    def test_three_different_choices_stay_undecided(self):
        u = self._unit("similar", ["p", "q", "r"])
        a = {"p": self.rec(8, 1), "q": self.rec(7, 2), "r": self.rec(6, 3)}
        b = {"p": self.rec(6, 3), "q": self.rec(8, 1), "r": self.rec(7, 2)}
        c = {"p": self.rec(6, 3), "q": self.rec(7, 2), "r": self.rec(9, 1)}
        out = ensemble.combine([u], a, b, c, 5)
        self.assertTrue(all(r["decided"] == "undecided" for r in out.values()))

    def test_a_photo_only_one_model_rated_keeps_its_score(self):
        u = self._unit("singles", ["x"])
        out = ensemble.combine([u], {"x": self.rec(8)}, {}, {}, 2)
        self.assertEqual(out["x"]["overall"], 8)
        self.assertEqual(out["x"]["decided"], "single")


class EnsembleRunTests(unittest.TestCase):
    """The whole run with a pretend provider: nothing is sent anywhere."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.photos = self.tmp / "photos"
        self.photos.mkdir()
        base = 1_700_000_000
        for name, shift, when in (("a_lone.jpg", 0, base), ("b1.jpg", 0, base + 7200),
                                  ("b2.jpg", 6, base + 7203), ("b3.jpg", 12, base + 7206)):
            im = Image.new("RGB", (400, 300), (90, 110, 130))
            ImageDraw.Draw(im).rectangle((50 + shift, 50, 200 + shift, 200), fill=(240, 240, 240))
            im.save(self.photos / name, quality=90)
            os.utime(self.photos / name, (when, when))
        self.calls = []
        self.old_call, self.old_usage = llm.call, llm.USAGE_FILE
        llm.USAGE_FILE = self.tmp / "usage.json"
        llm.call = self.fake_call
        self.addCleanup(setattr, llm, "call", self.old_call)
        self.addCleanup(setattr, llm, "USAGE_FILE", self.old_usage)

    def fake_call(self, model, key, parts, retries=5):
        text = " ".join(p.get("text", "") for p in parts)
        n = sum(1 for p in parts if "inline_data" in p)
        similar = "one after another" in text
        self.calls.append((model, n, similar, "earlier reviewers" in text))
        if not similar:                                       # the lone photo
            score = {"m1": 8, "m2": 3, "m3": 6}[model]
            rows = [{"n": 1, "overall": score, "composition": score, "angle": score, "light": score,
                     "rank": 1, "flags": [], "note": model}]
        else:                                                 # three similar shots: who is the best?
            import base64
            import io as _io2
            best = {"m1": 1, "m2": 2, "m3": 2}[model]
            order = [best] + [i for i in (1, 2, 3) if i != best]
            rows = []
            # the photos are shown in a shuffled order: tell them apart by where the white square starts
            for pos, part in enumerate((p for p in parts if "inline_data" in p), 1):
                im = Image.open(_io2.BytesIO(base64.b64decode(part["inline_data"]["data"]))).convert("L")
                left = next(x for x in range(im.width) if im.getpixel((x, im.height // 2)) > 200)
                orig = 1 + round(left / (im.width / 400) / 6 - 50 / 6)          # shift 0, 6, 12 -> 1, 2, 3
                rows.append({"n": pos, "overall": 9 - order.index(orig), "composition": 7, "angle": 7, "light": 7,
                             "rank": order.index(orig) + 1, "flags": [], "note": model})
        return json.dumps(rows)

    def run_tool(self, *extra):
        import contextlib
        import io as _io
        out = self.tmp / "out"
        argv = ["rate_raw", str(self.photos), "--include-other", "--no-prefilter", "--provider", "ollama",
                "--base-url", "http://localhost:1/v1", "--model", "m1", "--out", str(out)] + list(extra)
        old = sys.argv
        sys.argv = argv
        buf = _io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rate_raw.main()
        finally:
            sys.argv = old
        with open(out / "ratings.csv", encoding="utf-8-sig", newline="") as f:
            rows = {r["file"]: r for r in csv.DictReader(f)}
        return rows, buf.getvalue(), out

    def test_one_model_is_unchanged(self):
        rows, _log, _out = self.run_tool()
        self.assertEqual({c[0] for c in self.calls}, {"m1"})
        self.assertEqual(rows["a_lone.jpg"]["overall"], "8.0")
        self.assertEqual(rows["a_lone.jpg"]["decided_by"], "")

    def test_double_check_with_a_judge(self):
        rows, log, out = self.run_tool("--second-model", "m2", "--judge-model", "m3")
        lone = rows["a_lone.jpg"]
        self.assertEqual(lone["overall"], "6.0")                                   # median of 8, 3 and 6
        self.assertEqual((lone["score_model_1"], lone["score_model_2"], lone["score_judge"]), ("8.0", "3.0", "6.0"))
        self.assertEqual((lone["disputed"], lone["decided_by"]), ("yes", "judge"))
        self.assertEqual(rows["b2.jpg"]["rank_in_group"], "1")                      # two of three chose b2
        self.assertEqual(rows["b1.jpg"]["rank_in_group"], "2")
        self.assertIn("m3", {c[0] for c in self.calls})
        self.assertFalse(any(c[3] for c in self.calls))                              # the judge rated blind
        report = (out / "report.html").read_text(encoding="utf-8")
        self.assertIn('class="ens"', report)

    def test_a_second_run_asks_nothing_again(self):
        self.run_tool("--second-model", "m2", "--judge-model", "m3")
        before = len(self.calls)
        rows, _log, _out = self.run_tool("--second-model", "m2", "--judge-model", "m3")
        self.assertEqual(len(self.calls), before)
        self.assertEqual(rows["a_lone.jpg"]["decided_by"], "judge")

    def test_the_judge_can_be_shown_the_earlier_scores(self):
        self.run_tool("--second-model", "m2", "--judge-model", "m3", "--judge-sees-scores")
        self.assertTrue(any(c[0] == "m3" and c[3] for c in self.calls))

    def test_no_judge_marks_the_dispute_and_averages(self):
        rows, _log, _out = self.run_tool("--second-model", "m2")
        self.assertEqual(rows["a_lone.jpg"]["overall"], "5.5")
        self.assertEqual(rows["a_lone.jpg"]["decided_by"], "average")
        self.assertEqual(rows["a_lone.jpg"]["disputed"], "yes")


class GroupingTests(unittest.TestCase):
    def test_exposure_change_stays_together_and_scenes_split(self):
        import numpy as np
        from datetime import datetime, timedelta
        import rate_raw
        from PIL import Image
        def scene(seed):
            g = np.random.default_rng(seed).random((6, 6))
            return np.asarray(Image.fromarray((g * 255).astype("uint8")).resize((24, 24), Image.BILINEAR), dtype=np.float32)
        def sig(a):
            return (a - a.mean()).round(1).flatten().tolist()
        a = scene(1)
        shots = [("a1", a), ("a2", a * 0.6 + 30), ("b1", scene(2)), ("c1", scene(3)), ("d1", scene(4))]
        idx, files = {}, []
        for i, (n, arr) in enumerate(shots):
            f = Path(n); files.append(f)
            idx[str(f)] = {"time": (datetime(2026, 1, 1) + timedelta(seconds=i * 5)).isoformat(), "sig": sig(arr), "preview": "x"}
        units = rate_raw.make_units(files, idx, 120, 0.30, 8)
        sim = [[i["name"] for i in u["items"]] for u in units if u["kind"] == "similar"]
        self.assertEqual(sim, [["a1", "a2"]])


class FarGroupingTests(unittest.TestCase):
    def test_scene_returned_to_is_joined_only_within_the_time_window(self):
        import numpy as np
        from datetime import datetime, timedelta
        import rate_raw
        from PIL import Image
        def scene(seed):
            g = np.random.default_rng(seed).random((6, 6))
            return np.asarray(Image.fromarray((g * 255).astype("uint8")).resize((24, 24), Image.BILINEAR), dtype=np.float32)
        def sig(a):
            return (a - a.mean()).round(1).flatten().tolist()
        a = scene(1)
        shots = [("a1", a, 0), ("b1", scene(2), 20), ("c1", scene(3), 40), ("a2", a * 0.9 + 5, 60), ("d1", scene(4), 5000), ("a3", a, 9000)]
        idx, files = {}, []
        for n, arr, sec in shots:
            f = Path(n); files.append(f)
            idx[str(f)] = {"time": (datetime(2026, 1, 1) + timedelta(seconds=sec)).isoformat(), "sig": sig(arr), "preview": "x"}
        def sim(far):
            return [[i["name"] for i in u["items"]] for u in rate_raw.make_units(files, idx, 120, 0.30, 8, "", far) if u["kind"] == "similar"]
        self.assertEqual(sim(0), [])
        self.assertEqual(sim(1800), [["a1", "a2"]])          # a3 is more than half an hour away
        self.assertEqual(sim(20000), [["a1", "a2", "a3"]])
        self.assertEqual(sorted(sum(sim(1800), [])), ["a1", "a2"])


class BrandTests(unittest.TestCase):
    def test_brand_is_isolated_in_hebrew_lines(self):
        import bidi_text
        out = bidi_text.rtl_text("ברוך הבא ל-FocalPick.")
        self.assertIn(bidi_text.LRE + "FocalPick" + bidi_text.PDF, out)
        self.assertEqual(bidi_text.strip(out), "ברוך הבא ל-FocalPick.")
        self.assertEqual(bidi_text.rtl_text("FocalPick 1.0"), "FocalPick 1.0")


class GenreTests(unittest.TestCase):
    def test_genre_changes_group_keys_and_all_genres_have_text(self):
        import numpy as np
        from datetime import datetime
        import rate_raw
        f = Path("a.jpg")
        idx = {str(f): {"time": datetime(2026, 1, 1).isoformat(), "sig": [0.0] * 576, "preview": "x"}}
        k0 = rate_raw.make_units([f], idx, 120, 0.3, 8)[0]["key"]
        k1 = rate_raw.make_units([f], idx, 120, 0.3, 8, "street")[0]["key"]
        self.assertNotEqual(k0, k1)
        self.assertEqual(k0, rate_raw.make_units([f], idx, 120, 0.3, 8, "")[0]["key"])
        self.assertTrue(all(len(v) > 50 for v in rate_raw.GENRES.values()))


class PromptTests(unittest.TestCase):
    def test_object_reply_is_parsed(self):
        reply = 'Sure:\n```json\n{"differences": "eyes [closed] in 2", "photos": [{"n": 1, "overall": 6, "flags": []}, {"n": 2, "overall": 4, "flags": ["eyes_closed"]}]}\n```'
        rows = rate_raw.parse_json_list(reply)
        self.assertEqual([r["n"] for r in rows], [1, 2])

    def test_notes_are_requested_in_the_program_language(self):
        import i18n
        seen = []
        old = llm.call
        llm.call = lambda model, key, parts, retries=5: (seen.append(parts[0]["text"]) or '[{"n": 1, "overall": 5, "rank": 1}]')
        try:
            tmp = Path(tempfile.mkdtemp())
            self.addCleanup(shutil.rmtree, tmp, True)
            (tmp / "p.jpg").write_bytes(b"x")
            unit = {"kind": "singles", "key": "k", "items": [{"name": "p.jpg", "preview": "p.jpg"}]}
            for code, name in (("he", "Hebrew"), ("en", "English")):
                i18n.set_lang(code)
                rate_raw.rate_unit(unit, tmp, "", "m", "k")
                rate_raw.rate_highlights([{"name": "p.jpg", "preview": "p.jpg"}], tmp, "", "m", "k")
                self.assertIn(f"in {name}", seen[-2])
                self.assertIn(f"in {name}", seen[-1])
                self.assertNotIn("{LANGUAGE}", seen[-2] + seen[-1])
        finally:
            llm.call = old
            i18n.set_lang("he")

    def test_each_reviewer_sees_a_different_order_but_the_same_every_time(self):
        a = rate_raw.shown_order(8, "k" + "a")
        self.assertEqual(a, rate_raw.shown_order(8, "k" + "a"))
        self.assertNotEqual(a, rate_raw.shown_order(8, "k" + "b"))
        self.assertEqual(sorted(a), list(range(8)))


class TasteKeyTests(unittest.TestCase):
    def test_changed_taste_changes_the_key(self):
        from datetime import datetime
        f = Path("a.jpg")
        idx = {str(f): {"time": datetime(2026, 1, 1).isoformat(), "sig": [0.0] * 576, "preview": "x"}}
        k = lambda taste: rate_raw.make_units([f], idx, 120, 0.3, 8, rate_raw.taste_salt(taste))[0]["key"]
        self.assertEqual(k("a"), k("a"))
        self.assertNotEqual(k("a"), k("b"))
        self.assertNotEqual(k(""), k("a"))


class VisualBidiTests(unittest.TestCase):
    def vis(self, text):
        import bidi_visual
        return bidi_visual.to_visual(text)[0].replace(bidi_visual.LRM, "")

    def test_visual_order_matches_the_standard_algorithm(self):
        self.assertEqual(self.vis("שלום עולם"), "םלוע םולש")
        self.assertEqual(self.vis("נמצאו 117 תמונות"), "תונומת 117 ואצמנ")
        self.assertEqual(self.vis("קורא את IMG_2289.CR3 עכשיו"), "וישכע IMG_2289.CR3 תא ארוק")
        self.assertEqual(self.vis("הרצה (14 קבוצות)."), ".(תוצובק 14) הצרה")      # brackets are mirrored
        self.assertEqual(self.vis("שלום (hello) עולם"), "םלוע (hello) םולש")
        self.assertEqual(self.vis("English only"), "English only")

    def test_every_hebrew_letter_is_followed_by_a_left_to_right_mark(self):
        import bidi_visual
        out, mp = bidi_visual.to_visual("אבג 5")
        self.assertEqual(out.count(bidi_visual.LRM), 3)
        self.assertEqual(len(out), len(mp))
        self.assertEqual(sorted(m for m in mp if m is not None), [0, 1, 2, 3, 4])

    def test_wrapping_keeps_every_word_and_fits_the_width(self):
        import bidi_visual
        text = "זו שורה ארוכה מאוד של טקסט בעברית עם IMG_2289.CR3 ומספרים 12345 שצריכה להישבר לכמה שורות"
        measure = lambda s: 10 * len(s.replace(bidi_visual.LRM, ""))
        pieces = bidi_visual.wrap_visual(text, 200, measure)
        self.assertGreater(len(pieces), 2)
        self.assertTrue(all(measure(v) <= 200 for v, _, _, _ in pieces))
        joined = " ".join(text[a:b] for _, _, a, b in pieces)
        self.assertEqual(joined.split(), text.split())


class RtlLogTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        self.addCleanup(self.root.destroy)
        import log_view
        self.text = tk.Text(self.root, width=60, height=10, wrap="char")
        self.text.pack()
        self.root.update()
        self.log = log_view.RtlLog(self.text)

    def test_open_line_grows_and_text_is_logical(self):
        self.log.append("שלום ")
        self.log.append("עולם\nשורה שנייה")
        self.log.append(" נמשכת\n")
        self.assertEqual(self.log.text(), "שלום עולם\nשורה שנייה נמשכת")
        self.assertEqual(self.text.get("1.0", "end-1c").count("\n"), 2)

    def test_partial_selection_copies_the_real_text(self):
        self.log.append("שלום עולם יפה\n")
        vis = self.text.get("1.0", "1.end")
        self.text.tag_add("sel", "1.0", "1.end")
        self.assertEqual(self.log.selection(), "שלום עולם יפה")
        self.text.tag_remove("sel", "1.0", "end")
        start = vis.index("ם")                      # somewhere in the middle of the drawn line
        self.text.tag_add("sel", f"1.{start}", f"1.{start + 8}")
        got = self.log.selection()
        self.assertTrue(got and set(got) <= set("שלום עולם יפה "))
        self.assertNotIn("\u200e", got)


class ResultsWindowTests(unittest.TestCase):
    def test_window_draws_cells_loads_only_visible_thumbnails_and_opens_detail(self):
        import tkinter as tk
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        self.addCleanup(root.destroy)
        import results_view
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "previews").mkdir()
        idx, rows = {}, []
        for i in range(60):
            Image.new("RGB", (200, 150), (i * 4, 90, 120)).save(tmp / "previews" / f"p{i}.jpg")
            idx[f"/x/{i}.CR3"] = {"preview": f"previews/p{i}.jpg"}
            rows.append({"file": f"{i}.CR3", "path": f"/x/{i}.CR3", "overall": str(3 + i % 6), "gem": "",
                         "composition": "7", "angle": "6", "light": "7", "flags": "", "note": "הערה קצרה", "group": "1"})
        (tmp / "index.json").write_text(json.dumps(idx), encoding="utf-8")
        with open(tmp / "ratings.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        theme = {"bg": "#fff", "surface": "#fff", "fg": "#000", "muted": "#888", "accent": "#c80"}
        win = results_view.ResultsWindow(root, tmp, theme, lambda t: t, lambda p: None, 1.0)
        root.update()
        win.refresh()
        for _ in range(30):
            root.update()
        self.assertEqual(len(win.shown), 60)
        self.assertTrue(0 < len(win.img_items) < 60)                 # only what is in view is loaded
        self.assertEqual(win.shown[0]["note"], "הערה קצרה")
        win.detail(2)
        for _ in range(10):
            root.update()
        self.assertTrue(win.dw.winfo_exists())
        self.assertIn("note", win.shown[0])
