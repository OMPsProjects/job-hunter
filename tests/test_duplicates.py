"""One job, many sources: the same posting must come out once, however each source spells the
company or links to it, and a job you applied to must not come back under another spelling."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jobhunter import rank, sources, tracker  # noqa: E402
from jobhunter.common import company_id  # noqa: E402
from jobhunter.profile import Profile  # noqa: E402
from jobhunter.sources.ats import posting_key  # noqa: E402

WD = "https://cvshealth.wd1.myworkdayjobs.com/CVS_Health_Careers/job/CT---Hartford/Sr-Analyst--Pharmacy-Underwriter_R1021400-1"
BB = "https://bbinsurance.wd1.myworkdayjobs.com/Careers/job/Remote---Montana/Renewal-Underwriter_R26_0000003297-1"
OFF = ["jobspy", "remotive", "himalayas", "remoteok", "themuse", "adzuna", "usajobs", "jooble", "company_feeds",
       "arbeitnow", "dreamwork", "imported"]


def test_company_id_spellings():
    assert company_id("CVS Health") == company_id("Cvshealth") == "cvshealth"
    assert company_id("Attain Finance") == company_id("Attainfinance")
    assert company_id("At CBIZ") == company_id("CBIZ") == "cbiz"
    assert company_id("Stripe, Inc.") == company_id("Stripe")
    assert company_id("AT&T") == "att" and company_id("AT&T") != company_id("T")
    assert company_id("Brown & Brown Insurance") != company_id("Bbinsurance")  # only the posting id can match these


def test_posting_key_shapes():
    assert posting_key(WD) == posting_key(WD.replace("myworkdayjobs.com/", "myworkdayjobs.com/en-US/") + "?source=indeed")
    assert posting_key(BB) == "workday:bbinsurance:r26_0000003297-1"
    assert posting_key("https://stripe.com/jobs/search?gh_jid=7540441") == \
        posting_key("https://job-boards.greenhouse.io/stripe/jobs/7540441") == "greenhouse:7540441"
    assert posting_key("https://jobs.lever.co/a/6aa57fb6-7a58-4813-baa9-2f0713f08d69/apply").startswith("lever:")
    assert posting_key("https://apply.workable.com/acme/j/ABC123/") == "workable:acme:ABC123"
    # same req number at two different employers is two jobs
    assert posting_key(WD) != posting_key(WD.replace("cvshealth.", "othercorp."))
    for not_a_posting in ("https://www.indeed.com/viewjob?jk=abc123", "https://www.dreamworkhq.com/job/x",
                          "javascript:alert(1)", None, ""):
        assert posting_key(not_a_posting) is None


def _gather(monkeypatch, rows, **search):
    p = Profile({"search": {"locations": ["Hartford, CT"], "include_remote": True, **search},
                 "regions": [{"key": "ct", "pattern": "hartford|ct"}],
                 "tracks": {"core": ["underwriter"]}, "sources": {k: False for k in OFF} | {"remotive": True}})
    monkeypatch.setitem(sources.apis.SOURCES, "remotive", lambda p_: rows)
    jobs, _ = sources.gather(p)
    return jobs


def test_same_job_different_company_spelling(monkeypatch):
    rows = [
        {"title": "Sr Analyst, Pharmacy Underwriter", "company": "Cvshealth", "location": "Hartford, CT",
         "job_url": WD, "site": "dreamwork", "description": ""},
        {"title": "Sr Analyst, Pharmacy Underwriter", "company": "CVS Health", "location": "Hartford, CT",
         "job_url": "https://www.indeed.com/viewjob?jk=1", "site": "indeed", "description": "x" * 300},
    ]
    jobs = _gather(monkeypatch, rows)
    assert len(jobs) == 1 and jobs.iloc[0]["site"] == "indeed"  # the copy with a description wins


def test_same_posting_id_different_names(monkeypatch):
    rows = [
        {"title": "Renewal Underwriter", "company": "Bbinsurance", "location": "Remote", "is_remote": True,
         "job_url": BB, "site": "dreamwork"},
        {"title": "Renewal Underwriter - Commercial Lines", "company": "Brown & Brown", "location": "Remote",
         "is_remote": True, "job_url": "https://www.indeed.com/viewjob?jk=2", "job_url_direct": BB + "?src=indeed",
         "site": "indeed"},
    ]
    assert len(_gather(monkeypatch, rows)) == 1


def test_employer_site_copy_beats_aggregator_with_same_link(monkeypatch):
    rows = [
        {"title": "Underwriter", "company": "Cvshealth", "location": "Hartford, CT", "job_url": WD, "site": "dreamwork"},
        {"title": "Underwriter", "company": "CVS Health", "location": "Hartford, CT", "job_url": WD,
         "site": "workday", "verified": "verified_open", "employer_url": WD},
    ]
    jobs = _gather(monkeypatch, rows)
    assert len(jobs) == 1 and jobs.iloc[0]["verified"] == "verified_open"


def test_different_jobs_survive(monkeypatch):
    rows = [
        {"title": "Underwriter", "company": "CVS Health", "location": "Hartford, CT", "job_url": WD, "site": "x"},
        {"title": "Senior Underwriter", "company": "CVS Health", "location": "Hartford, CT",
         "job_url": WD.replace("R1021400-1", "R1099999-1"), "site": "x"},
        {"title": "Underwriter", "company": "Travelers", "location": "Hartford, CT",
         "job_url": "https://www.indeed.com/viewjob?jk=3", "site": "x"},
    ]
    assert len(_gather(monkeypatch, rows)) == 3


def _profile(**extra):
    return Profile({"tracks": {"core": ["underwriter"]}, **extra})


def test_already_applied_under_other_spelling_and_link():
    applied_df = pd.DataFrame([{"status": "submitted", "company": "CVS Health", "title": "Underwriter",
                                "job_url": "https://www.indeed.com/viewjob?jk=9",
                                "employer_url": WD + "?source=indeed"}])
    keys = rank.applied_keys(_profile(), applied_df)
    by_name = {"company": "Cvshealth", "title": "Underwriter", "job_url": "https://x.example/1"}
    by_posting = {"company": "Someone Else", "title": "Other title", "job_url": WD}
    assert rank.hard_filter_reason(by_name, _profile(), keys) == "already applied"
    assert rank.hard_filter_reason(by_posting, _profile(), keys) == "already applied"


def test_exclude_company_any_spelling():
    p = _profile(filters={"exclude_companies": ["CVS Health"]})
    assert "excluded company" in str(rank.hard_filter_reason({"company": "Cvshealth", "title": "Underwriter"}, p, []))


def test_tracker_finds_same_posting_by_id():
    df = pd.DataFrame([{"company": "CVS Health", "title": "Underwriter", "job_url": WD, "employer_url": None}])
    assert tracker.find(df, url=WD.replace("myworkdayjobs.com/", "myworkdayjobs.com/en-US/")) == 0
    assert tracker.find(df, company="Cvshealth", title="underwriter") == 0


def test_seen_under_another_link_is_not_new(tmp_path):
    from jobhunter.store import Store
    st = Store(tmp_path / "h.db")
    st.mark_seen([("https://www.indeed.com/viewjob?jk=1", "CVS Health", "Underwriter"), (WD, "CVS Health", "Analyst")])
    seen = st.seen_matcher()
    assert seen("https://www.indeed.com/viewjob?jk=1")
    assert seen(WD + "?source=dreamwork", "Cvshealth", "Something else")          # same posting id
    assert seen("https://www.dreamworkhq.com/job/x", "Cvshealth", "Underwriter")   # same company + title
    assert not seen("https://www.indeed.com/viewjob?jk=2", "CVS Health", "Senior Underwriter")


def test_title_gone_for_weeks_is_new_again(tmp_path):
    from jobhunter.store import Store
    st = Store(tmp_path / "h.db")
    st.mark_seen([("https://www.indeed.com/viewjob?jk=1", "CVS Health", "Underwriter")])
    st.db.execute("UPDATE seen SET first_seen='2026-01-01T00:00:00', last_seen='2026-01-02T00:00:00'")
    assert not st.seen_matcher()("https://www.indeed.com/viewjob?jk=7", "CVS Health", "Underwriter")
