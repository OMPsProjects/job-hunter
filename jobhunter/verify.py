"""Confirm a posting is live on the employer's own careers site.

For each job:
  1. If the job (or its direct apply link) is already on an employer ATS, ask that ATS.
  2. Otherwise find the company's ATS (profile override, cache, or by probing likely board
     names on Greenhouse / Lever / Ashby / SmartRecruiters / Recruitee / Workable), pull its
     open roles, and look for the same title.
  3. If the direct apply link is some other employer page, load it and look for "closed" text.

Statuses (column `verified`):
  verified_open          the employer's ATS lists it as open
  employer_page_live     the employer's own page loads and shows no "closed" text
  not_on_employer_site   we found the company's job board and this title isn't on it
  closed                 the employer says it's closed / the page is gone
  unverified             couldn't find the employer's job board; check by hand
"""
import concurrent.futures as cf
import json
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .common import UA, HTTPError, company_key, http_json, title_similarity
from .fileio import write_text_atomic
from .logs import log
from .sources import ats

MATCH_THRESHOLD = 0.80
CACHE_DAYS = 30
MISS_CACHE_DAYS = 7
CLOSED_TEXT = re.compile(
    r"no longer accepting applications|no longer available|position has been filled|job has expired|"
    r"this job is closed|posting has closed|no longer open|job you are looking for (?:is|was) not found|"
    r"this position is no longer|requisition (?:is )?closed|page not found", re.I)

# Probe order: cheap, single-request APIs first. Workable is rate-limited, so it goes last.
PROBE_ORDER = ["greenhouse", "lever", "ashby", "smartrecruiters", "recruitee", "workable"]


def slug_candidates(company):
    key = company_key(company)
    words = key.split()
    if not words:
        return []
    # Joined and hyphenated forms only. The first word alone ("first", "capital", "new") collides
    # with unrelated companies' boards far too often.
    c = ["".join(words), "-".join(words)]
    return list(dict.fromkeys(s for s in c if len(s) >= 3))


class ProbeError(Exception):
    """The answer was 'couldn't tell' (network error, rate limit), not 'no such board'."""


