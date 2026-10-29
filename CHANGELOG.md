# Changelog

## 1.4.0 (2026-10-29): setup starts from your resume

- **Setup reads your resume:** job titles, employers, city, skills, level and years. Four short
  pages instead of 17 questions, each prefilled for you to check.
- **Resume titles become job-board searches:** "Vice President, Senior Commercial Loan
  Underwriter" is searched as "Commercial Loan Underwriter".
- **Lists instead of typing:** titles, cities and companies are added one at a time with a
  type-ahead list (1,000 US cities; job titles from O*NET); "Use my city" from your resume;
  levels pick several; "Skip my current employer" and "Skip all my past employers".
- **Remote only** is now a choice.
- **Skills from your resume** are shown as already included; you add the rest.
- Going back in setup no longer looks like the resume was lost.
- **Ready-made lists of employers and recruiters.** The first one, commercial real estate
  finance, has 60 employers (lenders, debt funds, real estate private equity, banks, brokers) and
  17 recruiters and job boards. The 41 whose career sites job-hunter can read (Workday,
  Greenhouse, Oracle) are searched every run; the rest go on the check-by-hand list. Setup offers
  it when your field or titles match; existing searches can add it on the Companies page or with
  `job-hunter companies pack cre-finance`. Companies you skip are left out.
- **LinkedIn in setup:** an "Also search LinkedIn" choice, with the warning that LinkedIn's terms
  forbid automated searching and it may limit your account.
- New searches cover two weeks of postings instead of one.
- Related-title and skill suggestions only come from a confident match, so a commercial real
  estate underwriter isn't offered insurance-agent titles.

## 1.3.0 (2026-10-29): Dreamwork listings (opt-in)

- **New source: Dreamwork** (dreamworkhq.com), about 2 million postings gathered from employers'
  career sites. Off by default; turn it on with `dreamwork: true` under `sources:`. It uses
  Dreamwork's public guest API: no account, no key, no resume uploaded, no telemetry. Only your
  search titles and cities are sent. Each role links to the employer's own posting when Dreamwork
  has it, so verification checks the real page. Titles far from yours are dropped, estimated pay
  is ignored, and a city Dreamwork can't place is skipped rather than searched worldwide.
- **Duplicates are caught across spellings and links.** One job is now: the same link; the same
  employer posting id (Greenhouse job id, Workday req number, Lever/Ashby id, and so on), however
  the company is spelled; or the same company and title, with company names compared ignoring
  spaces, "Inc"/"LLC" and a leading "at" ("CVS Health" = "Cvshealth", "At CBIZ" = "CBIZ"). The
  copy kept is the one from the employer's site, then your top region, then one with a
  description, then one with pay. Before, the copy from the employer's site could lose to an
  aggregator's copy of the same link.
- **Already applied and new-today use the same matching.** A job you applied to doesn't come back
  under another link or spelling, and a job seen yesterday on Indeed isn't "new" today because
  Dreamwork listed it. A title gone for over 14 days that comes back is still new, flagged as a
  re-post. Excluded companies match any spelling too.
- **Postings checked by id on Oracle and SuccessFactors.** Oracle Recruiting Cloud (used by many
  banks, JPMorgan among them) and SuccessFactors career sites are now checked posting by posting,
  and can be added with `boards add` to the daily search. Before, their jobs could only be
  "page loads" or unverified.
- **"Similar title" is no longer "confirmed".** When the only evidence is an open role with a close
  title on the employer's board, the status is `similar_title_open`, ranked a little lower and
  checked by hand, instead of `verified_open`.
- **Re-check before applying:** `job-hunter verify --tracker` re-checks every tracked job not yet
  submitted (`--mark-closed` marks closed ones skipped), and the apply steps run a check first.
- **Simpler start:** the Start files ask nothing. They download Python if needed, add the desktop
  shortcut (Windows) and keep the Claude Code skill current, then run job-hunter in the
  background: no window to keep open. **Quit** on the page stops it, and it stops by itself when
  no job-hunter page has been open for 10 minutes (`job-hunter ui --quit-when-idle`).
- **Faster, safer first start:** setup uses uv and takes about a minute instead of 2-5. uv and
  Python stay inside the job-hunter folder. On Windows, starting job-hunter from inside the ZIP
  (without extracting it) now says to extract it first instead of failing halfway.
- **Direct download link:** each version is published as a GitHub release, so
  `releases/latest/download/job-hunter.zip` always downloads the newest one, in a folder named
  `job-hunter`.
