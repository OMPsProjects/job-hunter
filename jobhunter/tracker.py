"""applications.csv: one row per job you've acted on. Feeds the 'already applied' filter."""
import datetime as dt
from pathlib import Path

import pandas as pd

from .common import company_key, norm
from .fileio import write_csv_atomic

COLUMNS = ["id", "status", "company", "title", "location", "rank_score", "job_url", "employer_url",
           "resume_pdf", "notes", "added", "updated"]
STATUSES = ["shortlisted", "tailored", "needs_account", "ready_for_review", "submitted", "skipped",
            "interviewing", "rejected", "offer"]


def load(path: Path) -> pd.DataFrame:
    path = Path(path)
    if path.exists():
        df = pd.read_csv(path, dtype=str).fillna("")
        for c in COLUMNS:
            if c not in df:
                df[c] = ""
        return df[COLUMNS]
    return pd.DataFrame(columns=COLUMNS)


def save(df, path: Path):
    write_csv_atomic(df, path)


def find(df, company=None, title=None, url=None):
    """Same application = same URL, or (no URL match) same company and exactly the same title."""
    if url:
        for i, r in df.iterrows():
            if url in (r["job_url"], r["employer_url"]):
                return i
    for i, r in df.iterrows():
        if company and title and company_key(r["company"]) == company_key(company) and norm(r["title"]) == norm(title):
            return i
    return None


def upsert(path: Path, status, company, title, **fields):
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    df = load(path)
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    i = find(df, company, title, fields.get("job_url") or fields.get("employer_url"))
    if i is None:
        new_id = str(1 + max([int(x) for x in df["id"] if str(x).isdigit()] or [0]))
        row = {c: "" for c in COLUMNS}
        row.update({"id": new_id, "company": company, "title": title, "added": now})
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        i = df.index[-1]
    df.at[i, "status"] = status
    df.at[i, "updated"] = now
    for k, v in fields.items():
        if k in COLUMNS and v not in (None, ""):
            df.at[i, k] = str(v)
    save(df, path)
    return df.loc[i].to_dict()
