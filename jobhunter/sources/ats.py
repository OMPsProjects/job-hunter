"""Employer applicant-tracking systems with public, unauthenticated job APIs.

Used two ways: as job sources (company_feeds in the profile) and for verification
(is this posting live on the employer's own careers site?).

Every function returns a list of job dicts with JOB_COLUMNS keys. `include`/`exclude` are
regexes on the lowercased title; descriptions are fetched only for titles that pass them
when the ATS needs a second request per job.
"""
import re
import time
import urllib.parse

from ..common import html_to_text, http_json, qs

MATCH_ALL, MATCH_NONE = ".", r"(?!x)x"


def _keep(title, include, exclude):
    t = str(title or "").lower()
    return bool(re.search(include or MATCH_ALL, t)) and not re.search(exclude or MATCH_NONE, t)


def _row(**kw):
    kw.setdefault("is_remote", "remote" in str(kw.get("location", "")).lower())
    return kw


def greenhouse(company, slug, include=None, exclude=None, with_description=True):
    data = http_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content={'true' if with_description else 'false'}")
    rows = []
    for j in data.get("jobs", []):
        if not _keep(j.get("title"), include, exclude):
            continue
        loc = (j.get("location") or {}).get("name", "")
        rows.append(_row(title=j["title"], company=company, location=loc, job_url=j["absolute_url"],
                         date_posted=str(j.get("first_published") or j.get("updated_at") or "")[:10],
                         description=html_to_text(j.get("content")), site="greenhouse",
                         req_id=str(j.get("requisition_id") or j.get("id"))))
    return rows


def lever(company, slug, include=None, exclude=None, with_description=True):
    rows = []
    for j in http_json(f"https://api.lever.co/v0/postings/{slug}?mode=json") or []:
        if not _keep(j.get("text"), include, exclude):
            continue
        loc = (j.get("categories") or {}).get("location", "") or ""
        sal = j.get("salaryRange") or {}
        posted = ""
        if j.get("createdAt"):
            posted = time.strftime("%Y-%m-%d", time.gmtime(j["createdAt"] / 1000))
        rows.append(_row(title=j["text"], company=company, location=loc,
                         is_remote=j.get("workplaceType") == "remote" or "remote" in loc.lower(),
                         job_url=j["hostedUrl"], date_posted=posted,
                         description=j.get("descriptionPlain", "") + "\n" + " ".join(
                             html_to_text(x.get("content")) for x in j.get("lists", []) or []),
                         site="lever", min_amount=sal.get("min"), max_amount=sal.get("max"),
                         interval="yearly" if sal.get("interval") == "per-year-salary" else sal.get("interval"),
                         currency=sal.get("currency"), req_id=j.get("id")))
    return rows


def ashby(company, slug, include=None, exclude=None, with_description=True):
    data = http_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
    rows = []
    for j in data.get("jobs", []):
        if not _keep(j.get("title"), include, exclude) or j.get("isListed") is False:
            continue
        loc = j.get("location", "") or ""
        lo = hi = None
        for comp in ((j.get("compensation") or {}).get("summaryComponents") or []):
            if comp.get("compensationType") == "Salary":
                lo, hi = comp.get("minValue"), comp.get("maxValue")
        rows.append(_row(title=j["title"], company=company, location=loc,
                         is_remote=bool(j.get("isRemote")) or "remote" in loc.lower(),
                         job_url=j["jobUrl"], date_posted=str(j.get("publishedAt", ""))[:10],
                         description=j.get("descriptionPlain", ""), site="ashby",
                         min_amount=lo, max_amount=hi, interval="yearly" if hi else None, req_id=j.get("id")))
    return rows


def smartrecruiters(company, slug, include=None, exclude=None, with_description=True, max_jobs=1000):
    rows, offset = [], 0
    while offset < max_jobs:
        page = http_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?{qs({'limit': 100, 'offset': offset})}")
        content = page.get("content", [])
        for j in content:
            if not _keep(j.get("name"), include, exclude):
                continue
            loc = (j.get("location") or {})
            loc_s = loc.get("fullLocation") or ", ".join(x for x in [loc.get("city"), loc.get("region"), loc.get("country")] if x)
            desc = ""
            if with_description:
                try:
                    d = http_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{j['id']}")
                    secs = ((d.get("jobAd") or {}).get("sections") or {})
                    desc = "\n".join(html_to_text((secs.get(k) or {}).get("text")) for k in
                                     ("companyDescription", "jobDescription", "qualifications", "additionalInformation"))
                except Exception:
                    pass
                time.sleep(0.2)
            rows.append(_row(title=j["name"], company=company, location=loc_s,
                             is_remote=bool(loc.get("remote")) or "remote" in loc_s.lower(),
                             job_url=f"https://jobs.smartrecruiters.com/{slug}/{j['id']}",
                             date_posted=str(j.get("releasedDate", ""))[:10], description=desc,
                             site="smartrecruiters", req_id=j.get("refNumber") or j.get("id")))
        offset += 100
        if not content or offset >= page.get("totalFound", 0):
            break
    return rows


