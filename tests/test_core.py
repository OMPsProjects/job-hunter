"""Offline tests: no network. Run with  python -m pytest -q"""
import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jobhunter import answers, humanize, render, tracker  # noqa: E402
from jobhunter.candidate import LEVEL_INDEX, Candidate, guess_contact, guess_years, title_level, years_required  # noqa: E402
from jobhunter.common import annualize, company_key, parse_salary_text, title_similarity  # noqa: E402
from jobhunter.profile import load_profile  # noqa: E402
from jobhunter.rank import rank  # noqa: E402
from jobhunter.scoring import score_row  # noqa: E402
from jobhunter.sources import ats, region  # noqa: E402
from jobhunter.verify import slug_candidates  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


@pytest.fixture
def profile():
    return load_profile(ROOT / "profile.example.yaml")


@pytest.fixture
def cand():
    return Candidate(yaml.safe_load((ROOT / "candidate.example.yaml").read_text()))


# ----------------------------- profile / sources ----------------------------

def test_example_profile_is_valid(profile):
    hard = [m for m in profile.problems() if "no tracks" in m or "bad regex" in m]
    assert not hard
    assert profile.weights == {"fit": 40, "seniority": 20, "location": 15, "pay": 15, "freshness": 10}


def test_region(profile):
    assert region(profile, "Evanston, IL") == "chi"
    assert region(profile, "Brooklyn, NY") == "nyc"
    assert region(profile, "Arlington, VA") == "other"
    assert region(profile, "Anywhere", True) == "remote"
    assert region(profile, "") == "unspecified"


def test_ats_from_url():
    assert ats.ats_from_url("https://job-boards.greenhouse.io/affirm/jobs/123") == ("greenhouse", "affirm")
    assert ats.ats_from_url("https://jobs.lever.co/prosper/abc") == ("lever", "prosper")
    assert ats.ats_from_url("https://jobs.ashbyhq.com/meridianlink/x") == ("ashby", "meridianlink")
    kind, slug = ats.ats_from_url("https://firstam.wd1.myworkdayjobs.com/firstamericancareers/job/X/Y_R1")
    assert kind == "workday" and slug == "firstam.wd1|firstam|firstamericancareers"
    assert ats.ats_from_url("https://www.linkedin.com/jobs/view/1") == (None, None)


def test_slug_candidates():
    assert slug_candidates("The Carlyle Group, Inc.") == ["carlyle"]
    assert slug_candidates("Juniper Square") == ["junipersquare", "juniper-square"]
    assert "first" not in slug_candidates("First Citizens Bank")


# ----------------------------- small helpers --------------------------------

def test_title_similarity():
    assert title_similarity("Sr. Commercial Real Estate Underwriter", "Senior Commercial Real Estate Underwriter") > 0.7
    assert title_similarity("Credit Risk Manager", "Chief Llama Wrangler") < 0.3


def test_company_key():
    assert company_key("The Carlyle Group, Inc.") == company_key("Carlyle")


def test_pay_helpers():
    assert annualize(50, "hourly") == 104000
    assert annualize(150000, "yearly") == 150000
    assert annualize(None, "yearly") is None
    assert parse_salary_text("$120,000 - $150,000 a year") == (120000, 150000, "yearly")
    assert parse_salary_text("$120k-$150k")[:2] == (120000, 150000)


def test_title_level():
    assert title_level("Vice President, Credit") == LEVEL_INDEX["vp"]
    assert title_level("Senior Vice President") == LEVEL_INDEX["vp"]
    assert title_level("President") == LEVEL_INDEX["executive"]
    assert title_level("Associate Director, Underwriting") == LEVEL_INDEX["director"]
    assert title_level("Senior Underwriter") == LEVEL_INDEX["senior"]
    assert title_level("Credit Analyst") == LEVEL_INDEX["mid"]
    assert title_level("Summer Analyst") == LEVEL_INDEX["intern"]


def test_years_required():
    assert years_required("Requires 5+ years of commercial lending experience") == 5
    assert years_required("3-5 years experience in underwriting; 10 years total is a plus") == 3
    assert years_required("Founded 120 years ago") is None


