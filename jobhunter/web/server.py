"""`job-hunter ui`: a web page for job-hunter, served on your own computer only.

Standard library only (http.server). It listens on 127.0.0.1, so nothing else on your network
can reach it, and every request to /api must carry a token that's generated when the server
starts and embedded in the page, so other websites open in your browser can't call it either.
Requests whose Host header isn't localhost are refused (protection against DNS rebinding).

The page reads and writes the same files the command line does (results/, applications.csv,
companies.yaml, profile.yaml ...). Long jobs (search, re-rank, finding companies) run as the
normal `job-hunter` command in a background process, and their output streams to the page.
"""
from __future__ import annotations

import collections
import contextlib
import json
import math
import mimetypes
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import types
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pandas as pd

from .. import __version__, tracker
from ..fileio import write_csv_atomic, write_text_atomic
from ..logs import log
from ..profile import load_profile

STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 10 * 1024 * 1024  # resume uploads included
RESUME_TYPES = {".pdf", ".docx", ".txt", ".md"}
TASKS = {
    "search": ["search"],
    "search-no-verify": ["search", "--no-verify"],
    "rank": ["rank"],
    "discover": ["companies", "discover"],
    "discover-add": ["companies", "discover", "--add"],
    "data-update": ["data", "update"],
}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _clean(v):
    """JSON-safe values: NaN/NaT -> None, numpy numbers -> Python numbers."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "item"):
        with contextlib.suppress(ValueError, AttributeError):
            v = v.item()
    if isinstance(v, float) and not math.isfinite(v):
        return None  # Infinity isn't valid JSON
    return v


def _records(df, columns=None):
    if df is None or not len(df):
        return []
    if columns:
        df = df[[c for c in columns if c in df.columns]]
    return [{k: _clean(v) for k, v in row.items()} for row in df.to_dict(orient="records")]


class Task:
    """One background `job-hunter` command at a time, with its output kept for the page."""

    def __init__(self):
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.name = ""
        self.started = None
        self.finished = None
        self.returncode: int | None = None
        self.lines: collections.deque = collections.deque(maxlen=4000)
        self.offset = 0  # number of lines dropped from the front, so 'since' stays meaningful

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, name, argv, cwd):
        with self.lock:
            if self.running():
                raise ApiError(409, f"'{self.name}' is still running. Stop it or wait for it to finish.")
            self.lines.clear()
            self.offset = 0
            self.name, self.started, self.finished, self.returncode = name, time.time(), None, None
            env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
            # its own process group, so Stop also ends anything it started (browsers for scraping, ...)
            group = {"start_new_session": True} if os.name == "posix" else \
                {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
            self.proc = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, encoding="utf-8", errors="replace", env=env, **group)
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        proc = self.proc
        assert proc is not None and proc.stdout is not None
        for line in proc.stdout:
            with self.lock:
                if len(self.lines) == self.lines.maxlen:
                    self.offset += 1
                self.lines.append(line.rstrip("\n"))
        proc.wait()
        with self.lock:
            self.returncode = proc.returncode
            self.finished = time.time()

    def stop(self):
        with self.lock:
            if self.running() and self.proc is not None:
                if os.name == "posix":
                    import signal
                    try:
                        os.killpg(self.proc.pid, signal.SIGTERM)
                    except OSError:
                        self.proc.terminate()
                else:
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)], capture_output=True)
                return True
        return False

    def state(self, since=0):
        with self.lock:
            start = max(0, since - self.offset)
            return {"name": self.name, "running": self.running(), "returncode": self.returncode,
                    "started": self.started, "finished": self.finished,
                    "next": self.offset + len(self.lines), "lines": list(self.lines)[start:]}


class App:
    def __init__(self, profile_path: Path, port: int):
        self.profile_path = Path(profile_path).resolve()
        self.base = self.profile_path.parent
        self.port = port
        self.token = secrets.token_urlsafe(24)
        self.task = Task()
        self.write_lock = threading.Lock()  # one writer at a time for tracker / labels / settings
        self.cache: dict = {}
        self.cache_lock = threading.Lock()
        self.last_seen = time.monotonic()  # last request from the page (it checks in every 15 s)
        self.server: ThreadingHTTPServer | None = None

    def quit(self, q, body):
        """The page's Quit button: stop any running search and shut down."""
        if self.server is not None:
            threading.Timer(0.3, self.server.shutdown).start()
        return {"ok": True}

    # -- helpers -------------------------------------------------------------
    def profile(self, required=False):
        try:
            return load_profile(self.profile_path, required=required)
        except SystemExit as e:  # load_profile exits with a message on a broken file
            raise ApiError(400, str(e)) from None

    def out_dir(self, p=None):
        p = p or self.profile()
        d = p.resolve(p.output_dir or "results")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def cli(self, *args):
        return [sys.executable, "-m", "jobhunter.cli", *args, "--profile", str(self.profile_path)]

    # -- status ----------------------------------------------------------------
    def status(self, q, body):
        from ..candidate import load_candidate
        has_profile = self.profile_path.exists()
        out: dict = {"version": __version__, "folder": str(self.base), "has_profile": has_profile,
                     "task": self.task.state(since=10**9)}
        if not has_profile:
            return out
        p = self.profile()
        cand = load_candidate(p.resolve(p.candidate_file))
        res = self.out_dir(p)
        summary = {}
        if (res / "run_summary.json").exists():
            try:
                summary = json.loads((res / "run_summary.json").read_text(encoding="utf-8"))
            except ValueError:
                summary = {}
        out.update({
            "tracks": p.tracks, "locations": p.locations, "include_remote": p.include_remote,
            "sources_on": [k for k in p.sources if p.source_on(k)], "problems": p.problems(),
            "candidate": {"found": bool(cand), "skills": len(cand.skills) if cand else 0,
                          "name": (cand.raw.get("name") if cand else "") or ""},
            "last_run": summary,
            "companies": len(p.target_companies), "boards": len(p.browse_boards),
        })
        return out

    # -- jobs --------------------------------------------------------------------
    def _read_results(self, which):
        """The last search's results as a DataFrame (cached until the file changes)."""
        name = {"ranked": "jobs_new_details.jsonl", "excluded": "excluded.csv", "all": "jobs_all.csv"}[which]
        path = self.out_dir() / name
        try:
            stat = path.stat()
        except OSError:
            return pd.DataFrame()
        if not stat.st_size:
            return pd.DataFrame()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        with self.cache_lock:
            hit = self.cache.get(which)
            if hit and hit[0] == key:
                return hit[1]
        try:
            df = pd.read_json(path, lines=True, dtype=False) if which == "ranked" else pd.read_csv(path)
        except (ValueError, pd.errors.ParserError, pd.errors.EmptyDataError):
            raise ApiError(500, f"{path.name} in your results folder looks damaged. Run a search (or Re-rank) "
                                f"to rebuild it.") from None
        with self.cache_lock:
            self.cache[which] = (key, df)
        return df

    def _marks(self):
        """job_url -> tracker status and label, so the page can show what you've done with a job."""
        p = self.profile()
        marks: dict = {}
        tr = tracker.load(p.resolve(p.tracker_file))
        for _, r in tr.iterrows():
            for u in (r.get("job_url"), r.get("employer_url")):
                if u:
                    marks.setdefault(u, {})["status"] = r["status"]
        lab = self.out_dir(p) / "labels.csv"
        if lab.exists():
            from ..evalrank import clean_labels
            try:
                df = pd.read_csv(lab, dtype={"label": str})
            except (ValueError, pd.errors.ParserError, pd.errors.EmptyDataError):
                df = pd.DataFrame()
            if len(df) and {"job_url", "label"} <= set(df.columns):
                for u, v in zip(df["job_url"], clean_labels(df["label"]), strict=True):
                    if v:
                        marks.setdefault(u, {})["label"] = v
        return marks

    def jobs(self, q, body):
        which = (q.get("set") or ["ranked"])[0]
        if which not in ("ranked", "excluded", "all"):
            raise ApiError(400, "set must be ranked, excluded or all")
        df = self._read_results(which)
        cols = ["rank", "rank_score", "fit", "seniority", "location_score", "pay_score", "freshness", "verified",
                "title", "company", "location", "pay_top", "min_amount", "max_amount", "interval", "pay_estimate",
                "date_posted", "apply_by", "why", "gaps", "track", "site", "employer_url", "job_url",
                "excluded_reason", "integrity_note", "repost_note", "visa_note", "verify_note"]
        rows = _records(df, cols)
        marks = self._marks()
        for r in rows:
            m = marks.get(r.get("job_url")) or marks.get(r.get("employer_url")) or {}
            r["status"], r["label"] = m.get("status"), m.get("label")
        p = self.profile()
        return {"set": which, "jobs": rows, "weights": p.weights}

    def job(self, q, body):
        url = (q.get("url") or [""])[0]
        for which in ("ranked", "all", "excluded"):
            df = self._read_results(which)
            if len(df) and "job_url" in df:
                hit = df[df["job_url"] == url]
                if len(hit):
                    return _records(hit)[0]
        raise ApiError(404, "That job isn't in the latest results.")

    # -- tasks -----------------------------------------------------------------------
    def task_start(self, q, body):
        name = body.get("name")
        if name not in TASKS:
            raise ApiError(400, f"unknown task {name!r}")
        if not self.profile_path.exists():
            raise ApiError(400, "Set up your profile first.")
        args = list(TASKS[name])
        sources = [s for s in body.get("sources") or [] if re.fullmatch(r"[a-z_]+", str(s))]
        if sources and args[0] == "search":
            args += ["--sources", ",".join(sources)]
        self.task.start(name, self.cli(*args), cwd=str(self.base))
        return self.task.state()

    def task_state(self, q, body):
        since = int((q.get("since") or ["0"])[0] or 0)
        return self.task.state(since)

    def task_stop(self, q, body):
        return {"stopped": self.task.stop()}

    # -- applications ------------------------------------------------------------------
    def applications(self, q, body):
        p = self.profile()
        df = tracker.load(p.resolve(p.tracker_file))
        res = tracker.stats(df)
        return {"applications": _records(df), "statuses": tracker.STATUSES, "waiting": res["waiting_items"]}

    def track(self, q, body):
        from ..cli import _job_context
        p = self.profile(required=True)
        status, company, title = body.get("status"), str(body.get("company") or ""), str(body.get("title") or "")
        if status not in tracker.STATUSES or not company or not title:
            raise ApiError(400, f"Need a company, a title and a status ({', '.join(tracker.STATUSES)}).")
        args = types.SimpleNamespace(url=body.get("job_url") or None, employer_url=body.get("employer_url") or None,
                                     source=None, job_track=None, out=None)
        extra = _job_context(p, args)
        fields = {k: body.get(k) for k in ("location", "notes", "resume_pdf") if body.get(k)}
        if body.get("rank_score") is not None:
            fields["rank_score"] = body["rank_score"]
        with self.write_lock:
            row = tracker.upsert(p.resolve(p.tracker_file), status, company, title, job_url=args.url,
                                 employer_url=args.employer_url, **fields, **extra)
        return {k: _clean(v) for k, v in row.items()}

    def untrack(self, q, body):
        """Take a job off the shortlist: removes its row only while it's just 'shortlisted'."""
        p = self.profile(required=True)
        with self.write_lock:
            removed = tracker.remove_shortlisted(p.resolve(p.tracker_file), body.get("job_url"), body.get("employer_url"),
                                                 body.get("company"), body.get("title"))
        return {"removed": removed}

    def stats(self, q, body):
        p = self.profile()
        res = tracker.stats(tracker.load(p.resolve(p.tracker_file)))
        out_dir = self.out_dir(p)
        lab = out_dir / "labels.csv"
        if lab.exists():
            from ..evalrank import evaluate
            ranked_p = out_dir / "ranked.csv"
            ranked = pd.read_csv(ranked_p) if ranked_p.exists() and ranked_p.stat().st_size else None
            try:
                res["ranking_check"] = evaluate(ranked, pd.read_csv(lab, dtype={"label": str}), p.weights,
                                                low_fit_threshold=p.low_fit_threshold)
            except Exception as e:
                res["ranking_check_error"] = str(e)
        return res

    # -- labels -------------------------------------------------------------------------
    def label(self, q, body):
        from ..evalrank import SHEET_COLS
        url, value = body.get("job_url"), str(body.get("label") if body.get("label") is not None else "")
        if not url or value not in ("0", "1", "2", ""):
            raise ApiError(400, "label must be 2 (would apply), 1 (maybe), 0 (no), or empty")
        out_dir = self.out_dir()
        path = out_dir / "labels.csv"
        with self.write_lock:
            sheet = pd.read_csv(path, dtype={"label": str}) if path.exists() else pd.DataFrame(columns=["label"] + SHEET_COLS)
            if url in set(sheet.get("job_url", [])):
                sheet.loc[sheet["job_url"] == url, "label"] = value
            else:
                src = self._read_results("ranked")
                hit = src[src["job_url"] == url] if len(src) and "job_url" in src else src
                if not len(hit):
                    raise ApiError(404, "That job isn't in the latest ranked results.")
                row = {c: _clean(hit.iloc[0].get(c)) for c in SHEET_COLS}
                row["label"] = value
                sheet = pd.concat([sheet, pd.DataFrame([row])], ignore_index=True)
            write_csv_atomic(sheet, path)
        return {"job_url": url, "label": value}

    # -- companies and boards ------------------------------------------------------------
    def companies(self, q, body):
        from ..targets import Targets
        p = self.profile()
        t = Targets(p.resolve(p.companies_file))
        from .. import packs
        field = (p.raw.get("setup") or {}).get("field") or ""
        suggested = packs.matching(field, [t for ts in p.tracks.values() for t in ts])
        return {"companies": t.companies, "boards": t.browse_boards, "tracks": list(p.tracks),
                "packs": [{**packs.summary(pid), "suggested": pid in suggested} for pid in packs.all_packs()]}

    def companies_change(self, q, body):
        from ..targets import Targets, add_by_name, add_from_url
        p = self.profile(required=True)
        t = Targets(p.resolve(p.companies_file))
        action = body.get("action")
        name, url, track = str(body.get("name") or "").strip(), str(body.get("url") or "").strip(), body.get("track") or None
        with self.write_lock:
            if action == "remove":
                ok = t.remove(name or url)
                return {"ok": ok, "message": "Removed." if ok else f"{name or url} isn't on the list."}
            if action == "add-company":
                if not name and not url:
                    raise ApiError(400, "Enter a company name or its careers page URL.")
                ok, msg = add_from_url(t, url, name=name or None, track=track) if url else add_by_name(t, name, track)
                return {"ok": ok, "message": msg}
            if action == "add-board":
                if not url:
                    raise ApiError(400, "Enter the board's URL.")
                ok, msg = add_from_url(t, url, name=name or None, track=track)
                return {"ok": ok, "message": msg}
            if action == "add-pack":
                from .. import packs
                pid = str(body.get("pack") or "")
                if pid not in packs.all_packs():
                    raise ApiError(400, "No list by that name.")
                direct, browse = packs.apply(t, pid, skip=p.exclude_companies)
                return {"ok": True, "message": f"Added {direct} career sites to the daily search and {browse} to the "
                                              f"check-by-hand list."}
        raise ApiError(400, "action must be add-company, add-board, add-pack or remove")

    # -- setup ------------------------------------------------------------------------------
    def setup_info(self, q, body):
        from ..setup import FIELDS, QUESTIONS, current_answers, us_cities
        current = current_answers(self.base)
        resume = self._resume_info(current.get("resume"))
        from .. import packs
        return {"has_profile": self.profile_path.exists(), "current": current, "resume": resume,
                "cities": us_cities(), "fields": FIELDS,
                "packs": [{**packs.summary(pid), "keywords": packs.all_packs()[pid].get("keywords") or []}
                          for pid in packs.all_packs()],
                "questions": [{"key": k, "prompt": pr, "kind": kind, "default": d} for k, pr, kind, d in QUESTIONS]}

    def _resume_info(self, rel):
        """What setup read from the saved resume (titles, employers, city, skills), or None."""
        if not rel:
            return None
        path = (self.base / rel).resolve()
        if self.base.resolve() not in path.parents or not path.is_file():
            return None
        from ..resume_parse import parse_resume_file
        from ..setup import search_titles
        try:
            parsed = parse_resume_file(path)
        except Exception as e:  # an unreadable file shouldn't block setup
            log.warning(f"ui: couldn't read {path.name}: {e}")
            return {"path": rel, "file": path.name, "error": "Couldn't read this file; you can still fill in the rest."}
        return {"path": rel, "file": path.name, **parsed, "search_titles": search_titles(parsed["titles"])}

    def setup_titles(self, q, body):
        """Job titles for the dropdowns as you type: occupation names and the titles under them."""
        from .. import occupations
        text = (q.get("q") or [""])[0][:80]
        out: list[str] = []
        for o in occupations.search(text, limit=8):
            for t in [*o["examples"], o["title"]]:
                if t not in out:
                    out.append(t)
        return {"titles": out[:25]}

    def setup_suggest(self, q, body):
        from .. import occupations
        titles = [str(t) for t in body.get("titles") or [] if str(t).strip()][:20]
        return occupations.suggestions(titles)

    def setup_resume(self, q, body, raw=b"", filename=""):
        ext = Path(filename).suffix.lower()
        if ext not in RESUME_TYPES:
            raise ApiError(400, f"Upload a PDF, DOCX, TXT or MD file (got {ext or 'no extension'}).")
        if not raw:
            raise ApiError(400, "The file was empty.")
        from ..fileio import write_bytes_atomic
        for old in (self.base / "candidate").glob("base_resume.*"):  # one resume: a new one replaces the old
            if old.suffix.lower() in RESUME_TYPES and old.suffix.lower() != ext:
                old.unlink(missing_ok=True)
        dest = self.base / "candidate" / f"base_resume{ext}"
        write_bytes_atomic(dest, raw)
        rel = f"candidate/{dest.name}"
        info = self._resume_info(rel) or {"path": rel}
        info["original_name"] = Path(filename).name[:120]
        return info

    def setup_run(self, q, body):
        from ..setup import run_setup
        answers = body.get("answers") or {}
        if not isinstance(answers, dict) or not answers.get("titles"):
            raise ApiError(400, "Add at least one job title; that's what gets searched.")
        force = bool(body.get("force"))
        messages: list[str] = []
        with self.write_lock:
            try:
                res = run_setup(self.base, answers, ask=None, say=messages.append, force=force)
            except SystemExit as e:
                raise ApiError(409 if "already exists" in str(e) else 400, str(e)) from None
        p = load_profile(res["profile"])
        return {"messages": messages, "problems": p.problems(),
                "companies_added": [{"name": n, "ok": ok} for n, ok in res["companies_added"]]}

    # -- settings ---------------------------------------------------------------------------
    WEIGHT_KEYS = ("fit", "seniority", "location", "pay", "freshness")
    SETTINGS = {
        ("ranking", "weights"): "weights", ("ranking", "pay_floor"): "money", ("ranking", "pay_target"): "money",
        ("ranking", "pay_floor_is_hard"): bool, ("ranking", "pay_estimates"): bool,
        ("filters", "exclude_companies"): list, ("filters", "exclude_keywords"): list,
        ("filters", "needs_sponsorship"): bool, ("search", "include_remote"): bool,
        ("verify", "enabled"): bool, ("verify", "top_n"): int,
    }

    def settings(self, q, body):
        import yaml
        if not self.profile_path.exists():
            raise ApiError(400, "Set up your profile first.")
        data = yaml.safe_load(self.profile_path.read_text(encoding="utf-8")) or {}
        p = self.profile()
        out = {f"{a}.{b}": _clean((data.get(a) or {}).get(b)) for a, b in self.SETTINGS}
        out["ranking.weights"] = {k: _clean(p.weights.get(k)) for k in self.WEIGHT_KEYS}
        out["sources"] = dict(p.sources)
        return out

    def _setting_value(self, key, kind, v):
        """Strictly typed values only: a wrong type is an error, never a guess."""
        def finite(x, lo, hi, what):
            if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not lo <= x <= hi:
                raise ApiError(400, f"{what} should be a number from {lo:,} to {hi:,}.")
            return x
        if kind == "money":
            if v in (None, ""):
                return None
            if isinstance(v, str):
                try:
                    v = float(v)
                except ValueError:
                    raise ApiError(400, f"{key} should be a yearly amount like 85000.") from None
            return finite(v, 0, 10_000_000, key)
        if kind is bool:
            if not isinstance(v, bool):
                raise ApiError(400, f"{key} should be true or false.")
            return v
        if kind is int:
            return int(finite(v, 1, 5000, key))
        if kind is list:
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                raise ApiError(400, f"{key} should be a list of text.")
            return [x.strip() for x in v if x.strip()][:500]
        if kind == "weights":
            if not isinstance(v, dict) or set(v) - set(self.WEIGHT_KEYS):
                raise ApiError(400, f"weights should only have {', '.join(self.WEIGHT_KEYS)}.")
            out = {k: finite(x, 0, 100, f"the {k} weight") for k, x in v.items()}
            if not any(out.values()):
                raise ApiError(400, "At least one weight has to be above 0.")
            return out
        raise ApiError(400, f"can't set {key}")

    def settings_save(self, q, body):
        from ruamel.yaml import YAML

        from ..profile import DEFAULT_SOURCES
        from ..validate import validate_profile
        if not self.profile_path.exists():
            raise ApiError(400, "Set up your profile first.")
        unknown = set(body) - {f"{a}.{b}" for a, b in self.SETTINGS} - {"sources"}
        if unknown:
            raise ApiError(400, f"not a setting this page can change: {', '.join(sorted(unknown))}")
        changes = {k: self._setting_value(k, kind, body[f"{a}.{b}"]) for (a, b), kind in self.SETTINGS.items()
                   if (k := f"{a}.{b}") in body}
        sources = body.get("sources")
        if sources is not None:
            if not isinstance(sources, dict) or set(sources) - set(DEFAULT_SOURCES) or \
                    any(v not in (True, False, "auto") for v in sources.values()):
                raise ApiError(400, f"sources: use on/off/auto for {', '.join(DEFAULT_SOURCES)}.")
        # Round-trip YAML keeps your comments and layout; only the changed values are rewritten.
        rt = YAML()
        rt.preserve_quotes = True
        rt.width = 1000
        with self.write_lock:
            original = self.profile_path.read_text(encoding="utf-8")
            data = rt.load(original) or {}
            for key, v in changes.items():
                a, b = key.split(".")
                if data.get(a) is None:
                    data[a] = {}
                if v is None:
                    data[a].pop(b, None)
                elif isinstance(v, dict) and isinstance(data[a].get(b), dict):
                    data[a][b].update(v)
                else:
                    data[a][b] = v
            if sources:
                if data.get("sources") is None:
                    data["sources"] = {}
                data["sources"].update(sources)
            import io
            buf = io.StringIO()
            rt.dump(data, buf)
            import yaml
            errors, _ = validate_profile(yaml.safe_load(buf.getvalue()) or {})
            if errors:
                raise ApiError(400, "; ".join(errors))
            backup = self.profile_path.with_suffix(".yaml.bak")
            write_text_atomic(backup, original, private=True)
            write_text_atomic(self.profile_path, buf.getvalue(), private=True)
        return {"saved": True, "backup": backup.name}

    # -- routing ----------------------------------------------------------------------------
    def routes(self):
        return {
            ("GET", "/api/status"): self.status, ("GET", "/api/jobs"): self.jobs, ("GET", "/api/job"): self.job,
            ("POST", "/api/task"): self.task_start, ("GET", "/api/task"): self.task_state,
            ("POST", "/api/task/stop"): self.task_stop,
            ("GET", "/api/applications"): self.applications, ("POST", "/api/track"): self.track,
            ("POST", "/api/untrack"): self.untrack,
            ("GET", "/api/stats"): self.stats, ("POST", "/api/label"): self.label,
            ("GET", "/api/companies"): self.companies, ("POST", "/api/companies"): self.companies_change,
            ("GET", "/api/setup"): self.setup_info, ("POST", "/api/setup/suggest"): self.setup_suggest,
            ("POST", "/api/setup"): self.setup_run,
            ("GET", "/api/setup/titles"): self.setup_titles,
            ("GET", "/api/settings"): self.settings, ("POST", "/api/settings"): self.settings_save,
            ("POST", "/api/quit"): self.quit,
        }


