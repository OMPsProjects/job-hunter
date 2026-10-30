"""`job-hunter setup`: a short questionnaire that builds profile.yaml, candidate.yaml and the
start of companies.yaml, for any kind of job.

Run it in a terminal and answer the questions, or pass `--from answers.yaml` with the same keys
(that's how the Claude skill runs it after asking you in chat). Press Enter to skip a question
or keep the [default].
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import yaml

from .candidate import LEVELS, draft_candidate, read_resume_text
from .common import US_STATE_CODES
from .fileio import write_text_atomic

# Common US metros: the city people type -> the places a posting in that metro may name.
METROS = {
    "washington": ("dc", "washington,? dc|district of columbia|, dc\\b|arlington|alexandria|mclean|reston|tysons|"
                         "herndon|fairfax|falls church|bethesda|silver spring|rockville|gaithersburg|chevy chase"),
    "new york": ("nyc", "new york|manhattan|brooklyn|queens|bronx|jersey city|hoboken|newark|stamford|white plains|, ny\\b"),
    "los angeles": ("la", "los angeles|santa monica|culver city|el segundo|beverly hills|pasadena|burbank|glendale|"
                          "long beach|torrance|irvine|newport beach|costa mesa|santa ana|anaheim|century city"),
    "san francisco": ("sf", "san francisco|oakland|berkeley|emeryville|san mateo|redwood city|palo alto|menlo park|"
                            "mountain view|sunnyvale|san jose|santa clara|south san francisco"),
    "chicago": ("chi", "chicago|evanston|oak brook|naperville|schaumburg|rosemont|deerfield|northbrook"),
    "boston": ("bos", "boston|cambridge|somerville|waltham|newton|quincy|burlington, ma|needham"),
    "atlanta": ("atl", "atlanta|alpharetta|buckhead|sandy springs|marietta|duluth, ga|norcross"),
    "dallas": ("dal", "dallas|fort worth|plano|irving|frisco|addison|las colinas|richardson|arlington, tx"),
    "houston": ("hou", "houston|the woodlands|sugar land|katy"),
    "austin": ("aus", "austin|round rock|cedar park"),
    "miami": ("mia", "miami|fort lauderdale|boca raton|coral gables|west palm|doral"),
    "seattle": ("sea", "seattle|bellevue|redmond|kirkland|tacoma"),
    "denver": ("den", "denver|boulder|aurora, co|englewood, co|broomfield|lakewood, co"),
    "philadelphia": ("phl", "philadelphia|king of prussia|conshohocken|wayne, pa|camden|wilmington, de"),
    "phoenix": ("phx", "phoenix|scottsdale|tempe|mesa, az|chandler"),
    "charlotte": ("clt", "charlotte|fort mill"),
    "minneapolis": ("msp", "minneapolis|st\\.? paul|bloomington, mn|eden prairie"),
    "san diego": ("sd", "san diego|la jolla|carlsbad"),
    "nashville": ("bna", "nashville|franklin, tn|brentwood, tn"),
    "baltimore": ("bal", "baltimore|towson|columbia, md|owings mills"),
    "raleigh": ("rdu", "raleigh|durham|chapel hill|research triangle|cary, nc|morrisville"),
    "pittsburgh": ("pit", "pittsburgh"),
    "detroit": ("dtw", "detroit|troy, mi|southfield|ann arbor|dearborn"),
    "salt lake city": ("slc", "salt lake|lehi|draper|provo"),
    "portland": ("pdx", "portland, or|beaverton|hillsboro|lake oswego"),
    "tampa": ("tpa", "tampa|st\\.? petersburg|clearwater"),
    "orlando": ("orl", "orlando|lake mary|winter park"),
    "st. louis": ("stl", "st\\.? louis|clayton, mo"),
    "kansas city": ("mci", "kansas city|overland park|leawood"),
    "columbus": ("cmh", "columbus, oh|dublin, oh|westerville"),
    "toronto": ("yyz", "toronto|mississauga|markham|vaughan"),
    "london": ("lon", "london"),
}

QUESTIONS = [
    # key, prompt, kind, default
    ("resume", "Path to your resume (PDF, DOCX, TXT), or Enter to skip", "path", ""),
    ("field", "What kind of work do you want? Describe the field or industry\n"
              "  (e.g. 'commercial real estate lending', 'hospital nursing', 'B2B software sales')", "text", ""),
    ("titles", "Job titles you'd apply to tomorrow (comma-separated)", "list", ""),
    ("adjacent_titles", "Other titles you'd consider, same skills, different seat (comma-separated, optional)", "list", ""),
    ("pivot_titles", "Career-change titles, if any (comma-separated, optional)", "list", ""),
    ("levels", "Levels you want, from: " + ", ".join(LEVELS) + " (comma-separated)", "levels", ""),
    ("years_experience", "Years of experience in this field", "number", ""),
    ("skills", "Your main skills, worded as a job posting would (comma-separated)", "list", ""),
    ("locations", "Cities you'd work in, best first, separated by ';' (e.g. 'Chicago, IL; New York, NY')", "cities", ""),
    ("remote", "Open to remote jobs? (y/n)", "bool", "y"),
    ("remote_only", "Only remote jobs, none in an office? (y/n)", "bool", "n"),
    ("linkedin", "Also search LinkedIn? Its terms forbid automated searching and it may limit your account (y/n)",
     "bool", "n"),
    ("remote_like_top_city", "Should remote jobs rank as high as your first city? (y/n)", "bool", "y"),
    ("pay_floor", "Lowest base pay you'd consider, per year (e.g. 85k, or Enter to skip)", "money", ""),
    ("pay_target", "Pay you're aiming for, per year (e.g. 110k, or Enter to skip)", "money", ""),
    ("require_pay", "Hide jobs that don't list pay? Most people keep them (y/n)", "bool", "n"),
    ("avoid_companies", "Companies to never show (e.g. your current employer; comma-separated)", "list", ""),
    ("avoid_keywords", "Words that rule a job out, like a kind of role you won't do (comma-separated)", "list", ""),
    ("target_companies", "Companies you'd like to work for; their career sites get searched every run (comma-separated)", "list", ""),
    ("discover_companies", "After the first search, find more companies that hire for these roles? (y/n)", "bool", "y"),
]


def _split(text, sep=","):
    return [x.strip() for x in str(text or "").replace("\n", sep).split(sep) if x.strip()]


LEVEL_SYNONYMS = {
    "internship": "intern", "entry-level": "entry", "entry level": "entry", "junior": "entry", "jr": "entry",
    "associate": "mid", "mid-level": "mid", "mid level": "mid", "intermediate": "mid", "experienced": "mid",
    "senior-level": "senior", "senior level": "senior", "sr": "senior", "staff": "senior", "principal": "senior",
    "lead": "manager", "team lead": "manager", "supervisor": "manager", "head": "director",
    "vice president": "vp", "svp": "vp", "evp": "vp", "managing director": "vp", "c-level": "executive",
    "chief": "executive", "exec": "executive",
}
_US_STATES = US_STATE_CODES


def parse_money(raw):
    """Pay as a yearly number from free text: '120k', '$120,000', '55-65k' (low end), '1.5m',
    '€90.000', '$45/hr' (x2080). Returns None when it can't tell."""
    t = str(raw or "").lower().replace("\u00a0", " ").strip()
    if not t or t in ("n/a", "na", "none", "-", "skip"):
        return None
    hourly = bool(re.search(r"/\s*h(ou)?r|per hour|hourly|an hour", t))
    m = re.search(r"(\d{1,3}(?:[.,]\d{3})+|\d+(?:\.\d+)?)\s*([km]|mm)?", t)
    if not m:
        return None
    num = m.group(1)
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", num):  # thousands separators, either style
        value = float(re.sub(r"[.,]", "", num))
    else:
        value = float(num)
    suffix = m.group(2)
    if not suffix:  # '55-65k': the k on the second number applies to both
        later = re.search(r"\d\s*([km])\b", t[m.end():])
        suffix = later.group(1) if later and re.match(r"\s*(-|to|–)", t[m.end():]) else None
    value *= {"k": 1e3, "m": 1e6, "mm": 1e6}.get(suffix or "", 1)
    if hourly:
        value *= 2080
    return value


