"""Public reference data job-hunter downloads and keeps in a cache folder (never anything about you):

  ats_directory.csv   which careers system (Greenhouse, Workday, ...) ~24,000 companies use, from the
                      ats-scrapers project's public companies directory (MIT,
                      github.com/kalil0321/ats-scrapers). Used before guessing board names.
  wages.json          government pay data (BLS OEWS) fetched per occupation and metro, cached.
  sponsors.json       employers that filed H-1B petitions, built from a USCIS file you import.

The cache folder is JOBHUNTER_DATA_DIR if set, else ~/.cache/job-hunter (macOS/Linux) or
%LOCALAPPDATA%/job-hunter (Windows). Delete it any time; it's rebuilt as needed.
"""
from __future__ import annotations

import csv
import functools
import io
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

from .common import UA, company_key, http_json
from .fileio import write_text_atomic
from .logs import log

DIRECTORY_MANIFEST = "https://storage.stapply.ai/jobhive/v1/manifest.json"
DIRECTORY_FILE = "ats_directory.csv"
DIRECTORY_MAX_AGE_DAYS = 30
DIRECTORY_KINDS = ("greenhouse", "lever", "ashby", "smartrecruiters", "workable", "recruitee", "workday")

_settings = {"auto_download": False}  # the CLI turns this on (profile data.auto_download, default true)
# Names that stand for many unrelated companies in the directory (placeholders, stealth startups).
GENERIC_NAMES = {"confidential", "confidential company", "stealth", "stealth startup", "stealth mode", "careers", "jobs",
                 "talent", "remote", "hiring", "company", "recruiting", "staffing", "test", "demo", "n a", "na", "none"}
_tried: set = set()  # downloads already attempted this run, so a failure isn't retried per company
_lock = threading.Lock()


def configure(auto_download: bool):
    # JOBHUNTER_NO_DOWNLOAD=1 wins (tests, offline use)
    _settings["auto_download"] = bool(auto_download) and not os.environ.get("JOBHUNTER_NO_DOWNLOAD")


def data_dir() -> Path:
    env = os.environ.get("JOBHUNTER_DATA_DIR")
    if env:
        d = Path(env).expanduser()
    elif sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        d = Path(os.environ["LOCALAPPDATA"]) / "job-hunter"
    else:
        d = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "job-hunter"
    d.mkdir(parents=True, exist_ok=True)
    return d


def age_days(path: Path):
    try:
        return (time.time() - path.stat().st_mtime) / 86400
    except OSError:
        return None


def fetch_text(url, timeout=60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


# ----------------------------- careers-site directory ------------------------

def update_directory(fetch=fetch_text) -> int:
    """Download the companies directory and keep the career systems job-hunter can read.
    Returns how many companies it lists. Raises on a network failure."""
    from .sources.ats import ats_from_url
    manifest = http_json(DIRECTORY_MANIFEST, timeout=30)
    per_ats = (manifest or {}).get("by_ats_companies") or {}
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["key", "name", "ats", "slug"])
    n = 0
    for kind in DIRECTORY_KINDS:
        url = (per_ats.get(kind) or {}).get("csv")
        if not url:
            continue
        for row in csv.DictReader(io.StringIO(fetch(url))):
            if kind == "workday":  # job-hunter's Workday id is host|tenant|site, read from the URL
                k, slug = ats_from_url(row.get("url") or "")
                if k != kind:
                    continue
            else:
                slug = (row.get("slug") or "").strip()
            if not slug:
                continue
            key = company_key(row.get("name"))
            if key:
                w.writerow([key, row.get("name", "").strip(), kind, slug])
                n += 1
    if not n:
        raise RuntimeError("the directory download was empty")
    write_text_atomic(data_dir() / DIRECTORY_FILE, out.getvalue(), private=False)
    _directory.cache_clear()
    return n


def _maybe_download(name, path: Path, max_age_days, update):
    """Download `name` if it's missing or stale, at most once per run, when auto-download is on."""
    age = age_days(path)
    if age is not None and age < max_age_days:
        return
    with _lock:
        if name in _tried or not _settings["auto_download"]:
            return
        _tried.add(name)
    try:
        log.info(f"Updating the {name} (public data, about a minute)...")
        update()
    except Exception as e:
        log.warning(f"couldn't update the {name}: {e}" + (" (using the copy from before)" if path.exists() else ""))


@functools.lru_cache(maxsize=1)
def _directory():
    path = data_dir() / DIRECTORY_FILE
    index: dict = {}
    if not path.exists():
        return index
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            index.setdefault(row["key"], []).append((row["ats"], row["slug"], row["name"]))
    return index


def ensure_directory():
    """Download or refresh the directory now (before verification starts its worker threads)."""
    _maybe_download("careers-site directory", data_dir() / DIRECTORY_FILE, DIRECTORY_MAX_AGE_DAYS, update_directory)


def directory_lookup(company):
    """[(ats, slug, listed_name)] for a company name, from the careers-site directory (may be empty)."""
    path = data_dir() / DIRECTORY_FILE
    _maybe_download("careers-site directory", path, DIRECTORY_MAX_AGE_DAYS, update_directory)
    key = company_key(company)
    if not key or key in GENERIC_NAMES:
        return []
    return list(_directory().get(key, []))


def directory_status():
    path = data_dir() / DIRECTORY_FILE
    age = age_days(path)
    return {"file": str(path), "companies": sum(len(v) for v in _directory().values()) if path.exists() else 0,
            "age_days": round(age, 1) if age is not None else None}
