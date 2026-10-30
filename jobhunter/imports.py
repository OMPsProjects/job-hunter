"""Postings collected outside the script (Claude reading LinkedIn or another board in your
browser) join the next search: `job-hunter import file.jsonl --source linkedin`.

Each line is one posting: {"title", "company", "location", "url", "date_posted", "description",
"query"} (only title, company and url are required; "query" is the search title it was found
under). Imported postings are kept in results/imported/ and used by every search whose time
window they fall in, then ignored.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from .common import cell_safe, html_to_text

SOURCE_NAME = re.compile(r"[a-z][a-z0-9_-]{1,30}")
MAX_ROWS = 2000


def _clean_row(r: dict, source: str):
    if not isinstance(r, dict):
        return None
    url = str(r.get("url") or r.get("job_url") or "").strip()
    title, company = cell_safe(str(r.get("title") or "").strip()), cell_safe(str(r.get("company") or "").strip())
    if not (title and company and url.startswith("https://")) or len(url) > 2000:
        return None
    date = str(r.get("date_posted") or "")[:10]
    return {"title": title[:200], "company": company[:200],
            "location": cell_safe(str(r.get("location") or "").strip())[:200],
            "is_remote": "remote" in str(r.get("location") or "").lower() or bool(r.get("is_remote")),
            "job_url": url, "date_posted": date if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) else "",
            "description": html_to_text(r.get("description"))[:60_000], "site": source,
            "query": cell_safe(str(r.get("query") or "").strip())[:200]}


def import_file(path: Path, out_dir: Path, source: str) -> tuple[int, int]:
    """Read a JSON-lines (or JSON array) file into out_dir/imported/<source>-<date>.jsonl.
    Returns (kept, skipped). Rows already imported (same link) are skipped."""
    if not SOURCE_NAME.fullmatch(source):
        raise ValueError("source must be a short lowercase name like 'linkedin'")
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
        rows = data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        rows = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    rows = [r for r in rows if not (isinstance(r, dict) and "_meta" in r)]  # the page script's summary line
    folder = Path(out_dir) / "imported"
    folder.mkdir(parents=True, exist_ok=True)
    have = {r["job_url"]: r for r in load_rows(out_dir, hours=24 * 365)}
    dest = folder / f"{source}-{dt.date.today().isoformat()}.jsonl"
    kept, skipped = [], 0
    for r in rows[:MAX_ROWS]:
        row = _clean_row(r, source)
        old = have.get(row["job_url"]) if row else None
        # already imported: only a description it didn't have before is worth adding
        if not row or (old and (old.get("description") or not row["description"])):
            skipped += 1
            continue
        have[row["job_url"]] = row
        kept.append(row)
    if kept:
        with dest.open("a", encoding="utf-8") as fh:
            for row in kept:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(kept), skipped + max(0, len(rows) - MAX_ROWS)


def load_rows(out_dir: Path, hours: int) -> list[dict]:
    """Imported postings from files written in the last `hours`, one per link (a later row fills in
    what an earlier one lacked, like a description read on a second pass)."""
    folder = Path(out_dir) / "imported"
    if not folder.is_dir():
        return []
    cutoff = dt.datetime.now().timestamp() - hours * 3600
    by_url: dict[str, dict] = {}
    for f in sorted(folder.glob("*.jsonl"), key=lambda f: f.stat().st_mtime):
        if f.stat().st_mtime < cutoff:
            continue
        for ln in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if isinstance(r, dict) and r.get("job_url"):
                old = by_url.get(r["job_url"], {})
                by_url[r["job_url"]] = {**old, **{k: v for k, v in r.items() if v not in ("", None) or k not in old}}
    return list(by_url.values())


def as_frame_rows(p, out_dir: Path) -> list[dict]:
    """Imported postings for gather(), each put under the track whose title found it."""
    by_title = {q.lower(): t for t, q in p.all_titles()}
    first = next(iter(p.tracks), "core")
    rows = []
    for r in load_rows(out_dir, p.hours_old):
        r = dict(r)
        # "query" may hold several titles searched together ("A / B"): use the closest to the job's title
        searched = [q.strip().lower() for q in str(r.get("query") or "").split(" / ") if q.strip().lower() in by_title]
        words = set(re.findall(r"[a-z]+", str(r.get("title") or "").lower()))
        best = max(searched, key=lambda q: len(words & set(re.findall(r"[a-z]+", q))), default="")
        r["track"] = by_title.get(best, first)
        r["query"] = r.get("query") or "imported"
        rows.append(r)
    return rows