def _parse(kind, raw, default, say=None):
    raw = default if raw in (None, "") else raw
    if kind == "list":
        items = raw if isinstance(raw, list) else _split(raw)
        return [str(x).strip() for x in items if str(x).strip()]
    if kind == "cities":
        if isinstance(raw, list):  # 'Washington, DC,' -> 'Washington, DC'
            return [str(c).strip().strip(",;").strip() for c in raw if str(c).strip().strip(",;").strip()]
        parts = _split(raw, ";")
        # someone typed "Chicago, IL, New York, NY": re-pair city/state
        if len(parts) == 1 and re.search(r",\s*[A-Z]{2}\s*,", parts[0]):
            parts = [m.strip() for m in re.findall(r"[^,]+,\s*[A-Z]{2}", parts[0])]
        return parts
    if kind == "levels":
        items = raw if isinstance(raw, list) else _split(raw)
        out = []
        for x in items:
            k = str(x).strip().lower()
            k = LEVEL_SYNONYMS.get(k, k)
            if k in LEVELS:
                out.append(k)
            elif say:
                say(f"  (ignored level {x!r}: use {', '.join(LEVELS)})")
        return list(dict.fromkeys(out))
    if kind == "bool":
        if isinstance(raw, bool):
            return raw
        t = str(raw).strip().lower()
        if t.startswith(("y", "true", "sure", "ok")) or t == "1":
            return True
        if t.startswith(("n", "false")) or t in ("0", ""):
            return False
        if say:
            say(f"  (couldn't read {raw!r} as yes/no; treated as no)")
        return False
    if kind == "money":
        v = parse_money(raw)
        if v is not None and not 1000 <= v <= 2_000_000:
            if say:
                say(f"  (ignored pay {raw!r}: read it as {v:,.0f}, which doesn't look like a yearly amount)")
            return None
        return v
    if kind == "number":
        m = re.search(r"\d+(?:\.\d+)?", str(raw or ""))
        return float(m.group(0)) if m else None
    return str(raw or "").strip()