def workable(company, slug, include=None, exclude=None, with_description=True):
    rows, token = [], None
    for _ in range(20):  # page cap
        body = {"query": "", "location": [], "department": [], "worktype": [], "remote": []}
        if token:
            body["token"] = token
        page = http_json(f"https://apply.workable.com/api/v3/accounts/{slug}/jobs", method="POST", body=body, retries=2)
        for j in page.get("results", []):
            if not _keep(j.get("title"), include, exclude):
                continue
            loc = j.get("location") or {}
            loc_s = ", ".join(x for x in [loc.get("city"), loc.get("region"), loc.get("country")] if x)
            desc = ""
            if with_description:
                try:
                    d = http_json(f"https://apply.workable.com/api/v2/accounts/{slug}/jobs/{j['shortcode']}", retries=2)
                    desc = "\n".join(html_to_text(d.get(k)) for k in ("description", "requirements", "benefits"))
                except Exception:
                    pass
                time.sleep(0.5)
            rows.append(_row(title=j["title"], company=company, location=loc_s,
                             is_remote=bool(j.get("remote")) or "remote" in loc_s.lower(),
                             job_url=f"https://apply.workable.com/{slug}/j/{j['shortcode']}/",
                             date_posted=str(j.get("published", ""))[:10], description=desc,
                             site="workable", req_id=j.get("shortcode")))
        token = page.get("nextPage")
        if not token:
            break
    return rows


def recruitee(company, slug, include=None, exclude=None, with_description=True):
    data = http_json(f"https://{slug}.recruitee.com/api/offers/")
    rows = []
    for j in data.get("offers", []):
        if not _keep(j.get("title"), include, exclude):
            continue
        loc = j.get("location") or ", ".join(x for x in [j.get("city"), j.get("country")] if x)
        sal = j.get("salary") or {}
        rows.append(_row(title=j["title"], company=company, location=loc,
                         is_remote=bool(j.get("remote")) or "remote" in str(loc).lower(),
                         job_url=j.get("careers_url") or j.get("careers_apply_url"),
                         date_posted=str(j.get("published_at", ""))[:10],
                         description=html_to_text(j.get("description")) + "\n" + html_to_text(j.get("requirements")),
                         site="recruitee", min_amount=sal.get("min"), max_amount=sal.get("max"),
                         interval=sal.get("period"), req_id=j.get("id")))
    return rows


def workday(company, slug, include=None, exclude=None, with_description=True, search_text="", max_jobs=2000):
    """slug = 'host|tenant|site', e.g. 'equinix.wd1|equinix|External' from
    https://equinix.wd1.myworkdayjobs.com/External."""
    host, tenant, site = slug.split("|")
    base = f"https://{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"
    rows, offset, total = [], 0, None
    while offset < max_jobs:
        page = http_json(f"{base}/jobs", method="POST",
                         body={"limit": 20, "offset": offset, "searchText": search_text, "appliedFacets": {}})
        if total is None:  # Workday only reports the total on the first page
            total = page.get("total", 0)
        posts = page.get("jobPostings", [])
        for p in posts:
            if not _keep(p.get("title"), include, exclude):
                continue
            info = {}
            if with_description:
                try:
                    info = http_json(f"{base}{p['externalPath']}").get("jobPostingInfo", {})
                except Exception:
                    info = {}
                time.sleep(0.3)
            loc = info.get("location") or p.get("locationsText", "")
            rows.append(_row(title=p["title"], company=company, location=loc,
                             is_remote="remote" in str(info.get("remoteType", loc)).lower(),
                             job_url=info.get("externalUrl") or f"https://{host}.myworkdayjobs.com/{site}{p['externalPath']}",
                             date_posted=str(info.get("startDate", ""))[:10],
                             description=html_to_text(info.get("jobDescription")), site="workday",
                             req_id=info.get("jobReqId") or (p.get("bulletFields") or [None])[0]))
        offset += 20
        if not posts or offset >= (total or 0):
            break
    return rows


FETCHERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "smartrecruiters": smartrecruiters,
            "workable": workable, "recruitee": recruitee, "workday": workday}


def list_postings(ats, company, slug, include=None, exclude=None, with_description=True, **kw):
    return FETCHERS[ats](company, slug, include=include, exclude=exclude, with_description=with_description, **kw)


# URL patterns that identify a posting as already being on an employer ATS.
ATS_URL_PATTERNS = [
    ("greenhouse", re.compile(r"greenhouse\.io/embed/job_app\?.*?for=([^&#]+)")),
    ("greenhouse", re.compile(r"(?:boards|job-boards)\.greenhouse\.io/(?!embed/)([^/?#]+)")),
    ("lever", re.compile(r"jobs\.lever\.co/([^/?#]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([^/?#]+)")),
    ("smartrecruiters", re.compile(r"jobs\.smartrecruiters\.com/([^/?#]+)")),
    ("workable", re.compile(r"apply\.workable\.com/([^/?#]+)")),
    ("recruitee", re.compile(r"https?://([^./]+)\.recruitee\.com")),
    ("workday", re.compile(r"https?://([^./]+\.wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/?#]+)")),
    ("icims", re.compile(r"https?://([^./]+)\.icims\.com")),
]


def ats_from_url(url):
    """('greenhouse', 'dealpath') if the URL is on a known ATS, else (None, None).
    Workday returns ('workday', 'host|?|site') - tenant isn't in the public URL, so it's '?'."""
    u = urllib.parse.unquote(str(url or ""))
    for ats, rx in ATS_URL_PATTERNS:
        m = rx.search(u)
        if m:
            if ats == "workday":
                host, site = m.group(1), m.group(2)
                return ats, f"{host}|{host.split('.')[0]}|{site}"
            return ats, m.group(1)
    return None, None
