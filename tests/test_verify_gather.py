"""Employer-site verification and the source runner, offline."""
import sys
import urllib.error
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import jobhunter.sources as sources  # noqa: E402
from jobhunter import verify  # noqa: E402
from jobhunter.common import HTTPError  # noqa: E402
from jobhunter.profile import Profile  # noqa: E402

BOARD = [{"title": "Senior Credit Analyst", "location": "Chicago, IL", "job_url": "https://job-boards.greenhouse.io/acme/jobs/1234567",
          "req_id": "R1"},
         {"title": "Software Engineer", "location": "Remote", "job_url": "https://job-boards.greenhouse.io/acme/jobs/7654321"}]


@pytest.fixture
def v(tmp_path, monkeypatch):
    p = Profile({"tracks": {"core": ["credit analyst"]}, "verify": {"ats_overrides": {"Override Co": ["lever", "ovr"]}}})
    ver = verify.Verifier(p, tmp_path / "cache.json")
    monkeypatch.setattr(verify.ats, "list_postings", lambda kind, company, slug, **k: [] if slug == "empty" else list(BOARD))
    return ver


def test_already_verified_passes_through(v):
    r = v.verify_one({"verified": "verified_open", "job_url": "https://x", "employer_url": "https://e"})
    assert r["verified"] == "verified_open" and r["employer_url"] == "https://e"


def test_ats_url_exact_and_closed(v):
    r = v.verify_one({"title": "Sr Credit Analyst", "company": "Acme", "job_url": "https://job-boards.greenhouse.io/acme/jobs/1234567"})
    assert r["verified"] == "verified_open"
    gone = v.verify_one({"title": "Underwriter", "company": "Acme", "job_url": "https://job-boards.greenhouse.io/acme/jobs/9999999"})
    assert gone["verified"] == "closed"  # board lists jobs, and this id isn't one of them


def test_board_by_discovery(v, monkeypatch):
    monkeypatch.setattr(verify, "discover", lambda name: {"ats": "greenhouse", "slug": "acme", "confirmed": True})
    hit = v.verify_one({"title": "Senior Credit Analyst", "company": "Acme Corp", "job_url": "https://www.linkedin.com/jobs/view/1"})
    assert hit["verified"] == "verified_open" and hit["employer_url"].endswith("1234567")
    miss = v.verify_one({"title": "Chief Llama Officer", "company": "Acme Corp", "job_url": "https://www.linkedin.com/jobs/view/2"})
    assert miss["verified"] == "not_on_employer_site"


def test_unconfirmed_or_empty_board_stays_unverified(v, monkeypatch):
    monkeypatch.setattr(verify, "discover", lambda name: {"ats": "greenhouse", "slug": "acme", "confirmed": False})
    r = v.verify_one({"title": "Chief Llama Officer", "company": "Maybe Acme", "job_url": "https://www.linkedin.com/jobs/view/3"})
    assert r["verified"] == "unverified"
    monkeypatch.setattr(verify, "discover", lambda name: {"ats": "greenhouse", "slug": "empty", "confirmed": True})
    r = v.verify_one({"title": "Analyst", "company": "Empty Co", "job_url": "https://www.linkedin.com/jobs/view/4"})
    assert r["verified"] == "unverified"


def test_override_is_used(v, monkeypatch):
    monkeypatch.setattr(verify, "discover", lambda name: pytest.fail("should use the override"))
    assert v.board_for("Override Co")["slug"] == "ovr"


