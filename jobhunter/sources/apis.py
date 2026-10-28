"""Job boards with official APIs. Keyless ones are on by default; keyed ones turn on when their
environment variables are set (see profile.SOURCE_KEYS).

Boards with real keyword search (Adzuna, USAJobs, Jooble, Himalayas) are queried once per
title. Boards without it (Remotive, RemoteOK, The Muse, Arbeitnow) are pulled once and filtered
locally: a posting is kept when its title is close enough to one of your search titles.
"""
import os
import time

from ..common import html_to_text, http_json, parse_salary_text, qs, title_similarity
from ..logs import log


def best_track(title, profile):
    """(track, query) of the closest search title, or (None, None) below the threshold."""
    best, best_sim = (None, None), 0.0
    for track, q in profile.all_titles():
        sim = title_similarity(title, q)
        if sim > best_sim:
            best, best_sim = (track, q), sim
    return best if best_sim >= profile.title_match_threshold else (None, None)


def remote_ok_for(profile, loc_text) -> bool:
    loc = str(loc_text or "").lower().strip()
    if not loc or loc in {"us", "remote"}:
        return True
    return any(a in loc for a in profile.remote_allowed)


def _log(name, n, extra=""):
    log.info(f"  {name:10} | {extra[:40]:40} | {'api':16} | {n}", extra={"source": name, "rows": n})


# ----------------------------- keyless --------------------------------------

def remotive(profile):
    if not profile.include_remote:
        return []
    data = http_json("https://remotive.com/api/remote-jobs")
    rows = []
    for j in data.get("jobs", []):
        track, q = best_track(j.get("title"), profile)
        if not track or not remote_ok_for(profile, j.get("candidate_required_location")):
            continue
        lo, hi, iv = parse_salary_text(j.get("salary"))
        rows.append(dict(title=j["title"], company=j.get("company_name"), location="Remote",
                         is_remote=True, job_url=j["url"], date_posted=str(j.get("publication_date", ""))[:10],
                         description=html_to_text(j.get("description")), site="remotive",
                         min_amount=lo, max_amount=hi, interval=iv, track=track, query=q))
    _log("remotive", len(rows), "full feed, filtered by title")
    return rows


def himalayas(profile):
    if not profile.include_remote:
        return []
    rows, seen = [], set()
    for track, q in profile.all_titles():
        try:
            data = http_json(f"https://himalayas.app/jobs/api/search?{qs({'q': q, 'page': 1})}")
        except Exception as e:
            log.warning(f"himalayas / {q}: {e}", extra={"source": "himalayas"})
            continue
        n = 0
        for j in data.get("jobs", []):
            url = j.get("applicationLink") or j.get("guid")
            restr = ", ".join(j.get("locationRestrictions") or [])
            if url in seen or not remote_ok_for(profile, restr):
                continue
            seen.add(url)
            posted = time.strftime("%Y-%m-%d", time.gmtime(int(j["pubDate"]))) if j.get("pubDate") else ""
            rows.append(dict(title=j["title"], company=j.get("companyName"), location="Remote" + (f" ({restr})" if restr else ""),
                             is_remote=True, job_url=url, date_posted=posted,
                             description=html_to_text(j.get("description")), site="himalayas",
                             min_amount=j.get("minSalary"), max_amount=j.get("maxSalary"),
                             interval="yearly" if j.get("salaryPeriod") in (None, "annual") else j.get("salaryPeriod"),
                             currency=j.get("currency"), track=track, query=q))
            n += 1
        time.sleep(1)
    _log("himalayas", len(rows), "per title")
    return rows