- **CI:** Mac tests run weekly and on demand in their own workflow instead of on every push, so a
  run GitHub can't find a Mac machine for no longer marks main as failed.

## 1.2.1 (2026-10-28): security review

An audit following Cloudflare's security-audit method (five independent reviewers, a coverage
check, and a second reviewer re-testing every finding), plus Gitleaks, Semgrep, Bandit,
pip-audit, OSV-Scanner, AXguard and vibe-check. Fixes:

- **Answer bank:** the never-store check missed rewordings ("Are you disabled?", "Year of birth",
  "SS#" with no dashes), non-English forms and lookalike letters. It now catches them, refuses
  SSN-, card- and IBAN-shaped answers, and never reuses an entry an older version saved. Saving the
  answer to a negated question ("Are you **not** authorized...") no longer overwrites your answer
  to the original question; the CLI says when a saved answer changes.
- **Web page key:** the key is no longer in the page, so other accounts on a shared computer can't
  read it from the port. It's delivered through `open-job-hunter.html`, readable by your account
  only. A program squatting on the port is no longer mistaken for job-hunter; a free port is used.
- **Fetching posting links:** only public http(s) addresses, re-checked on every redirect (no
  file://, localhost, home network or cloud metadata). Board ids are validated, so a link or the
  downloaded directory can't change which server is contacted. Downloads are size-capped, and a
  page that drips slowly can't hold a check open.
- **Hidden instructions:** the scan catches soft hyphens, lookalike letters, fake "already
  approved, submit" notes, and text in button labels, image descriptions and screen-reader-only
  elements, and now covers titles and company names. The skill scans every application page,
  and only a new message after the review table authorizes a submit.
- **Copied prompts** quote the title and company and strip invisible characters and line breaks.
- **Spreadsheets:** titles and companies can't start with `=`, `+`, `-` or `@`.
- **Privacy:** API keys no longer appear in on-screen error lines. Everything job-hunter writes
  (PDFs and uploads included) is owner-only on macOS and Linux.
- **Humanizer always runs.** The humanizer skill (blader/humanizer, MIT) is bundled inside the
  job-hunter skill and applied to every tailored resume, cover letter, application essay and
  follow-up; before, it ran only if you'd installed it yourself. `jh lint` adds about 60 more AI
  tells (from the humanizer and stop-slop, MIT): "not just X, it's Y" contrasts, throat-clearing
  openers, jargon, sales language, send-offs, chatbot leftovers, any dash used as a dash, and
  stacked intensifiers. The reviewer now scores directness, rhythm, trust, authenticity and
  density, and anything under 35 of 50 gets reworked.
- **Shape check.** `jh lint` also runs slop-guard's scoring engine (MIT, included; no extra
  packages, works on Python 3.10) for the shape of the writing: sentences or bullets all the same
  length, tidy lists of three, "X. But Y." setups, one-line closers, repeated phrases, colon and dash
  habits. Findings are warnings with specific advice; markdown-only rules are left out so normal
  resumes aren't flagged. The 0-100 score is shown only for texts of 300+ words, because on a short
  resume or letter one finding drops it to single digits.
- Hardening: script/style stripping runs in linear time; `object-src 'none'` and cross-origin
  isolation headers; pypdf and Pillow minimums raised past known bugs; the live CI job doesn't keep
  its token on disk; the Windows Start script handles apostrophes and `&` in folder names; the
  demo and eval fixtures are included in the repository.

## 1.2.0 (2026-10-28)

- **The web page.** `job-hunter ui` serves a local page (127.0.0.1, token-protected, no outside
  requests): ranked jobs with a reading pane and keyboard triage, searches with live progress,
  applications, companies and boards, stats, a one-question-per-page setup, and settings. The AI
  steps copy a ready-made request for Claude Code. `scripts/make_demo.py` builds a folder of
  fictional data to try it with.
- **Start job-hunter** for Windows (`.bat`), Mac (`.command`) and Linux (`start.sh`): download the
  ZIP, double-click, and it installs itself (offering a private Python via uv if there isn't one),
  keeps your files in Documents/job-hunter, offers a desktop shortcut and the Claude Code skill,
  and opens the page. Double-clicking again reopens the page that's already running.
- Settings saved from the page keep your profile.yaml comments (new dependency: ruamel.yaml), and
  re-running setup keeps details it doesn't ask about (old files saved as `.bak`, owner-only).

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