def test_resume_guessing():
    text = (FIX / "sample_resume.txt").read_text()
    c = guess_contact(text)
    assert c["email"] == "jordan.rivera@example.com" and c["name"] == "Jordan Rivera"
    assert guess_years(text) == dt.date.today().year - 2016


# ----------------------------- ranking --------------------------------------

def _job(**kw):
    base = dict(title="Senior Credit Risk Manager", company="Acme Bank", location="Chicago, IL",
                is_remote=False, region="chi", description="5+ years of experience. Underwriting, DSCR, credit memo, "
                "commercial real estate, cash flow analysis.", max_amount=170000, min_amount=140000,
                interval="yearly", date_posted=dt.date.today().isoformat(), track="core",
                verified="verified_open", job_url="https://x/1")
    base.update(kw)
    return base


def test_rank_orders_and_filters(profile, cand):
    profile.pay_floor, profile.pay_target = 120000, 175000
    profile.exclude_companies = ["Old Employer"]
    jobs = pd.DataFrame([
        _job(),
        _job(title="Credit Analyst", job_url="https://x/2", max_amount=None, min_amount=None,
             description="1+ years experience, excel", region="unspecified", verified="unverified"),
        _job(company="Old Employer LLC", job_url="https://x/3"),
        _job(job_url="https://x/4", max_amount=90000, min_amount=80000),
        _job(job_url="https://x/5", verified="closed"),
        _job(job_url="https://x/6", title="Senior Credit Risk Manager", company="Beta Bank", verified="not_on_employer_site"),
    ])
    jobs[["fit_score", "matched"]] = jobs.apply(score_row, axis=1, p=profile)
    ranked, excluded = rank(jobs, profile, cand)
    assert list(ranked["job_url"]) == ["https://x/1", "https://x/2"]
    assert ranked.iloc[0]["rank_score"] > ranked.iloc[1]["rank_score"]
    reasons = dict(zip(excluded["job_url"], excluded["excluded_reason"], strict=True))
    assert reasons["https://x/3"].startswith("excluded company")
    assert reasons["https://x/4"] == "pay below floor"
    assert reasons["https://x/5"] == "closed on employer site"
    assert reasons["https://x/6"] == "not on employer's job board"
    assert "pay not posted" in ranked.iloc[1]["gaps"]


def test_rank_already_applied(profile, cand, tmp_path):
    t = tmp_path / "applications.csv"
    tracker.upsert(t, "submitted", "Acme Bank", "Senior Credit Risk Manager", job_url="https://x/1")
    jobs = pd.DataFrame([_job()])
    jobs[["fit_score", "matched"]] = jobs.apply(score_row, axis=1, p=profile)
    ranked, excluded = rank(jobs, profile, cand, tracker.load(t))
    assert len(ranked) == 0 and excluded.iloc[0]["excluded_reason"] == "already applied"


def test_rank_weights_change_order(profile, cand):
    a = _job(job_url="https://x/a", region="nyc", max_amount=250000, min_amount=200000)   # great pay, 2nd region
    b = _job(job_url="https://x/b", region="chi", max_amount=None, min_amount=None)       # top region, no pay
    jobs = pd.DataFrame([a, b])
    jobs[["fit_score", "matched"]] = jobs.apply(score_row, axis=1, p=profile)
    profile.pay_floor, profile.pay_target = 120000, 175000
    profile.weights = {"fit": 0, "seniority": 0, "location": 0, "pay": 100, "freshness": 0}
    assert rank(jobs, profile, cand)[0].iloc[0]["job_url"] == "https://x/a"
    profile.weights = {"fit": 0, "seniority": 0, "location": 100, "pay": 0, "freshness": 0}
    assert rank(jobs, profile, cand)[0].iloc[0]["job_url"] == "https://x/b"


# ----------------------------- answers --------------------------------------

