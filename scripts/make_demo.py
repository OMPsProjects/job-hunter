#!/usr/bin/env python3
"""Build a folder of fictional job-hunter data, for trying the web page or taking screenshots.

    python scripts/make_demo.py /tmp/jh-demo
    cd /tmp/jh-demo && job-hunter ui

Every company, person and posting in it is made up. Nothing touches the network.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TODAY = dt.date.today()
POSTINGS = [
    ("Senior Credit Underwriter", "Lakeshore Community Bank", "Chicago, IL", 135000, 160000, 2, "verified_open",
     "Underwrite commercial real estate loans from $5M to $40M. Size loans on DSCR and debt yield, write the credit memo, "
     "and present at committee. 7+ years of commercial underwriting. Apply by {soon}."),
    ("Commercial Real Estate Underwriter", "Harbor Point Capital", "New York, NY", None, None, 5, "verified_open",
     "Join our bridge lending team. You will spread rent rolls and operating statements, build cash flow models, and "
     "work with originators on structure. Experience with multifamily and industrial assets required."),
    ("Vice President, Credit Risk", "Meridian Trust", "Chicago, IL", 170000, 210000, 9, "employer_page_live",
     "Lead credit reviews for a $2B CRE portfolio. Manage two analysts. Regulatory exam experience preferred."),
    ("Real Estate Credit Analyst", "Bluestem Bank", "Evanston, IL", 95000, 115000, 1, "verified_open",
     "Spread financials, analyze guarantors, and support senior underwriters on construction and term loans."),
    ("Multifamily Loan Underwriter", "Prairie Housing Finance", "Remote", None, None, 3, "unverified",
     "Agency multifamily underwriting (Fannie Mae DUS or Freddie Mac Optigo). Remote within the U.S."),
    ("Underwriting Manager, Bridge Lending", "Northgate Lending", "New York, NY", 180000, 220000, 12, "verified_open",
     "Run the underwriting desk for transitional loans. Hire and coach a team of four. We are unable to sponsor visas."),
    ("Portfolio Manager, CRE", "Cedar Ridge Bank", "Naperville, IL", 125000, 150000, 6, "unverified",
     "Monitor covenant compliance, run annual reviews, and flag watch-list credits early."),
    ("Senior Analyst, Debt Investments", "Alder Street Partners", "New York, NY", None, None, 20, "verified_open",
     "Evaluate mezzanine and preferred equity investments. Strong modeling skills."),
    ("Credit Officer", "First Lantern Bank", "Chicago, IL", 150000, 175000, 4, "employer_page_live",
     "Approve credits within authority, review memos, and mentor underwriters."),
    ("Loan Review Specialist", "Union Grove Bancorp", "Chicago, IL", 90000, 105000, 15, "unverified",
     "Independent review of commercial loan files for risk rating accuracy."),
]


def build(dest: Path):
    from jobhunter import tracker
    from jobhunter.candidate import load_candidate
    from jobhunter.cli import write_outputs
    from jobhunter.profile import load_profile
    from jobhunter.rank import rank
    from jobhunter.scoring import score_row

    dest = Path(dest)
    if dest.exists() and any(dest.iterdir()):
        sys.exit(f"{dest} isn't empty; pick a new folder.")
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "profile.example.yaml", dest / "profile.yaml")
    shutil.copy(ROOT / "evals" / "fixtures" / "candidate.yaml", dest / "candidate.yaml")
    (dest / "candidate").mkdir()
    shutil.copy(ROOT / "evals" / "fixtures" / "resume.txt", dest / "candidate" / "resume.txt")

    import pandas as pd
    rows = []
    for i, (title, company, loc, lo, hi, days, verified, desc) in enumerate(POSTINGS):
        soon = (TODAY + dt.timedelta(days=5)).strftime("%B %d, %Y")
        rows.append({"title": title, "company": company, "location": loc, "is_remote": loc == "Remote",
                     "job_url": f"https://jobs.example.com/{i + 1}", "employer_url": f"https://careers.example.com/{i + 1}",
                     "date_posted": (TODAY - dt.timedelta(days=days)).isoformat(), "description": desc.format(soon=soon),
                     "min_amount": lo, "max_amount": hi, "interval": "yearly" if lo else None, "site": "indeed",
                     "track": "core", "region": "remote" if loc == "Remote" else ("nyc" if "NY" in loc else "chi"),
                     "verified": verified})
    jobs = pd.DataFrame(rows)
    p = load_profile(dest / "profile.yaml")
    jobs[["fit_score", "matched"]] = jobs.apply(score_row, axis=1, p=p)
    jobs.loc[1, "repost_note"] = "re-listed: this company posted the same title 34 days ago"
    ranked, excluded = rank(jobs, p, load_candidate(dest / "candidate.yaml"), wage_cache=None)
    out = dest / "results"
    out.mkdir()
    write_outputs(out, jobs, ranked, excluded, set(jobs.job_url))
    (out / "run_summary.json").write_text(json.dumps({
        "run_at": dt.datetime.now().replace(hour=8, minute=12).isoformat(timespec="minutes"), "scored": len(jobs),
        "new": len(ranked), "excluded": len(excluded), "verified": jobs["verified"].value_counts().to_dict(),
        "sources": {"jobspy": {"rows": 61, "errors": 0, "seconds": 412}, "remotive": {"rows": 3, "errors": 0, "seconds": 2},
                    "company_feeds": {"rows": 18, "errors": 1, "seconds": 37}}, "health_warnings": []}, indent=1))
    apps = dest / "applications.csv"
    tracker.upsert(apps, "shortlisted", "Lakeshore Community Bank", "Senior Credit Underwriter",
                   job_url="https://jobs.example.com/1", source="indeed")
    tracker.upsert(apps, "submitted", "Westbrook Savings", "Senior Underwriter", job_url="https://jobs.example.com/90",
                   source="company_feeds")
    tracker.upsert(apps, "interviewing", "Westbrook Savings", "Senior Underwriter", job_url="https://jobs.example.com/90")
    tracker.upsert(apps, "submitted", "Pine Hill Capital", "Credit Analyst", job_url="https://jobs.example.com/91", source="indeed")
    (dest / "companies.yaml").write_text(
        "companies:\n- {name: Lakeshore Community Bank, ats: greenhouse, slug: lakeshore-demo, source: you}\n"
        "- {name: Meridian Trust, ats: workday, slug: 'meridian.wd1|meridian|External', source: discovered}\n"
        "browse_boards:\n- {name: Example CRE Jobs, url: 'https://cre-jobs.example.com'}\n", encoding="utf-8")
    print(f"Demo folder ready: {dest}\nThen: cd {dest} && job-hunter ui")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    build(Path(sys.argv[1]))
