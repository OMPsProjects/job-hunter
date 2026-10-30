"""profile.yaml -> a typed Profile with defaults. See profile.example.yaml for every key."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("pip install pyyaml")

REMOTE, UNSPECIFIED_KEY, OTHER = "remote", "unspecified", "other"
ATS_TYPES = {"greenhouse", "lever", "ashby", "workday", "smartrecruiters", "workable", "recruitee", "oracle",
             "successfactors"}

# Boards scraped through python-jobspy. Only Indeed is on by default:
#   linkedin       works, but LinkedIn's terms forbid automated access and it rate-limits and may
#                  restrict accounts. Opt in by adding it to search.sites if you accept that.
#   google, glassdoor, zip_recruiter: returned nothing / 400 / Cloudflare 403 in late 2026.
DEFAULT_SITES = ["indeed"]
JOBSPY_SITES = {"indeed", "linkedin", "google", "glassdoor", "zip_recruiter", "bayt", "naukri"}

# Source switches. True/False, or "auto" = on when its API key env vars are set.
DEFAULT_SOURCES = {
    "jobspy": True,      # Indeed + LinkedIn (+ whatever else is in search.sites)
    "remotive": True,    # remote jobs, keyless
    "himalayas": True,   # remote jobs, keyless
    "remoteok": True,    # remote jobs, keyless (requires a link back to RemoteOK if you republish)
    "themuse": True,     # keyless; no keyword search, so results are filtered by title locally
    "arbeitnow": False,  # keyless, mostly Europe
    "adzuna": "auto",    # ADZUNA_APP_ID + ADZUNA_APP_KEY (free at developer.adzuna.com)
    "usajobs": "auto",   # USAJOBS_API_KEY + USAJOBS_EMAIL (free at developer.usajobs.gov)
    "jooble": "auto",    # JOOBLE_API_KEY (free at jooble.org/api/about)
    "dreamwork": False,  # keyless aggregator; off because it sends your titles and cities to dreamworkhq.com
    "company_feeds": True,
}
SOURCE_KEYS = {
    "adzuna": ["ADZUNA_APP_ID", "ADZUNA_APP_KEY"],
    "usajobs": ["USAJOBS_API_KEY", "USAJOBS_EMAIL"],
    "jooble": ["JOOBLE_API_KEY"],
}

DEFAULT_WEIGHTS = {"fit": 40, "seniority": 20, "location": 15, "pay": 15, "freshness": 10}


class Profile:
    schema_warnings: list = []

    def __init__(self, data: dict, path: Path | None = None):
        self.path = path
        self.base = path.parent if path else Path.cwd()
        s = data.get("search", {}) or {}
        self.locations = list(s.get("locations", []))
        self.include_remote = bool(s.get("include_remote", True))
        self.remote_only = bool(s.get("remote_only", False)) and self.include_remote
        self.results_per_search = int(s.get("results_per_search", 25))
        self.hours_old = int(s.get("hours_old", 168))
        self.sites = list(s.get("sites", DEFAULT_SITES))
        self.pause_seconds = float(s.get("pause_seconds", 2))
        self.country = s.get("country_indeed", "USA")
        self.api_country = str(s.get("api_country", "us")).lower()  # Adzuna country code
        # Remote-only boards: keep a posting only if its "candidate location" mentions one of these
        # (or is blank). Lowercase substrings.
        self.remote_allowed = [str(x).lower() for x in s.get("remote_allowed", [
            "united states", "usa", "u.s.", "us only", "north america", "americas", "worldwide",
            "anywhere", "global"])]
        self.title_match_threshold = float(s.get("title_match_threshold", 0.5))

        src = dict(DEFAULT_SOURCES)
        src.update(data.get("sources", {}) or {})
        self.sources = src

        self.regions = [(r["key"], r["pattern"]) for r in data.get("regions", [])]
        order = data.get("region_order") or [k for k, _ in self.regions] + [REMOTE, UNSPECIFIED_KEY]
        self.region_order = {k: i for i, k in enumerate(order)}
        self.region_order.setdefault(OTHER, len(self.region_order))
        for k in (REMOTE, UNSPECIFIED_KEY):
            self.region_order.setdefault(k, len(self.region_order))
        self.keep_unspecified = bool(data.get("keep_unspecified_locations", True))

        self.tracks = {k: list(v) for k, v in (data.get("tracks") or {}).items()}
        self.feeds = []
        for f in data.get("company_feeds", []) or []:
            self.feeds.append(dict(
                track=f["track"],
                companies=[tuple(c) for c in f.get("companies", [])],
                include=f.get("title_include", "."),
                exclude=f.get("title_exclude", r"(?!x)x"),  # matches nothing
            ))

        sc = data.get("scoring", {}) or {}
        self.skills = {str(k).lower(): float(v) for k, v in (sc.get("skills") or {}).items()}
        self.negative = {str(k).lower(): float(v) for k, v in (sc.get("negative") or {}).items()}
        self.title_negative = {str(k): float(v) for k, v in (sc.get("title_negative") or {}).items()}
        self.required_terms = {t: [set(map(str.lower, g)) for g in groups]
                               for t, groups in (sc.get("required_terms") or {}).items()}
        self.missing_required_penalty = float(sc.get("missing_required_penalty", -15))
        self.salary_bonus = float(sc.get("salary_bonus", 2))
        self.desc_window = int(sc.get("negative_desc_chars", 600))
        self.max_raw = float(sc.get("max_raw", 90))
        self.min_score = float(sc.get("min_score", 20))

        rk = data.get("ranking", {}) or {}
        self.weights = dict(DEFAULT_WEIGHTS)
        self.weights.update({k: float(v) for k, v in (rk.get("weights") or {}).items()})
        self.pay_floor = rk.get("pay_floor")
        self.pay_target = rk.get("pay_target")
        self.pay_floor_is_hard = bool(rk.get("pay_floor_is_hard", True))
        self.require_posted_pay = bool(rk.get("require_posted_pay", False))  # hide jobs that don't list pay
        self.remote_rank_as = rk.get("remote_rank_as")  # region key; default: your top region
        self.unverified_multiplier = float(rk.get("unverified_multiplier", 0.85))
        self.max_age_days = float(rk.get("max_age_days", 30))
        self.low_fit_threshold = float(rk.get("low_fit_threshold", 40))
        # 'auto' uses the JobBERT title model when it's installed (pip install -e ".[ml]")
        self.title_model = rk.get("title_model", "auto")
        self.pay_estimates = bool(rk.get("pay_estimates", True))  # BLS pay when a posting has none
        self.repost_multiplier = float(rk.get("repost_multiplier", 1.0))  # 1.0 = flag re-listed jobs only

        fl = data.get("filters", {}) or {}
        self.exclude_companies = [str(c) for c in fl.get("exclude_companies", []) or []]
        self.allow_companies = [str(c) for c in fl.get("allow_companies", []) or []]
        self.exclude_keywords = [str(k).lower() for k in fl.get("exclude_keywords", []) or []]
        self.already_applied = [str(a) for a in fl.get("already_applied", []) or []]
        self.needs_sponsorship = bool(fl.get("needs_sponsorship", False))

        vf = data.get("verify", {}) or {}
        self.verify_enabled = bool(vf.get("enabled", True))
        self.verify_top_n = int(vf.get("top_n", 150))
        self.ats_overrides = {str(k): tuple(v) for k, v in (vf.get("ats_overrides") or {}).items()}

        llm = data.get("llm", {}) or {}
        self.candidate_summary = (llm.get("candidate_summary") or "").strip()
        self.llm_model = llm.get("model", "claude-sonnet-5-5")
        self.llm_top_n = int(llm.get("top_n", 30))

        self.output_dir = data.get("output_dir")
        self.candidate_file = data.get("candidate_file", "candidate.yaml")
        self.answers_file = data.get("answers_file", "answers.yaml")
        self.tracker_file = data.get("tracker_file", "applications.csv")
        self.browse_boards = list(data.get("browse_boards", []) or [])
        self.review = data.get("review", {}) or {}
        self.auto_download = bool((data.get("data") or {}).get("auto_download", True))
        # track -> O*NET-SOC occupation code, chosen in setup; used for pay estimates
        self.track_occupations = {str(k): str(v) for k, v in
                                  (((data.get("setup") or {}).get("occupations")) or {}).items() if v}
        self.raw = data

        # companies.yaml (managed by `job-hunter companies` / `boards`): merged in, not copied.
        self.companies_file = data.get("companies_file", "companies.yaml")
        self.target_companies: list[dict] = []
        cpath = self.resolve(self.companies_file)
        if cpath.exists():
            try:
                cdata = yaml.safe_load(cpath.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as e:
                raise SystemExit(f"{cpath.name} isn't valid YAML: {e}") from None
            self.target_companies = [c for c in (cdata.get("companies") or []) if c.get("ats") and c.get("slug")]
            known = {b.get("url") for b in self.browse_boards}
            self.browse_boards += [b for b in (cdata.get("browse_boards") or []) if b.get("url") not in known]

    # -- helpers -----------------------------------------------------------
    def resolve(self, p) -> Path:
        p = Path(os.path.expanduser(str(p)))
        return p if p.is_absolute() else self.base / p

    def source_on(self, name) -> bool:
        v = self.sources.get(name, False)
        if v == "auto":
            return all(os.environ.get(k) for k in SOURCE_KEYS.get(name, []))
        return bool(v)

    def occupation_for_track(self, track):
        """The occupation code for a track: the one chosen in setup, else the closest match to
        the track's search titles (None when none match well)."""
        if track in self.track_occupations:
            return self.track_occupations[track]
        from .occupations import match
        for title in self.tracks.get(track, []):
            m = match(title)
            if m and m["score"] >= 0.9:
                return m["code"]
        return None

    def all_titles(self):
        """(track, title) pairs, in profile order."""
        return [(t, q) for t, qs in self.tracks.items() for q in qs]

    def problems(self) -> list:
        p = list(getattr(self, "schema_warnings", []))
        if not self.tracks:
            p.append("no tracks: add at least one track with search titles")
        if not self.locations and not self.include_remote:
            p.append("no locations and include_remote is false: nothing to search")
        if not self.skills:
            p.append("scoring.skills is empty: keyword scores will all be 0")
        for key, pat in self.regions:
            try:
                re.compile(pat)
            except re.error as e:
                p.append(f"region {key}: bad regex ({e})")
        for pat in self.title_negative:
            try:
                re.compile(pat)
            except re.error as e:
                p.append(f"title_negative {pat!r}: bad regex ({e})")
        for f in self.feeds:
            for c in f["companies"]:
                if len(c) != 3 or c[1] not in ATS_TYPES:
                    p.append(f"feed entry {c}: want [company, {'|'.join(sorted(ATS_TYPES))}, slug]")
            if f["track"] not in self.tracks:
                p.append(f"feed track {f['track']!r} is not one of your tracks (it will still run)")
        for loc in self.locations:
            if re.fullmatch(r"\s*[A-Za-z]{2}\s*", str(loc)):
                p.append(f"search.locations has {loc!r} on its own: in a [..] list, quote 'City, ST' "
                         f"or the comma splits it into two locations")
        for s in self.sites:
            if s not in JOBSPY_SITES:
                p.append(f"search.sites: unknown site {s!r}")
        for name, v in self.sources.items():
            if v == "auto" and not self.source_on(name):
                p.append(f"source {name}: off (set {' + '.join(SOURCE_KEYS.get(name, []))} to turn it on)")
        p += spelling_problems(self)
        for k in self.weights:
            if k not in DEFAULT_WEIGHTS:
                p.append(f"ranking.weights: unknown key {k!r} (use {', '.join(DEFAULT_WEIGHTS)})")
        return p


