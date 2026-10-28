"""1.1 features: occupation data, careers-site directory, pay estimates, visa wording, reposts,
response stats, cover letters, the optional title model. All offline."""
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jobhunter import datasets, occupations, rank, tracker, verify, visa, wages  # noqa: E402
from jobhunter.candidate import Candidate  # noqa: E402
from jobhunter.cli import main  # noqa: E402
from jobhunter.humanize import lint_letter  # noqa: E402
from jobhunter.profile import Profile  # noqa: E402
from jobhunter.render import is_letter, render_letter  # noqa: E402
from jobhunter.setup import _numbered, build_profile, track_occupations  # noqa: E402
from jobhunter.store import Store  # noqa: E402

# ----------------------------- occupations ----------------------------------


def test_occupation_match_exact_and_noise_words():
    m = occupations.match("Senior Credit Analyst II")
    assert m["title"] == "Credit Analysts" and m["score"] == 1.0
    assert occupations.match("Registered Nurse")["code"].startswith("29-1141")
    assert occupations.soc6("13-2041.00") == "132041"


def test_occupation_match_refuses_vague_or_unknown_titles():
    assert occupations.match("Analyst") is None          # used by a dozen occupations
    assert occupations.match("Senior Analyst") is None
    assert occupations.match("Zorblax Wrangler") is None
    assert occupations.match("") is None


def test_suggestions_offer_related_titles_and_skills():
    s = occupations.suggestions(["Credit Analyst", "Loan Officer"])
    assert {m["query"] for m in s["matched"]} == {"Credit Analyst", "Loan Officer"}
    titles = [r["title"] for r in s["related_titles"]]
    assert titles and "Credit Analyst" not in titles and all(len(t.split()) > 1 for t in titles)
    assert "Microsoft Excel" in s["skills"] and "English Language" not in s["skills"]
    assert "O*NET" in s["attribution"]


def test_occupation_search():
    hits = occupations.search("underwriter")
    assert any(h["title"] == "Insurance Underwriters" for h in hits)


# ----------------------------- careers-site directory -----------------------

MANIFEST = {"by_ats_companies": {
    "greenhouse": {"csv": "https://x/greenhouse.csv"}, "workday": {"csv": "https://x/workday.csv"},
    "smartrecruiters": {"csv": "https://x/sr.csv"}}}
FILES = {
    "https://x/greenhouse.csv": "name,slug,url\nAcme Corp,acme,https://job-boards.greenhouse.io/acme\nTwin,twin,https://job-boards.greenhouse.io/twin\n",
    "https://x/workday.csv": ("name,slug,url\nBig Bank,bigbank/campus,https://bigbank.wd1.myworkdayjobs.com/Campus\n"
                              "Big Bank,bigbank/external,https://bigbank.wd1.myworkdayjobs.com/External_Careers\n"
                              "Twin,twin/x,https://twin.wd5.myworkdayjobs.com/Jobs\n"),
    "https://x/sr.csv": "name,slug,url\nShop Co,shopco,https://careers.smartrecruiters.com/shopco\n",
}


@pytest.fixture
def directory(monkeypatch):
    monkeypatch.setattr(datasets, "http_json", lambda url, **k: MANIFEST)
    n = datasets.update_directory(fetch=lambda url: FILES[url])
    assert n == 6
    return n


def test_directory_lookup_and_pick(directory, monkeypatch):
    assert datasets.directory_lookup("Acme Corp, Inc.") == [("greenhouse", "acme", "Acme Corp")]
    assert datasets.directory_lookup("Shop Co")[0][:2] == ("smartrecruiters", "shopco")
    monkeypatch.setattr(verify, "_probe", lambda *a: pytest.fail("the directory should answer first"))
    big = verify.discover("Big Bank")
    assert big == {"ats": "workday", "slug": "bigbank.wd1|bigbank|External_Careers", "confirmed": False, "how": "directory"}


def test_directory_missing_falls_back_to_probing(monkeypatch):
    calls = []
    monkeypatch.setattr(verify, "_probe", lambda kind, slug, company: calls.append(kind) or (kind == "lever", False))
    found = verify.discover("Nobody Listed")
    assert found["ats"] == "lever" and found["how"] == "name guess" and calls[0] == "greenhouse"


