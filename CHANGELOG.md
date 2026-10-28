# Changelog

## 1.1.0 (2026-10-28)

- **Careers-site directory.** Finding a company's careers site now checks a public directory of
  ~24,000 companies on Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee and Workday
  (from the MIT-licensed ats-scrapers project) before guessing board names. Downloaded to a cache
  folder and refreshed monthly; `job-hunter data update | status`.
- **Pay estimates.** Jobs that don't post pay get the BLS median for their occupation and metro,
  counted at half strength in the pay score and never used to exclude a job. Cached for months;
  `BLS_API_KEY` in `.env` is optional. New `pay_estimate` column.
- **Occupation data in setup.** Titles are mapped to standard occupations (bundled subset of the
  O*NET 31.0 Database, CC BY 4.0) to suggest related titles and skills, and to pick the
  occupation for pay estimates. `job-hunter occupations match | suggest | search`.
- **Re-listed jobs flagged.** A new posting for a title the same company listed under another link
  2+ weeks earlier is flagged in `gaps` (and `repost_note`). Flag only by default.
- **Visa sponsorship.** `filters.needs_sponsorship: true` excludes postings that say they won't
  sponsor or need U.S. citizenship or a clearance, and notes ones that say they do.
  `job-hunter data import-sponsors FILE` adds employers' H-1B history from USCIS's data hub CSV.
- **Optional title model.** `pip install -e ".[ml]"` adds TechWolf's JobBERT-v3 (MIT) so title
  closeness counts meaning, not just shared words. `ranking.title_model: off` to disable.
- **Application stats.** The tracker records each status change and where the job came from;
  `job-hunter stats` shows response and interview rates by source, careers system, track and
  tailored vs. not.
- **Cover letters.** `render` and `lint` accept a cover letter YAML (one page; stock openers and
  invented numbers flagged); the skill has a cover-letter guide.
- **Reviewer pass.** The skill has a separate agent review every tailored resume and cover letter
  against the posting with a fixed rubric (truth, fit, specifics, human tone) before you see it.
- **PDF read-back.** `render` extracts the PDF's text the way an applicant tracking system would
  and flags anything missing or out of order (exit code 3).
- **Posting checks.** Hidden text, invisible "smuggled" characters and lines aimed at AI tools are
  flagged (`integrity_note`, `job-hunter scan FILE`); hidden HTML text is kept and labeled instead
  of silently dropped.
- **Interview prep and story bank.** `candidate/stories.md`, `job-hunter stories list | check`,
  and a prep-pack and mock-interview guide in the skill.
- **Deadlines and follow-ups.** "Apply by" dates are parsed and jobs closing soon flagged
  (`apply_by`); `stats --json` lists applications with no answer for the skill to draft
  follow-ups (never sent).

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
