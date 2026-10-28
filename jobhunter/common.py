"""Small shared helpers: HTTP, text cleanup, salary normalization, name matching."""
import difflib
import html
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request

US_STATE_CODES = frozenset(
    "al ak az ar ca co ct de fl ga hi id il in ia ks ky la me md ma mi mn ms mo mt ne nv nh nj nm ny nc nd "
    "oh ok or pa ri sc sd tn tx ut vt va wa wv wi wy dc".split())

UA = "Mozilla/5.0 (compatible; job-hunter/1.0)"

# Columns every source returns (missing ones are filled with None).
JOB_COLUMNS = [
    "title", "company", "location", "is_remote", "job_url", "date_posted", "description",
    "min_amount", "max_amount", "interval", "currency", "site", "track", "query",
]


class HTTPError(Exception):
    def __init__(self, code, url):
        super().__init__(f"HTTP {code} for {url}")
        self.code = code


def http_json(url, method="GET", body=None, headers=None, timeout=20, retries=2):
    """GET/POST and parse JSON. Raises HTTPError on a 4xx/5xx. Retries 429/5xx and network errors
    with exponential backoff (honoring Retry-After up to 60s)."""
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                wait = 2 ** attempt + random.random()
                ra = e.headers.get("Retry-After") if e.headers else None
                if ra and str(ra).isdigit():
                    wait = min(60, int(ra))
                time.sleep(wait)
                continue
            raise HTTPError(e.code, url) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt < retries:
                time.sleep(2 ** attempt + random.random())
                continue
            raise HTTPError(0, f"{url} ({e})") from None
    return None


def qs(params: dict) -> str:
    return urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})


def html_to_text(s) -> str:
    s = str(s or "")
    if "&lt;" in s:  # some APIs (Greenhouse) send HTML-escaped HTML: unescape first, then strip tags
        s = html.unescape(s)
    s = re.sub(r"<(script|style|template|noscript)\b[^>]*>.*?</\1\s*>", " ", s, flags=re.I | re.S)
    from .integrity import mark_hidden_html
    s = mark_hidden_html(s)  # hidden text aimed at AI tools is labeled so the scan can say it was hidden
    s = re.sub(r"<\s*(br|/p|/li|/h\d)\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


_COMPANY_SUFFIX = re.compile(
    r"\b(inc|incorporated|llc|l l c|ltd|limited|corp|corporation|co|company|plc|lp|llp|group|holdings|"
    r"the|n a|na|usa|us|international|global)\b")


def company_key(name) -> str:
    """'The Carlyle Group, Inc.' -> 'carlyle'. Used to match the same employer across sources."""
    return re.sub(r"\s+", " ", _COMPANY_SUFFIX.sub(" ", norm(name))).strip()


def title_similarity(a, b) -> float:
    """0..1. Token-set style: order-insensitive, tolerant of extra words like 'Sr.' or a req code."""
    ta, tb = set(norm(a).split()), set(norm(b).split())
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    jacc = len(inter) / len(ta | tb)
    contain = len(inter) / min(len(ta), len(tb))
    seq = difflib.SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    return max(jacc, 0.6 * contain + 0.4 * seq)


_INTERVAL_MULT = {"yearly": 1, "year": 1, "annual": 1, "annually": 1, "monthly": 12, "month": 12,
                  "weekly": 52, "week": 52, "daily": 260, "day": 260, "hourly": 2080, "hour": 2080}


def annualize(amount, interval):
    """Turn a pay figure into a yearly number. Unknown interval: guess hourly if < 500, else yearly."""
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return None
    if amount != amount or amount <= 0:  # NaN or zero
        return None
    mult = _INTERVAL_MULT.get(str(interval or "").lower().strip())
    if mult is None:
        mult = 2080 if amount < 500 else 1
    return amount * mult


def parse_salary_text(text):
    """Pull a pay range out of free text like '$120,000 - $150,000' or '$55/hr'. Returns (min, max, interval)."""
    t = str(text or "")
    m = re.findall(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k|K)?", t)
    if not m:
        return None, None, None
    vals = []
    for num, k in m[:2]:
        v = float(num.replace(",", ""))
        if k:
            v *= 1000
        vals.append(v)
    interval = "hourly" if re.search(r"/\s?h(ou)?r|per hour|hourly", t, re.I) else "yearly"
    return min(vals), max(vals), interval
