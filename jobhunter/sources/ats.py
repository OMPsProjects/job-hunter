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


# ----------------------------- Oracle Recruiting Cloud ------------------------
# Big employers (JPMorgan and many other banks) use Oracle's candidate site at
# <tenant>.fa.<region>.oraclecloud.com/hcmUI/CandidateExperience/en/sites/<site>/job/<id>.
# Its public REST API answers without a login.

_ORACLE_HOST = re.compile(r"[a-z0-9-]{1,63}\.fa(?:\.[a-z0-9-]{1,30}){0,3}\.oraclecloud\.com")
_ORACLE_SITE = re.compile(r"[A-Za-z0-9_]{1,40}")


def _oracle_api(host, resource, finder, extra=""):
    # the finder's ; , " = are part of Oracle's syntax and must reach the server unescaped
    f = urllib.parse.quote(finder, safe=';,="')
    return http_json(f"https://{host}/hcmRestApi/resources/latest/{resource}?onlyData=true{extra}&finder={f}")


def oracle_job(host, site, job_id):
    """The posting's details, or None when Oracle no longer serves it (closed or removed)."""
    if not (_ORACLE_HOST.fullmatch(host) and _ORACLE_SITE.fullmatch(site) and re.fullmatch(r"\d{1,20}", str(job_id))):
        raise ValueError("not an Oracle posting")
    data = _oracle_api(host, "recruitingCEJobRequisitionDetails", f'ById;Id="{job_id}",siteNumber={site}', "&expand=all")
    items = (data or {}).get("items") or []
    return items[0] if items else None


def oracle(company, slug, include=None, exclude=None, with_description=True, search_text="", max_jobs=200):
    """slug = 'host|site', e.g. 'jpmc.fa.oraclecloud.com|CX_1001'. Searches by keyword (big
    employers list thousands of roles)."""
    host, site = slug.split("|")
    kw = re.sub(r'["\\;,]', " ", str(search_text or "")).strip()[:100]
    rows, offset = [], 0
    while offset < max_jobs:
        finder = f"findReqs;siteNumber={site},limit=25,offset={offset},sortBy=POSTING_DATES_DESC"
        if kw:
            finder += f',keyword="{kw}"'
        data = _oracle_api(host, "recruitingCEJobRequisitions", finder, "&expand=requisitionList")
        item = ((data or {}).get("items") or [{}])[0]
        reqs = item.get("requisitionList") or []
        for j in reqs:
            if not _keep(j.get("Title"), include, exclude) or not re.fullmatch(r"\d{1,20}", str(j.get("Id"))):
                continue
            desc = j.get("ShortDescriptionStr") or ""
            if with_description:
                try:
                    d = oracle_job(host, site, j["Id"]) or {}
                    desc = "\n\n".join(str(d.get(k) or "") for k in ("ExternalDescriptionStr", "ExternalResponsibilitiesStr",
                                                                    "ExternalQualificationsStr")) or desc
                except Exception:
                    pass
                time.sleep(0.3)
            rows.append(_row(title=j.get("Title"), company=company, location=j.get("PrimaryLocation", ""),
                             is_remote="remote" in str(j.get("WorkplaceType") or j.get("PrimaryLocation") or "").lower(),
                             job_url=f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{j['Id']}",
                             date_posted=str(j.get("PostedDate") or "")[:10], description=html_to_text(desc),
                             site="oracle", req_id=str(j["Id"])))
        offset += 25
        if len(reqs) < 25 or offset >= int(item.get("TotalJobsCount") or 0):
            break
        time.sleep(0.3)
    return rows


# ----------------------------- SAP SuccessFactors -----------------------------
# Career Site Builder sites (jobs.<employer>.com/job/<City-Title>/<id>/) are server-rendered
# pages on the employer's own domain. There's no public API, so the search page is read; the
# host is the board id. Sites behind a bot check (some are) can't be read and stay unverified.

SF_JOB_PATH = re.compile(r"^/job/[^/]+/(\d{6,12})/?$")
_SF_MARK = re.compile(r"rmkcdn\.successfactors\.com|jobs2web|j2w\.|career site builder", re.I)
_SF_ROW = re.compile(r'(?s)<tr class="data-row[^"]*"[^>]*>.*?(?=<tr class="data-row|</tbody>|$)')


def _sf_get(url):
    from ..common import open_public, read_capped
    with open_public(url, headers={"Accept": "text/html"}, timeout=20) as r:
        return r.geturl(), read_capped(r, 1_500_000).decode("utf-8", "ignore")