def test_auto_download_runs_once_and_only_when_on(monkeypatch):
    tries = []
    monkeypatch.setattr(datasets, "update_directory", lambda: tries.append(1) or (_ for _ in ()).throw(OSError("offline")))
    datasets._tried.clear()
    monkeypatch.delenv("JOBHUNTER_NO_DOWNLOAD")
    datasets.directory_lookup("Acme")
    assert tries == []  # off by default (tests, library use)
    datasets.configure(auto_download=True)
    datasets.directory_lookup("Acme")
    datasets.directory_lookup("Beta")
    assert tries == [1]  # a failed download isn't retried for every company
    datasets._tried.clear()


# ----------------------------- pay estimates --------------------------------

def _bls_ok(series, key):
    vals = {"12": 70000, "13": 90000, "14": 115000}
    out = []
    for sid in series:
        if sid.startswith("OEUM0099999"):  # an area BLS has no figure for
            out.append({"seriesID": sid, "data": []})
        else:
            out.append({"seriesID": sid, "data": [{"year": "2025", "value": str(vals[sid[-2:]] + (5000 if sid.startswith("OEUM") else 0))}]})
    return {"status": "REQUEST_SUCCEEDED", "Results": {"series": out}}


def test_series_ids():
    assert wages.series_id("0016980", "132041", "median") == "OEUM001698000000013204113"
    assert wages.series_id(wages.NATIONAL, "132041", "p25") == "OEUN000000000000013204112"


def test_prefetch_caches_and_falls_back_to_national(tmp_path):
    cache = wages.WageCache(tmp_path / "w.json")
    seen = []

    def req(series, key):
        seen.append(list(series))
        return _bls_ok(series, key)
    assert wages.prefetch([("0016980", "132041"), ("0099999", "132041")], cache, request=req) == 3
    assert wages.estimate("0016980", "132041", cache)["median"] == 95000
    est = wages.estimate("0099999", "132041", cache)
    assert est["median"] == 90000 and est["area"] == wages.NATIONAL
    assert json.loads((tmp_path / "w.json").read_text())  # saved
    assert wages.prefetch([("0016980", "132041")], cache, request=req) == 0  # cached: no request
    assert len(seen) == 1


def test_prefetch_survives_refusal(tmp_path):
    cache = wages.WageCache(tmp_path / "w.json")
    refused = {"status": "REQUEST_NOT_PROCESSED", "message": ["daily threshold reached"]}
    assert wages.prefetch([("0016980", "132041")], cache, request=lambda s, k: refused) == 0
    assert wages.estimate("0016980", "132041", cache) is None


def test_area_for_region_uses_profile_patterns():
    p = Profile({"regions": [{"key": "chi", "pattern": "chicago|evanston"}, {"key": "x", "pattern": "boise"}]})
    assert wages.area_for_region(p, "chi") == ("0016980", "Chicago metro")
    assert wages.area_for_region(p, "x")[0] == wages.NATIONAL
    assert wages.area_for_region(p, "remote")[0] == wages.NATIONAL


def _profile(**over):
    data = {"search": {"locations": ["Chicago, IL"]}, "regions": [{"key": "chi", "pattern": "chicago"}],
            "tracks": {"core": ["Credit Analyst"]}, "scoring": {"skills": {"credit": 5}},
            "ranking": {"pay_floor": 80000, "pay_target": 120000}}
    for k, v in over.items():
        data.setdefault(k, {}).update(v) if isinstance(v, dict) else data.__setitem__(k, v)
    return Profile(data)


def test_rank_uses_estimate_at_half_strength_and_never_excludes(tmp_path):
    p = _profile()
    cache = wages.WageCache(tmp_path / "w.json")
    cache.put("0016980", "132041", {"median": 125000.0, "p25": 100000.0, "p75": 150000.0, "year": 2025})
    cache.put(wages.NATIONAL, "132041", {"median": 60000.0, "year": 2025})
    jobs = pd.DataFrame([
        {"title": "Credit Analyst", "company": "A", "location": "Chicago, IL", "region": "chi", "track": "core",
         "job_url": "https://a/1", "description": "credit"},
        {"title": "Senior Credit Analyst", "company": "B", "location": "Remote", "region": "remote", "track": "core",
         "job_url": "https://a/2", "description": "credit"},
        {"title": "Credit Analyst", "company": "C", "location": "Chicago, IL", "region": "chi", "track": "core",
         "job_url": "https://a/3", "description": "credit", "max_amount": 150000, "interval": "yearly"},
    ])
    ranked, excluded = rank.rank(jobs, p, wage_cache=cache)
    assert excluded.empty  # the national estimate is under the floor, but estimates never exclude
    by = ranked.set_index("company")
    assert by.loc["A", "pay_score"] == 75 and by.loc["A", "pay_estimate"] == 125000
    assert "BLS median for Credit Analysts, Chicago metro 2025" in by.loc["A", "gaps"]
    assert by.loc["B", "pay_score"] == 25 and "U.S." in by.loc["B", "gaps"]
    assert by.loc["C", "pay_score"] == 100 and pd.isna(by.loc["C", "pay_estimate"])
    off = _profile(ranking={"pay_estimates": False})
    r2, _ = rank.rank(jobs, off, wage_cache=cache)
    assert set(r2.set_index("company").loc[["A", "B"], "pay_score"]) == {50}


