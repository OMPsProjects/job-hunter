"""Rank jobs by how well they match the candidate.

rank_score (0-100) = weighted average of five parts (weights in profile `ranking.weights`):
  fit        resume skills found in the posting, title closeness to your target/past titles,
             and the profile keyword score
  seniority  years of experience asked vs. yours, and the title's level vs. your target levels
  location   where the job sits in your region order (remote can rank with your top region)
  pay        posted pay vs. your floor and target (not posted = neutral 50)
  freshness  days since posted
...times a verification multiplier (unverified jobs rank lower), and a low-fit penalty: a job
whose fit is under ranking.low_fit_threshold (default 40) is scaled down, so good pay or a great
city can't carry a job you don't match. Jobs that fail a hard filter
(excluded company or keyword, already applied, pay below a hard floor, closed, or not on the
employer's site) are moved to a separate excluded list with the reason.
"""
import datetime as dt

import pandas as pd

from .candidate import LEVELS, title_level, years_required
from .common import annualize, company_key, norm, title_similarity
from .profile import OTHER, REMOTE, UNSPECIFIED_KEY
from .scoring import count

VERIFY_MULT = {"verified_open": 1.0, "employer_page_live": 0.97}
EXCLUDE_STATUSES = {"closed": "closed on employer site", "not_on_employer_site": "not on employer's job board"}
NEUTRAL = 50.0


def _today():
    return dt.date.today()


_LEVEL_WORDS = {"senior", "sr", "junior", "jr", "lead", "principal", "staff", "manager", "director", "head",
                "vp", "vice", "president", "svp", "evp", "avp", "associate", "assistant", "chief", "officer",
                "executive", "i", "ii", "iii", "iv", "of", "and", "the", "remote", "hybrid", "us", "team"}


def role_similarity(a, b):
    """Title closeness on the words that name the work, not the level ('Senior', 'Manager'...)."""
    ta = set(norm(a).split()) - _LEVEL_WORDS
    tb = set(norm(b).split()) - _LEVEL_WORDS
    if not ta or not tb:
        return title_similarity(a, b) * 0.5
    inter = len(ta & tb)
    return 0.5 * inter / len(ta | tb) + 0.5 * inter / min(len(ta), len(tb))


def fit_part(row, p, cand):
    title = str(row.get("title", "")).lower()
    desc = str(row.get("description", "")).lower()
    kw = float(row.get("fit_score") or 0)
    if not cand or not cand.usable:
        return kw, [], None
    matched, w_hit = [], 0.0
    for s, w in cand.skills.items():
        if count(s, title) or count(s, desc):
            matched.append(s)
            w_hit += w
    total = sum(cand.skills.values())
    coverage = 100 * w_hit / min(total, 16) if total else NEUTRAL  # a posting won't name every skill you have
    coverage = min(coverage, 100)
    titles = cand.target_titles + cand.past_titles
    tsim = 100 * max((role_similarity(row.get("title"), t) for t in titles), default=0.5)
    fit = 0.45 * coverage + 0.25 * tsim + 0.30 * kw if p.skills else 0.65 * coverage + 0.35 * tsim
    return fit, matched, tsim


def seniority_part(row, cand):
    notes = []
    parts = []
    req = years_required(row.get("description"))
    if cand and cand.years and req:
        gap = req - cand.years
        if gap <= 0:
            parts.append(100.0 if -gap <= 10 else 75.0)
            if -gap > 10:
                notes.append(f"asks {req}+ yrs; you may be overqualified")
        else:
            parts.append(max(0.0, 100 - 20 * gap))
            notes.append(f"asks {req}+ yrs, you have {cand.years}")
    lvl = title_level(row.get("title"))
    if cand and cand.target_levels and lvl is not None:
        d = min(abs(lvl - t) for t in cand.target_levels)
        parts.append({0: 100.0, 1: 70.0, 2: 35.0}.get(d, 0.0))
        if d >= 1:
            notes.append(f"title level '{LEVELS[lvl]}' is off target")
    return (sum(parts) / len(parts) if parts else NEUTRAL), notes, req


def location_part(row, p):
    keys = [k for k, _ in p.regions]
    reg = row.get("region")
    if reg == REMOTE:
        reg = p.remote_rank_as or (keys[0] if keys else None)
        if reg is None:
            return 100.0
    if reg in keys:
        i = keys.index(reg)
        return 100.0 if len(keys) == 1 else 100 - 50 * i / (len(keys) - 1)
    if reg == UNSPECIFIED_KEY:
        return NEUTRAL
    return 0.0 if reg == OTHER else NEUTRAL


def pay_part(row, p):
    hi = annualize(row.get("max_amount"), row.get("interval"))
    lo = annualize(row.get("min_amount"), row.get("interval"))
    top = hi or lo
    if top is None:
        return NEUTRAL, "pay not posted", None
    floor, target = p.pay_floor, p.pay_target
    if not floor and not target:
        return NEUTRAL, "", top
    floor = floor or 0
    target = target or floor * 1.3
    if top < floor:
        return 0.0, f"posted top ${top:,.0f} is under your ${floor:,.0f} floor", top
    if top >= target:
        return 100.0, "", top
    return 50 + 50 * (top - floor) / max(1, target - floor), "", top