def _close(word, vocab):
    import difflib
    hits = [h for h in difflib.get_close_matches(word, vocab, n=1, cutoff=0.88) if h[0] == word[0]]
    return hits[0] if hits else None


def spelling_problems(p) -> list:
    """Likely typos in search titles and cities ('Commerical', 'Washigton'): a misspelled title
    finds nothing on the job boards, and a misspelled city never matches a posting."""
    out: list[str] = []
    try:
        from .occupations import _load
        from .setup import us_cities
        words = set(_load()[2])
        cities = us_cities()
    except Exception:  # the check is a convenience; never block a run on it
        return out
    city_names = {c.split(",")[0].strip().lower() for c in cities}
    for titles in p.tracks.values():
        for t in titles:
            for w in re.findall(r"[a-z]{4,}", str(t).lower()):
                if w not in words and w.rstrip("s") not in words:
                    fix = _close(w, words)
                    if fix:
                        out.append(f"search title {t!r}: {w!r} looks misspelled (did you mean {fix!r}?). "
                                   f"Job boards won't find titles with a typo.")
    for loc in p.locations:
        name = str(loc).split(",")[0].strip().lower()
        if name and name not in city_names:
            fix = _close(name, list(city_names))
            if fix:
                out.append(f"city {loc!r} looks misspelled (did you mean {fix.title()!r}?). "
                           f"Jobs there won't match it.")
    return out


def load_profile(path, required=True) -> Profile:
    path = Path(path)
    if not path.exists() and not required:
        return Profile({}, path.resolve())
    if not path.exists():
        sys.exit(f"No profile at {path}. Run `job-hunter setup` (or copy profile.example.yaml to "
                 f"profile.yaml and edit it).")
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except yaml.YAMLError as e:
        sys.exit(f"{path.name} isn't valid YAML: {e}")
    if not isinstance(data, dict):
        sys.exit(f"{path.name} should be a set of settings (key: value), not a {type(data).__name__}.")
    from .validate import validate_profile
    errors, warnings = validate_profile(data)
    if errors:
        sys.exit(f"{path.name} has problems:\n" + "\n".join(f"  - {e}" for e in errors))
    prof = Profile(data, path.resolve())
    prof.schema_warnings = warnings
    return prof