class _Server(ThreadingHTTPServer):
    """On Windows, Python's default (SO_REUSEADDR) lets a second program bind the same port and
    share its traffic. Ask for the port exclusively there, so a squatter is detected, not joined."""
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_handler(app: App):
    routes = app.routes()
    static_files = {p.relative_to(STATIC).as_posix(): p for p in STATIC.rglob("*") if p.is_file()}

    class Handler(BaseHTTPRequestHandler):
        server_version = "job-hunter"
        sys_version = ""

        def log_message(self, fmt, *args):  # quiet; the terminal shows the URL and errors only
            pass

        def _host_ok(self):
            host = (self.headers.get("Host") or "").lower()
            return host in {f"127.0.0.1:{app.port}", f"localhost:{app.port}", "127.0.0.1", "localhost"}

        def _send(self, status, payload, content_type="application/json; charset=utf-8", extra_headers=None):
            data = payload if isinstance(payload, bytes) else json.dumps(payload, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            for k, v in (extra_headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def _static(self, path):
            rel = path.lstrip("/") or "index.html"
            f = static_files.get(rel)
            if f is None:
                return self._send(404, {"error": "not found"})
            data = f.read_bytes()  # no secrets in any static file: the key arrives in the link (see launcher)
            ctype = mimetypes.guess_type(rel)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            csp = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; font-src 'self'; "
                   "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            return self._send(200, data, ctype, {"Content-Security-Policy": csp, "Cross-Origin-Opener-Policy": "same-origin",
                                                 "Cross-Origin-Resource-Policy": "same-origin"})

        def _dispatch(self, method):
            if not self._host_ok():
                return self._send(403, {"error": "This page only answers on localhost."})
            parsed = urllib.parse.urlparse(self.path)
            if not parsed.path.startswith("/api/"):
                if method != "GET":
                    return self._send(405, {"error": "method not allowed"})
                return self._static(parsed.path)
            if not secrets.compare_digest(self.headers.get("X-JH-Token") or "", app.token):
                return self._send(403, {"error": "This page has an old key. Open job-hunter again from its Start file or shortcut."})
            app.last_seen = time.monotonic()
            q = urllib.parse.parse_qs(parsed.query)
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0:
                return self._send(400, {"error": "bad Content-Length"})
            if length > MAX_BODY:
                return self._send(413, {"error": "That upload is too large (10 MB max)."})
            raw = self.rfile.read(length) if length else b""
            try:
                if method == "POST" and parsed.path == "/api/setup/resume":
                    filename = urllib.parse.unquote(self.headers.get("X-Filename") or "")
                    return self._send(200, app.setup_resume(q, {}, raw=raw, filename=filename))
                fn = routes.get((method, parsed.path))
                if fn is None:
                    return self._send(404, {"error": "no such endpoint"})
                body = {}
                if raw:
                    if "application/json" not in (self.headers.get("Content-Type") or ""):
                        return self._send(415, {"error": "send JSON"})
                    body = json.loads(raw.decode("utf-8"))
                    if not isinstance(body, dict):
                        raise ApiError(400, "send a JSON object")
                return self._send(200, fn(q, body))
            except ApiError as e:
                return self._send(e.status, {"error": str(e)})
            except (ValueError, KeyError, TypeError) as e:
                return self._send(400, {"error": f"{type(e).__name__}: {e}"})
            except Exception as e:  # keep serving; show the error on the page
                log.warning(f"ui: {parsed.path} failed: {e}")
                return self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{type(e).__name__}: {e}"})

        def do_GET(self):  # noqa: N802
            self._dispatch("GET")

        def do_HEAD(self):  # noqa: N802
            self._dispatch("GET")

        def do_POST(self):  # noqa: N802
            self._dispatch("POST")

    return Handler


