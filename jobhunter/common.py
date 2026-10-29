"""Small shared helpers: HTTP, text cleanup, salary normalization, name matching."""
import difflib
import html
import ipaddress
import json
import random
import re
import socket
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


MAX_RESPONSE = 20_000_000  # bytes; no job API or data file comes close


def _no_query(url):
    """The URL without its query string, so error messages never carry API keys."""
    try:
        u = urllib.parse.urlsplit(str(url))
        return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, "", ""))
    except ValueError:
        return "<url>"


class HTTPError(Exception):
    def __init__(self, code, url):
        super().__init__(f"HTTP {code} for {_no_query(url)}")
        self.code = code


# ----------------------------- fetching untrusted URLs -----------------------------
# Job postings choose their own apply links. Before job-hunter fetches one, the link must be a
# plain http(s) address on the public internet: never a file on this computer, this computer
# itself (127.0.0.1), the home or office network, or a cloud metadata address. Checked again on
# every redirect.

def public_url(url) -> bool:
    try:
        u = urllib.parse.urlsplit(str(url or "").strip())
        if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
            return False
        port = u.port or (443 if u.scheme == "https" else 80)
        infos = socket.getaddrinfo(u.hostname, port, proto=socket.IPPROTO_TCP)
    except (ValueError, OSError, UnicodeError):
        return False
    try:
        return bool(infos) and all(ipaddress.ip_address(str(i[4][0]).split("%")[0]).is_global for i in infos)
    except ValueError:
        return False


class _PublicRedirects(urllib.request.HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not public_url(newurl):
            raise urllib.error.URLError("redirect to a non-public address refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# http(s) only: no file:// or ftp:// handlers at all, whatever a URL or redirect says
_PUBLIC_OPENER = urllib.request.OpenerDirector()
for _h in (urllib.request.HTTPHandler(), urllib.request.HTTPSHandler(), _PublicRedirects(),
           urllib.request.HTTPErrorProcessor(), urllib.request.HTTPDefaultErrorHandler()):
    _PUBLIC_OPENER.add_handler(_h)


def open_public(url, headers=None, timeout=20):
    """urlopen for an address that came from a job posting. Raises URLError if it isn't public."""
    if not public_url(url):
        raise urllib.error.URLError("not a public web address")
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    return _PUBLIC_OPENER.open(req, timeout=timeout)


def read_capped(resp, limit, deadline_s=45):
    """Read at most `limit` bytes, giving up after `deadline_s` seconds in total (a server that
    drips one byte at a time can't hold a worker forever)."""
    end, chunks, n = time.monotonic() + deadline_s, [], 0
    while n < limit:
        if time.monotonic() > end:
            raise TimeoutError("response too slow")
        b = resp.read(min(65536, limit - n))
        if not b:
            break
        chunks.append(b)
        n += len(b)
    return b"".join(chunks)


_BLOCK_OPEN = re.compile(r"<(script|style|noscript|template)\b", re.I)


def strip_blocks(s: str) -> str:
    """Remove <script>/<style>/<noscript>/<template> blocks in linear time. (The obvious regex is
    quadratic on a page full of unclosed tags, which lets one hostile posting stall a run.)"""
    out, pos, low = [], 0, s.lower()
    while True:
        m = _BLOCK_OPEN.search(s, pos)
        if not m:
            break
        out.append(s[pos:m.start()])
        end = low.find("</" + m.group(1).lower(), m.end())
        if end == -1:
            pos = len(s)  # unclosed: the rest is inside the block
            break
        gt = s.find(">", end)
        out.append(" ")
        pos = len(s) if gt == -1 else gt + 1
    out.append(s[pos:])
    return "".join(out)


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
                raw = r.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise HTTPError(0, f"{url} (response too large)")
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
            raise HTTPError(0, f"{_no_query(url)} ({e})") from None
    return None


_INVISIBLE = re.compile("[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u00ad\u034f\u061c\u115f\u1160"
                        "\u17b4\u17b5\u180b-\u180f\u200b-\u200f\u202a-\u202e\u2060-\u206f\u3164\ufe00-\ufe0f"
                        "\ufeff\uffa0\U000e0000-\U000e0fff]")


# Lookalike letters (Cyrillic/Greek) that make a Cyrillic-e "Gender" slip past a plain-English word list.
_CONFUSABLE = str.maketrans({
    "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0440": "p", "\u0441": "c", "\u0443": "y", "\u0445": "x",
    "\u0456": "i", "\u0458": "j", "\u0455": "s", "\u0501": "d", "\u04bb": "h", "\u04cf": "l", "\u0261": "g",
    "\u0410": "a", "\u0412": "b", "\u0415": "e", "\u041a": "k", "\u041c": "m", "\u041d": "h", "\u041e": "o",
    "\u0420": "p", "\u0421": "c", "\u0422": "t", "\u0425": "x", "\u04ae": "y", "\u03b1": "a", "\u03bf": "o",
    "\u03bd": "v", "\u03b5": "e", "\u03b9": "i", "\u03ba": "k", "\u03c1": "p", "\u03c4": "t", "\u03c5": "u",
    "\u03c7": "x"})


def fold_lookalikes(s: str) -> str:
    return str(s).translate(_CONFUSABLE)


def cell_safe(v):
    """A posting's title, company or location as it's kept: no invisible characters, and never
    starting with = + - @ (a spreadsheet would treat "=HYPERLINK(...)" as a formula when you open
    ranked.csv or applications.csv). Real titles and company names don't start with those."""
    if not isinstance(v, str):
        return v
    return re.sub(r"^[\s=+\-@]+", "", _INVISIBLE.sub("", v)).strip()


def qs(params: dict) -> str:
    return urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})


def html_to_text(s) -> str:
    s = str(s or "")[:300_000]  # longer than any real posting
    if "&lt;" in s:  # some APIs (Greenhouse) send HTML-escaped HTML: unescape first, then strip tags
        s = html.unescape(s)
    s = strip_blocks(s)
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
