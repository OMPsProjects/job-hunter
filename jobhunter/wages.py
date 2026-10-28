"""Typical pay for an occupation and metro from the U.S. Bureau of Labor Statistics (OEWS survey),
used when a posting doesn't list pay.

Fetched from the official BLS API (api.bls.gov) and cached for 180 days in the data folder (see
datasets.py), so a normal day's run makes few or no requests. Without a key BLS allows 25 requests
a day per network; a free key (BLS_API_KEY in .env, from https://data.bls.gov/registrationEngine/)
raises that to 500. Only occupation codes and metro codes are sent, nothing about you.

An estimate is what the middle of the market pays for that kind of job in that metro, not what
this employer pays. Ranking uses it at half strength and never filters a job out on it.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

from .common import http_json
from .datasets import data_dir
from .fileio import write_text_atomic
from .logs import log

API_V1 = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
API_V2 = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
CACHE_FILE = "wages.json"
CACHE_DAYS = 180
NATIONAL = "0000000"
# datatype codes in OEWS series ids: annual 25th percentile, median, 75th percentile
DATATYPES = {"p25": "12", "median": "13", "p75": "14"}
MAX_REQUESTS_PER_RUN = 8  # stay well under the 25/day keyless limit

# Metro areas (OEWS area codes) for the cities setup knows, with a sample place used to match a
# profile region's pattern to one of them. Codes checked against BLS's oe.area list (2025).
AREAS = {
    "washington": ("0047900", "Washington, DC metro", "washington, dc"),
    "new york": ("0035620", "New York metro", "new york, ny"),
    "los angeles": ("0031080", "Los Angeles metro", "los angeles, ca"),
    "san francisco": ("0041860", "San Francisco Bay Area", "san francisco, ca"),
    "san jose": ("0041940", "San Jose metro", "san jose, ca"),
    "chicago": ("0016980", "Chicago metro", "chicago, il"),
    "boston": ("0014460", "Boston metro", "boston, ma"),
    "atlanta": ("0012060", "Atlanta metro", "atlanta, ga"),
    "dallas": ("0019100", "Dallas-Fort Worth", "dallas, tx"),
    "houston": ("0026420", "Houston metro", "houston, tx"),
    "austin": ("0012420", "Austin metro", "austin, tx"),
    "miami": ("0033100", "Miami metro", "miami, fl"),
    "seattle": ("0042660", "Seattle metro", "seattle, wa"),
    "denver": ("0019740", "Denver metro", "denver, co"),
    "philadelphia": ("0037980", "Philadelphia metro", "philadelphia, pa"),
    "phoenix": ("0038060", "Phoenix metro", "phoenix, az"),
    "charlotte": ("0016740", "Charlotte metro", "charlotte, nc"),
    "minneapolis": ("0033460", "Minneapolis-St. Paul", "minneapolis, mn"),
    "san diego": ("0041740", "San Diego metro", "san diego, ca"),
    "nashville": ("0034980", "Nashville metro", "nashville, tn"),
    "baltimore": ("0012580", "Baltimore metro", "baltimore, md"),
    "raleigh": ("0039580", "Raleigh metro", "raleigh, nc"),
    "durham": ("0020500", "Durham-Chapel Hill", "durham, nc"),
    "pittsburgh": ("0038300", "Pittsburgh metro", "pittsburgh, pa"),
    "detroit": ("0019820", "Detroit metro", "detroit, mi"),
    "salt lake city": ("0041620", "Salt Lake City metro", "salt lake city, ut"),
    "portland": ("0038900", "Portland metro", "portland, or"),
    "tampa": ("0045300", "Tampa metro", "tampa, fl"),
    "orlando": ("0036740", "Orlando metro", "orlando, fl"),
    "st. louis": ("0041180", "St. Louis metro", "st. louis, mo"),
    "kansas city": ("0028140", "Kansas City metro", "kansas city, mo"),
    "columbus": ("0018140", "Columbus, OH metro", "columbus, oh"),
}

_lock = threading.Lock()


def _area_for_location(location):
    loc = str(location or "").lower()
    for code, label, sample in AREAS.values():
        city, state = (x.strip() for x in sample.split(","))
        if re.search(rf"\b{re.escape(city)}\b.*\b{state}\b", loc):
            return code, label
    return None


def area_for_job(profile, row):
    """(area_code, label) for a job: its own location when that names a known metro ('San Jose, CA'),
    else its region when that region's pattern covers exactly one known metro, else national.
    Remote jobs and places outside the list use national figures."""
    region = row.get("region")
    if region == "remote":
        return NATIONAL, "U.S."
    hit = _area_for_location(row.get("location"))
    if hit:
        return hit
    return area_for_region(profile, region)


def area_for_region(profile, region_key):
    pattern = dict(profile.regions).get(region_key)
    if pattern:
        try:
            hits = [(code, label) for code, label, sample in AREAS.values() if re.search(pattern, sample, re.I)]
        except re.error:
            hits = []
        if len(hits) == 1:  # a pattern covering several metros ('ca') can't say which one
            return hits[0]
    return NATIONAL, "U.S."


def series_id(area, soc6, datatype):
    prefix = "OEUN" if area == NATIONAL else "OEUM"
    return f"{prefix}{area}000000{soc6}{DATATYPES[datatype]}"


class WageCache:
    def __init__(self, path=None):
        self.path = path or data_dir() / CACHE_FILE
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self.data = {}

    def get(self, area, soc6):
        hit = self.data.get(f"{area}|{soc6}")
        if hit and time.time() - hit.get("checked", 0) < CACHE_DAYS * 86400:
            return hit
        return None

    def put(self, area, soc6, values):
        self.data[f"{area}|{soc6}"] = {**values, "checked": time.time()}

    def save(self):
        write_text_atomic(self.path, json.dumps(self.data, indent=0, sort_keys=True), private=False)


def _request(series, key):
    body: dict = {"seriesid": series, "latest": True}
    if key:
        body["registrationkey"] = key
    return http_json(API_V2 if key else API_V1, method="POST", body=body, timeout=30, retries=1)


def prefetch(pairs, cache: WageCache | None = None, request=None):
    """Fetch BLS figures for (area_code, soc6) pairs not cached yet, plus the national figure for each
    occupation as a fallback. Returns how many pairs were fetched. Network failures and odd replies
    are logged, not raised (cli.prefetch_pay also guards the call): pay estimates are a
    nice-to-have, so a failure just leaves jobs at 'pay not posted'."""
    cache = cache or WageCache()
    request = request or _request
    key = os.environ.get("BLS_API_KEY", "").strip()
    per_request = 48 if key else 24  # a multiple of 3, so a pair's three series share one request
    todo = []
    for area, soc in dict.fromkeys(pairs):
        for a in dict.fromkeys((area, NATIONAL)):
            if cache.get(a, soc) is None and (a, soc) not in todo:
                todo.append((a, soc))
    if not todo:
        return 0
    series = [(a, s, dt, series_id(a, s, dt)) for a, s in todo for dt in DATATYPES]
    fetched, requests = set(), 0
    for i in range(0, len(series), per_request):
        if requests >= MAX_REQUESTS_PER_RUN:
            log.info("  (pay estimates: request limit for this run reached; the rest come next run)")
            break
        chunk = series[i:i + per_request]
        try:
            d = request([c[3] for c in chunk], key)
            requests += 1
        except Exception as e:  # HTTP errors, a non-JSON maintenance page, ...
            log.warning(f"pay estimates: BLS didn't answer ({e})")
            break
        if not isinstance(d, dict) or d.get("status") != "REQUEST_SUCCEEDED":
            msg = " ".join(str(x) for x in ((d or {}).get("message") or [])) if isinstance(d, dict) else ""
            log.warning("pay estimates: BLS refused the request" + (f" ({msg[:160]})" if msg else "")
                        + ("" if key else ". A free BLS_API_KEY in .env raises the daily limit."))
            break
        values: dict = {}
        results = d.get("Results") if isinstance(d, dict) else None
        series_list = results.get("series") if isinstance(results, dict) else None
        for s in series_list if isinstance(series_list, list) else []:
            if not isinstance(s, dict):
                continue
            sid = s.get("seriesID", "")
            match = next((c for c in chunk if c[3] == sid), None)
            if not match or not s.get("data"):
                continue
            row = s["data"][0] if isinstance(s["data"], list) and isinstance(s["data"][0], dict) else {}
            try:
                values.setdefault((match[0], match[1]), {})[match[2]] = float(row["value"])
                values[(match[0], match[1])]["year"] = int(row["year"])
            except (TypeError, ValueError, KeyError):
                continue  # '-' or '#' (suppressed or above the top-coded maximum)
        for a, s, _, _ in chunk:
            fetched.add((a, s))
            cache.put(a, s, values.get((a, s), {}))  # an empty entry means 'BLS has no figure'
    with _lock:
        try:
            cache.save()
        except OSError as e:
            log.warning(f"couldn't save pay estimates: {e}")
    return len(fetched)


def estimate(area, soc6, cache: WageCache):
    """dict(median, p25, p75, year, area) from the cache: the metro figure, else the national one."""
    for a in dict.fromkeys((area, NATIONAL)):
        hit = cache.get(a, soc6)
        if hit and hit.get("median"):
            return {**{k: hit.get(k) for k in ("median", "p25", "p75", "year")}, "area": a}
    return None
