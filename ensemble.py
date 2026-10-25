# © 2026 נתאי שנדורפי (Nitay Sandorffy). MIT License.
"""
Double check: two AI models rate the same photos, and a third model settles the disagreements.

Pure logic, no network: it only merges the ratings the models gave. rate_raw.py does the asking.

  a, b   {photo name: rating} from the first and the second model (a rating is the dict rate_unit returns)
  c      {photo name: rating} from the judge, only for the photos or groups that were in dispute

A photo is in dispute when the two overall scores differ by `gap` or more. In a group of similar shots, the
group is in dispute when the two models chose a different best shot, or when any photo is in dispute.
"""
__author__ = "נתאי שנדורפי"
__copyright__ = "© 2026 נתאי שנדורפי. MIT License."
from collections import Counter

SCORE_KEYS = ("composition", "angle", "light")
DEFAULT_GAP = 2.0


def _median(vals):
    v = sorted(vals)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def _overall(rec):
    return None if not rec else rec.get("overall")


def _top(unit, res):
    """Name of the photo a model put first in a group of similar shots, or None."""
    for it in unit["items"]:
        r = res.get(it["name"])
        if r and r.get("rank") == 1:
            return it["name"]
    return None


def photo_in_dispute(ra, rb, gap):
    oa, ob = _overall(ra), _overall(rb)
    return oa is not None and ob is not None and abs(oa - ob) >= gap


def find_disputes(units, a, b, gap=DEFAULT_GAP):
    """What the judge should look at: a list of (unit, [photo names]).

    A group of similar shots goes to the judge whole, so it can pick the best of them. In a group of unrelated
    photos only the disputed photos go."""
    out = []
    for u in units:
        names = [i["name"] for i in u["items"]]
        if not any(n in a and n in b for n in names):
            continue
        hot = [n for n in names if photo_in_dispute(a.get(n), b.get(n), gap)]
        if u["kind"] == "similar":
            ta, tb = _top(u, a), _top(u, b)
            if hot or (ta and tb and ta != tb):
                out.append((u, [n for n in names if n in a or n in b]))
        elif hot:
            out.append((u, hot))
    return out


def combine(units, a, b, c=None, gap=DEFAULT_GAP):
    """Merge the ratings into one result set shaped like a single model's, plus the extra fields:

    score_a, score_b, score_c  what each model gave
    disputed                   the two models differed by `gap` or more on this photo
    decided                    "average" | "judge" | "undecided" | "single" (only one model rated it)
    """
    c = c or {}
    res = {}
    for u in units:
        names = [i["name"] for i in u["items"]]
        # ---- scores of each photo
        for n in names:
            ra, rb, rc = a.get(n), b.get(n), c.get(n)
            if not ra and not rb:
                continue
            base = dict(ra or rb)
            if ra and rb:
                oa, ob, oc = _overall(ra), _overall(rb), _overall(rc)
                disputed = photo_in_dispute(ra, rb, gap)
                vals = [v for v in (oa, ob) if v is not None]
                if disputed and oc is not None:
                    final, decided = _median([oa, ob, oc]), "judge"
                elif vals:
                    final, decided = sum(vals) / len(vals), "average"
                else:
                    final, decided = None, "single"
                base["overall"] = final
                for k in SCORE_KEYS:
                    got = [r[k] for r in (ra, rb) if r.get(k)]
                    base[k] = sum(got) / len(got) if got else None
                base["flags"] = sorted(set(ra.get("flags", [])) | set(rb.get("flags", [])))
                base["note_b"] = rb.get("note", "")
                base.update(score_a=oa, score_b=ob, score_c=oc, disputed=disputed, decided=decided)
            else:
                only = ra or rb
                base.update(score_a=_overall(ra), score_b=_overall(rb), score_c=None, disputed=False,
                            decided="single")
                base["overall"] = only.get("overall")
            base.update(unit=u["id"], kind=u["kind"])
            res[n] = base
        # ---- who is the best of a group of similar shots
        if u["kind"] != "similar":
            continue
        rated = [n for n in names if n in res]
        if not rated:
            continue
        votes = [t for t in (_top(u, a), _top(u, b), _top(u, c)) if t]
        winner, undecided = None, False
        if votes:
            top, cnt = Counter(votes).most_common(1)[0]
            if len(set(votes)) == 1 or cnt >= 2:
                winner = top
            else:
                undecided = True                      # every model chose a different photo

        def mean_rank(n):
            ranks = [r["rank"] for r in (a.get(n), b.get(n), c.get(n)) if r and r.get("rank")]
            return sum(ranks) / len(ranks) if ranks else 99

        order = sorted(rated, key=lambda n: (mean_rank(n), -(res[n].get("overall") or 0)))
        if winner in order:
            order.remove(winner)
            order.insert(0, winner)
        for pos, n in enumerate(order, 1):
            res[n]["rank"] = pos
            if undecided:
                res[n]["decided"] = "undecided"
                res[n]["group_disputed"] = True
            elif len(set(votes)) > 1:
                res[n]["group_disputed"] = True
                if res[n].get("decided") == "average":
                    res[n]["decided"] = "judge" if _top(u, c) else "average"
    return res


def summary(res):
    """Numbers for the report and the log: (rated by two models, in dispute, settled by the judge, undecided)."""
    two = [r for r in res.values() if r.get("score_a") is not None and r.get("score_b") is not None]
    disputed = [r for r in two if r.get("disputed")]
    judged = [r for r in disputed if r.get("decided") == "judge"]
    undecided = [r for r in res.values() if r.get("decided") == "undecided"]
    return len(two), len(disputed), len(judged), len(undecided)