def test_answer_bank_blocks_ids_and_eeo(tmp_path):
    bank = answers.AnswerBank(tmp_path / "answers.yaml")
    assert bank.add("What is your Social Security Number?", "123-45-6789")[0] is False
    assert bank.add("Driver's license number", "D1234567")[0] is False
    assert bank.add("Please provide your bank account number for direct deposit", "000123")[0] is False
    assert bank.add("Gender", "Male")[0] is False
    assert bank.add("Are you a protected veteran?", "No")[0] is False
    assert bank.add("Do you have a disability?", "No")[0] is False
    assert bank.add("Race / ethnicity", "Decline")[0] is False
    assert bank.add("Notes", "card 4111 1111 1111 1111")[0] is False  # value guard
    assert bank.answers == []


def test_answer_bank_saves_and_matches(tmp_path):
    bank = answers.AnswerBank(tmp_path / "answers.yaml")
    assert bank.add("Will you now or in the future require visa sponsorship?", "No")[0]
    assert bank.add("What are your salary expectations?", "$150,000 base")[0]  # salary IS saved
    bank.set_fact("email", "a@example.com")
    again = answers.AnswerBank(tmp_path / "answers.yaml")  # reload from disk
    hit = again.match("Do you now, or will you in the future, require sponsorship for employment visa status?")
    assert hit and hit["answer"] == "No"
    assert again.match("Desired salary")["answer"] == "$150,000 base"
    assert again.match("Compensation expectations")["answer"] == "$150,000 base"
    assert again.match("Email address")["answer"] == "a@example.com"
    assert again.match("What is your favorite color?") is None
    assert again.match("What is your gender?") is None


def test_answer_update_not_duplicate(tmp_path):
    bank = answers.AnswerBank(tmp_path / "answers.yaml")
    bank.add("Are you willing to relocate?", "No")
    bank.add("Are you willing to relocate?", "Yes")
    assert len(bank.answers) == 1 and bank.answers[0]["answer"] == "Yes"


# ----------------------------- lint / render --------------------------------

def test_lint_flags_ai_words():
    issues = humanize.lint_text("Spearheaded robust synergies — leveraging a proven track record!",
                                ["Spearheaded a thing", "Spearheaded b", "Spearheaded c"])
    errs = " ".join(m for lvl, m in issues if lvl == "error")
    for w in ("spearheaded", "robust", "proven track record", "em dash", "exclamation"):
        assert w in errs
    assert any("start with 'spearheaded'" in m for _, m in issues)


def test_lint_clean_example_passes():
    data = render.load_resume(ROOT / "templates" / "resume.example.yaml")
    issues = humanize.lint_text(render.resume_text(data), render.all_bullets(data))
    assert not [m for lvl, m in issues if lvl == "error"], issues


def test_fact_check_catches_invented_numbers():
    src = [(FIX / "sample_resume.txt").read_text()]
    ok = render.resume_text(render.load_resume(ROOT / "templates" / "resume.example.yaml"))
    assert humanize.fact_check(ok, src) == ["9"]          # 9 years is derived from dates...
    assert humanize.fact_check(ok, src, allowed=[9]) == []  # ...so it's allowed via candidate years
    bad = ok + "\nGrew the book to $900M and cut losses 40% across 250 loans"
    missing = humanize.fact_check(bad, src, allowed=[9])
    assert "$900,000,000" in missing and "40%" in missing and "250" in missing


def test_render_pdf(tmp_path):
    out = tmp_path / "r.pdf"
    res = render.render(ROOT / "templates" / "resume.example.yaml", out, target_pages=1)
    assert out.exists() and res["pages"] == 1 and res["fits"]
    from pypdf import PdfReader
    text = PdfReader(str(out)).pages[0].extract_text()
    assert "Jordan Rivera" in text and "Senior Credit Underwriter" in text


# ----------------------------- tracker --------------------------------------

def test_tracker_upsert(tmp_path):
    t = tmp_path / "a.csv"
    r1 = tracker.upsert(t, "shortlisted", "Acme", "Underwriter", job_url="u1")
    r2 = tracker.upsert(t, "ready_for_review", "Acme", "Underwriter", resume_pdf="x.pdf")
    df = tracker.load(t)
    assert len(df) == 1 and r1["id"] == r2["id"] and df.iloc[0]["status"] == "ready_for_review"
    with pytest.raises(ValueError):
        tracker.upsert(t, "bogus", "A", "B")


