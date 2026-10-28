#!/usr/bin/env python3
"""Build a throwaway job-hunter folder for the fictional candidate, ready for an apply eval.

    python evals/make_workspace.py /tmp/jh-eval [--port 8765]

It copies the code, the fictional candidate's files, renders their tailored resume PDF, and
records the Mockbank job as 'tailored' in applications.csv, pointing at the mock site.
Then: start the mock site, open Claude Code in that folder, and say
"apply to the Mockbank Senior Credit Underwriter job". Afterwards run grade.py.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "evals" / "fixtures"


def build(dest: Path, port: int):
    dest = Path(dest)
    if dest.exists() and any(dest.iterdir()):
        sys.exit(f"{dest} isn't empty; pick a new folder.")
    dest.mkdir(parents=True, exist_ok=True)
    for item in ["job_hunter.py", "jobhunter", "skills", "templates", "profile.example.yaml", "requirements.txt"]:
        src = ROOT / item
        (shutil.copytree if src.is_dir() else shutil.copy)(src, dest / item)
    shutil.copy(ROOT / "profile.example.yaml", dest / "profile.yaml")
    shutil.copy(FIX / "candidate.yaml", dest / "candidate.yaml")
    shutil.copy(FIX / "answers.yaml", dest / "answers.yaml")
    (dest / "candidate").mkdir()
    shutil.copy(FIX / "resume.txt", dest / "candidate" / "resume.txt")

    sys.path.insert(0, str(dest))
    from jobhunter import tracker
    from jobhunter.render import render
    folder = dest / "applications" / "eval_mockbank_senior-credit-underwriter"
    folder.mkdir(parents=True)
    shutil.copy(ROOT / "templates" / "resume.example.yaml", folder / "resume.yaml")
    pdf = folder / "Jordan_Rivera_Resume_Mockbank.pdf"
    render(folder / "resume.yaml", pdf, target_pages=1)
    url = f"http://127.0.0.1:{port}/"
    tracker.upsert(dest / "applications.csv", "tailored", "Mockbank", "Senior Credit Underwriter",
                   location="Chicago, IL", job_url=url, employer_url=url, resume_pdf=str(pdf),
                   notes="EVAL: fictional job on the local mock site")
    print(f"Workspace ready at {dest}\n"
          f"1. python {ROOT / 'evals/mock_ats/server.py'} --port {port}\n"
          f"2. Open Claude Code in {dest} and say: apply to the Mockbank Senior Credit Underwriter job\n"
          f"3. python {ROOT / 'evals/mock_ats/grade.py'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("dest")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    build(Path(a.dest), a.port)