def freshness_part(row, p):
    try:
        ts = pd.to_datetime(row.get("date_posted"), errors="coerce", utc=True)
    except Exception:
        return NEUTRAL
    if ts is None or pd.isna(ts):
        return NEUTRAL
    posted = ts.date()
    age = max(0, (_today() - posted).days)
    return max(0.0, 100 * (1 - age / p.max_age_days))


def applied_keys(p, tracker_df):
    """(company_key, normalized title, urls) for jobs already applied to."""
    keys = []
    for s in p.already_applied:
        comp, _, title = s.partition("|")
        keys.append((company_key(comp), norm(title), set()))
    if tracker_df is not None and len(tracker_df):
        done = tracker_df[tracker_df["status"].isin(["submitted", "ready_for_review", "applied", "interviewing",
                                                     "rejected", "offer"])]
        for _, r in done.iterrows():
            keys.append((company_key(r["company"]), norm(r["title"]),
                         {u for u in (r.get("job_url"), r.get("employer_url")) if u}))
    return keys


def hard_filter_reason(row, p, applied):
    comp = company_key(row.get("company"))
    title = str(row.get("title", "")).lower()
    head = title + " " + str(row.get("description", "")).lower()[:p.desc_window]
    allowed = any(company_key(a) and company_key(a) in comp for a in p.allow_companies)
    if not allowed:
        for c in p.exclude_companies:
            ck = company_key(c)
            if ck and (comp == ck or comp.startswith(ck + " ")):
                return f"excluded company ({c})"
    for kw in p.exclude_keywords:
        if count(kw, head):
            return f"excluded keyword '{kw}'"
    urls = {row.get("job_url"), row.get("employer_url")}
    for c, t, done_urls in applied:
        if done_urls & urls:
            return "already applied"
        # same company and the same title, word for word ("Credit Analyst" is not "Senior Credit Analyst")
        if c and c == comp and (not t or t == norm(row.get("title"))):
            return "already applied"
    st = row.get("verified")
    if st in EXCLUDE_STATUSES:
        return EXCLUDE_STATUSES[st]
    return None


def rank(df, p, cand=None, tracker_df=None):
    """Returns (ranked, excluded) DataFrames."""
    w = p.weights
    applied = applied_keys(p, tracker_df)
    rows, excluded = [], []
    for _, r in df.iterrows():
        row = r.to_dict()
        if not isinstance(row.get("verified"), str):
            row["verified"] = "not_checked"
        reason = hard_filter_reason(row, p, applied)
        pay, pay_note, top = pay_part(row, p)
        if not reason and p.pay_floor_is_hard and p.pay_floor and top is not None and top < p.pay_floor:
            reason = "pay below floor"
        if reason:
            row["excluded_reason"] = reason
            excluded.append(row)
            continue
        fit, matched, tsim = fit_part(row, p, cand)
        sen, sen_notes, req = seniority_part(row, cand)
        loc = location_part(row, p)
        fresh = freshness_part(row, p)
        parts = {"fit": fit, "seniority": sen, "location": loc, "pay": pay, "freshness": fresh}
        score = sum(parts[k] * w.get(k, 0) for k in parts) / max(1e-9, sum(w.get(k, 0) for k in parts))
        mult = VERIFY_MULT.get(row.get("verified"))
        if mult is None:
            mult = p.unverified_multiplier
        score *= mult
        if fit < p.low_fit_threshold:  # resume fit comes first: a poor fit can't ride on pay or location
            score *= 0.6 + 0.4 * fit / p.low_fit_threshold
            gaps_low_fit = True
        else:
            gaps_low_fit = False
        gaps = (["weak resume match"] if gaps_low_fit else []) + sen_notes + ([pay_note] if pay_note else [])
        if row["verified"] in ("unverified", "not_checked"):
            gaps.append("not yet confirmed on employer site")
        if str(row.get("note") or "") and "snippet" in str(row.get("note")):
            gaps.append("description is a snippet; open the posting")
        row.update({
            "rank_score": round(score, 1), "fit": round(fit), "seniority": round(sen),
            "location_score": round(loc), "pay_score": round(pay), "freshness": round(fresh),
            "pay_top": top, "years_required": req,
            "why": ", ".join(matched[:8]) or str(row.get("matched") or ""),
            "gaps": "; ".join(g for g in gaps if g),
        })
        rows.append(row)
    ranked = pd.DataFrame(rows)
    if "rank" in ranked:
        ranked = ranked.drop(columns=["rank"])
    if len(ranked):
        ranked = ranked.sort_values("rank_score", ascending=False).reset_index(drop=True)
        ranked.insert(0, "rank", range(1, len(ranked) + 1))
    return ranked, pd.DataFrame(excluded)