def _probe(kind, slug, company):
    """(exists, identity_confirmed) for one ATS board name. Raises ProbeError when the ATS
    couldn't be reached, so a temporary failure isn't remembered as 'no board'."""
    try:
        if kind == "greenhouse":
            d = http_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}", retries=0)
            return True, company_key(d.get("name")) == company_key(company)
        if kind == "lever":
            d = http_json(f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=1", retries=0)
            return isinstance(d, list), False
        if kind == "ashby":
            d = http_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", retries=0)
            return isinstance(d, dict) and "jobs" in d, False
        if kind == "smartrecruiters":
            d = http_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1", retries=0)
            content = d.get("content") or []
            if not content:
                return False, False
            return True, company_key((content[0].get("company") or {}).get("name")) == company_key(company)
        if kind == "recruitee":
            d = http_json(f"https://{slug}.recruitee.com/api/offers/", retries=0)
            return isinstance(d, dict) and "offers" in d, False
        if kind == "workable":
            d = http_json(f"https://apply.workable.com/api/v1/accounts/{slug}", retries=0, timeout=10)
            return bool(d), company_key((d or {}).get("name")) == company_key(company)
    except HTTPError as e:
        if e.code in (400, 401, 403, 404, 410, 422):
            return False, False  # the ATS answered: no board by that name
        raise ProbeError(str(e)) from None
    except Exception as e:  # malformed reply, DNS failure for a made-up subdomain, ...
        if kind == "recruitee":  # unknown subdomains don't resolve: that's a definite 'no'
            return False, False
        raise ProbeError(str(e)) from None
    return False, False


def discover(company):
    """Find a company's public ATS board. Returns dict(ats, slug, confirmed), or
    dict(ats=None, definitive=bool): definitive=False means some lookups failed, so try again later."""
    definitive = True
    for slug in slug_candidates(company):
        for kind in PROBE_ORDER:
            try:
                ok, confirmed = _probe(kind, slug, company)
            except ProbeError:
                definitive = False
                continue
            if ok:
                return {"ats": kind, "slug": slug, "confirmed": confirmed}
    return {"ats": None, "definitive": definitive}


class Verifier:
    def __init__(self, profile, cache_path: Path):
        self.p = profile
        self.cache_path = cache_path
        try:
            self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            self.cache = {}
        self.postings: dict = {}  # (ats, slug) -> list of rows, fetched once per run
        self._locks: dict = {}    # one lock per company / board, so threads don't probe the same one twice
        self._guard = threading.Lock()

    def _lock(self, key):
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    def save(self):
        with self._guard:
            text = json.dumps(self.cache, indent=1, sort_keys=True)
        write_text_atomic(self.cache_path, text, private=False)

    def board_for(self, company):
        for name, (kind, slug) in self.p.ats_overrides.items():
            if company_key(name) == company_key(company):
                return {"ats": kind, "slug": slug, "confirmed": True}
        key = company_key(company)
        with self._lock(("company", key)):
            hit = self.cache.get(key)
            # boards found are kept 30 days; a 'no board' answer only 7, in case they add one
            ttl = CACHE_DAYS if hit and hit.get("ats") else MISS_CACHE_DAYS
            if hit and time.time() - hit.get("checked", 0) < ttl * 86400:
                return hit
            found = discover(company)
            found["checked"] = time.time()
            if found.get("ats") or found.get("definitive", True):
                self.cache[key] = found  # don't remember 'couldn't reach the ATS' as 'no board'
            return found

    def board_postings(self, kind, slug, company, title=""):
        k = (kind, slug, title if kind == "workday" else "")
        with self._lock(("board",) + k):
            if k not in self.postings:
                try:
                    kw = {"search_text": title} if kind == "workday" else {}
                    self.postings[k] = ats.list_postings(kind, company, slug, with_description=False, **kw)
                except Exception:
                    self.postings[k] = None
            return self.postings[k]

    def match(self, rows, title, location):
        best, best_sim = None, 0.0
        for r in rows or []:
            sim = title_similarity(title, r["title"])
            if location and r.get("location") and str(location).split(",")[0].lower() in str(r["location"]).lower():
                sim += 0.05  # same city: small tiebreak
            if sim > best_sim:
                best, best_sim = r, sim
        return (best, best_sim) if best_sim >= MATCH_THRESHOLD else (None, best_sim)

    def check_page(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                text = r.read(400_000).decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            return "closed" if e.code in (404, 410) else "unverified"
        except Exception:
            return "unverified"
        # Only look at visible text: single-page apps ship every error message ("job no longer
        # available") inside their script bundles, which would read as closed.
        visible = re.sub(r"(?is)<(script|style|noscript|template)\b.*?</\1>", " ", text)
        visible = re.sub(r"(?s)<[^>]+>", " ", visible)
        visible = re.sub(r"\s+", " ", visible).strip()
        if len(visible) < 400:
            return "unverified"  # page renders in the browser; needs a by-hand (or browser) check
        return "closed" if CLOSED_TEXT.search(visible) else "employer_page_live"

    def check_workday_url(self, url):
        m = re.search(r"https?://([^./]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/?#]+)(/job/[^?#]+)", url)
        if not m:
            return None
        tenant, wd, site, path = m.groups()
        try:
            info = http_json(f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{path}", retries=0)
        except HTTPError as e:
            return "closed" if e.code in (404, 410) else "unverified"
        except Exception:
            return "unverified"
        jp = (info or {}).get("jobPostingInfo") or {}
        if not jp:
            return "closed"
        return "verified_open" if jp.get("canApply", True) else "closed"

    def verify_one(self, row):
        title, company, location = row.get("title"), row.get("company"), row.get("location")
        direct = row.get("job_url_direct") if isinstance(row.get("job_url_direct"), str) else None
        out = {"verified": "unverified", "employer_url": None, "verify_note": ""}
        if row.get("verified") == "verified_open":
            return {"verified": "verified_open", "employer_url": row.get("employer_url") or row.get("job_url"),
                    "verify_note": "listed on employer site"}

        # 1. the posting (or its apply link) is already on an ATS
        for url in [direct, row.get("job_url")]:
            kind, slug = ats.ats_from_url(url)
            if not kind:
                continue
            if kind == "workday":
                status = self.check_workday_url(url)
                if status:
                    return {"verified": status, "employer_url": url, "verify_note": "workday posting checked"}
            elif kind in ats.FETCHERS:
                rows = self.board_postings(kind, slug, company)
                if rows is not None:
                    pid = posting_id(url)
                    if pid and rows:
                        # the URL names one specific posting: it's open only if the board still lists that id
                        hit = next((r for r in rows if pid in str(r.get("job_url", "")) or pid == str(r.get("req_id"))), None)
                        if hit:
                            return {"verified": "verified_open", "employer_url": hit["job_url"],
                                    "verify_note": f"found on {kind}/{slug}", "req_id": hit.get("req_id")}
                        return {"verified": "closed", "employer_url": url,
                                "verify_note": f"{kind}/{slug} lists {len(rows)} jobs but not this one"}
                    hit, _ = self.match(rows, title, location)
                    if hit:
                        return {"verified": "verified_open", "employer_url": hit["job_url"],
                                "verify_note": f"title matched on {kind}/{slug}", "req_id": hit.get("req_id")}
                    return {"verified": "unverified", "employer_url": url,
                            "verify_note": f"on {kind}/{slug} but couldn't confirm it's still open"}
            elif kind == "icims":
                return {"verified": self.check_page(url), "employer_url": url, "verify_note": "icims page checked"}

        # 2. find the company's own board and look for the title
        if company and str(company).lower() not in ("nan", "none", ""):
            board = self.board_for(company)
            if board.get("ats"):
                rows = self.board_postings(board["ats"], board["slug"], company, title)
                hit, sim = self.match(rows, title, location)
                if hit:
                    return {"verified": "verified_open", "employer_url": hit["job_url"],
                            "verify_note": f"matched on {board['ats']}/{board['slug']} ({sim:.2f})",
                            "req_id": hit.get("req_id")}
                if rows and board.get("confirmed"):  # a real, non-empty board that's definitely theirs
                    return {"verified": "not_on_employer_site", "employer_url": None,
                            "verify_note": f"{company} board on {board['ats']} has no matching title"}
                out["verify_note"] = f"possible board {board['ats']}/{board['slug']}, no title match"

        # 3. a direct apply link on some other employer page
        if direct and not re.search(r"linkedin\.com|indeed\.com|glassdoor\.|ziprecruiter\.|google\.com", direct):
            status = self.check_page(direct)
            if status != "unverified":
                return {"verified": status, "employer_url": direct, "verify_note": "employer page checked"}
        if not out["verify_note"]:
            out["verify_note"] = "employer job board not found; check by hand"
        return out


def _safe(v, row):
    """One job's verification failing must never stop the run."""
    try:
        return v.verify_one(row)
    except Exception as e:
        return {"verified": "unverified", "employer_url": None, "verify_note": f"check failed: {type(e).__name__}"}


def posting_id(url):
    """The posting's own id in an ATS URL (a long number or a UUID), or None."""
    m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", str(url or ""), re.I)
    if m:
        return m.group(0).lower()
    m = re.search(r"(?:jobs/|gh_jid=|/j/|/)(\d{6,})", str(url or ""))
    return m.group(1) if m else None


def verify_frame(df, profile, cache_path: Path, workers=8):
    """Adds verified / employer_url / verify_note / req_id columns (in place on a copy)."""
    v = Verifier(profile, cache_path)
    df = df.copy()
    for c in ("verified", "employer_url", "verify_note", "req_id"):
        if c not in df:
            df[c] = None
    idx = list(df.index)
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda i: _safe(v, df.loc[i].to_dict()), idx))
    for i, res in zip(idx, results, strict=True):
        for k, val in res.items():
            df.at[i, k] = val
    try:
        v.save()
    except OSError as e:
        log.warning(f"couldn't save the ATS cache: {e}")
    counts = df["verified"].value_counts().to_dict()
    log.info("Verification: " + ", ".join(f"{k} {n}" for k, n in counts.items()))
    return df
