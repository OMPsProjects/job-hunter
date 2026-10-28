"""Logging: plain messages on screen, and one JSON line per event in results/logs/ for later
debugging. Emails, phone numbers and ID-like numbers are masked before anything is written."""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
from pathlib import Path

from .fileio import secure

log = logging.getLogger("jobhunter")

_REDACT = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<email>"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "<id>"),
    (re.compile(r"(?:\+1[\s.-]?)?\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b"), "<phone>"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "<number>"),
    (re.compile(r"(?i)(api[_-]?key|app[_-]?key|app[_-]?id|token|authorization-key)=([^&\s]+)"), r"\1=<secret>"),
    (re.compile(r"(?i)(jooble\.org/api/)[^/\s?]+"), r"\1<secret>"),
]


def redact(text: str) -> str:
    for rx, sub in _REDACT:
        text = rx.sub(sub, text)
    return text


class _JsonLines(logging.Handler):
    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, record):
        try:
            entry = {"t": dt.datetime.now().isoformat(timespec="seconds"), "level": record.levelname,
                     "msg": redact(record.getMessage())}
            for k in ("source", "rows", "errors", "seconds"):
                if hasattr(record, k):
                    entry[k] = getattr(record, k)
            new = not self.path.exists()
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
            if new:
                secure(self.path)
        except Exception:  # logging must never take a run down
            pass


class _Console(logging.Handler):
    def emit(self, record):
        msg = record.getMessage()
        if record.levelno >= logging.WARNING:
            msg = f"  ! {msg}"
        print(msg, flush=True)


def setup(out_dir: Path | None = None, verbose: bool = False) -> Path | None:
    log.handlers.clear()
    log.setLevel(logging.DEBUG)
    console = _Console()
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    log.addHandler(console)
    log.propagate = False
    path = None
    if out_dir is not None:
        path = Path(out_dir) / "logs" / f"run-{dt.date.today().isoformat()}.jsonl"
        fh = _JsonLines(path)
        fh.setLevel(logging.DEBUG)
        log.addHandler(fh)
    # quiet the libraries; their warnings still reach the file at WARNING
    for name in ("jobspy", "urllib3", "httpx"):
        logging.getLogger(name).setLevel(logging.ERROR)
    return path
