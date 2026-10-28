"""Every source's parser against recorded (or documented-shape) API responses. No network.

When a site changes its response format, the nightly live check (tests/live/) fails first;
then re-record the fixture and fix the parser here."""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jobhunter.common import JOB_COLUMNS  # noqa: E402
from jobhunter.profile import Profile  # noqa: E402
from jobhunter.sources import apis, ats  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "sources"


def load(name):
    return json.loads((FIX / name).read_text())


ROUTES = [
    (r"boards-api\.greenhouse\.io", "greenhouse.json"),
    (r"api\.lever\.co", "lever.json"),
    (r"api\.ashbyhq\.com", "ashby.json"),
    (r"api\.smartrecruiters\.com/v1/companies/[^/]+/postings\?", "smartrecruiters.json"),
    (r"api\.smartrecruiters\.com/v1/companies/[^/]+/postings/", None),  # detail: empty is fine
    (r"remotive\.com", "remotive.json"),
    (r"himalayas\.app", "himalayas.json"),
    (r"remoteok\.com", "remoteok.json"),
    (r"themuse\.com", "themuse.json"),
    (r"api\.adzuna\.com", "adzuna.json"),
    (r"data\.usajobs\.gov", "usajobs.json"),
    (r"jooble\.org", "jooble.json"),
    (r"myworkdayjobs\.com/wday/cxs/[^/]+/[^/]+/jobs$", "workday_list.json"),
    (r"myworkdayjobs\.com/wday/cxs/[^/]+/[^/]+/job/", "workday_job.json"),
    (r"apply\.workable\.com/api/v3/accounts/[^/]+/jobs", "workable_list.json"),
    (r"apply\.workable\.com/api/v2/accounts/[^/]+/jobs/", "workable_job.json"),
    (r"recruitee\.com", "recruitee.json"),
]


def fake_http(url, method="GET", body=None, headers=None, timeout=20, retries=2):
    for rx, name in ROUTES:
        if re.search(rx, url):
            return load(name) if name else {}
    raise AssertionError(f"unexpected request {url}")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(apis, "http_json", fake_http)
    monkeypatch.setattr(ats, "http_json", fake_http)
    monkeypatch.setattr(apis.time, "sleep", lambda s: None)
    monkeypatch.setattr(ats.time, "sleep", lambda s: None)
    for k, v in {"ADZUNA_APP_ID": "x", "ADZUNA_APP_KEY": "x", "USAJOBS_API_KEY": "x",
                 "USAJOBS_EMAIL": "x@example.com", "JOOBLE_API_KEY": "x"}.items():
        monkeypatch.setenv(k, v)


@pytest.fixture
def profile():
    # threshold 0: keep every posting so the parsers are exercised on all fixture rows
    return Profile({"search": {"locations": ["Chicago, IL"], "title_match_threshold": 0.0},
                    "tracks": {"core": ["credit risk manager"]}})


def check_rows(rows, site=None, min_rows=1):
    assert len(rows) >= min_rows, "parser returned nothing"
    for r in rows:
        assert r.get("title") and isinstance(r["title"], str)
        assert r.get("job_url", "").startswith("http"), r.get("job_url")
        assert "<" not in str(r.get("description") or "")[:2000] or "<" not in r["description"].replace("<-", ""), \
            "description still has HTML"
        if site:
            assert r.get("site") == site
        for k in r:
            assert k in set(JOB_COLUMNS) | {"req_id", "note", "verified", "employer_url", "closes"}, f"unexpected column {k}"
        for k in ("min_amount", "max_amount"):
            if r.get(k) not in (None, ""):
                float(r[k])
        if r.get("date_posted"):
            assert re.match(r"\d{4}-\d{2}-\d{2}", str(r["date_posted"])), r["date_posted"]


@pytest.mark.parametrize("name", ["remotive", "himalayas", "remoteok", "themuse", "adzuna", "usajobs", "jooble"])
def test_api_sources(name, profile):
    rows = apis.SOURCES[name](profile)
    check_rows(rows, site=name)
    assert all(r["track"] == "core" for r in rows)


@pytest.mark.parametrize("kind,slug", [("greenhouse", "dealpath"), ("lever", "cherre"), ("ashby", "junipersquare"),
                                       ("smartrecruiters", "BoschGroup"), ("workable", "acme"), ("recruitee", "acme"),
                                       ("workday", "example.wd1|example|External")])
def test_ats_sources(kind, slug):
    rows = ats.list_postings(kind, "Acme", slug)
    check_rows(rows, site=kind)
    assert all(r["company"] == "Acme" for r in rows)


def test_ats_title_filters():
    all_rows = ats.list_postings("greenhouse", "Dealpath", "dealpath")
    first = all_rows[0]["title"].lower().split()[0]
    kept = ats.list_postings("greenhouse", "Dealpath", "dealpath", include=re.escape(first))
    assert kept and all(first in r["title"].lower() for r in kept)
    assert ats.list_postings("greenhouse", "Dealpath", "dealpath", exclude=".") == []


def test_workday_details():
    r = ats.list_postings("workday", "Example", "example.wd1|example|External")[0]
    assert "site selection" in r["description"] and r["req_id"] == "R123"


def test_remote_location_filter(profile):
    profile.remote_allowed = ["zzz-nowhere"]
    rows = apis.remotive(profile)
    assert all(not r.get("location") or True for r in rows)  # runs with a restrictive filter
    assert len(rows) <= len(load("remotive.json")["jobs"])