def test_wage_requests_only_for_jobs_without_pay():
    p = _profile()
    jobs = pd.DataFrame([{"title": "Credit Analyst", "region": "chi", "track": "core"},
                         {"title": "Credit Analyst", "region": "chi", "track": "core", "max_amount": 100000},
                         {"title": "Mystery Role", "region": "remote", "track": "nope"}])
    assert rank.wage_requests(jobs, p) == [("0016980", "132041")]


# ----------------------------- visa -----------------------------------------

@pytest.mark.parametrize("text,status", [
    ("We are unable to sponsor visas for this role.", "no_sponsorship"),
    ("Must be authorized to work in the U.S. without the need for current or future visa sponsorship.", "no_sponsorship"),
    ("This position is not eligible for visa sponsorship.", "no_sponsorship"),
    ("Applicants must be a U.S. citizen.", "citizens_only"),
    ("Active Secret clearance required.", "citizens_only"),
    ("Visa sponsorship is available for this role.", "sponsors"),
    ("We will sponsor H-1B visas for the right candidate.", "sponsors"),
    ("Our sponsors include major banks.", ""),
    ("We are an equal opportunity employer.", ""),
])
def test_visa_wording(text, status):
    assert visa.posting_status(text)[0] == status


def test_rank_excludes_no_sponsorship_only_when_needed():
    jobs = pd.DataFrame([{"title": "Credit Analyst", "company": "A", "job_url": "https://a/1",
                          "description": "Credit role. We are unable to sponsor visas."},
                         {"title": "Credit Analyst", "company": "B", "job_url": "https://a/2",
                          "description": "Credit role. Visa sponsorship is available."}])
    ranked, excluded = rank.rank(jobs, _profile(filters={"needs_sponsorship": True}))
    assert list(excluded["excluded_reason"]) == ["says it won't sponsor a visa"]
    assert ranked.iloc[0]["visa_note"] == "posting mentions visa sponsorship"
    ranked, excluded = rank.rank(jobs, _profile())
    assert excluded.empty and set(ranked["visa_note"]) == {""}


def test_import_sponsors_both_layouts(tmp_path):
    new = tmp_path / "new.csv"
    new.write_text("Line by line,Fiscal Year   ,Employer (Petitioner) Name,Tax ID,New Employment Approval,"
                   "New Employment Denial,Continuation Approval\n1,2025,ACME CORP,1234,3,1,4\n2,2025,Acme Corp.,1234,1,0,0\n",
                   encoding="utf-8")
    old = tmp_path / "old.tsv"
    old.write_bytes("Fiscal Year\tEmployer\tInitial Approvals\tContinuing Approvals\n2019\tBeta LLC\t0\t0\n".encode("utf-16"))
    assert visa.import_sponsors(new) == 2
    assert visa.import_sponsors(old) == 1
    assert visa.employer_history("Acme Corporation") == "H-1B approvals on record: 8 in FY2025"
    assert visa.employer_history("Beta") == "no H-1B approvals on record"
    assert visa.employer_history("Gamma") == ""
    bad = tmp_path / "bad.csv"
    bad.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError):
        visa.import_sponsors(bad)


# ----------------------------- reposts ----------------------------------------

def test_repost_notes(tmp_path):
    st = Store(tmp_path / "db.sqlite")
    st.mark_seen([("https://a/old", "Acme Inc", "Credit Analyst"), ("https://a/recent", "Beta", "Analyst")])
    old = (dt.datetime.now() - dt.timedelta(days=40)).isoformat(timespec="seconds")
    st.db.execute("UPDATE seen SET first_seen=? WHERE job_url='https://a/old'", (old,))
    st.db.commit()
    notes = st.repost_notes([("https://a/new", "Acme", "Credit Analyst"), ("https://a/new2", "Beta", "Analyst"),
                             ("https://a/old", "Acme", "Credit Analyst")])
    assert notes == {"https://a/new": "re-listed: this company posted the same title 40 days ago"}
    st.close()