def is_successfactors_page(html) -> bool:
    return bool(_SF_MARK.search(html or ""))


_SF_CLOSED = re.compile(r"not accepting (?:any )?(?:further |more |new )?applica|no longer (?:accepting|available)|"
                        r"position has been filled|job (?:has )?expired|requisition (?:is )?closed", re.I)


def successfactors_job(url):
    """'open', 'closed' or None (not a SuccessFactors page / couldn't tell). A removed posting
    sends you to the site's error or search page; a closed one often stays at its address with
    "not accepting any further applicants" and no description."""
    final, html = _sf_get(url)
    if not is_successfactors_page(html):
        return None
    path = urllib.parse.urlsplit(final).path
    if "/errorpage" in path or path.rstrip("/") in ("/search", "") or not SF_JOB_PATH.match(path):
        return "closed"
    from ..common import strip_blocks
    visible = re.sub(r"(?s)<[^>]+>", " ", strip_blocks(html))
    if _SF_CLOSED.search(visible):
        return "closed"
    return "open" if 'class="jobdescription"' in html else None


def successfactors(company, slug, include=None, exclude=None, with_description=True, search_text="", max_jobs=200):
    """slug = the career site's host, e.g. 'jobs.scotiabank.com'."""
    rows, seen, start = [], set(), 0
    while start < max_jobs:
        _, html = _sf_get(f"https://{slug}/search/?{qs({'q': search_text or None, 'startrow': start})}")
        found = 0
        for block in _SF_ROW.findall(html):
            m = re.search(r'<a(?=[^>]*class="jobTitle-link")[^>]*href="(/job/[^"]+)"[^>]*>([^<]+)</a>', block)
            if not m or not SF_JOB_PATH.match(m.group(1)) or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            found += 1
            title = html_to_text(m.group(2))
            if not _keep(title, include, exclude):
                continue
            loc = re.search(r'class="jobLocation"[^>]*>\s*([^<]{1,120})', block)
            url = f"https://{slug}{m.group(1)}"
            desc = ""
            if with_description:
                try:
                    _, page = _sf_get(url)
                    d = re.search(r'(?s)<span class="jobdescription">(.*?)</span>\s*</div>', page)
                    desc = html_to_text(d.group(1)) if d else ""
                except Exception:
                    pass
                time.sleep(0.3)
            rows.append(_row(title=title, company=company, location=(loc.group(1).strip() if loc else ""),
                             job_url=url, description=desc, site="successfactors",
                             req_id=SF_JOB_PATH.match(m.group(1)).group(1)))
        if found < 25:
            break
        start += 25
        time.sleep(0.5)
    return rows


FETCHERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "smartrecruiters": smartrecruiters,
            "workable": workable, "recruitee": recruitee, "workday": workday, "oracle": oracle,
            "successfactors": successfactors}
# Boards too big to list whole: searched once per title instead.
SEARCH_BOARDS = {"workday", "oracle", "successfactors"}


# What a board id may look like. A slug becomes part of a URL (for Recruitee and Workday, part of
# the host name), so anything else - from a posting link, companies.yaml or the downloaded
# directory - is refused before a request is made.
_SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}")
_HOST_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")


def valid_slug(ats, slug) -> bool:
    slug = str(slug or "")
    if ats == "workday":
        parts = slug.split("|")
        if len(parts) != 3:
            return False
        host, tenant, site = parts
        return bool(re.fullmatch(r"[A-Za-z0-9-]{1,63}\.wd\d{1,3}", host) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}|\?", tenant)
                    and _SLUG.fullmatch(site))
    if ats in ("recruitee", "icims"):
        return bool(_HOST_LABEL.fullmatch(slug))
    if ats == "oracle":
        host, _, site = slug.partition("|")
        return bool(_ORACLE_HOST.fullmatch(host) and _ORACLE_SITE.fullmatch(site))
    if ats == "successfactors":  # a public host name; open_public re-checks where it points
        labels = slug.split(".")
        return (2 <= len(labels) <= 6 and all(_HOST_LABEL.fullmatch(x) for x in labels)
                and not labels[-1].isdigit() and len(slug) <= 200)
    return bool(_SLUG.fullmatch(slug)) and ".." not in slug


def list_postings(ats, company, slug, include=None, exclude=None, with_description=True, **kw):
    if not valid_slug(ats, slug):
        raise ValueError(f"not a valid {ats} board id: {slug!r}")
    return FETCHERS[ats](company, slug, include=include, exclude=exclude, with_description=with_description, **kw)