def remoteok(profile):
    if not profile.include_remote:
        return []
    data = http_json("https://remoteok.com/api")
    rows = []
    for j in (data or [])[1:]:  # first element is the API's legal notice
        track, q = best_track(j.get("position"), profile)
        if not track or not remote_ok_for(profile, j.get("location")):
            continue
        where = "Remote" + (f" ({j['location']})" if j.get("location") else "")
        rows.append(dict(title=j["position"], company=j.get("company"), location=where,
                         is_remote=True, job_url=j.get("url"), date_posted=str(j.get("date", ""))[:10],
                         description=html_to_text(j.get("description")), site="remoteok",
                         min_amount=j.get("salary_min") or None, max_amount=j.get("salary_max") or None,
                         interval="yearly", track=track, query=q))
    _log("remoteok", len(rows), "latest feed, filtered by title")
    return rows


def themuse(profile, pages_per_location=3):
    rows, seen = [], set()
    locs = list(profile.locations) + (["Flexible / Remote"] if profile.include_remote else [])
    for loc in locs:
        for page in range(pages_per_location):
            try:
                params = {"page": page, "location": loc, "descending": "true", "api_key": os.environ.get("THEMUSE_API_KEY")}
                data = http_json(f"https://www.themuse.com/api/public/jobs?{qs(params)}")
            except Exception as e:
                log.warning(f"themuse / {loc}: {e}", extra={"source": "themuse"})
                break
            for j in data.get("results", []):
                url = (j.get("refs") or {}).get("landing_page")
                track, q = best_track(j.get("name"), profile)
                if not track or url in seen:
                    continue
                seen.add(url)
                locs_s = "; ".join(x.get("name", "") for x in j.get("locations", []))
                rows.append(dict(title=j["name"], company=(j.get("company") or {}).get("name"), location=locs_s,
                                 is_remote="remote" in locs_s.lower() or "flexible" in locs_s.lower(),
                                 job_url=url, date_posted=str(j.get("publication_date", ""))[:10],
                                 description=html_to_text(j.get("contents")), site="themuse", track=track, query=q))
            if page + 1 >= data.get("page_count", 0):
                break
            time.sleep(0.5)
    _log("themuse", len(rows), "by location, filtered by title")
    return rows


def arbeitnow(profile, pages=3):
    rows = []
    for page in range(1, pages + 1):
        data = http_json(f"https://www.arbeitnow.com/api/job-board-api?page={page}")
        for j in data.get("data", []):
            track, q = best_track(j.get("title"), profile)
            if not track:
                continue
            rows.append(dict(title=j["title"], company=j.get("company_name"), location=j.get("location"),
                             is_remote=bool(j.get("remote")), job_url=j.get("url"),
                             date_posted=time.strftime("%Y-%m-%d", time.gmtime(j["created_at"])) if j.get("created_at") else "",
                             description=html_to_text(j.get("description")), site="arbeitnow", track=track, query=q))
        if not (data.get("links") or {}).get("next"):
            break
    _log("arbeitnow", len(rows), "latest pages, filtered by title")
    return rows


# ----------------------------- keyed ----------------------------------------

def _passes(profile):
    """(location, is_remote_pass) pairs for boards with a location parameter."""
    out = [(loc, False) for loc in profile.locations]
    if profile.include_remote:
        out.append(("", True))
    return out


