# Changelog

## 1.0.0 (2026-10-28)

First public release.

- `job-hunter setup`: a questionnaire (or `--from answers.yaml`) that builds your profile,
  structured resume and company list for any kind of job.
- Search across Indeed (and opt-in LinkedIn, Google, Glassdoor, ZipRecruiter), Remotive,
  Himalayas, RemoteOK, The Muse, Arbeitnow, Adzuna, USAJobs, Jooble, and employers' own career
  sites on Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee and Workday.
- `companies discover`: finds employers posting roles like yours and adds their career sites.
  `companies add NAME`, `boards add URL` for ones you find yourself.
- Verification of each posting on the employer's own site.
- Ranking on resume fit, seniority, location, pay and freshness, with your weights;
  `labels` + `eval-rank --tune` to check it against your own judgment.
- Resume render (PDF) and lint (AI-sounding phrasing, numbers not in your source resume).
- Answer bank with strict matching; never stores IDs, passwords, birth dates or EEO answers.
- Run history in SQLite, source-health warnings, atomic writes, one-run-at-a-time lock,
  redacted JSON logs, `.env` for API keys.
- Claude Code skill for setup, daily shortlists, tailoring, and filling applications in the
  browser with the person on the submit button; mock application site and grader in `evals/`.
