"""Visa sponsorship: what a posting says about it, and whether the employer has sponsored before.

Turned on by `filters.needs_sponsorship: true` in profile.yaml. Then:
  - postings that say they won't sponsor, or that need U.S. citizenship or a security clearance,
    are moved to excluded.csv with the reason;
  - postings that say they do sponsor are noted in the `visa_note` column;
  - if you've imported USCIS's H-1B employer data (`job-hunter data import-sponsors FILE`), an
    employer's recent H-1B approvals are noted too. That's history, not a promise.

Wording varies a lot, so the patterns lean toward missing a statement rather than misreading one.
"""
from __future__ import annotations

import contextlib
import csv
import functools
import json
import re
from pathlib import Path

from .common import company_key
from .datasets import data_dir
from .fileio import write_text_atomic

SPONSORS_FILE = "sponsors.json"

_V = r"(?:visa\s+|immigration\s+|employment\s+|work\s+|h-?1b\s+)?"
# After "sponsor(ship)", what makes it about immigration and not events or marketing deals: a visa
# word, someone being sponsored, or the end of the sentence ("we do not sponsor.").
_ABOUT_PEOPLE = (r"(?=\s*(?:[.,;:)]|$|visas?\b|h-?1b|work|employment|immigration|candidates?|applicants?|individuals?"
                 r"|anyone|you\b|employees?|for\s+(?:this|the)\s+(?:role|position|job)|at\s+this\s+time|now\b"
                 r"|in\s+the\s+future|now\s+or|of\s+(?:visas?|work|employment|any|h-?1b)))")
_NOT_MARKETING = r"(?!\s+(?:deals?|of\s+(?:our|the|an?)\b|programs?|events?|opportunit|packages?|levels?|tiers?|needs|agreements?|budget))"
NO_SPONSOR = re.compile(
    r"(?:unable|not\s+able|cannot|can\s?not|will\s+not|won'?t|do(?:es)?\s+not|are\s+not\s+able|is\s+not\s+able)"
    rf"\s+(?:to\s+)?(?:provide\s+|offer\s+|support\s+)?{_V}sponsor(?:ship)?{_ABOUT_PEOPLE}"
    r"|\b(?:no|without)\s+(?:the\s+need\s+for\s+|requiring\s+|need\s+of\s+)?(?:current\s+or\s+future\s+|future\s+)?"
    rf"(?:visa\s+|immigration\s+|employment\s+|work\s+|h-?1b\s+)?sponsorship{_NOT_MARKETING}"
    rf"|{_V}sponsorship\s+(?:is\s+)?(?:not\s+(?:available|offered|provided)|unavailable|will\s+not\s+be\s+(?:provided|offered))"
    r"(?!\s+(?:for|to)\s+(?:this|our|the)\s+(?:event|program|conference))"
    rf"|not\s+eligible\s+for\s+{_V}sponsorship"
    rf"|(?:does|do)\s+not\s+(?:currently\s+)?(?:offer|provide)\s+{_V}sponsorship{_NOT_MARKETING}",
    re.I)
CITIZENS_ONLY = re.compile(
    r"(?<!not\s)(?<!no\s)(?:u\.?\s?s\.?|united\s+states)\s+citizenship\s+(?:is\s+)?required"
    r"|must\s+(?:be\s+)?(?:a\s+)?(?:u\.?\s?s\.?|united\s+states)\s+citizen(?!\s*(?:,|or|/)\s*(?:or\s+)?"
    r"(?:a\s+)?(?:green|permanent|lawful|authorized|hold|national|resident))"
    r"|(?<!no\s)(?:active|current)\s+(?:secret|top\s+secret|ts(?:/sci)?)\s+(?:security\s+)?clearance"
    r"(?!\s+(?:is\s+)?(?:preferred|a\s+plus|desired|nice|helpful|not\s+required))"
    r"|(?<!no\s)(?<!not\s)security\s+clearance\s+(?:is\s+)?required"
    r"|requires?\s+(?:an?\s+)?(?:active\s+)?security\s+clearance",
    re.I)
