"""Job titles -> standard occupations, using a compact copy of the O*NET(R) 31.0 Database.

Used by setup (suggest related titles and skills you might not think to search) and by ranking
(which occupation a posting is, for government pay estimates when it doesn't post pay).

This module includes information from the O*NET 31.0 Database by the U.S. Department of Labor,
Employment and Training Administration (USDOL/ETA). Used under the CC BY 4.0 license. O*NET(R) is
a trademark of USDOL/ETA. job-hunter has modified all or some of this information (kept a subset
of fields; see scripts/build_occupations.py). USDOL/ETA has not approved, endorsed, or tested these
modifications.
"""
from __future__ import annotations

import functools
import gzip
import json
from collections import defaultdict
from pathlib import Path

from .common import norm, title_similarity

DATA = Path(__file__).resolve().parent / "data" / "occupations.json.gz"
MATCH_THRESHOLD = 0.72
ATTRIBUTION = ("Occupation data: O*NET 31.0 Database, USDOL/ETA, CC BY 4.0 (modified). "
               "O*NET is a trademark of USDOL/ETA.")

# Words that say how senior a job is, not what the job is. Dropped before matching so
# "Senior Credit Analyst II" finds "Credit Analysts".
_NOISE = {"senior", "sr", "junior", "jr", "lead", "principal", "i", "ii", "iii", "iv", "v", "remote",
          "hybrid", "contract", "temporary", "temp", "part", "time", "full", "the", "of", "and", "a", "an", "to",
          "for", "in", "at", "us", "level", "entry", "experienced", "associate"}


@functools.lru_cache(maxsize=1)
def _load():
    with gzip.open(DATA, "rt", encoding="utf-8") as fh:
        d = json.load(fh)
    index = defaultdict(set)  # word -> titles containing it
    for t in d["titles"]:
        for w in set(t.split()) - _NOISE:
            index[w].add(t)
    return d["occupations"], d["titles"], index


def _clean(title):
    return " ".join(w for w in norm(title).split() if w not in _NOISE)


@functools.lru_cache(maxsize=20000)
def match(title):
    """Best occupation for a job title: dict(code, title, score, via, ambiguous) or None when
    nothing is close. Exact matches on O*NET's ~45,000 known titles score 1.0. `ambiguous` means
    the title is used in more than one occupation ('Analyst', 'Underwriter')."""
    occ, titles, index = _load()
    full, t = norm(title), _clean(title)
    if not t:
        return None
    for key in dict.fromkeys((full, t, t.rstrip("s"), t + "s")):
        if key in titles:
            codes = titles[key]
            if len(codes) > 1 and len(key.split()) == 1:
                return None  # 'analyst' alone could be a dozen occupations
            return {"code": codes[0], "title": occ[codes[0]]["t"], "score": 1.0, "via": key,
                    "ambiguous": len(codes) > 1}
    words = set(t.split())
    # candidates share at least one word; rank them by how many they share, then score the best
    counts: dict[str, int] = defaultdict(int)
    for w in words:
        for cand in index.get(w, ()):
            counts[cand] += 1
        if w.endswith("s"):
            for cand in index.get(w[:-1], ()):
                counts[cand] += 1
    if not counts:
        return None
    best, best_sim = None, 0.0
    mine = words | {w.rstrip("s") for w in words}
    for cand, _ in sorted(counts.items(), key=lambda kv: (-kv[1], len(kv[0])))[:400]:
        cw = set(cand.split()) - _NOISE
        sim = title_similarity(t, cand)
        # Every word of the known title should be in yours ('Credit Analyst' for 'Credit Analyst',
        # not 'Analyst'), and it should cover most of yours: a lone 'Chief' says nothing about
        # 'Chief of Staff'. A wrong occupation is worse than none (it drives pay estimates).
        if not cw <= mine:
            sim *= 0.85
        coverage = len({w.rstrip("s") for w in cw} & {w.rstrip("s") for w in words}) / max(1, len(words))
        sim *= 0.6 + 0.4 * coverage
        if sim > best_sim:
            best, best_sim = cand, sim
    if best is None or best_sim < MATCH_THRESHOLD:
        return None
    codes = titles[best]
    return {"code": codes[0], "title": occ[codes[0]]["t"], "score": round(best_sim, 3), "via": best,
            "ambiguous": len(codes) > 1}


def info(code):
    occ, _, _ = _load()
    o = occ.get(code)
    if not o:
        return None
    return {"code": code, "title": o["t"], "job_zone": o.get("z"), "related": o.get("r", []),
            "software": o.get("s", []), "knowledge": o.get("k", [])}


def soc6(code):
    """'13-2041.00' -> '132041' (the 6-digit SOC code government wage data uses)."""
    return str(code).split(".")[0].replace("-", "")


# Software and knowledge areas nearly every office job lists; not worth suggesting as skills.
_GENERIC_SKILLS = {"microsoft office software", "microsoft outlook", "microsoft word", "microsoft powerpoint",
                   "microsoft windows", "google docs", "english language", "mathematics", "administrative",
                   "customer and personal service", "email software", "web browser software"}


def suggestions(titles, limit_titles=12, limit_skills=15):
    """For the titles someone wants: their occupations, job titles from related occupations to
    consider, and skills (software and knowledge areas) that postings in those occupations ask for."""
    occ, _, _ = _load()
    matched, related_codes = [], []
    for t in titles:
        m = match(t)
        if not m:
            continue
        matched.append({"query": t, **m})
        related_codes += [c for c in occ[m["code"]].get("r", []) if c not in related_codes]
    mine = {m["code"] for m in matched}
    have = {norm(t) for t in titles}
    related = []
    for code in related_codes:
        if code in mine:
            continue
        for example in occ[code].get("e", [])[:2]:
            if norm(example) not in have and len(example.split()) > 1:  # 'Analyst' alone is too vague
                have.add(norm(example))
                related.append({"title": example, "occupation": occ[code]["t"], "code": code})
        if len(related) >= limit_titles:
            break
    skills = []
    for m in matched:
        o = occ[m["code"]]
        for s in o.get("s", []) + o.get("k", []):
            if s not in skills and s.lower() not in _GENERIC_SKILLS:
                skills.append(s)
    return {"matched": matched, "related_titles": related[:limit_titles], "skills": skills[:limit_skills],
            "unmatched": [t for t in titles if not any(m["query"] == t for m in matched)],
            "attribution": ATTRIBUTION}


def search(text, limit=10):
    """Occupations whose name or known job titles share the most words with `text` (to pick one by hand)."""
    occ, titles, index = _load()
    words = set(_clean(text).split())
    if not words:
        return []
    stems = {w.rstrip("s") for w in words}
    score: dict[str, float] = defaultdict(float)
    for code, o in occ.items():
        name = {w.rstrip("s") for w in norm(o["t"]).split()}
        if name & stems:
            score[code] = max(score[code], 1.5 * len(name & stems))
    for w in words:
        for t in index.get(w, ()):
            overlap = len({x.rstrip("s") for x in t.split()} & stems)
            for code in titles[t]:
                score[code] = max(score[code], overlap)
    ranked = sorted(score.items(), key=lambda kv: (-kv[1], occ[kv[0]]["t"]))[:limit]
    return [{"code": c, "title": occ[c]["t"], "examples": occ[c].get("e", [])[:4]} for c, _ in ranked]