def _numbered(raw, options):
    """'1, 3, Credit Officer' -> [options[0], options[2], 'Credit Officer']."""
    items = raw if isinstance(raw, list) else _split(raw)
    out = []
    for x in items:
        x = str(x).strip()
        if x.isdigit() and 1 <= int(x) <= len(options):
            out.append(options[int(x) - 1])
        elif x:
            out.append(x)
    return ", ".join(dict.fromkeys(out))


def _hints(key, out, say):
    """Before some questions, show suggestions from occupation data. Returns the numbered options."""
    from . import occupations
    if key not in ("adjacent_titles", "skills") or not out.get("titles"):
        return []
    sug = occupations.suggestions(out["titles"] + (out.get("adjacent_titles") or []))
    if key == "adjacent_titles":
        if sug["matched"]:
            say("  Your titles map to: " + "; ".join(f"{m['title']}" for m in sug["matched"]))
        options = [r["title"] for r in sug["related_titles"]]
        label = "Titles in related occupations"
    else:
        options = sug["skills"]
        label = "Skills postings in these occupations often ask for"
    if options:
        say(f"  {label} (type numbers to include them, plus any of your own):")
        say("    " + "  ".join(f"{i}) {o}" for i, o in enumerate(options, 1)))
        say(f"  ({occupations.ATTRIBUTION})")
    return options


def ask_all(answers_in: dict | None = None, ask=input, say=print):
    """Collect answers. Keys in answers_in are used as given; anything missing is asked (or, when
    `ask` is None, left at its default)."""
    answers_in = dict(answers_in or {})
    out = {}
    for key, prompt, kind, default in QUESTIONS:
        if key in answers_in:
            out[key] = _parse(kind, answers_in[key], default, say=say)
            continue
        if ask is None:
            out[key] = _parse(kind, "", default, say=say)
            continue
        options = _hints(key, out, say)
        while True:
            suffix = f" [{default}]" if default else ""
            raw = ask(f"\n{prompt}{suffix}\n> ").strip()
            if options:
                raw = _numbered(raw, options)
            val = _parse(kind, raw, default, say=say)
            if key == "titles" and not val:
                say("  At least one title is needed; that's what gets searched.")
                continue
            if key == "levels" and raw and not val:
                say(f"  Use words from: {', '.join(LEVELS)}")
                continue
            break
        out[key] = val
    if isinstance(answers_in.get("occupations"), dict):  # track -> occupation code, chosen in chat
        out["occupations"] = answers_in["occupations"]
    return out