def adzuna(profile):
    app_id, app_key = os.environ["ADZUNA_APP_ID"], os.environ["ADZUNA_APP_KEY"]
    rows = []
    for track, q in profile.all_titles():
        for loc, remote in _passes(profile):
            what = q + (" remote" if remote else "")
            try:
                data = http_json(f"https://api.adzuna.com/v1/api/jobs/{profile.api_country}/search/1?" + qs({
                    "app_id": app_id, "app_key": app_key, "what": what, "where": loc,
                    "results_per_page": min(50, profile.results_per_search),
                    "max_days_old": max(1, profile.hours_old // 24), "content-type": "application/json"}))
            except Exception as e:
                log.warning(f"adzuna / {q} / {loc or 'remote'}: {e}", extra={"source": "adzuna"})
                continue
            for j in data.get("results", []):
                place = (j.get("location") or {}).get("display_name", "")
                rows.append(dict(title=j.get("title"), company=(j.get("company") or {}).get("display_name"),
                                 location=place, is_remote=remote and "remote" in str(j.get("description", "")).lower(),
                                 job_url=j.get("redirect_url"), date_posted=str(j.get("created", ""))[:10],
                                 description=html_to_text(j.get("description")), site="adzuna",
                                 min_amount=j.get("salary_min"), max_amount=j.get("salary_max"),
                                 interval="yearly", track=track, query=q,
                                 note="adzuna descriptions are snippets"))
            time.sleep(0.5)
    _log("adzuna", len(rows), "per title x location")
    return rows


def usajobs(profile):
    headers = {"Host": "data.usajobs.gov", "User-Agent": os.environ["USAJOBS_EMAIL"],
               "Authorization-Key": os.environ["USAJOBS_API_KEY"]}
    rows, seen = [], set()
    for track, q in profile.all_titles():
        for loc, remote in _passes(profile):
            params = {"Keyword": q, "ResultsPerPage": min(250, profile.results_per_search * 4),
                      "DatePosted": min(60, max(1, profile.hours_old // 24))}
            if remote:
                params["RemoteIndicator"] = "True"
            else:
                params["LocationName"] = loc
            try:
                data = http_json("https://data.usajobs.gov/api/search?" + qs(params), headers=headers)
            except Exception as e:
                log.warning(f"usajobs / {q} / {loc or 'remote'}: {e}", extra={"source": "usajobs"})
                continue
            for item in ((data or {}).get("SearchResult") or {}).get("SearchResultItems", []):
                d = item.get("MatchedObjectDescriptor", {})
                url = d.get("PositionURI")
                if url in seen:
                    continue
                seen.add(url)
                pay = (d.get("PositionRemuneration") or [{}])[0]
                summary = ((d.get("UserArea") or {}).get("Details") or {})
                rows.append(dict(title=d.get("PositionTitle"), company=d.get("OrganizationName"),
                                 location=d.get("PositionLocationDisplay"), is_remote=remote, job_url=url,
                                 date_posted=str(d.get("PublicationStartDate", ""))[:10],
                                 description="\n".join(str(x) for x in [summary.get("JobSummary"),
                                                                        d.get("QualificationSummary")] if x),
                                 site="usajobs", min_amount=pay.get("MinimumRange"), max_amount=pay.get("MaximumRange"),
                                 interval={"PA": "yearly", "PH": "hourly"}.get(pay.get("RateIntervalCode"), "yearly"),
                                 track=track, query=q, verified="verified_open",
                                 employer_url=url, closes=str(d.get("ApplicationCloseDate", ""))[:10]))
            time.sleep(0.5)
    _log("usajobs", len(rows), "per title x location")
    return rows


def jooble(profile):
    key = os.environ["JOOBLE_API_KEY"]
    rows = []
    for track, q in profile.all_titles():
        for loc, remote in _passes(profile):
            try:
                data = http_json(f"https://jooble.org/api/{key}", method="POST",
                                 body={"keywords": q + (" remote" if remote else ""), "location": loc, "page": "1"})
            except Exception as e:
                log.warning(f"jooble / {q} / {loc or 'remote'}: {e}", extra={"source": "jooble"})
                continue
            for j in (data or {}).get("jobs", []):
                lo, hi, iv = parse_salary_text(j.get("salary"))
                rows.append(dict(title=html_to_text(j.get("title")), company=j.get("company"), location=j.get("location"),
                                 is_remote=remote or "remote" in str(j.get("location", "")).lower(),
                                 job_url=j.get("link"), date_posted=str(j.get("updated", ""))[:10],
                                 description=html_to_text(j.get("snippet")), site="jooble",
                                 min_amount=lo, max_amount=hi, interval=iv, track=track, query=q,
                                 note="jooble descriptions are snippets"))
            time.sleep(0.5)
    _log("jooble", len(rows), "per title x location")
    return rows


SOURCES = {"remotive": remotive, "himalayas": himalayas, "remoteok": remoteok, "themuse": themuse,
           "arbeitnow": arbeitnow, "adzuna": adzuna, "usajobs": usajobs, "jooble": jooble}