def test_repost_is_flagged_not_dropped():
    jobs = pd.DataFrame([{"title": "Credit Analyst", "company": "A", "job_url": "https://a/1", "description": "credit",
                          "repost_note": "re-listed: this company posted the same title 40 days ago"}])
    ranked, excluded = rank.rank(jobs, _profile())
    assert excluded.empty and "re-listed" in ranked.iloc[0]["gaps"]


# ----------------------------- tracker stats -----------------------------------

def test_tracker_history_and_stats(tmp_path):
    path = tmp_path / "apps.csv"
    tracker.upsert(path, "submitted", "A", "Analyst", job_url="https://a/1", source="indeed", ats="greenhouse")
    tracker.upsert(path, "interviewing", "A", "Analyst", job_url="https://a/1")
    tracker.upsert(path, "rejected", "A", "Analyst", job_url="https://a/1")
    tracker.upsert(path, "submitted", "B", "Analyst", source="indeed", resume_pdf="b.pdf")
    tracker.upsert(path, "submitted", "C", "Analyst", source="company_feeds")
    tracker.upsert(path, "shortlisted", "D", "Analyst")
    df = tracker.load(path)
    assert df.loc[df.company == "A", "history"].iloc[0].count("@") == 3
    st = tracker.stats(df)
    assert st["overall"] == {"sent": 3, "responses": 1, "interviews": 1, "response_rate": 0.33, "interview_rate": 0.33}
    assert st["by"]["source"]["indeed"]["interviews"] == 1
    assert st["by"]["resume"]["tailored resume"]["sent"] == 1
    later = dt.date.today() + dt.timedelta(days=30)
    assert len(tracker.stats(df, today=later)["waiting"]) == 2


# ----------------------------- cover letters ---------------------------------

LETTER = {"name": "Jordan Rivera", "contact": ["Chicago, IL", "jordan.rivera@example.com"], "date": "October 28, 2026",
          "recipient": ["Hiring Team", "Example Bank"], "greeting": "Dear Hiring Team,",
          "paragraphs": ["Your posting asks for someone who has sized bridge loans; I have closed 40 of them.",
                         "At Example Lending I rebuilt the credit memo template the team still uses."],
          "closing": "Sincerely,"}


def test_letter_render_and_lint(tmp_path):
    assert is_letter(LETTER)
    res = render_letter(LETTER, tmp_path / "l.pdf")
    assert res["fits"] and (tmp_path / "l.pdf").stat().st_size > 1000
    assert lint_letter(LETTER["paragraphs"]) == []
    issues = lint_letter(["I am writing to express my interest in this role!"] + LETTER["paragraphs"])
    assert any("stock opening" in m for _, m in issues) and any("exclamation" in m for _, m in issues)


def test_cli_lint_letter_checks_numbers(tmp_path, capsys):
    import yaml
    src = tmp_path / "resume.txt"
    src.write_text("Closed 40 bridge loans.")
    f = tmp_path / "letter.yaml"
    f.write_text(yaml.safe_dump({**LETTER, "paragraphs": LETTER["paragraphs"] + ["I managed a $90M book."]}))
    rc = main(["lint", str(f), "--sources", str(src), "--profile", str(tmp_path / "none.yaml")])
    out = capsys.readouterr().out
    assert rc == 1 and "90" in out and "2026" not in out  # the date isn't fact-checked; the body is


# ----------------------------- title model -----------------------------------

class _FakeSim:
    def __init__(self, scores):
        self.scores = scores

    def get(self, title):
        return self.scores.get(title)


def test_title_model_raises_title_closeness():
    from jobhunter import embed
    cand = Candidate({"target_titles": ["Credit Underwriter"], "skills": {"core": ["credit"]}})
    row = {"title": "Mortgage Underwriter", "description": "credit"}
    p = _profile()
    _, _, base = rank.fit_part(row, p, cand)
    _, _, boosted = rank.fit_part(row, p, cand, _FakeSim({"Mortgage Underwriter": 0.95}))
    assert boosted == 95 and boosted > base
    assert embed.scale(0.85) == 1 and embed.scale(0.1) == 0


# ----------------------------- setup -----------------------------------------