# ----------------------------- building the files ----------------------------

CITY_ALIASES = {"washington dc": "washington", "washington d.c.": "washington", "dc": "washington",
                "nyc": "new york", "new york city": "new york", "manhattan": "new york", "la": "los angeles",
                "sf": "san francisco", "bay area": "san francisco", "silicon valley": "san francisco",
                "philly": "philadelphia", "dfw": "dallas", "atl": "atlanta", "chi": "chicago", "the twin cities": "minneapolis",
                "twin cities": "minneapolis", "st louis": "st. louis", "saint louis": "st. louis", "slc": "salt lake city"}


_LEVEL_ONLY = re.compile(r"^(?:senior |sr\.? |executive |assistant |associate )?(?:vice president|vp|svp|evp|avp|"
                         r"managing director|director|partner|principal)$", re.I)
_LEVEL_WORDS = re.compile(r"\b(?:senior|sr\.?|junior|jr\.?|lead|principal|i{1,3}|iv)\b", re.I)


def search_title(title: str) -> str:
    """A resume title as a job-board search: 'Vice President, Senior Commercial Loan
    Underwriter' -> 'Commercial Loan Underwriter'; 'Senior Underwriter, Multifamily' ->
    'Multifamily Underwriter'. Level words go (level is its own setting, and they narrow a search)."""
    from .resume_parse import _TITLE_WORDS
    title = re.sub(r"\s*\([^)]*\)?", " ", str(title or ""))  # '(Vice President)', '(concurrent)'
    # 'Director of Ops / Chief of Staff', 'Director of Operations – Affordable Housing'
    title = re.split(r"\s+/\s+|\s+&\s+(?=[A-Z])|\s+[–—-]\s+", title)[0]
    parts = [p.strip() for p in title.split(",") if p.strip()]
    parts = [p for p in parts if not _LEVEL_ONLY.match(p)] or parts
    core = next((p for p in parts if _TITLE_WORDS.search(_LEVEL_WORDS.sub("", p))), "")
    if not core:  # 'VP, Credit Risk': nothing but the level says what the job is; keep it whole
        return re.sub(r"\s+", " ", title).strip()
    extra = [p for p in parts if p != core and len(p.split()) <= 3 and not _TITLE_WORDS.search(p)]
    out = " ".join(extra[:1] + [core])
    bare = re.sub(r"\s+", " ", _LEVEL_WORDS.sub("", out)).strip(" -/&")
    # 'Senior Underwriter' stays as is: 'Underwriter' alone would bring in every kind of underwriter
    out = bare if len(bare.split()) >= 2 else re.sub(r"\s+", " ", out).strip()
    return out or str(title or "").strip()


_SIDE_ROLE = re.compile(r"\bconcurrent\b|\bowner\b|\bfounder\b|\bco-?founder\b|\bmanaging member\b|"
                        r"\bself-employed\b|\bfreelance\b|\bvolunteer\b|\bboard member\b", re.I)


def search_titles(titles, limit=3) -> list[str]:
    """Searches from resume titles, most recent first, leaving out side roles (owner, founder,
    'concurrent'), which aren't the jobs someone is applying for."""
    main = [t for t in titles if not _SIDE_ROLE.search(str(t))] or list(titles)
    return list(dict.fromkeys(t for t in (search_title(x) for x in main) if t))[:limit]


FIELDS = sorted([
    "Accounting", "Administrative and office support", "Architecture", "Banking", "Commercial real estate",
    "Commercial real estate lending", "Construction", "Consulting", "Customer service", "Cybersecurity",
    "Data and analytics", "Design", "Education", "Energy", "Engineering", "Finance", "Government",
    "Healthcare", "Hospitality", "Human resources", "Insurance", "Investment management", "Law",
    "Logistics and supply chain", "Manufacturing", "Marketing", "Media", "Mortgage lending", "Nonprofit",
    "Nursing", "Operations", "Pharmaceuticals", "Product management", "Project management", "Real estate",
    "Retail", "Sales", "Skilled trades", "Social work", "Software engineering", "Telecommunications",
    "Transportation"])


def us_cities() -> list[str]:
    """The 1,000 largest US cities as 'City, ST', biggest first (for the city picker)."""
    from importlib.resources import files
    text = (files("jobhunter") / "data" / "us_cities.txt").read_text(encoding="utf-8")
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]


