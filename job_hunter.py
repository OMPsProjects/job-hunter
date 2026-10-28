#!/usr/bin/env python3
"""Run job-hunter without installing it: `python job_hunter.py <command>`.
Installed with pip, the same thing is the `job-hunter` command. See `python job_hunter.py -h`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jobhunter.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
