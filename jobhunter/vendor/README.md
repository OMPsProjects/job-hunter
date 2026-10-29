# Vendored code

## slop_guard

The scoring engine of [slop-guard](https://github.com/eric-tramel/slop-guard) by Eric Tramel,
MIT License (`slop_guard/LICENSE`), copied from release 0.5.0, commit 7ef2113 (2026-07-09). The
command-line and MCP-server parts (`apps/`, `__main__.py`) were left out, so it needs no extra
packages. Changes from upstream:

- imports point at `jobhunter.vendor.slop_guard` instead of `slop_guard`;
- `version.py` is a fixed string instead of reading installed-package metadata;
- `typing.TypedDict` instead of `typing_extensions`, and a small `StrEnum` fallback, so it runs
  on Python 3.10.

job-hunter calls it from `jobhunter/humanize.py` (`shape_check`). To update: copy `src/slop_guard`
from a newer release, drop `apps/` and `__main__.py`, and repeat the changes above.