# URL patterns that identify a posting as already being on an employer ATS.
ATS_URL_PATTERNS = [
    ("greenhouse", re.compile(r"greenhouse\.io/embed/job_app\?.*?for=([^&#]+)")),
    ("greenhouse", re.compile(r"(?:boards|job-boards)\.greenhouse\.io/(?!embed/)([^/?#]+)")),
    ("lever", re.compile(r"jobs\.lever\.co/([^/?#]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([^/?#]+)")),
    ("smartrecruiters", re.compile(r"jobs\.smartrecruiters\.com/([^/?#]+)")),
    ("workable", re.compile(r"apply\.workable\.com/([^/?#]+)")),
    ("recruitee", re.compile(r"^https?://([^./?#@:]+)\.recruitee\.com(?:[/:?#]|$)")),
    ("workday", re.compile(r"^https?://([^./?#@:]+\.wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/?#]+)")),
    ("icims", re.compile(r"^https?://([^./?#@:]+)\.icims\.com(?:[/:?#]|$)")),
    ("oracle", re.compile(r"^https://([a-z0-9-]+\.fa(?:\.[a-z0-9-]+){0,3}\.oraclecloud\.com)/hcmUI/CandidateExperience/"
                          r"[a-z]{2}(?:-[A-Za-z]{2})?/sites/([A-Za-z0-9_]+)(?:[/?#]|$)")),
]


_UUID_RX = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def posting_key(url):
    """The same posting's identity whatever site linked to it, or None when the link isn't an
    employer ATS posting. Two rows with the same key are one job, even when the sources spell the
    company differently ('Brown & Brown' / 'Bbinsurance').

    Greenhouse ids and Lever/Ashby UUIDs are unique across all employers; Workday req numbers and
    other ATS ids only within one employer's board, so the board is part of the key."""
    u = urllib.parse.unquote(str(url or "")).strip()
    if not u.startswith(("https://", "http://")):
        return None
    m = re.search(r"[?&#]gh_jid=(\d{5,})", u)  # Greenhouse on the employer's own domain
    if m:
        return f"greenhouse:{m.group(1)}"
    kind, slug = ats_from_url(u)
    parts = urllib.parse.urlsplit(u)
    if not kind:
        m = SF_JOB_PATH.match(parts.path)  # Career Site Builder shape: the id is unique on its host
        return f"successfactors:{(parts.hostname or '').lower()}:{m.group(1)}" if m and parts.hostname else None
    path = parts.path.rstrip("/")
    if kind == "oracle":
        m = re.search(r"/(?:job|requisitions/preview)/(\d{1,20})$", path)
        return f"oracle:{slug.split('|')[0]}:{m.group(1)}" if m else None
    if kind == "greenhouse":
        m = re.search(r"/jobs/(\d{5,})", path) or re.search(r"[?&]token=(\d{5,})", u)
        return f"greenhouse:{m.group(1)}" if m else None
    if kind in ("lever", "ashby"):
        m = _UUID_RX.search(path)
        return f"{kind}:{m.group(0).lower()}" if m else None
    if kind == "workday":
        # .../job/<City>/<Title-Words>_<REQ>  ->  the req id, e.g. R1021400-1 or R26_0000003297-1
        last = path.rsplit("/", 1)[-1]
        if "/job/" not in path or "_" not in last:
            return None
        tenant = slug.split("|")[0].split(".")[0].lower()
        return f"workday:{tenant}:{last.split('_', 1)[1].lower()}"
    if kind == "workable":
        m = re.search(r"/j/([A-Za-z0-9]{6,})", path)
        return f"workable:{slug.lower()}:{m.group(1).upper()}" if m else None
    m = _UUID_RX.search(path) or re.search(r"/(\d{5,})(?:[/-]|$)", path)
    return f"{kind}:{slug.lower()}:{m.group(1) if m.lastindex else m.group(0).lower()}" if m else None


def ats_from_url(url):
    """('greenhouse', 'dealpath') if the URL is on a known ATS, else (None, None).
    Workday returns ('workday', 'host|?|site') - tenant isn't in the public URL, so it's '?'."""
    u = urllib.parse.unquote(str(url or "")).strip()
    for ats, rx in ATS_URL_PATTERNS:
        m = rx.search(u)
        if m:
            if ats == "workday":
                host, site = m.group(1), m.group(2)
                slug = f"{host}|{host.split('.')[0]}|{site}"
            elif ats == "oracle":
                slug = f"{m.group(1)}|{m.group(2)}"
            else:
                slug = m.group(1)
            return (ats, slug) if valid_slug(ats, slug) else (None, None)
    return None, None
