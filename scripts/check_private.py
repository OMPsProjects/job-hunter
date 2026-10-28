#!/usr/bin/env python3
"""Refuse to commit personal files or personal data.

    python scripts/check_private.py [files...]   # pre-commit passes the staged files
    python scripts/check_private.py --all        # everything git tracks (CI)

.gitignore keeps private files out by default, but `git add -f` or a renamed file gets past it.
This catches both: private file names and paths, and contents that look like a real person's
email, phone or ID number. Fictional examples use example.com and 555-01xx numbers.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PRIVATE_NAMES = {"profile.yaml", "candidate.yaml", "answers.yaml", "applications.csv", "companies.yaml", ".env",
                 "labels.csv", "jobhunter.db", "ats_cache.json", "state.json", "seen_jobs.csv", "setup_answers.yaml",
                 "ranked.csv", "jobs_all.csv", "jobs_new.csv", "excluded.csv", "run_summary.json", ".coverage",
                 "jobs_new_details.jsonl"}
PRIVATE_PATTERNS = (re.compile(r"^(profile|candidate|answers|companies)\.ya?ml\.(bak|old|orig|\d+)$"),
                    re.compile(r"^shortlist-.*\.md$"), re.compile(r"^run-.*\.jsonl$"))
PRIVATE_DIRS = ("results/", "applications/", "candidate/", "resumes/", "logs/")
PRIVATE_SUFFIXES = (".pdf", ".docx", ".doc", ".odt", ".rtf", ".pages", ".xlsx", ".xls", ".db", ".sqlite", ".pkl")
# Recorded public job postings may contain recruiters' public contact details.
CONTENT_EXEMPT = ("tests/fixtures/sources/",)
ALLOWED_EMAIL = re.compile(r"@(example\.(com|org|net)|users\.noreply\.github\.com|anthropic\.com)$|^noreply@", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+\w")
PHONE = re.compile(r"(?<!\d)\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)")
INTL_PHONE = re.compile(r"(?<![\w])\+(?!1\b)\d{1,3}[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,4}){2,4}(?!\d)")
SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")


def tracked():
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if f]


def problems(path: str):
    p = path.replace("\\", "/")
    name = Path(p).name
    if name in PRIVATE_NAMES or name.startswith(".env") or any(rx.match(name) for rx in PRIVATE_PATTERNS):
        yield "private file (it belongs in .gitignore, not the repo)"
        return
    if any(p.startswith(d) or f"/{d}" in p for d in PRIVATE_DIRS):
        yield "file in a private folder"
        return
    if p.lower().endswith(PRIVATE_SUFFIXES):
        yield "document or database file (resumes and run data stay local)"
        return
    if p.startswith(CONTENT_EXEMPT) or p.endswith("check_private.py"):
        return
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
        return
    for m in EMAIL.finditer(text):
        e = m.group(0)
        if not ALLOWED_EMAIL.search(e) and not re.search(r"\.(png|jpg|svg|gif)$", e):
            yield f"email address {e!r} (use an @example.com address in examples)"
    for m in PHONE.finditer(text):
        if not re.search(r"555[\s.-]?01\d\d$", m.group(0)):
            yield f"phone number {m.group(0)!r} (use 555-01xx in examples)"
    for m in INTL_PHONE.finditer(text):
        yield f"international phone number {m.group(0)!r}"
    for m in SSN.finditer(text):
        if m.group(0) not in ("123-45-6789",):  # the canonical fake used in tests
            yield f"SSN-like number {m.group(0)!r}"


def ignored_but_tracked():
    """Files .gitignore says to keep out that are in the repo anyway (added with -f, or before the rule)."""
    out = subprocess.run(["git", "ls-files", "-ci", "--exclude-standard"], capture_output=True, text=True).stdout
    return [f for f in out.splitlines() if f]


def main(argv):
    files = tracked() if "--all" in argv else [a for a in argv if not a.startswith("--")]
    bad = 0
    for f in ignored_but_tracked():
        print(f"{f}: tracked even though .gitignore excludes it (git rm --cached {f})")
        bad += 1
    for f in files:
        for msg in problems(f):
            print(f"{f}: {msg}")
            bad += 1
    if bad:
        print(f"\n{bad} problem(s). If a flagged value is genuinely fake, change it to the example formats above.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