LAUNCHER = "open-job-hunter.html"


def _launcher_html(url):
    u = json.dumps(url)
    return ("<!doctype html><meta charset='utf-8'><title>Opening job-hunter</title>"
            f"<meta http-equiv='refresh' content='0;url={url}'>"
            f"<script>location.replace({u})</script>"
            "<p>Opening job-hunter... If nothing happens, job-hunter has stopped: double-click Start job-hunter.</p>\n")


def write_launcher(app):
    """The page's key goes in a file only this account can read, which redirects the browser to
    the page with the key after the # (never sent over the network, never in the page). Other
    accounts on the computer can reach the port but can't get the key."""
    path = app.base / LAUNCHER
    write_text_atomic(path, _launcher_html(f"http://127.0.0.1:{app.port}/#k={app.token}"), private=True)
    return path


def _read_launcher(base):
    try:
        text = (Path(base) / LAUNCHER).read_text(encoding="utf-8")
    except OSError:
        return None, None
    m = re.search(r"http://127\.0\.0\.1:(\d+)/#k=([A-Za-z0-9_-]+)", text)
    return (int(m.group(1)), m.group(2)) if m else (None, None)


def _already_running(port, base):
    """True only if the program on `port` is this account's own job-hunter: it has to answer to
    the key in this account's private launcher file. Anything else on the port is a stranger."""
    lport, key = _read_launcher(base)
    if lport != port or not key:
        return False
    try:
        import urllib.request
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/status", headers={"X-JH-Token": key})
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _open(path):
    import webbrowser
    webbrowser.open(Path(path).resolve().as_uri())


