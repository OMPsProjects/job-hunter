"""Rank jobs by how well they match the candidate.

rank_score (0-100) = weighted average of five parts (weights in profile `ranking.weights`):
  fit        resume skills found in the posting, title closeness to your target/past titles,
             and the profile keyword score
  seniority  years of experience asked vs. yours, and the title's level vs. your target levels
  location   where the job sits in your region order (remote can rank with your top region)
  pay        posted pay vs. your floor and target. Not posted: the government's typical pay for
             that occupation and metro (BLS), counted at half strength; no data = neutral 50
  freshness  days since posted
...times a verification multiplier (unverified jobs rank lower), and a low-fit penalty: a job
whose fit is under ranking.low_fit_threshold (default 40) is scaled down, so good pay or a great
city can't carry a job you don't match. Jobs that fail a hard filter
(excluded company or keyword, already applied, pay below a hard floor, closed, or not on the
employer's site, or, if you need visa sponsorship, a posting that says it won't sponsor) are moved
to a separate excluded list with the reason. Re-listed postings are flagged in `gaps`.
"""
import datetime as dt

import pandas as pd

from . import deadlines, integrity, occupations, visa, wages
from .candidate import LEVELS, title_level, years_required
from .common import annualize, company_id, company_key, norm, title_similarity
from .logs import log
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


def fit_part(row, p, cand, title_sim=None):
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
    model = title_sim.get(row.get("title")) if title_sim is not None else None
    if model is not None:  # meaning-based score from the optional title model; keep whichever is higher
        tsim = max(tsim, 100 * model)
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


def _pay_score(amount, p):
    floor, target = p.pay_floor, p.pay_target
    if not floor and not target:
        return NEUTRAL
    floor = floor or 0
    target = target or floor * 1.3
    if amount < floor:
        return 0.0
    if amount >= target:
        return 100.0
    return 50 + 50 * (amount - floor) / max(1, target - floor)


def pay_part(row, p, est=None):
    """(score, note, posted top). `est` is a BLS estimate for jobs without posted pay: it moves
    the score only halfway from neutral, and is never a reason to exclude a job."""
    hi = annualize(row.get("max_amount"), row.get("interval"))
    lo = annualize(row.get("min_amount"), row.get("interval"))
    top = hi or lo
    if top is None:
        if est and est.get("median"):
            score = NEUTRAL + 0.5 * (_pay_score(est["median"], p) - NEUTRAL)
            return score, f"pay not posted; typical ${est['median']:,.0f} ({est['label']})", None
        return NEUTRAL, "pay not posted", None
    score = _pay_score(top, p)
    if p.pay_floor and top < p.pay_floor:
        return score, f"posted top ${top:,.0f} is under your ${p.pay_floor:,.0f} floor", top
    return score, "", top


# ----------------------------- pay estimates --------------------------------

def occupation_for(row, p):
    """The occupation code for a job: its own title when that's an unambiguous known title, else
    the occupation of the search track it was found under."""
    m = occupations.match(str(row.get("title") or ""))
    if m and m["score"] >= 1.0 and not m.get("ambiguous"):
        return m["code"]
    track = row.get("track")
    return p.occupation_for_track(track) if isinstance(track, str) else None


def wage_requests(df, p):
    """(area_code, soc6) pairs for jobs that don't post pay, for wages.prefetch()."""
    pairs = []
    for _, r in df.iterrows():
        if annualize(r.get("max_amount"), r.get("interval")) or annualize(r.get("min_amount"), r.get("interval")):
            continue
        code = occupation_for(r, p)
        if code:
            area, _ = wages.area_for_job(p, r)
            pairs.append((area, occupations.soc6(code)))
    return list(dict.fromkeys(pairs))


def pay_estimate(row, p, cache):
    code = occupation_for(row, p)
    if not code or cache is None:
        return None
    area, area_label = wages.area_for_job(p, row)
    est = wages.estimate(area, occupations.soc6(code), cache)
    if not est:
        return None
    where = area_label if est["area"] == area else "U.S."
    occ = (occupations.info(code) or {}).get("title", "this occupation")
    year = f" {est['year']}" if est.get("year") else ""
    return {**est, "label": f"BLS median for {occ}, {where}{year}"}


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


def _ids(urls) -> set:
    """Links plus their employer posting ids, so a job you applied to is recognized under any link."""
    from .sources.ats import posting_key
    links = {u for u in urls if isinstance(u, str) and u}
    return links | {k for k in map(posting_key, links) if k}


