"""File safety: atomic writes, private-file permissions, a one-run-at-a-time lock, and .env loading.

Atomic writes go to a temp file in the same folder and are swapped in with os.replace, so a
crash or Ctrl-C mid-write never leaves a half-written results file or answer bank.
"""
from __future__ import annotations

import contextlib
import os
import stat
import tempfile
import time
from pathlib import Path

# Files that hold someone's personal data. Created owner-read/write only (on macOS/Linux).
PRIVATE_NAMES = {"profile.yaml", "candidate.yaml", "answers.yaml", "applications.csv", ".env"}


def secure(path: Path) -> None:
    """chmod 600 on POSIX. On Windows, files inherit the user-profile folder's ACL (already private)."""
    if os.name == "posix":
        with contextlib.suppress(OSError):
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def write_text_atomic(path, text: str, private: bool | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        if private or (private is None and path.name in PRIVATE_NAMES):
            secure(Path(tmp))
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def write_csv_atomic(df, path, **kw) -> None:
    kw.setdefault("index", False)
    write_text_atomic(path, df.to_csv(**kw))


def write_jsonl_atomic(df, path) -> None:
    text = "" if df is None or df.empty else df.to_json(orient="records", lines=True, force_ascii=False,
                                                         date_format="iso")
    write_text_atomic(path, text)


class RunLock:
    """Stops two searches writing the same results folder at once. A lock older than
    `stale_hours` is assumed to be left over from a crash and taken over."""

    def __init__(self, folder: Path, stale_hours: float = 3):
        self.path = Path(folder) / ".run.lock"
        self.stale = stale_hours * 3600

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            age = time.time() - self.path.stat().st_mtime
            if age < self.stale:
                raise RuntimeError(
                    f"Another search is already writing to {self.path.parent} (started {age / 60:.0f} min ago). "
                    f"If it crashed, delete {self.path} and run again.") from None
            self.path.unlink(missing_ok=True)
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as fh:
            fh.write(str(os.getpid()))
        return self

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)
        return False


def load_dotenv(path: Path) -> list[str]:
    """Read KEY=value lines from a .env file into os.environ (existing variables win).
    Returns the keys it set. No dependency on python-dotenv."""
    path = Path(path)
    if not path.exists():
        return []
    set_keys = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val
            set_keys.append(key)
    return set_keys
