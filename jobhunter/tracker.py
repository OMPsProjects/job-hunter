"""applications.csv: one row per job you've acted on. Feeds the 'already applied' filter and
`job-hunter stats` (which channels and kinds of jobs get responses)."""
import datetime as dt
from pathlib import Path

import pandas as pd

from .common import cell_safe, company_id, norm
from .fileio import write_csv_atomic

COLUMNS = ["id", "status", "company", "title", "location", "rank_score", "job_url", "employer_url",
           "resume_pdf", "notes", "added", "updated", "source", "ats", "track", "history"]
STATUSES = ["shortlisted", "tailored", "needs_account", "ready_for_review", "submitted", "skipped",
            "interviewing", "rejected", "offer"]


def load(path: Path) -> pd.DataFrame:
    path = Path(path)
    if path.exists() and path.stat().st_size:
        try:
            df = pd.read_csv(path, dtype=str).fillna("")
        except pd.errors.EmptyDataError:
            return pd.DataFrame(columns=COLUMNS)
        for c in COLUMNS:
            if c not in df:
                df[c] = ""
        return df[COLUMNS]
    return pd.DataFrame(columns=COLUMNS)


def save(df, path: Path):
    write_csv_atomic(df, path)


def find(df, company=None, title=None, url=None):
    """Same application = same URL or employer posting id, or (no link match) same company and exactly
    the same title."""
    if url:
        from .sources.ats import posting_key
        pid = posting_key(url)
        for i, r in df.iterrows():
            if url in (r["job_url"], r["employer_url"]):
                return i
            if pid and pid in {posting_key(u) for u in (r["job_url"], r["employer_url"]) if isinstance(u, str)}:
                return i
    for i, r in df.iterrows():
        if company and title and company_id(r["company"]) == company_id(company) and norm(r["title"]) == norm(title):
            return i
    return None


def remove_shortlisted(path: Path, job_url=None, employer_url=None, company=None, title=None) -> bool:
    """Undo a shortlist: drop the row, but only if nothing else has happened to it yet."""
    df = load(path)
    i = find(df, company, title, job_url or employer_url)
    if i is None or df.at[i, "status"] != "shortlisted":
        return False
    save(df.drop(index=i).reset_index(drop=True), path)
    return True


def upsert(path: Path, status, company, title, **fields):
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    company, title = cell_safe(company), cell_safe(title)  # may come straight from a posting
    df = load(path)
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    i = find(df, company, title, fields.get("job_url") or fields.get("employer_url"))
    if i is None:
        new_id = str(1 + max([int(x) for x in df["id"] if str(x).isdigit()] or [0]))
        row = {c: "" for c in COLUMNS}
        row.update({"id": new_id, "company": company, "title": title, "added": now})
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        i = df.index[-1]
    if df.at[i, "status"] != status:  # every change of status, for response-rate stats
        hist = [h for h in str(df.at[i, "history"] or "").split(";") if h]
        df.at[i, "history"] = ";".join(hist + [f"{status}@{now[:10]}"])
    df.at[i, "status"] = status
    df.at[i, "updated"] = now
    for k, v in fields.items():
        if k in COLUMNS and v not in (None, ""):
            df.at[i, k] = str(v)
    save(df, path)
    return df.loc[i].to_dict()


# ----------------------------- stats -------------------------------------------

SENT = {"submitted", "interviewing", "rejected", "offer"}
HEARD = {"interviewing", "rejected", "offer"}
INTERVIEW = {"interviewing", "offer"}


def _statuses(r):
    hist = [h.split("@")[0] for h in str(r.get("history") or "").split(";") if h]
    return set(hist) | {r.get("status")}


def _days_since_sent(r, today):
    day = None
    for h in str(r.get("history") or "").split(";"):
        st, _, d = h.partition("@")
        if st == "submitted":
            day = d
            break
    if day is None and r.get("status") == "submitted":  # rows from before status history was kept
        day = str(r.get("updated") or r.get("added") or "")[:10]
    try:
        return (today - dt.date.fromisoformat(day)).days if day else None
    except ValueError:
        return None


def stats(df, today=None, waiting_days=21):
    """Applications sent, responses and interviews, overall and by source, careers system, track
    and whether the resume was tailored. A 'response' is any interview, offer or rejection."""
    today = today or dt.date.today()
    rows = [r for _, r in df.iterrows() if _statuses(r) & SENT]

    def summarize(group):
        sent = len(group)
        heard = sum(1 for r in group if _statuses(r) & HEARD)
        interviews = sum(1 for r in group if _statuses(r) & INTERVIEW)
        return {"sent": sent, "responses": heard, "interviews": interviews,
                "response_rate": round(heard / sent, 2) if sent else None,
                "interview_rate": round(interviews / sent, 2) if sent else None}

    out = {"overall": summarize(rows), "by": {}}
    for field, label in (("source", "source"), ("ats", "careers system"), ("track", "track")):
        groups: dict = {}
        for r in rows:
            groups.setdefault(str(r.get(field) or "unknown"), []).append(r)
        out["by"][label] = {k: summarize(v) for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))}
    tailored: dict = {"tailored resume": [], "no tailored resume": []}
    for r in rows:
        tailored["tailored resume" if str(r.get("resume_pdf") or "").strip() else "no tailored resume"].append(r)
    out["by"]["resume"] = {k: summarize(v) for k, v in tailored.items() if v}
    waiting = [(r, d) for r in rows if r.get("status") == "submitted"
               and (d := _days_since_sent(r, today)) is not None and d >= waiting_days]
    waiting.sort(key=lambda x: -x[1])
    out["waiting"] = [f"{r['company']} - {r['title']} ({d} days)" for r, d in waiting]
    # for follow-up drafts: everything the skill needs to find the application folder and posting
    out["waiting_items"] = [{"company": r["company"], "title": r["title"], "days": d, "job_url": r.get("job_url", ""),
                             "employer_url": r.get("employer_url", ""), "resume_pdf": r.get("resume_pdf", "")}
                            for r, d in waiting]
    return out