IDLE_MINUTES = 10
IDLE_CHECK_SECONDS = 15


def _watch_idle(server, app, minutes):
    """Shut down once no job-hunter page has checked in for `minutes` and nothing is running, so
    a copy started in the background doesn't linger after you close the tab."""
    while True:
        time.sleep(IDLE_CHECK_SECONDS)
        if app.task.running():
            app.last_seen = time.monotonic()
        elif time.monotonic() - app.last_seen > minutes * 60:
            print(f"No job-hunter page open for {minutes} minutes: stopping.", flush=True)
            server.shutdown()
            return


def serve(profile_path: Path, port: int = 8765, open_browser: bool = True, ready=None, quit_when_idle=False):
    """Run until Ctrl+C, the page's Quit button, or (quit_when_idle) no open page for a while.
    `ready(server, app)` is called once listening (tests use it)."""
    app = App(profile_path, port)
    try:
        server = _Server(("127.0.0.1", port), make_handler(app))
    except OSError as e:
        if _already_running(port, app.base):  # double-clicked Start twice: just show the one that's open
            print(f"job-hunter is already running at http://127.0.0.1:{port}/ ; opening it.", flush=True)
            if open_browser:
                _open(app.base / LAUNCHER)
            return 0
        try:  # another program has the port: use a free one instead
            server = _Server(("127.0.0.1", 0), make_handler(app))
        except OSError:
            print(f"Can't open port {port} ({e.strerror}). Start job-hunter with --port {port + 1}.", file=sys.stderr)
            return 1
        print(f"Port {port} is taken by another program, so job-hunter is using port "
              f"{server.server_address[1]} instead.", flush=True)
    app.port = server.server_address[1]
    app.server = server
    server.daemon_threads = True
    if quit_when_idle:
        threading.Thread(target=_watch_idle, args=(server, app, IDLE_MINUTES), daemon=True).start()
    launcher = write_launcher(app)
    print(f"job-hunter is open at http://127.0.0.1:{app.port}/  (Ctrl+C to stop)\n"
          f"Using the files in {app.base}\n"
          f"If your browser didn't open it, open this file: {launcher}", flush=True)
    if open_browser:
        threading.Timer(0.5, lambda: _open(launcher)).start()
    if ready:
        ready(server, app)

    def _stop(*_):
        raise KeyboardInterrupt
    with contextlib.suppress(ValueError):  # only possible on the main thread
        signal.signal(signal.SIGTERM, _stop)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        app.task.stop()
        server.server_close()
        if _read_launcher(app.base)[1] == app.token:
            (app.base / LAUNCHER).unlink(missing_ok=True)
    return 0