def region_for(city: str):
    name = city.split(",")[0].strip().lower()
    words = name.split()
    if len(words) > 1 and words[-1].strip(".") in _US_STATES:  # "Chicago IL" -> "chicago"
        name = " ".join(words[:-1])
    name = CITY_ALIASES.get(name, name)
    if name in METROS:
        return METROS[name]
    key = re.sub(r"[^a-z]", "", name)[:6] or "city"
    return key, re.escape(name)


def track_occupations(tracks, given=None):
    """track -> occupation code (for pay estimates): as given, else the first title that matches
    a known job title exactly."""
    from . import occupations
    out = {}
    for track, titles in tracks.items():
        if isinstance(given, dict) and given.get(track):
            out[track] = str(given[track])
            continue
        for t in titles:
            m = occupations.match(t)
            if m and m["score"] >= 0.9:
                out[track] = m["code"]
                break
    return out


def build_profile(a: dict) -> dict:  # noqa: C901
    regions, seen = [], set()
    cities = []
    for city in a.get("locations") or []:
        if str(city).strip().lower() in ("remote", "anywhere", "remote us", "remote (us)"):
            a["remote"] = True  # remote is its own setting, not a city
        else:
            cities.append(city)
    if a.get("remote_only"):
        a["remote"], cities = True, []  # remote only: no cities to search or rank
    a["locations"] = cities
    for city in cities:
        key, pat = region_for(city)
        while key in seen:
            key += "2"
        seen.add(key)
        regions.append({"key": key, "pattern": pat})
    keys = [r["key"] for r in regions]
    order = list(keys)
    if a.get("remote"):
        order.insert(1 if a.get("remote_like_top_city") and keys else len(order), "remote")
    order += [k for k in ("remote", "unspecified") if k not in order]

    tracks = {"core": a["titles"]}
    if a.get("adjacent_titles"):
        tracks["adjacent"] = a["adjacent_titles"]
    if a.get("pivot_titles"):
        tracks["pivot"] = a["pivot_titles"]

    skills = a.get("skills") or []
    skill_w = {s.lower(): (5 if i < 10 else 3) for i, s in enumerate(skills)}
    levels = a.get("levels") or []
    negative = {"commission only": -25, "unpaid": -30}
    title_negative = {}
    if levels and "intern" not in levels:
        negative.update({"intern": -30, "internship": -30})
        title_negative["\\bsummer\\b"] = -30
    if levels and not set(levels) & {"intern", "entry"}:
        negative.update({"entry level": -20, "junior": -15})
    if levels and min(LEVELS.index(lv) for lv in levels) >= LEVELS.index("senior"):
        title_negative["\\b(junior|jr\\.?)\\b"] = -15

    prof: dict = {
        "output_dir": "results",
        "search": {"locations": a.get("locations") or [], "include_remote": bool(a.get("remote")),
                   **({"remote_only": True} if a.get("remote_only") else {}),
                   # two weeks: a first search over one week of postings is thin in most fields
                   "results_per_search": 25, "hours_old": 336,
                   "sites": ["indeed", "linkedin"] if a.get("linkedin") else ["indeed"], "pause_seconds": 2},
        "regions": regions,
        "region_order": order,
        "keep_unspecified_locations": True,
        "tracks": tracks,
        "scoring": {"skills": skill_w, "negative": negative, "title_negative": title_negative,
                    "required_terms": {"pivot": [[s.lower() for s in skills]]} if a.get("pivot_titles") and skills else {},
                    # a raw score of max_raw maps to 100; scale it to how many skills there are to match
                    "missing_required_penalty": -15, "max_raw": max(30, min(90, 6 * len(skills))), "min_score": 15},
        "ranking": {"weights": {"fit": 40, "seniority": 20, "location": 15, "pay": 15, "freshness": 10},
                    "pay_floor": a.get("pay_floor"), "pay_target": a.get("pay_target"),
                    "pay_floor_is_hard": bool(a.get("pay_floor")),
                    **({"require_posted_pay": True} if a.get("require_pay") else {}),
                    "remote_rank_as": keys[0] if keys and a.get("remote_like_top_city") else None,
                    "low_fit_threshold": 40},
        "filters": {"exclude_companies": a.get("avoid_companies") or [],
                    "exclude_keywords": [k.lower() for k in a.get("avoid_keywords") or []]},
        "verify": {"enabled": True, "top_n": 150},
        "llm": {"candidate_summary": f"Looking for {', '.join(a['titles'][:3])} roles in {a.get('field') or 'my field'}."},
        "review": {"shortlist_size": 10, "tailor_top_n": 5,
                   "hard_no": [f"roles at {c}" for c in a.get("avoid_companies") or []]
                   + [f"anything that is mainly {k}" for k in a.get("avoid_keywords") or []],
                   "resume_rules": ["write a new resume for each job from its description; it must not read as AI-written",
                                    "1 page if the posting asks for under 5 years of experience, otherwise 2 pages"]},
        "setup": {"field": a.get("field"), "discover_companies": bool(a.get("discover_companies")),
                  "created": dt.date.today().isoformat(), "occupations": track_occupations(tracks, a.get("occupations"))},
    }
    # drop empty values so the file stays readable
    prof["ranking"] = {k: v for k, v in prof["ranking"].items() if v not in (None, "")}
    return prof


