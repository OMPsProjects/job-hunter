"""SQLite run history: which jobs you've seen, every run, and how each source did.

results/jobhunter.db. Used to tell 'new' jobs from ones you've seen, and to notice when a
source quietly breaks (returns nothing for runs in a row when it used to return plenty).
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import statistics
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started TEXT NOT NULL,
  finished TEXT,
  status TEXT NOT NULL DEFAULT 'running',
  summary TEXT
);
CREATE TABLE IF NOT EXISTS source_stats (
  run_id INTEGER NOT NULL REFERENCES runs(id),
  source TEXT NOT NULL,
  rows INTEGER NOT NULL,
  errors INTEGER NOT NULL,
  seconds REAL NOT NULL,
  PRIMARY KEY (run_id, source)
);
CREATE TABLE IF NOT EXISTS seen (
  job_url TEXT PRIMARY KEY,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  company TEXT,
  title TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""
SCHEMA_VERSION = "1"


def _now():
    return dt.datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30)
        from .fileio import secure
        secure(self.path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.db.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
        self.db.commit()

    def close(self):
        self.db.close()

    # -- runs ----------------------------------------------------------------
    def start_run(self) -> int:
        cur = self.db.execute("INSERT INTO runs (started) VALUES (?)", (_now(),))
        self.db.commit()
        return int(cur.lastrowid or 0)

    def finish_run(self, run_id: int, status: str, summary: dict):
        self.db.execute("UPDATE runs SET finished=?, status=?, summary=? WHERE id=?",
                        (_now(), status, json.dumps(summary, default=str), run_id))
        self.db.commit()

    def record_sources(self, run_id: int, stats: dict):
        self.db.executemany(
            "INSERT OR REPLACE INTO source_stats VALUES (?,?,?,?,?)",
            [(run_id, s, int(v.get("rows", 0)), int(v.get("errors", 0)), float(v.get("seconds", 0)))
             for s, v in stats.items()])
        self.db.commit()

    # -- seen ----------------------------------------------------------------
    def seen_urls(self) -> set:
        return {r[0] for r in self.db.execute("SELECT job_url FROM seen")}

    def seen_matcher(self, recent_days: int = 14):
        """A function row -> bool: was this job already seen, under any link? Same link, same
        employer posting id, or the same company and title still listed in the last `recent_days`
        days (the same job from another source). A title that disappeared longer ago than that
        stays new, and repost_notes says it's a re-post."""
        from .common import company_id, norm
        from .sources.ats import posting_key
        urls, pids, recent = set(), set(), set()
        cutoff = (dt.datetime.now() - dt.timedelta(days=recent_days)).isoformat(timespec="seconds")
        for url, last, comp, title in self.db.execute("SELECT job_url, last_seen, company, title FROM seen"):
            urls.add(url)
            pid = posting_key(url)
            if pid:
                pids.add(pid)
            if comp and title and str(last) >= cutoff:
                recent.add((company_id(comp), norm(title)))

        def seen(job_url, company=None, title=None, *links) -> bool:
            if job_url in urls:
                return True
            if any(k in pids for k in (posting_key(u) for u in (job_url, *links) if isinstance(u, str)) if k):
                return True
            return bool(company and title) and (company_id(company), norm(title)) in recent
        return seen

    def mark_seen(self, rows):
        """rows: iterable of (job_url, company, title)."""
        now = _now()
        self.db.executemany(
            "INSERT INTO seen (job_url, first_seen, last_seen, company, title) VALUES (?,?,?,?,?) "
            "ON CONFLICT(job_url) DO UPDATE SET last_seen=excluded.last_seen",
            [(u, now, now, c, t) for u, c, t in rows if u])
        self.db.commit()

    def repost_notes(self, rows, min_days: int = 14) -> dict:
        """For new postings, a note when the same company listed the same title under a different
        link at least `min_days` ago: {job_url: note}. A re-listed job can be a hard-to-fill role,
        a refreshed ad for a role that's quietly filled, or a standing 'pipeline' posting, so this
        is shown as a flag, never used to drop a job. rows: iterable of (job_url, company, title)."""
        from .common import company_id, norm
        earlier: dict = {}
        for url, first, comp, title in self.db.execute(
                "SELECT job_url, first_seen, company, title FROM seen WHERE company IS NOT NULL AND title IS NOT NULL"):
            earlier.setdefault((company_id(comp), norm(title)), []).append((first, url))
        today = dt.datetime.now()
        notes = {}
        for url, comp, title in rows:
            prior = [(f, u) for f, u in earlier.get((company_id(comp), norm(title)), []) if u != url]
            old = []
            for first, _ in prior:
                try:
                    age = (today - dt.datetime.fromisoformat(first)).days
                except (TypeError, ValueError):
                    continue
                if age >= min_days:
                    old.append(age)
            if old:
                n = len(old)
                notes[url] = (f"re-listed: this company posted the same title {max(old)} days ago"
                              + (f" ({n} earlier listings)" if n > 1 else ""))
        return notes

    def import_seen_csv(self, csv_path: Path) -> int:
        """One-time import of the older seen_jobs.csv."""
        if not csv_path.exists() or self.db.execute("SELECT value FROM meta WHERE key='seen_csv_imported'").fetchone():
            return 0
        import pandas as pd
        urls = [u for u in pd.read_csv(csv_path).get("job_url", []) if isinstance(u, str)]
        self.mark_seen((u, None, None) for u in urls)
        self.db.execute("INSERT OR REPLACE INTO meta VALUES ('seen_csv_imported', ?)", (_now(),))
        self.db.commit()
        return len(urls)

    # -- health --------------------------------------------------------------
    def history(self, source: str, last: int = 10):
        q = ("SELECT r.id, r.started, s.rows, s.errors FROM source_stats s JOIN runs r ON r.id = s.run_id "
             "WHERE s.source=? AND r.status='ok' ORDER BY r.id DESC LIMIT ?")
        return list(self.db.execute(q, (source, last)))

    def health(self, sources=None, zero_runs: int = 2, lookback: int = 8):
        """Warnings for sources that look broken. A source is flagged when its last `zero_runs`
        runs returned 0 rows but its usual (median of earlier runs) is above 0, or when every
        search it ran in the last run failed."""
        names = sources or [r[0] for r in self.db.execute("SELECT DISTINCT source FROM source_stats")]
        out = []
        for s in names:
            h = self.history(s, lookback)
            if not h:
                continue
            recent, earlier = h[:zero_runs], h[zero_runs:]
            last_rows, last_err = h[0][2], h[0][3]
            if last_rows == 0 and last_err > 0:
                out.append(f"{s}: every request failed last run ({last_err} errors)")
                continue
            if len(recent) == zero_runs and all(r[2] == 0 for r in recent) and earlier:
                usual = statistics.median(r[2] for r in earlier)
                if usual > 0:
                    out.append(f"{s}: 0 jobs for {zero_runs} runs in a row (usually ~{usual:.0f}). "
                               f"The site or its API may have changed.")
        return out

    def last_runs(self, n=10):
        return list(self.db.execute("SELECT id, started, finished, status, summary FROM runs ORDER BY id DESC LIMIT ?",
                                    (n,)))