def test_setup_numbered_choices_and_occupations():
    assert _numbered("1, 3, Credit Officer", ["A", "B", "C"]) == "A, C, Credit Officer"
    assert _numbered("9", ["A"]) == "9"
    occ = track_occupations({"core": ["Credit Analyst"], "pivot": ["Zorblax Wrangler"]})
    assert occ == {"core": "13-2041.00"}
    assert track_occupations({"core": ["x"]}, {"core": "13-2072.00"}) == {"core": "13-2072.00"}
    prof = build_profile({"titles": ["Credit Analyst"], "locations": ["Chicago, IL"]})
    assert prof["setup"]["occupations"] == {"core": "13-2041.00"}
    assert Profile(prof).occupation_for_track("core") == "13-2041.00"


# ----------------------------- CLI smoke ---------------------------------------

def test_cli_occupations_data_stats(tmp_path, capsys):
    prof = tmp_path / "profile.yaml"
    prof.write_text("tracks: {core: [Credit Analyst]}\n")
    assert main(["occupations", "match", "Credit Analyst", "--profile", str(prof)]) == 0
    assert "Credit Analysts" in capsys.readouterr().out
    assert main(["data", "status", "--profile", str(prof)]) == 0
    assert "not downloaded yet" in capsys.readouterr().out
    assert main(["stats", "--profile", str(prof)]) == 0
    assert "No submitted applications" in capsys.readouterr().out


# ----------------------------- review fixes ----------------------------------

def test_directory_hits_can_verify_but_never_rule_out(directory):
    assert verify.discover("Acme Corp")["confirmed"] is False
    assert datasets.directory_lookup("Confidential") == []


def test_prefetch_keeps_each_pairs_series_together(tmp_path):
    cache = wages.WageCache(tmp_path / "w.json")
    pairs = [("0016980", f"13{i:04d}") for i in range(20)]
    wages.prefetch(pairs, cache, request=_bls_ok)
    for a, s in pairs:
        hit = cache.get(a, s)
        assert hit and {"p25", "median", "p75"} <= set(hit), (a, s)


def test_prefetch_never_raises(tmp_path):
    def broken(series, key):
        raise ValueError("not JSON")
    assert wages.prefetch([("0016980", "132041")], wages.WageCache(tmp_path / "w.json"), request=broken) == 0


def test_job_location_beats_a_multi_metro_region():
    p = Profile({"regions": [{"key": "ca", "pattern": ", ca\\b"}]})
    assert wages.area_for_job(p, {"region": "ca", "location": "San Jose, CA"})[0] == "0041940"
    assert wages.area_for_job(p, {"region": "ca", "location": "Fresno, CA"})[0] == wages.NATIONAL
    assert wages.area_for_job(p, {"region": "x", "location": "Portland, ME"})[0] == wages.NATIONAL
    assert wages.area_for_job(p, {"region": "remote", "location": "Chicago, IL"})[0] == wages.NATIONAL


@pytest.mark.parametrize("text", [
    "No security clearance required.", "Active Secret clearance preferred but not required.",
    "We welcome applicants with or without visa sponsorship needs.",
    "Must be a U.S. citizen, green card holder, or hold a valid work visa.",
    "Report to the Sponsor; there is no sponsor audit.",
])
def test_visa_false_positives(text):
    assert visa.posting_status(text)[0] == ""


def test_sponsor_reimport_replaces(tmp_path):
    f = tmp_path / "h.csv"
    f.write_text("Fiscal Year,Employer (Petitioner) Name,New Employment Approval\n2025,Acme,7\n")
    visa.import_sponsors(f)
    visa.import_sponsors(f)
    assert visa.employer_history("Acme") == "H-1B approvals on record: 7 in FY2025"


def test_stats_waiting_includes_rows_from_before_history():
    df = pd.DataFrame([{c: "" for c in tracker.COLUMNS} | {"status": "submitted", "company": "A", "title": "T",
                                                          "updated": "2026-01-01 10:00"}])
    assert tracker.stats(df, today=dt.date(2026, 3, 1))["waiting"] == ["A - T (59 days)"]


def test_example_cover_letter_lints_clean():
    import yaml
    data = yaml.safe_load((ROOT / "templates" / "cover_letter.example.yaml").read_text())
    assert [i for i in lint_letter(data["paragraphs"]) if i[0] == "error"] == []
    assert not any("starts with 'I'" in m for _, m in lint_letter(data["paragraphs"]))