PROFILE_HEADER = """# profile.yaml - what job-hunter searches for. Made by `job-hunter setup`; edit freely.
# Private: gitignored. Check it with `job-hunter check`. Every key is explained in
# profile.example.yaml. LinkedIn is off by default (search.sites); add it if you accept
# that LinkedIn's terms forbid automated access and it may limit your account.
"""


def build_candidate(a: dict, resume_text: str, resume_path):
    cand = draft_candidate(resume_text, resume_path) if resume_text else {
        "name": "", "contact": {}, "base_resume": "", "years_experience": None, "headline": "",
        "target_titles": [], "past_titles": [], "target_levels": [], "skills": {"core": [], "other": []},
        "industries": [], "summary": "", "facts_files": []}
    if resume_text:  # past titles and city from the resume, for ranking and the skill's tailoring
        from .resume_parse import parse_resume
        parsed = parse_resume(resume_text)
        cand["past_titles"] = parsed["titles"] or cand.get("past_titles", [])
        if parsed["city"]:
            cand.setdefault("contact", {})["city"] = parsed["city"]
    if a.get("years_experience"):
        cand["years_experience"] = a["years_experience"]
    cand["target_titles"] = list(dict.fromkeys(a["titles"] + (a.get("adjacent_titles") or [])))
    cand["target_levels"] = a.get("levels") or []
    if a.get("skills"):
        cand["skills"] = {"core": a["skills"][:15], "other": a["skills"][15:]}
    if a.get("field"):
        cand["industries"] = [a["field"]]
        cand["headline"] = cand.get("headline") or f"{a['titles'][0]} ({a['field']})"
    return cand


def _empty(v):
    return v in (None, "", [], {}) or v == {"core": [], "other": []}


def merge_candidate(old: dict, new: dict) -> dict:
    """New answers win; anything the new run left empty keeps its old value."""
    out = dict(new)
    for k, v in old.items():
        if _empty(out.get(k)) and not _empty(v):
            out[k] = v
    return out


def current_answers(repo: Path) -> dict:
    """The answers an existing profile and candidate.yaml imply, to prefill a re-run of setup."""
    from .profile import load_profile
    repo = Path(repo)
    prof_path = repo / "profile.yaml"
    if not prof_path.exists():
        return {}
    try:
        p = load_profile(prof_path)
        raw = p.raw
        cand = yaml.safe_load((repo / p.candidate_file).read_text(encoding="utf-8")) if (repo / p.candidate_file).exists() else {}
    except (SystemExit, OSError, yaml.YAMLError):
        return {}
    cand = cand or {}
    skills = cand.get("skills") or {}
    skill_list = (skills.get("core", []) + skills.get("other", [])) if isinstance(skills, dict) else list(skills or [])
    keys = [k for k, _ in p.regions]
    st = raw.get("setup") or {}
    out = {
        "resume": cand.get("base_resume") or "", "field": st.get("field") or "",
        "titles": p.tracks.get("core", []), "adjacent_titles": p.tracks.get("adjacent", []),
        "pivot_titles": p.tracks.get("pivot", []), "levels": cand.get("target_levels") or [],
        "years_experience": cand.get("years_experience"), "skills": skill_list or list(p.skills),
        "locations": p.locations, "remote": p.include_remote, "remote_only": p.remote_only,
        "linkedin": "linkedin" in p.sites,
        "remote_like_top_city": bool(keys and p.remote_rank_as == keys[0]),
        "pay_floor": p.pay_floor, "pay_target": p.pay_target, "require_pay": p.require_posted_pay,
        "avoid_companies": p.exclude_companies, "avoid_keywords": p.exclude_keywords,
        "target_companies": [], "discover_companies": bool(st.get("discover_companies", True)),
    }
    if st.get("occupations"):
        out["occupations"] = st["occupations"]
    return {k: v for k, v in out.items() if v not in (None, "")}