SPONSORS = re.compile(
    rf"{_V}sponsorship\s+(?:is\s+)?(?:available|offered|provided)"
    rf"|(?:will|can|are\s+able\s+to|is\s+able\s+to|happy\s+to|open\s+to)\s+(?:provide\s+|offer\s+)?{_V}sponsor"
    r"|we\s+sponsor\s+(?:visas|h-?1b)",
    re.I)


def posting_status(text):
    """('no_sponsorship' | 'citizens_only' | 'sponsors' | '', the sentence it came from)."""
    t = str(text or "")
    for status, rx in (("no_sponsorship", NO_SPONSOR), ("citizens_only", CITIZENS_ONLY), ("sponsors", SPONSORS)):
        m = rx.search(t)
        if m:
            start = max(0, t.rfind(".", 0, m.start()) + 1)
            end = t.find(".", m.end())
            return status, t[start:end if end != -1 else len(t)].strip()[:200]
    return "", ""


# ----------------------------- employer history ------------------------------

def import_sponsors(csv_path) -> int:
    """Read a USCIS H-1B Employer Data Hub CSV (any recent year's layout) into sponsors.json:
    employer -> approvals per fiscal year. Only employer names and counts are kept."""
    path = Path(csv_path)
    data: dict = {}
    try:
        data = json.loads((data_dir() / SPONSORS_FILE).read_text(encoding="utf-8"))
    except Exception:
        data = {}
    raw = path.read_bytes()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig", errors="replace")
    sample = text[:4096]
    delim = "\t" if sample.count("\t") > sample.count(",") else ","
    rows = csv.DictReader(text.splitlines(), delimiter=delim)
    cols = rows.fieldnames or []
    name_col = next((c for c in cols if "employer" in c.lower() and "name" in c.lower()), None) \
        or next((c for c in cols if "employer" in c.lower()), None)
    year_col = next((c for c in cols if "fiscal" in c.lower() or c.strip().lower() == "year"), None)
    approval_cols = [c for c in cols if "approv" in c.lower()]
    if not name_col or not approval_cols:
        raise ValueError(f"{path.name} doesn't look like USCIS H-1B employer data (columns: {', '.join(cols[:8])})")
    n = 0
    fresh: dict = {}
    for r in rows:
        key = company_key(r.get(name_col))
        if not key:
            continue
        total = 0
        for c in approval_cols:
            with contextlib.suppress(ValueError):
                total += int(float(str(r.get(c) or "0").replace(",", "")))
        year = str(r.get(year_col) or "").strip() if year_col else ""
        entry = fresh.setdefault(key, {"name": str(r.get(name_col)).strip(), "approvals": {}})
        entry["approvals"][year or "?"] = entry["approvals"].get(year or "?", 0) + total
        n += 1
    # Importing the same year again replaces that year's counts instead of adding to them.
    years = {y for e in fresh.values() for y in e["approvals"]}
    for e in data.values():
        e["approvals"] = {y: c for y, c in e.get("approvals", {}).items() if y not in years}
    for key, e in fresh.items():
        data.setdefault(key, {"name": e["name"], "approvals": {}})["approvals"].update(e["approvals"])
    write_text_atomic(data_dir() / SPONSORS_FILE, json.dumps(data, sort_keys=True), private=False)
    _sponsors.cache_clear()
    return n


@functools.lru_cache(maxsize=1)
def _sponsors():
    try:
        return json.loads((data_dir() / SPONSORS_FILE).read_text(encoding="utf-8"))
    except Exception:
        return {}


def employer_history(company):
    """'H-1B approvals: 42 in FY2025' style note, or '' when there's no record (or no data imported)."""
    entry = _sponsors().get(company_key(company))
    if not entry:
        return ""
    approvals = {y: n for y, n in entry.get("approvals", {}).items() if n}
    if not approvals:
        return "no H-1B approvals on record"
    years = [y for y in approvals if y.isdigit()]
    if not years:
        return f"H-1B approvals on record: {sum(approvals.values())}"
    year = max(years)
    return f"H-1B approvals on record: {approvals[year]} in FY{year}"
