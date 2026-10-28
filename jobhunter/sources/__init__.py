"""Run every enabled source and return one de-duplicated DataFrame of postings, plus per-source
stats (rows, errors, seconds) that feed the source-health check."""
from __future__ import annotations

import logging
import re
import time

import pandas as pd

from ..common import JOB_COLUMNS, US_STATE_CODES
from ..logs import log
from ..profile import OTHER, REMOTE, UNSPECIFIED_KEY
from . import apis, ats

UNSPECIFIED = {"", "nan", "none", "us", "usa", "united states", "us, us"}
ONE_CALL_ATS = {"greenhouse", "lever", "ashby", "recruitee"}
US_STATES = US_STATE_CODES | {"us", "usa"}
ALL_SOURCES = ["jobspy", *apis.SOURCES, "company_feeds"]


class NoResults(RuntimeError):
    pass


def region(p, location, is_remote=None) -> str:
    loc = str(location).lower().strip()
    if str(is_remote).lower() == "true" or "remote" in loc:  # is_remote may be a numpy bool or NaN
        return REMOTE
    for key, pat in p.regions:
        if re.search(pat, loc):
            return key
    if loc in UNSPECIFIED:
        return UNSPECIFIED_KEY
    return OTHER


def remote_location_ok(p, location) -> bool:
    """A remote posting's location text is compatible with where you can work (search.remote_allowed).
    Plain "Remote", a US state code, or a city in one of your regions pass."""
    loc = str(location or "").lower()
    rest = re.sub(r"\bremote\b|[()\-–,/|:]", " ", loc).split()
    if not rest or loc in ("nan", "none"):
        return True
    if any(a in loc for a in p.remote_allowed):
        return True
    if len(rest) <= 2 and all(w.strip(".") in US_STATES for w in rest):
        return True
    return any(re.search(pat, loc) for _, pat in p.regions)


