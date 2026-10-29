"""Oracle Recruiting Cloud and SuccessFactors: listing, posting-by-posting checks, and the
pre-apply re-check. Recorded responses (JPMorgan on Oracle, Scotiabank on SuccessFactors), no
network."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jobhunter import cli, tracker, verify  # noqa: E402
from jobhunter.profile import Profile  # noqa: E402
from jobhunter.sources import ats  # noqa: E402
from jobhunter.targets import resolve_url  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "sources"
HOST, SITE = "jpmc.fa.oraclecloud.com", "CX_1001"
OPEN_ID = "210804172"
ORACLE_URL = f"https://{HOST}/hcmUI/CandidateExperience/en/sites/{SITE}/job/{OPEN_ID}"
SF = "https://jobs.scotiabank.com"
SF_OPEN = f"{SF}/job/Vancouver-Team-Lead-Credit-BC-V5H1Z5/607153517/"
SF_CLOSED = f"{SF}/job/Toronto-Senior-Manager-ON-M5H1H1/602788017/"


def _json(name):
    return json.loads((FIX / name).read_text())


def fake_oracle(url, **k):
    assert url.startswith(f"https://{HOST}/hcmRestApi/resources/latest/"), url
    if "recruitingCEJobRequisitionDetails" in url:
        return _json("oracle_job.json") if f'Id="{OPEN_ID}"' in url else {"items": []}
    return _json("oracle_list.json")


def fake_sf(url):
    html = lambda n: (FIX / n).read_text()  # noqa: E731
    if "/search/" in url:
        return url, html("successfactors_search.html")
    if "607153517" in url:
        return url, html("successfactors_job.html")
    if "602788017" in url:
        return url, html("successfactors_closed.html")
    return f"{SF}/errorpage/?errortype=Exception", "<html><link href='https://rmkcdn.successfactors.com/a.css'></html>"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(ats, "http_json", fake_oracle)
    monkeypatch.setattr(ats, "_sf_get", fake_sf)
    monkeypatch.setattr(ats.time, "sleep", lambda s: None)


@pytest.fixture
def v(tmp_path):
    return verify.Verifier(Profile({"tracks": {"core": ["underwriter"]}}), tmp_path / "cache.json")


# ----------------------------- recognizing links ---------------------------

def test_oracle_link_shapes():
    assert ats.ats_from_url(ORACLE_URL) == ("oracle", f"{HOST}|{SITE}")
    assert ats.ats_from_url("https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/jobsearch/job/1") \
        == ("oracle", "eeho.fa.us2.oraclecloud.com|jobsearch")
    assert ats.posting_key(ORACLE_URL + "?utm=x") == f"oracle:{HOST}:{OPEN_ID}"
    assert ats.posting_key(SF_OPEN) == "successfactors:jobs.scotiabank.com:607153517"
    for bad in ("http://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/1",  # not https
                "https://evil.example/hcmUI/CandidateExperience/en/sites/CX/job/1",
                "https://x.fa.oraclecloud.com.evil.example/hcmUI/CandidateExperience/en/sites/CX/job/1"):
        assert ats.ats_from_url(bad) == (None, None)
    assert not ats.valid_slug("oracle", "jpmc.fa.oraclecloud.com|CX_1001/../x")
    assert not ats.valid_slug("successfactors", "127.0.0.1") and not ats.valid_slug("successfactors", "a/b.com")
    with pytest.raises(ValueError):
        ats.oracle_job("evil.example", SITE, OPEN_ID)


# ----------------------------- listing -------------------------------------

def test_oracle_listing():
    rows = ats.list_postings("oracle", "JPMorgan", f"{HOST}|{SITE}", search_text='credit "underwriter"')
    assert len(rows) == 3 and rows[0]["job_url"] == ORACLE_URL and rows[0]["site"] == "oracle"
    assert rows[0]["date_posted"] and len(rows[0]["description"]) > 200  # full text from the detail call


def test_successfactors_listing():
    rows = ats.list_postings("successfactors", "Scotiabank", "jobs.scotiabank.com", search_text="credit")
    assert len(rows) == 3
    assert all(r["job_url"].startswith(f"{SF}/job/") and r["location"] for r in rows)
    assert rows[0]["req_id"] and rows[0]["site"] == "successfactors"


def test_boards_add_recognizes_both():
    assert resolve_url(ORACLE_URL) == ("oracle", f"{HOST}|{SITE}")
    assert resolve_url(f"{SF}/search/?q=analyst") == ("successfactors", "jobs.scotiabank.com")


# ----------------------------- posting checks ------------------------------

def test_oracle_posting_open_and_closed(v):
    r = v.verify_one({"title": "x", "company": "JPMorgan", "job_url": "https://www.indeed.com/viewjob?jk=1",
                      "job_url_direct": ORACLE_URL})
    assert r["verified"] == "verified_open" and r["employer_url"] == ORACLE_URL
    gone = v.verify_one({"title": "x", "company": "JPMorgan", "job_url": ORACLE_URL.replace(OPEN_ID, "999999999")})
    assert gone["verified"] == "closed"


def test_oracle_posting_past_end_date_is_closed(v, monkeypatch):
    ended = _json("oracle_job.json")
    ended["items"][0]["ExternalPostedEndDate"] = "2020-01-31T00:00:00+00:00"
    monkeypatch.setattr(ats, "http_json", lambda url, **k: ended)
    assert v.verify_one({"title": "x", "company": "JPMorgan", "job_url": ORACLE_URL})["verified"] == "closed"


def test_successfactors_open_closed_removed(v):
    assert v.verify_one({"title": "x", "company": "Scotiabank", "job_url": SF_OPEN})["verified"] == "verified_open"
    # still at its address, but "not accepting any further applicants"
    assert v.verify_one({"title": "x", "company": "Scotiabank", "job_url": SF_CLOSED})["verified"] == "closed"
    gone = f"{SF}/job/Toronto-Nothing/123456789/"
    assert v.verify_one({"title": "x", "company": "Scotiabank", "job_url": gone})["verified"] == "closed"


def test_non_successfactors_job_path_falls_through(v, monkeypatch):
    monkeypatch.setattr(ats, "_sf_get", lambda url: (url, "<html>some other careers system</html>"))
    r = v.verify_one({"title": "x", "company": "", "job_url": "https://careers.example.com/job/Analyst/1234567/"})
    assert r["verified"] == "unverified"


# ----------------------------- re-check before applying ---------------------

def test_verify_tracker_marks_closed(tmp_path, monkeypatch, capsys):
    p = Profile({"tracks": {"core": ["underwriter"]}, "tracker_file": str(tmp_path / "applications.csv")},
                tmp_path / "profile.yaml")
    path = p.resolve(p.tracker_file)
    tracker.upsert(path, "tailored", "JPMorgan", "Underwriter", job_url=ORACLE_URL)
    tracker.upsert(path, "shortlisted", "JPMorgan", "Analyst", job_url=ORACLE_URL.replace(OPEN_ID, "999999999"))
    tracker.upsert(path, "submitted", "Scotiabank", "Team Lead", job_url=SF_CLOSED)  # already sent: not re-checked
    monkeypatch.setattr(cli, "out_dir_for", lambda p_, a: tmp_path)
    args = type("A", (), {"tracker": True, "mark_closed": True, "url": None, "company": None, "title": None,
                          "location": ""})()
    assert cli.cmd_verify(p, args) == 2
    out = capsys.readouterr().out
    assert "open" in out and "GONE" in out and "Team Lead" not in out
    df = tracker.load(path)
    assert dict(zip(df["title"], df["status"], strict=True)) == {
        "Underwriter": "tailored", "Analyst": "skipped", "Team Lead": "submitted"}


def test_verify_needs_a_target(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "out_dir_for", lambda p_, a: tmp_path)
    args = type("A", (), {"tracker": False, "mark_closed": False, "url": None, "company": None, "title": None,
                          "location": ""})()
    assert cli.cmd_verify(Profile({"tracks": {"core": ["x"]}}), args) == 1
