# Contributing

Thanks for helping. Most useful right now: new job sources, fixes for sources that broke, and
results from running the apply eval with different browsers and models.

## Set up

```bash
git clone https://github.com/OWNER/job-hunter && cd job-hunter
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install            # blocks committing personal files or data
python -m pytest              # offline tests
JOBHUNTER_LIVE=1 python -m pytest tests/live    # optional: hits the real sites
```

Use the fictional examples (`*.example.yaml`, `evals/fixtures/`) for anything you test or paste.
Never commit your own profile, resume, answers or results.

## Add a job source

1. **Prefer an official API** or a public ATS endpoint over scraping HTML. Scrapers that break a
   site's terms are opt-in only and need a clear warning in the profile comments.
2. Add a function in `jobhunter/sources/apis.py` (a board) or `jobhunter/sources/ats.py` (an
   employer career-site system). It takes the profile (board) or `(company, slug, ...)` (ATS) and
   returns a list of dicts with the keys in `common.JOB_COLUMNS`. Log failures with
   `log.warning(..., extra={"source": name})` so source health counts them; never let one bad
   response raise out of the source.
3. Register it: `apis.SOURCES` / `ats.FETCHERS`, plus `profile.DEFAULT_SOURCES` (keyed APIs use
   `"auto"` and list their env vars in `SOURCE_KEYS`). For an ATS, add its URL pattern to
   `ats.ATS_URL_PATTERNS` and, if it can be probed by company name, to `verify._probe`.
4. Record a small real response into `tests/fixtures/sources/` (trim to 3-5 postings) and add it to
   `ROUTES` in `tests/test_sources.py`. Add one live check in `tests/live/`.
5. Document it in the README's sources table.

## Update bundled or downloaded data

- **Occupations:** download the newest O*NET database ("Text" zip) from
  onetcenter.org/database.html, run `python scripts/build_occupations.py <zip>`, update the version
  in `jobhunter/data/README.md` and `occupations.ATTRIBUTION`, and run the tests.
- **Metro areas for pay estimates:** `wages.AREAS` maps setup's cities to BLS OEWS area codes
  (check them against `https://download.bls.gov/pub/time.series/oe/oe.area`).
- The careers-site directory is downloaded at run time, not committed.

## Change the ranking

Run `job-hunter labels`, label a run, and compare `job-hunter eval-rank` before and after. Put
the numbers in the pull request.

## Change the skill

Anything touching applying (`skills/job-hunter/references/applying.md`, `SKILL.md`) needs an
apply eval run (`evals/README.md`) with zero safety failures, pasted in the pull request.

## Style

`ruff check .` and `mypy` must pass. Plain, specific error messages that tell the person what to
do next. No new required dependencies without a good reason.
