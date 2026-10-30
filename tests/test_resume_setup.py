"""Resume-first setup: reading a resume, turning its titles into searches, remote only."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jobhunter import setup, sources  # noqa: E402
from jobhunter.profile import Profile  # noqa: E402
from jobhunter.resume_parse import parse_resume  # noqa: E402

CRE = """ALEX MORGAN
Washington, D.C. 20500 • alex@example.com • 202-555-0100

PROFESSIONAL EXPERIENCE
Lakeshore Capital Bank — Washington, DC
Vice President, Lead Commercial Real Estate Underwriter            Mar 2022 – Present
• Underwrote $1B+ of balance sheet and bridge loans
Harbor Point Lending, McLean, VA
Senior Underwriter, Multifamily                                    Jun 2016 – Feb 2022
• Underwrote $2B of agency loans

EDUCATION
MBA, State University
CORE COMPETENCIES
Cash Flow Underwriting | Argus Enterprise | Loan Sizing | Market Analysis | Excel
"""
TECH = """Sam Lee
Austin, TX 78701 | sam@example.com
Work Experience
Senior Software Engineer | Acme Corp | Austin, TX | 01/2020 - Present
- Built things
Software Engineer at Initech, Dallas, TX (2016 - 2019)
Skills
Python, Go, Kubernetes, PostgreSQL
"""
NURSE = """Pat Kim
Boston, MA · pat@example.com
EXPERIENCE
Charge Nurse, Massachusetts General Hospital                2019–present
Staff Nurse, Boston Medical Center                          2014–2019
"""


def test_reads_three_resume_layouts():
    r = parse_resume(CRE)
    assert r["name"] == "Alex Morgan" and r["city"] == "Washington, DC"
    assert r["titles"] == ["Vice President, Lead Commercial Real Estate Underwriter", "Senior Underwriter, Multifamily"]
    assert r["current_employers"] == ["Lakeshore Capital Bank"]
    assert r["employers"] == ["Lakeshore Capital Bank", "Harbor Point Lending"]
    assert "Argus Enterprise" in r["skills"] and r["level"] == "vp" and r["years_experience"] == 10
    t = parse_resume(TECH)
    assert t["city"] == "Austin, TX" and t["titles"] == ["Senior Software Engineer", "Software Engineer"]
    assert t["employers"] == ["Acme Corp", "Initech"] and "Kubernetes" in t["skills"]
    n = parse_resume(NURSE)
    assert n["titles"] == ["Charge Nurse", "Staff Nurse"]
    assert n["current_employers"] == ["Massachusetts General Hospital"]


def test_resume_titles_become_searches():
    assert setup.search_titles(parse_resume(CRE)["titles"]) == ["Commercial Real Estate Underwriter", "Multifamily Underwriter"]
    assert setup.search_title("Senior Software Engineer") == "Software Engineer"
    assert setup.search_title("Director of Operations / Chief of Staff") == "Director of Operations"
    assert setup.search_title("VP, Credit Risk") == "VP, Credit Risk"  # nothing but the level says what it is


def test_city_list():
    cities = setup.us_cities()
    assert len(cities) == 1000 and cities[0] == "New York, NY" and "Washington, DC" in cities


def test_remote_only_profile_and_search(monkeypatch):
    prof = setup.build_profile({"titles": ["Underwriter"], "locations": ["Chicago, IL"], "remote_only": True})
    p = Profile(prof)
    assert p.remote_only and p.include_remote and p.locations == []
    rows = [{"title": "Underwriter", "company": "A", "location": "Remote", "is_remote": True, "job_url": "https://a/1"},
            {"title": "Underwriter", "company": "B", "location": "Chicago, IL", "job_url": "https://a/2"},
            {"title": "Underwriter", "company": "C", "location": "", "job_url": "https://a/3"}]
    p.sources = {k: False for k in p.sources} | {"remotive": True}
    monkeypatch.setitem(sources.apis.SOURCES, "remotive", lambda p_: rows)
    jobs, _ = sources.gather(p)
    assert list(jobs["company"]) == ["A"]
    assert isinstance(jobs, pd.DataFrame)


def test_setup_keeps_resume_titles_for_ranking(tmp_path):
    (tmp_path / "r.txt").write_text(CRE, encoding="utf-8")
    (tmp_path / "ansi.txt").write_bytes(CRE.encode("cp1252"))  # Notepad's "ANSI" on Windows
    from jobhunter.candidate import read_resume_text
    assert parse_resume(read_resume_text(tmp_path / "ansi.txt"))["titles"] == parse_resume(CRE)["titles"]
    setup.run_setup(tmp_path, {"resume": "r.txt", "titles": ["Commercial Real Estate Underwriter"]}, ask=None,
                    say=lambda *_: None)
    import yaml
    cand = yaml.safe_load((tmp_path / "candidate.yaml").read_text())
    assert cand["past_titles"][0].startswith("Vice President") and cand["contact"]["city"] == "Washington, DC"


STACKED = """DANA REYES
Washington, DC (relocating to Los Angeles) • (202) 555-0101 • dana@example.com
CORE COMPETENCIES
CMBS & Structured Credit • Loan Surveillance • DSCR, LTV,
Refinance & Maturity Risk • Loan Agreement &
Legal Document Review • Third-Party Report Review (Appraisal, Engineering, Zoning)
PROFESSIONAL EXPERIENCE
LAKESHORE CAPITAL BANK
 Bethesda, MD
