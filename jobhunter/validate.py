"""Check profile.yaml / candidate.yaml before anything runs, with messages a person can act on.

Errors stop the run (wrong types, broken regexes). Warnings don't (unknown keys, usually typos,
with a did-you-mean suggestion).
"""
from __future__ import annotations

import difflib
import re

NUM = (int, float)
ANY = object

# key -> type, or a nested dict schema. Lists are written as [type].
PROFILE_SCHEMA = {
    "output_dir": str, "candidate_file": str, "answers_file": str, "tracker_file": str, "companies_file": str,
    "search": {"locations": [str], "include_remote": bool, "results_per_search": int, "hours_old": int,
               "sites": [str], "pause_seconds": NUM, "country_indeed": str, "api_country": str,
               "remote_allowed": [str], "title_match_threshold": NUM},
    "sources": dict,
    "browse_boards": [dict],
    "regions": [dict],
    "region_order": [str],
    "keep_unspecified_locations": bool,
    "tracks": dict,
    "company_feeds": [dict],
    "scoring": {"skills": dict, "negative": dict, "title_negative": dict, "required_terms": dict,
                "missing_required_penalty": NUM, "salary_bonus": NUM, "negative_desc_chars": int,
                "max_raw": NUM, "min_score": NUM},
    "ranking": {"weights": dict, "pay_floor": NUM, "pay_target": NUM, "pay_floor_is_hard": bool,
                "remote_rank_as": str, "unverified_multiplier": NUM, "max_age_days": NUM,
                "low_fit_threshold": NUM},
    "filters": {"exclude_companies": [str], "allow_companies": [str], "exclude_keywords": [str],
                "already_applied": [str]},
    "verify": {"enabled": bool, "top_n": int, "ats_overrides": dict},
    "llm": {"model": str, "top_n": int, "candidate_summary": str},
    "review": dict,
    "setup": dict,
}


def _type_name(t):
    if isinstance(t, list):
        return f"a list of {_type_name(t[0])}"
    if isinstance(t, dict):
        return "a section (key: value lines)"
    if t is NUM:
        return "a number"
    return {str: "text", int: "a whole number", bool: "true or false", dict: "a section", list: "a list"}.get(t, str(t))


def _is(value, t):
    if value is None:
        return True  # empty means "use the default"
    if t is ANY:
        return True
    if isinstance(t, list):
        return isinstance(value, list) and all(_is(v, t[0]) for v in value)
    if isinstance(t, dict):
        return isinstance(value, dict)
    if t is NUM:
        return isinstance(value, NUM) and not isinstance(value, bool)
    if t is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if t is str:
        return isinstance(value, (str, int, float)) and not isinstance(value, bool)
    return isinstance(value, t)


def _walk(data, schema, path, errors, warnings):
    for key, value in data.items():
        here = f"{path}{key}"
        if key not in schema:
            close = difflib.get_close_matches(str(key), list(schema), n=1, cutoff=0.6)
            warnings.append(f"{here}: not a setting job-hunter knows" + (f" (did you mean '{path}{close[0]}'?)" if close else ""))
            continue
        t = schema[key]
        if not _is(value, t):
            errors.append(f"{here}: should be {_type_name(t)}, got {type(value).__name__} ({str(value)[:40]!r})")
            continue
        if isinstance(t, dict) and isinstance(value, dict):
            _walk(value, t, here + ".", errors, warnings)


def _regex(pat, where, errors):
    try:
        re.compile(str(pat))
    except re.error as e:
        errors.append(f"{where}: {pat!r} isn't a valid pattern ({e})")


def validate_profile(data: dict):
    errors: list[str] = []
    warnings: list[str] = []
    _walk(data, PROFILE_SCHEMA, "", errors, warnings)
    for i, r in enumerate(data.get("regions") or []):
        if not isinstance(r, dict) or "key" not in r or "pattern" not in r:
            errors.append(f"regions[{i}]: each region needs a key and a pattern, e.g. {{key: dc, pattern: 'washington'}}")
        else:
            _regex(r["pattern"], f"regions.{r['key']}", errors)
    for name, titles in (data.get("tracks") or {}).items():
        if not isinstance(titles, list) or not all(isinstance(t, str) for t in titles):
            errors.append(f"tracks.{name}: should be a list of job titles")
    for pat in ((data.get("scoring") or {}).get("title_negative") or {}):
        _regex(pat, "scoring.title_negative", errors)
    for k, v in ((data.get("scoring") or {}).get("skills") or {}).items():
        if not isinstance(v, NUM) or isinstance(v, bool):
            errors.append(f"scoring.skills.{k}: weight should be a number, got {v!r}")
    for k, v in ((data.get("ranking") or {}).get("weights") or {}).items():
        if k not in ("fit", "seniority", "location", "pay", "freshness"):
            warnings.append(f"ranking.weights.{k}: unknown part (use fit, seniority, location, pay, freshness)")
        elif not isinstance(v, NUM) or v < 0:
            errors.append(f"ranking.weights.{k}: should be a number 0 or more, got {v!r}")
    for i, f in enumerate(data.get("company_feeds") or []):
        if not isinstance(f, dict) or "track" not in f:
            errors.append(f"company_feeds[{i}]: needs a track and a companies list")
            continue
        for key in ("title_include", "title_exclude"):
            if f.get(key):
                _regex(f[key], f"company_feeds[{i}].{key}", errors)
    rk = data.get("ranking") or {}
    if isinstance(rk.get("pay_floor"), NUM) and isinstance(rk.get("pay_target"), NUM) and rk["pay_floor"] > rk["pay_target"]:
        errors.append(f"ranking: pay_floor ({rk['pay_floor']}) is above pay_target ({rk['pay_target']})")
    return errors, warnings


CANDIDATE_SCHEMA = {
    "name": str, "contact": dict, "base_resume": str, "facts_files": [str], "years_experience": NUM,
    "headline": str, "past_titles": [str], "target_titles": [str], "target_levels": [str],
    "skills": ANY, "industries": [str], "summary": str,
}


def validate_candidate(data: dict):
    from .candidate import LEVELS
    errors: list[str] = []
    warnings: list[str] = []
    _walk(data, CANDIDATE_SCHEMA, "", errors, warnings)
    for lv in data.get("target_levels") or []:
        if str(lv).lower() not in LEVELS:
            errors.append(f"target_levels: {lv!r} isn't a level (use {', '.join(LEVELS)})")
    sk = data.get("skills")
    if sk is not None and not isinstance(sk, (list, dict)):
        errors.append("skills: should be {core: [...], other: [...]} or a list")
    return errors, warnings