def test_cache_survives(v, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(verify, "discover", lambda name: calls.append(name) or {"ats": None})
    v.board_for("Nobody Inc")
    v.board_for("Nobody Inc")
    v.save()
    v2 = verify.Verifier(v.p, v.cache_path)
    v2.board_for("Nobody Inc")
    assert calls == ["Nobody Inc"]


def test_workday_url(v, monkeypatch):
    url = "https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/Chicago-IL/Analyst_R1"
    monkeypatch.setattr(verify, "http_json", lambda u, **k: {"jobPostingInfo": {"canApply": True}})
    assert v.verify_one({"title": "Analyst", "company": "Acme", "job_url": url})["verified"] == "verified_open"
    monkeypatch.setattr(verify, "http_json", lambda u, **k: {"jobPostingInfo": {"canApply": False}})
    assert v.verify_one({"title": "Analyst", "company": "Acme", "job_url": url})["verified"] == "closed"

    def gone(u, **k):
        raise HTTPError(404, u)
    monkeypatch.setattr(verify, "http_json", gone)
    assert v.verify_one({"title": "Analyst", "company": "Acme", "job_url": url})["verified"] == "closed"


class _Resp:
    def __init__(self, text):
        self.text = text.encode()

    def read(self, n):
        return self.text[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_check_page(v, monkeypatch):
    body = "<html><body>" + "We are hiring a credit analyst. " * 30 + "</body></html>"
    monkeypatch.setattr(verify.urllib.request, "urlopen", lambda req, timeout=20: _Resp(body))
    assert v.check_page("https://careers.example.com/1") == "employer_page_live"
    closed = body.replace("We are hiring", "This position has been filled. We were hiring")
    monkeypatch.setattr(verify.urllib.request, "urlopen", lambda req, timeout=20: _Resp(closed))
    assert v.check_page("https://careers.example.com/1") == "closed"
    spa = "<html><script>var msg='job no longer available'</script><div id=root></div></html>"
    monkeypatch.setattr(verify.urllib.request, "urlopen", lambda req, timeout=20: _Resp(spa))
    assert v.check_page("https://careers.example.com/1") == "unverified"  # JS-only page: can't tell

    def e404(req, timeout=20):
        raise urllib.error.HTTPError("u", 404, "nf", {}, None)
    monkeypatch.setattr(verify.urllib.request, "urlopen", e404)
    assert v.check_page("https://careers.example.com/1") == "closed"


def test_verify_frame_never_crashes(v, monkeypatch, tmp_path):
    def boom(self, row):
        raise ValueError("bad row")
    monkeypatch.setattr(verify.Verifier, "verify_one", boom)
    df = pd.DataFrame([{"title": "A", "company": "B", "job_url": "https://x"}])
    out = verify.verify_frame(df, v.p, tmp_path / "c.json")
    assert out.iloc[0]["verified"] == "unverified" and "check failed" in out.iloc[0]["verify_note"]


def test_posting_id():
    assert verify.posting_id("https://job-boards.greenhouse.io/a/jobs/8006357003") == "8006357003"
    assert verify.posting_id("https://jobs.lever.co/p/6aa57fb6-7a58-4813-baa9-2f0713f08d69") == "6aa57fb6-7a58-4813-baa9-2f0713f08d69"
    assert verify.posting_id("https://example.com/careers") is None


# ----------------------------- gather ---------------------------------------

def test_gather_filters_dedupes_and_counts(monkeypatch):
    p = Profile({"search": {"locations": ["Chicago, IL"], "include_remote": True},
                 "regions": [{"key": "chi", "pattern": "chicago"}],
                 "tracks": {"core": ["credit analyst"]}, "sources": {k: False for k in
                 ["jobspy", "himalayas", "remoteok", "themuse", "adzuna", "usajobs", "jooble", "company_feeds", "arbeitnow"]}})
    rows = [
        {"title": "Credit Analyst", "company": "Acme", "location": "Chicago, IL", "job_url": "https://a/1", "site": "remotive"},
        {"title": "Credit Analyst", "company": "Acme", "location": "Remote", "is_remote": True, "job_url": "https://a/2", "site": "remotive"},
        {"title": "Credit Analyst", "company": "Other", "location": "Boston, MA", "job_url": "https://a/3", "site": "remotive"},
    ]

    def fake(p_):
        sources.log.warning("one failed", extra={"source": "remotive"})
        return rows
    monkeypatch.setitem(sources.apis.SOURCES, "remotive", fake)
    jobs, stats = sources.gather(p)
    assert list(jobs["job_url"]) == ["https://a/1"]  # Boston dropped; the duplicate keeps the top region
    assert stats["remotive"] == {"rows": 3, "errors": 1, "seconds": pytest.approx(0, abs=1)}


def test_gather_no_results(monkeypatch):
    p = Profile({"tracks": {"core": ["x"]}, "sources": {k: False for k in
                 ["jobspy", "remotive", "himalayas", "remoteok", "themuse", "adzuna", "usajobs", "jooble", "company_feeds"]}})
    with pytest.raises(sources.NoResults):
        sources.gather(p)


def test_gather_drops_remote_when_not_wanted(monkeypatch):
    p = Profile({"search": {"locations": ["Chicago, IL"], "include_remote": False},
                 "regions": [{"key": "chi", "pattern": "chicago"}], "tracks": {"core": ["credit analyst"]},
                 "sources": {k: False for k in ["jobspy", "himalayas", "remoteok", "themuse", "adzuna", "usajobs", "jooble",
                                                "company_feeds"]}})
    p.sources["remotive"] = True
    monkeypatch.setitem(sources.apis.SOURCES, "remotive", lambda p_: [
        {"title": "Credit Analyst", "company": "A", "location": "Remote", "is_remote": True, "job_url": "https://r/1"}])
    with pytest.raises(sources.NoResults):
        jobs, _ = sources.gather(p)
        if jobs.empty:
            raise sources.NoResults("empty")


def test_url_id_decides_even_when_title_matches(v):
    """A specific posting URL whose id is gone is closed, even if another job has the same title."""
    r = v.verify_one({"title": "Senior Credit Analyst", "company": "Acme",
                      "job_url": "https://job-boards.greenhouse.io/acme/jobs/5555555"})
    assert r["verified"] == "closed"


def test_failed_lookups_are_not_cached(v, monkeypatch):
    monkeypatch.setattr(verify, "discover", lambda name: {"ats": None, "definitive": False})
    v.board_for("Flaky Co")
    assert verify.company_key("Flaky Co") not in v.cache
    monkeypatch.setattr(verify, "discover", lambda name: {"ats": None, "definitive": True})
    v.board_for("Nobody Co")
    assert verify.company_key("Nobody Co") in v.cache


def test_probe_network_error_is_not_a_no(monkeypatch):
    def down(url, **k):
        raise HTTPError(503, url)
    monkeypatch.setattr(verify, "http_json", down)
    assert verify.discover("Acme")["definitive"] is False
    def missing(url, **k):
        raise HTTPError(404, url)
    monkeypatch.setattr(verify, "http_json", missing)
    assert verify.discover("Acme") == {"ats": None, "definitive": True}


def test_remote_elsewhere_is_dropped(monkeypatch):
    p = Profile({"search": {"locations": ["Chicago, IL"]}, "regions": [{"key": "chi", "pattern": "chicago"}],
                 "tracks": {"core": ["credit analyst"]},
                 "sources": {k: False for k in ["jobspy", "himalayas", "remoteok", "themuse", "adzuna", "usajobs",
                                                "jooble", "company_feeds"]}})
    monkeypatch.setitem(sources.apis.SOURCES, "remotive", lambda p_: [
        {"title": "Credit Analyst", "company": "A", "location": "Remote, Poland", "is_remote": True, "job_url": "https://r/1"},
        {"title": "Credit Analyst", "company": "B", "location": "Remote EMEA", "is_remote": True, "job_url": "https://r/2"},
        {"title": "Credit Analyst", "company": "C", "location": "Remote (United States)", "is_remote": True, "job_url": "https://r/3"},
        {"title": "Credit Analyst", "company": "D", "location": "Remote - TX", "is_remote": True, "job_url": "https://r/4"},
        {"title": "Credit Analyst", "company": "E", "location": "Remote", "is_remote": True, "job_url": "https://r/5"}])
    jobs, _ = sources.gather(p)
    assert sorted(jobs["company"]) == ["C", "D", "E"]
