"""Application deadlines: read 'apply by' dates out of postings (or a source's own close date)
and flag jobs that close soon. A date that has passed is flagged, not removed: postings often
leave stale dates in place, and employer verification is the better test of whether it's open."""
from __future__ import annotations

import datetime as dt
import re

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MON = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?"
        r"|nov(?:ember)?|dec(?:ember)?)\.?")
_DATE = (rf"(?P<mdy>{_MON}\s+(?P<d1>\d{{1,2}})(?!\d)(?:st|nd|rd|th)?(?:,?\s+(?P<y1>\d{{4}}))?)"
         rf"|(?P<dmy>(?P<d2>\d{{1,2}})(?!\d)(?:st|nd|rd|th)?\s+(?:of\s+)?{_MON}(?:,?\s+(?P<y2>\d{{4}}))?)"
         r"|(?P<num>(?P<n1>\d{1,2})/(?P<n2>\d{1,2})/(?P<ny>\d{2,4}))"
         r"|(?P<iso>(?P<iy>\d{4})-(?P<im>\d{2})-(?P<id>\d{2}))")
CUE = re.compile(
    r"(?:apply\s+(?:by|before|no\s+later\s+than)|application(?:s)?\s+(?:deadline|due|close|closes|must\s+be\s+received\s+by)"
    r"|deadline(?:\s+to\s+apply)?|closing\s+date|clos(?:es|ing)\s+on|posting\s+(?:closes|close\s+date|end\s+date)"
    r"|(?:accepting|accept)\s+applications\s+(?:through|until|till)|open\s+(?:until|through))\s*(?:is|:|-|on)?\s*"
    r"(?:(?:mon|tues|wednes|thurs|fri|satur|sun)day,?\s+)?(?:" + _DATE + ")",
    re.I)


def _month(text):
    return MONTHS.get(text.lower()[:3])


def find(text, reference=None, us=True):
    """The deadline a posting states, as a date, or None. Dates without a year are read as the next
    one on or after `reference` (the posting date, default today). Numeric dates are month-first
    for U.S. jobs; elsewhere an ambiguous one like 05/11/2026 is skipped."""
    ref = reference or dt.date.today()
    m = CUE.search(str(text or ""))
    if not m:
        return None
    try:
        if m.group("mdy"):
            mon = _month(re.match(_MON, m.group("mdy"), re.I).group(1))
            day, year = int(m.group("d1")), m.group("y1")
        elif m.group("dmy"):
            mon = _month(re.search(_MON, m.group("dmy"), re.I).group(1))
            day, year = int(m.group("d2")), m.group("y2")
        elif m.group("num"):
            a, b, y = int(m.group("n1")), int(m.group("n2")), m.group("ny")
            year = y if len(y) == 4 else f"20{y}"
            if a > 12:            # 25/11/2026: day first
                mon, day = b, a
            elif b > 12 or a == b or us:  # 11/25/2026, or U.S. month-first
                mon, day = a, b
            else:                 # 05/11/2026 outside the U.S.: can't tell
                return None
        else:
            return dt.date(int(m.group("iy")), int(m.group("im")), int(m.group("id")))
        if mon is None:
            return None
        if year:
            return dt.date(int(year), mon, day)
        d = dt.date(ref.year, mon, day)
        return d if d >= ref - dt.timedelta(days=60) else dt.date(ref.year + 1, mon, day)  # recent past: this year
    except (ValueError, AttributeError):
        return None


_US = re.compile(r",\s*(?:a[lkzr]|c[aot]|d[ce]|fl|ga|hi|i[adln]|k[sy]|la|m[adeinost]|n[cdehjmvy]|o[hkr]|pa|ri|s[cd]|t[nx]|ut|"
                 r"v[at]|w[aivy])\b|\bu\.?s\.?a?\b|united states|remote\s*\(?us", re.I)


def _looks_us(row):
    loc = str(row.get("location") or "")
    return not loc.strip() or bool(_US.search(loc))


def note(row, soon_days=10, today=None):
    """('closes Nov 15 (6 days)' style note, the date) for a job, or ('', None)."""
    today = today or dt.date.today()
    closes = None
    for key in ("closes", "apply_by"):  # a source's own close date, or one found on an earlier run
        raw = row.get(key)
        if closes is None and isinstance(raw, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw.strip()):
            try:
                closes = dt.date.fromisoformat(raw.strip())
            except ValueError:
                closes = None
    if closes is None:
        posted = None
        try:
            import pandas as pd
            ts = pd.to_datetime(row.get("date_posted"), errors="coerce")
            posted = None if pd.isna(ts) else ts.date()
        except Exception:
            posted = None
        closes = find(row.get("description"), reference=posted or today, us=_looks_us(row))
    if closes is None:
        return "", None
    days = (closes - today).days
    label = closes.strftime("%b %d").replace(" 0", " ")
    if days < 0:
        return f"says applications closed {label}; check it's still open", closes
    if days <= soon_days:
        return f"closes {label} ({days} day{'s' if days != 1 else ''})", closes
    return "", closes