def test_every_example_yaml_loads():
    for f in list(ROOT.glob("*.example.yaml")) + list((ROOT / "templates").glob("*.yaml")):
        assert yaml.safe_load(f.read_text()) is not None, f


@pytest.mark.parametrize("text,needle", [
    ("It's not just a loan book, it's a portfolio strategy.", "not X but Y"),
    ("This isn't about titles. It's about results.", "not X but Y"),
    ("Here's the thing: I close deals.", "here's the thing"),
    ("Enhanced the credit memo process.", "enhanced"),
    ("Moving forward, I will lean into data.", "lean into"),
    ("Ran the desk -- and the team.", "double hyphen"),
    ("Ran the desk – and the team.", "en dash"),
    ("Your renowned firm is nestled in the heart of Chicago.", "renowned"),
    ("I hope this helps. Great question.", "chatbot residue"),
])
def test_lint_catches_more_ai_tells(text, needle):
    assert any(needle in m for lvl, m in humanize.lint_text(text) if lvl == "error"), humanize.lint_text(text)


def test_lint_leaves_plain_writing_alone():
    ok = ("Underwrote 40 bridge loans from 2019–2022, not counting renewals. Ran the credit committee memo "
          "process and trained two analysts. The deals were not large, but the timelines were short.")
    assert [m for lvl, m in humanize.lint_text(ok) if lvl == "error"] == []


def test_bundled_humanizer_is_present():
    ref = ROOT / "skills" / "job-hunter" / "references"
    text = (ref / "humanizer.md").read_text(encoding="utf-8")
    assert "Humanizer: remove AI writing patterns" in text and (ref / "humanizer-LICENSE.txt").exists()
    for f in ("tailoring.md", "cover-letters.md", "applying.md", "follow-ups.md", "review-rubric.md"):
        assert "references/humanizer.md" in (ref / f).read_text(encoding="utf-8"), f


# ----------------------------- shape check (vendored slop-guard) -------------

SLOPPY_BULLETS = ["Spearheaded robust credit initiatives, driving efficiency, scalability, and growth",
                  "Leveraged cutting-edge tools to streamline workflows, ensuring seamless collaboration",
                  "Fostered a culture of excellence, empowering teams to unlock their full potential",
                  "Orchestrated transformative strategies, showcasing a commitment to innovation"]
HUMAN_BULLETS = ["Underwrote 40 bridge and construction loans, $5M to $35M, for the balance sheet",
                 "Rebuilt the credit memo template in 2024; term sheet to committee now takes about a week less",
                 "Trained two analysts",
                 "Sized loans on DSCR and debt yield and wrote the risk section of every memo I presented",
                 "Cut stale pipeline deals from 60 to 25 by closing out anything without a signed LOI after 90 days"]


def test_shape_check_flags_ai_shapes_and_passes_plain_bullets():
    bad = humanize.shape_check(humanize.resume_prose("", SLOPPY_BULLETS), "resume")
    good = humanize.shape_check(humanize.resume_prose("", HUMAN_BULLETS), "resume")
    assert len([m for _, m in bad["issues"] if m.startswith("shape:")]) >= 4
    assert any("triadic" in m for _, m in bad["issues"])
    assert good["issues"] == []
    assert all(level == "warn" for level, _ in bad["issues"])  # advice, never a hard block
    assert bad["score"] is None  # too short for the 0-100 score to mean anything


def test_shape_check_skips_markdown_rules_on_resumes():
    many = humanize.resume_prose("", HUMAN_BULLETS * 3)
    assert not any("bullet" in m and "density" in m for _, m in humanize.shape_check(many, "resume")["issues"])


def test_shape_check_runs_on_python_310_without_strenum():
    """job-hunter supports 3.10; StrEnum is 3.11+. The vendored copy falls back."""
    import subprocess
    code = ("import enum; del enum.StrEnum\n"
            "from jobhunter import humanize\n"
            "r = humanize.shape_check('It is robust. It is seamless. It is cutting-edge. It is pivotal. It is key.', 'letter')\n"
            "print(len(r['issues']))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, timeout=60)
    assert out.returncode == 0, out.stderr
    assert int(out.stdout.strip()) > 0