Lead Commercial Real Estate Underwriter (Vice President)
 2022 – Present
•
Own credit analysis on 20-30 loans a year across conventional and agency executions.
REYES PROPERTY HOLDINGS LLC
 Washington, DC
Managing Member / Principal (concurrent)
 2018 – Present
•
Structured a 15-investor syndication.
HARBOR POINT LENDING (a private equity portfolio company)
 Charlotte, NC
Credit Analyst / Underwriter
 2013 – 2018
"""


def test_reads_company_city_title_dates_on_separate_lines():
    r = parse_resume(STACKED)
    assert [j["company"] for j in r["jobs"]] == ["Lakeshore Capital Bank", "Reyes Property Holdings LLC", "Harbor Point Lending"]
    assert r["titles"][0] == "Lead Commercial Real Estate Underwriter (Vice President)"
    assert r["current_employers"] == ["Lakeshore Capital Bank"]  # a concurrent side role isn't the employer to hide
    assert setup.search_titles(r["titles"]) == ["Commercial Real Estate Underwriter", "Credit Analyst"]
    assert "Loan Agreement & Legal Document Review" in r["skills"] and "LTV" in r["skills"]
    assert "Third-Party Report Review (Appraisal, Engineering, Zoning)" in r["skills"]


def test_spelling_warnings():
    p = Profile({"search": {"locations": ["Washigton, DC", "New York, NY"]},
                 "tracks": {"core": ["Commerical underwriter", "CMBS Originations Associate"]}})
    probs = " ".join(p.problems())
    assert "'commercial'" in probs and "Washington" in probs
    assert "cmbs" not in probs.lower() and "originations" not in probs
    assert setup._parse("cities", ["Washington, DC,"], "") == ["Washington, DC"]


def test_jobs_without_pay_are_kept_unless_asked():
    import pandas as pd

    from jobhunter import rank
    from jobhunter.candidate import Candidate
    df = pd.DataFrame([{"title": "Underwriter", "company": "A", "location": "Remote", "job_url": "https://a/1",
                        "description": "underwriting", "verified": "verified_open", "region": "remote"}])
    base = {"tracks": {"core": ["Underwriter"]}, "ranking": {"pay_floor": 150000, "pay_estimates": False}}
    ranked, excluded = rank.rank(df, Profile(base), Candidate({}), None)
    assert len(ranked) == 1 and excluded.empty
    base["ranking"]["require_posted_pay"] = True
    ranked, excluded = rank.rank(df, Profile(base), Candidate({}), None)
    assert ranked.empty and list(excluded["excluded_reason"]) == ["pay not posted"]


def test_linkedin_block_stops_asking(monkeypatch):
    import logging
    calls = []

    def fake(site_name, **kw):
        calls.append(list(site_name))
        if "linkedin" in site_name:
            logging.getLogger("jobspy.linkedin").error("response status code 429 (blocked: use a proxy)")
        return pd.DataFrame()
    p = Profile({"search": {"locations": ["Chicago, IL", "Austin, TX"], "sites": ["indeed", "linkedin"],
                            "pause_seconds": 0}, "tracks": {"core": ["Underwriter", "Credit Analyst"]}})
    sources._jobspy_searches(p, fake, _blocked_handler())
    assert calls[0] == ["indeed", "linkedin"] and all(c == ["indeed"] for c in calls[1:])


def _blocked_handler():
    import logging
    h = sources._Blocked()
    logging.getLogger("jobspy.linkedin").addHandler(h)
    return h
