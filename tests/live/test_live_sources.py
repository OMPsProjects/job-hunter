"""Live checks against the real job boards. Skipped unless JOBHUNTER_LIVE=1.
Run nightly in CI so a site changing its format is caught before users notice:

    JOBHUNTER_LIVE=1 python -m pytest tests/live -q
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from jobhunter.profile import Profile  # noqa: E402
from jobhunter.sources import apis, ats  # noqa: E402

pytestmark = pytest.mark.skipif(os.environ.get("JOBHUNTER_LIVE") != "1", reason="set JOBHUNTER_LIVE=1 to hit real sites")


@pytest.fixture
def profile():
    return Profile({"search": {"locations": ["New York, NY"], "title_match_threshold": 0.0},
                    "tracks": {"core": ["software engineer"]}})


@pytest.mark.parametrize("name", ["remotive", "himalayas", "remoteok", "themuse"])
def test_keyless_api(name, profile):
    rows = apis.SOURCES[name](profile)
    assert rows, f"{name} returned nothing: the site may be down or its format changed"
    assert all(r.get("title") and str(r.get("job_url", "")).startswith("http") for r in rows)


# Large, stable employers on each ATS. If one of them moves ATS, swap in another.
BOARDS = [("greenhouse", "airbnb"), ("lever", "palantir"), ("ashby", "ramp"), ("smartrecruiters", "BoschGroup")]


@pytest.mark.parametrize("kind,slug", BOARDS)
def test_ats(kind, slug):
    rows = ats.list_postings(kind, slug, slug, with_description=False)
    assert rows, f"{kind}/{slug} returned nothing"


def test_jobspy_indeed():
    jobspy = pytest.importorskip("jobspy")
    df = jobspy.scrape_jobs(site_name=["indeed"], search_term="accountant", location="Chicago, IL",
                            results_wanted=5, country_indeed="USA")
    assert len(df) > 0, "Indeed via python-jobspy returned nothing"


def test_dreamwork(profile, monkeypatch):
    monkeypatch.setattr(apis, "DREAMWORK_DETAILS_PER_RUN", 2)
    profile.include_remote = False
    rows = apis.dreamwork(profile)
    assert rows, "dreamwork returned nothing: the API may be down or its format changed"
    assert all(str(r["job_url"]).startswith("http") for r in rows)
    assert any(len(r["description"]) > 200 for r in rows[:2]), "no description from the detail route"


def test_oracle_and_successfactors_boards():
    """JPMorgan (Oracle Recruiting Cloud) and Scotiabank (SuccessFactors). If either moves
    system, swap in another employer on it."""
    jpm = ats.list_postings("oracle", "JPMorgan", "jpmc.fa.oraclecloud.com|CX_1001", with_description=False,
                            search_text="analyst", max_jobs=25)
    assert jpm, "oracle returned nothing: the API may have changed"
    sco = ats.list_postings("successfactors", "Scotiabank", "jobs.scotiabank.com", with_description=False,
                            search_text="analyst", max_jobs=25)
    assert sco, "successfactors search page returned nothing: the markup may have changed"
    assert ats.successfactors_job(sco[0]["job_url"]) == "open"