def applied_keys(p, tracker_df):
    """(company id, normalized title, links and posting ids) for jobs already applied to."""
    keys = []
    for s in p.already_applied:
        comp, _, title = s.partition("|")
        keys.append((company_id(comp), norm(title), set()))
    if tracker_df is not None and len(tracker_df):
        done = tracker_df[tracker_df["status"].isin(["submitted", "ready_for_review", "applied", "interviewing",
                                                     "rejected", "offer"])]
        for _, r in done.iterrows():
            keys.append((company_id(r["company"]), norm(r["title"]),
                         _ids((r.get("job_url"), r.get("employer_url")))))
    return keys


def hard_filter_reason(row, p, applied):
    comp = company_key(row.get("company"))
    cid = company_id(row.get("company"))
    title = str(row.get("title", "")).lower()
    head = title + " " + str(row.get("description", "")).lower()[:p.desc_window]
    allowed = any((company_key(a) and company_key(a) in comp) or (company_id(a) and company_id(a) == cid)
                  for a in p.allow_companies)
    if not allowed:
        for c in p.exclude_companies:
            ck = company_key(c)
            if ck and (comp == ck or comp.startswith(ck + " ") or company_id(c) == cid):
                return f"excluded company ({c})"
    for kw in p.exclude_keywords:
        if count(kw, head):
            return f"excluded keyword '{kw}'"
    urls = _ids((row.get("job_url"), row.get("employer_url"), row.get("job_url_direct")))
    for c, t, done_urls in applied:
        if done_urls & urls:
            return "already applied"
        # same company and the same title, word for word ("Credit Analyst" is not "Senior Credit Analyst")
        if c and c == cid and (not t or t == norm(row.get("title"))):
            return "already applied"
    st = row.get("verified")
    if st in EXCLUDE_STATUSES:
        return EXCLUDE_STATUSES[st]
    if p.needs_sponsorship:
        status, _ = visa.posting_status(row.get("description"))
        if status == "no_sponsorship":
            return "says it won't sponsor a visa"
        if status == "citizens_only":
            return "requires U.S. citizenship or a security clearance"
    return None


def _title_model(df, p, cand):
    from . import embed
    if not len(df) or not cand or not cand.usable or not embed.wanted(p.title_model):
        return None
    sim = embed.TitleSimilarity(cand.target_titles + cand.past_titles, df["title"].dropna().astype(str).unique())
    return sim if sim.ok else None


def rank(df, p, cand=None, tracker_df=None, wage_cache=None):
    """Returns (ranked, excluded) DataFrames. Works offline: pay estimates come from `wage_cache`
    (filled beforehand by wages.prefetch), or from the saved cache when not given."""
    w = p.weights
    applied = applied_keys(p, tracker_df)
    rows, excluded = [], []
    title_sim = _title_model(df, p, cand)
    if p.pay_estimates and wage_cache is None:
        try:
            wage_cache = wages.WageCache()
        except Exception as e:
            log.warning(f"pay estimates off this run: {e}")
    for _, r in df.iterrows():
        row = r.to_dict()
        if not isinstance(row.get("verified"), str):
            row["verified"] = "not_checked"
        reason = hard_filter_reason(row, p, applied)
        posted = annualize(row.get("max_amount"), row.get("interval")) or annualize(row.get("min_amount"), row.get("interval"))
        est = pay_estimate(row, p, wage_cache) if p.pay_estimates and not posted else None
        pay, pay_note, top = pay_part(row, p, est)
        if not reason and p.pay_floor_is_hard and p.pay_floor and top is not None and top < p.pay_floor:
            reason = "pay below floor"
        if reason:
            row["excluded_reason"] = reason
            excluded.append(row)
            continue
        fit, matched, tsim = fit_part(row, p, cand, title_sim)
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
        deadline_note, closes = deadlines.note(row)
        if deadline_note:
            gaps.append(deadline_note)
        integrity_note = integrity.note("\n".join(str(row.get(k) or "") for k in ("title", "company", "description")))
        if integrity_note:
            gaps.append(integrity_note)
        repost = row.get("repost_note")
        if isinstance(repost, str) and repost:
            gaps.append(repost)
            score *= p.repost_multiplier
        visa_note = ""
        if p.needs_sponsorship:
            status, _ = visa.posting_status(row.get("description"))
            history = visa.employer_history(row.get("company"))
            visa_note = "; ".join(x for x in (
                "posting mentions visa sponsorship" if status == "sponsors" else "", history) if x)
        row.update({
            "rank_score": round(score, 1), "fit": round(fit), "seniority": round(sen),
            "location_score": round(loc), "pay_score": round(pay), "freshness": round(fresh),
            "pay_top": top, "years_required": req,
            "pay_estimate": est["median"] if est else None, "visa_note": visa_note,
            "integrity_note": integrity_note, "apply_by": closes.isoformat() if closes else None,
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