class _ErrorCounter(logging.Handler):
    """Counts WARNING records tagged with a source, so every source's failures are tallied the same way."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.counts: dict[str, int] = {}

    def emit(self, record):
        src = getattr(record, "source", None)
        if src:
            self.counts[src] = self.counts.get(src, 0) + 1


def run_jobspy(p) -> list:
    from jobspy import scrape_jobs  # imported here so `check` works without it

    frames = []
    for track, title in p.all_titles():
        passes = [(loc, {"hours_old": p.hours_old}) for loc in p.locations]
        if p.include_remote:
            # Indeed only allows one of hours_old / is_remote per call, so remote is its own pass
            passes.append(("United States", {"is_remote": True}))
        for loc, extra in passes:
            try:
                df = scrape_jobs(
                    site_name=p.sites, search_term=title, location=loc,
                    results_wanted=p.results_per_search, country_indeed=p.country,
                    description_format="markdown",
                    linkedin_fetch_description="linkedin" in p.sites,  # else LinkedIn rows have no description
                    **extra,
                )
            except Exception as e:  # boards fail intermittently; keep going
                log.warning(f"jobspy: {title} / {loc}: {e}", extra={"source": "jobspy"})
                continue
            finally:
                time.sleep(p.pause_seconds)  # LinkedIn rate-limits (429) without a pause
            if df is not None and len(df):
                df["track"] = track
                df["query"] = title
                frames.append(df)
                log.info(f"  {track:10} | {title[:40]:40} | {loc:16} | {len(df)}")
    return frames


def run_feeds(p) -> list:
    frames = []
    for f in p.feeds:
        rows = []
        for company, kind, slug in f["companies"]:
            try:
                rows += ats.list_postings(kind, company, slug, include=f["include"], exclude=f["exclude"])
            except Exception as e:  # a company moving ATS shouldn't kill the run
                log.warning(f"feed {company} ({kind}/{slug}): {e}", extra={"source": "company_feeds"})
        if rows:
            df = pd.DataFrame(rows)
            df["track"], df["query"] = f["track"], "company feed"
            # postings straight from the employer's ATS are verified by definition
            df["verified"], df["employer_url"] = "verified_open", df["job_url"]
            frames.append(df)
        log.info(f"  {f['track']:10} | company feeds ({len(f['companies'])} companies){'':8} | direct           | {len(rows)}")

    # companies.yaml: keep each company's roles that are close to one of your search titles
    rows = []
    for c in p.target_companies:
        try:
            one_call = c["ats"] in ONE_CALL_ATS  # these return descriptions with the listing
            if c["ats"] == "workday":
                # big Workday sites list thousands of jobs: use their search, once per title
                seen_urls, postings = set(), []
                for _, title in p.all_titles():
                    for r in ats.list_postings("workday", c.get("name") or c["slug"], c["slug"],
                                               with_description=False, search_text=title, max_jobs=60):
                        if r["job_url"] not in seen_urls:
                            seen_urls.add(r["job_url"])
                            postings.append(r)
            else:
                postings = ats.list_postings(c["ats"], c.get("name") or c["slug"], c["slug"], with_description=one_call)
        except Exception as e:
            log.warning(f"company {c.get('name')} ({c['ats']}/{c['slug']}): {e}", extra={"source": "company_feeds"})
            continue
        keep = []
        for r in postings:
            track, q = apis.best_track(r.get("title"), p)
            if track:
                r["track"], r["query"] = c.get("track") or track, q
                keep.append(r)
        if keep and c["ats"] == "workday":
            for r in keep:  # one search per kept posting, with its description
                try:
                    hits = ats.list_postings("workday", c.get("name") or c["slug"], c["slug"], with_description=True,
                                             search_text=r["title"], include=re.escape(r["title"].lower()), max_jobs=20)
                    r["description"] = next((h["description"] for h in hits if h["job_url"] == r["job_url"]),
                                            hits[0]["description"] if hits else "")
                except Exception as e:
                    log.warning(f"company {c.get('name')} description: {e}", extra={"source": "company_feeds"})
        elif keep and not one_call:
            # these ATSs need one more request per posting for the description: only for the keepers
            try:
                full = {r["job_url"]: r for r in ats.list_postings(
                    c["ats"], c.get("name") or c["slug"], c["slug"], with_description=True,
                    include="|".join(re.escape(r["title"].lower()) for r in keep))}
                keep = [{**r, "description": full.get(r["job_url"], {}).get("description", "")} for r in keep]
            except Exception as e:
                log.warning(f"company {c.get('name')} descriptions: {e}", extra={"source": "company_feeds"})
        rows += keep
    if rows:
        df = pd.DataFrame(rows)
        df["verified"], df["employer_url"] = "verified_open", df["job_url"]
        frames.append(df)
    if p.target_companies:
        log.info(f"  {'companies':10} | companies.yaml ({len(p.target_companies)} companies){'':7} | direct           | {len(rows)}")
    return frames


def _rows(frames) -> int:
    return int(sum(len(f) for f in frames if f is not None))


def gather(p, only=None):
    """Fetch from every enabled source (or just `only`), filter to your regions, de-duplicate.
    Returns (jobs DataFrame, stats dict: source -> {rows, errors, seconds})."""
    counter = _ErrorCounter()
    log.addHandler(counter)
    frames, stats = [], {}

    def want(name):
        return (only is None or name in only) and p.source_on(name)

    def run(name, fn):
        t0 = time.time()
        try:
            got = fn()
        except Exception as e:
            log.warning(f"{name}: {e}", extra={"source": name})
            got = []
        if isinstance(got, list) and got and isinstance(got[0], dict):
            got = [pd.DataFrame(got)]
        got = [f for f in got if f is not None and len(f)]
        frames.extend(got)
        stats[name] = {"rows": _rows(got), "seconds": round(time.time() - t0, 1)}

    try:
        if want("jobspy") and p.tracks:
            run("jobspy", lambda: run_jobspy(p))
        for name, fn in apis.SOURCES.items():
            if want(name):
                run(name, lambda fn=fn: fn(p))
        if want("company_feeds") and (p.feeds or p.target_companies):
            run("company_feeds", lambda: run_feeds(p))
    finally:
        log.removeHandler(counter)
    for name in stats:
        stats[name]["errors"] = counter.counts.get(name, 0)

    if not frames:
        raise NoResults("No results came back from any source. Check your network, or run with fewer sources.")

    out = pd.concat([f.dropna(axis=1, how="all") for f in frames], ignore_index=True)
    for c in JOB_COLUMNS:
        if c not in out:
            out[c] = None
    out = out[out["job_url"].notna()].drop_duplicates(subset="job_url")

    out["_region"] = [region(p, loc, rem) for loc, rem in zip(out["location"], out["is_remote"], strict=True)]
    before = len(out)
    drop = {OTHER} if p.keep_unspecified else {OTHER, UNSPECIFIED_KEY}
    if not p.include_remote:
        drop.add(REMOTE)
    # "Remote, Poland" / "Remote EMEA" aren't remote jobs you can take: same rule as the remote boards
    remote_elsewhere = (out["_region"] == REMOTE) & ~out["location"].map(lambda loc: remote_location_ok(p, loc))
    out.loc[remote_elsewhere, "_region"] = OTHER
    out = out[~out["_region"].isin(drop)]
    log.info(f"\nLocation filter dropped {before - len(out)} of {before} jobs outside your regions.")

    # The same role posted on several boards / cities: keep the copy that's on the employer's site
    # if there is one, then your highest-priority region, then the one that shows pay.
    out["_key"] = (out["company"].astype(str).str.lower().str.strip() + "|"
                   + out["title"].astype(str).str.lower().str.replace(r"[^a-z0-9]+", " ", regex=True).str.strip())
    out["_has_salary"] = out["max_amount"].notna()
    verified = out["verified"] if "verified" in out else pd.Series(index=out.index, dtype=object)
    out["_direct"] = verified.eq("verified_open")
    out["_rank"] = out["_region"].map(p.region_order)
    out = (out.sort_values(["_direct", "_rank", "_has_salary"], ascending=[False, True, False])
              .drop_duplicates(subset="_key"))
    log.info(f"Duplicate filter left {len(out)} unique roles.")
    out["region"] = out["_region"]
    jobs = out.drop(columns=["_region", "_key", "_has_salary", "_direct", "_rank"]).reset_index(drop=True)
    return jobs, stats