def run_setup(repo: Path, answers_in=None, ask=input, say=print, force=False):
    """Writes profile.yaml, candidate.yaml (and candidate/resume.txt), adds target companies.
    Returns dict of what it did."""
    repo = Path(repo)
    prof_path, cand_path = repo / "profile.yaml", repo / "candidate.yaml"
    if prof_path.exists() and not force:
        raise SystemExit(f"{prof_path} already exists. Run with --force to replace it "
                         f"(your current file is saved as profile.yaml.bak).")
    a = ask_all(answers_in, ask=ask, say=say)
    if not a.get("titles"):
        raise SystemExit("Setup needs at least one job title to search for (the 'titles' answer). Nothing was written.")

    resume_text, resume_path = "", None
    if a.get("resume"):
        resume_path = Path(a["resume"]).expanduser()
        if not resume_path.is_absolute():
            resume_path = (repo / resume_path).resolve()
        if resume_path.exists():
            resume_text = read_resume_text(resume_path)
            (repo / "candidate").mkdir(exist_ok=True)
            write_text_atomic(repo / "candidate" / "resume.txt", resume_text, private=True)
        else:
            say(f"  (couldn't find {resume_path}; skipping the resume)")
            resume_path = None

    if prof_path.exists():
        prof_path.replace(prof_path.with_suffix(".yaml.bak"))
    prof = build_profile(a)
    write_text_atomic(prof_path, PROFILE_HEADER + yaml.safe_dump(prof, sort_keys=False, allow_unicode=True, width=1000))

    cand = build_candidate(a, resume_text, str(resume_path) if resume_path else "")
    if cand_path.exists() and not force:
        say(f"  {cand_path.name} already exists; left it alone (use --force to rebuild it).")
    else:
        if cand_path.exists():
            # Re-running setup keeps what it didn't ask about (name, contact, past titles, summary,
            # facts) and anything left blank this time; the old file is kept as candidate.yaml.bak.
            try:
                old = yaml.safe_load(cand_path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                old = {}
            write_text_atomic(cand_path.with_suffix(".yaml.bak"), cand_path.read_text(encoding="utf-8"), private=True)
            cand = merge_candidate(old, cand)
        header = ("# candidate.yaml - your resume, structured. Private (gitignored). Made by `job-hunter setup`.\n"
                  "# Add past_titles and more skills for better ranking; the Claude skill can fill these in.\n")
        write_text_atomic(cand_path, header + yaml.safe_dump(cand, sort_keys=False, allow_unicode=True, width=1000))

    added = []
    if a.get("target_companies"):
        from .targets import Targets, add_by_name
        t = Targets(repo / prof.get("companies_file", "companies.yaml"))
        for name in a["target_companies"]:
            ok, msg = add_by_name(t, name)
            say(f"  {msg}")
            added.append((name, ok))
    packs = [x for x in (answers_in or {}).get("packs") or [] if isinstance(x, str)]
    if packs:
        from . import packs as packs_mod
        from .targets import Targets
        t = Targets(repo / prof.get("companies_file", "companies.yaml"))
        for pid in packs:
            if pid not in packs_mod.all_packs():
                say(f"  (no list called {pid!r}; skipped)")
                continue
            direct, browse = packs_mod.apply(t, pid, skip=a.get("avoid_companies") or [])
            say(f"  {packs_mod.all_packs()[pid].get('name', pid)}: {direct} career sites added to the daily search, "
                f"{browse} to the check-by-hand list")
    return {"answers": a, "profile": prof_path, "candidate": cand_path, "companies_added": added}
