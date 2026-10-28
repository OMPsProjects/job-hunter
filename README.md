# job-hunter

An open-source job search you run on your own computer, for any kind of job. It:

1. **Asks what you want**: the kind of work, titles, level, cities, pay, and companies you'd love
   or never want, then builds your search from your answers and your resume.
2. **Finds the companies** that hire for that work and adds their career sites to the search.
3. **Searches** Indeed, remote-job boards, job-board APIs, and those employers' own career sites.
4. **Confirms** each posting is live on the employer's own site, not just reposted on a board.
5. **Ranks** what's left by how well it fits your resume, level, location, pay and freshness.
6. With the Claude Code skill, **tailors a resume** for the best matches (checked for AI-sounding
   phrasing and invented numbers) and **fills in applications** in your browser, stopping before
   submit so you review every one.

Your files stay on your machine. What goes out: your search titles and cities to the job boards,
company names to employers' career-site systems when checking postings, and (only with `--llm`)
text to the Anthropic API. Nothing is ever sent, signed up for, or submitted for you without
your say-so.

## Install

Python 3.10 or newer.

```bash
git clone https://github.com/OWNER/job-hunter && cd job-hunter
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .                                       # gives you the `job-hunter` command
```

(`python job_hunter.py <command>` works too, without installing.)

## Set up (5 minutes)

```bash
job-hunter setup
```

It asks, one at a time: your resume file, the kind of work you want, job titles (plus ones you'd
also consider and any career change), level, years of experience, skills, cities in order, remote,
pay floor and target, companies and kinds of roles to avoid, and companies you'd like to work for.
It writes three private files:

| File | What it holds |
|---|---|
| `profile.yaml` | what to search for and how to rank it |
| `candidate.yaml` | your resume, structured (titles, levels, skills, years) |
| `companies.yaml` | employers' career sites searched every run, and boards you've added |

Check it any time with `job-hunter check`.

**With Claude Code:** install the skill and say *"set up my job search"*. Claude has the same
conversation in chat, reads your resume, researches companies in your field, and runs setup for you.

```bash
mkdir -p ~/.claude/skills && cp -r skills/job-hunter ~/.claude/skills/
# Windows PowerShell: Copy-Item -Recurse skills\job-hunter $HOME\.claude\skills\
```

## Daily use

```bash
job-hunter search            # 10-30 minutes; results in results/
job-hunter health            # run history, and any source that's stopped returning jobs
```

With Claude Code, say *"run my job search"* for a shortlist where Claude has read every
description, checked the top jobs on the employers' sites, and explained each pick and skip.

| Result file | What's in it |
|---|---|
| `results/ranked.csv` | new jobs, best first, with every part score, why it fits, and its gaps |
| `results/jobs_new_details.jsonl` | the same jobs with full descriptions |
| `results/excluded.csv` | what was filtered out, and why |
| `results/run_summary.json` | counts per source, verification results, health warnings |

## Grow where it searches

```bash
job-hunter companies discover          # employers posting roles like yours, and whether their site is readable
job-hunter companies discover --add    # add the readable ones
job-hunter companies add "Acme Health" # one company: finds its career site by name
job-hunter boards add https://careers.acme.com --name "Acme"   # any board or careers page you find
job-hunter companies list / boards list / companies remove "Acme"
```

`boards add` puts a career site the script can read (Greenhouse, Lever, Ashby, SmartRecruiters,
Workable, Recruitee, Workday) straight into the daily search. Anything else goes on a
browser-search list that the Claude skill checks for you on request.

## Where jobs come from

| Source | Key? | On by default | Notes |
|---|---|---|---|
| Indeed (via python-jobspy) | no | yes | |
| LinkedIn (via python-jobspy) | no | **no** | opt in via `search.sites`; LinkedIn's terms forbid automated access and it may limit your account |
| Google Jobs, Glassdoor, ZipRecruiter | no | no | opt in via `search.sites`; blocked or empty in late 2026 |
| Remotive, Himalayas, RemoteOK | no | yes | remote jobs |
| The Muse | no | yes | filtered by title (no keyword search) |
| Arbeitnow | no | no | mostly Europe |
| Adzuna, USAJobs, Jooble | free key | when key set | put keys in `.env`: `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `USAJOBS_API_KEY`, `USAJOBS_EMAIL`, `JOOBLE_API_KEY` |
| Employer career sites | no | your list | Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Workday |

## How a job gets confirmed

For the top matches, the script asks the employer's own system whether the posting is open: the
apply link's ATS if it has one, otherwise the company's board found by name, otherwise the
employer's apply page itself. Results: `verified_open`, `employer_page_live`, `unverified`,
`not_on_employer_site` or `closed`. The last two are dropped. Unverified jobs rank lower, and the
skill checks the shortlist's unverified jobs by hand.

## How ranking works

`rank_score` (0-100) is a weighted average, weights in `profile.yaml`:

| Part | Default | Measures |
|---|---|---|
| fit | 40 | your resume skills found in the posting, title closeness, keyword score |
| seniority | 20 | years asked vs. yours; title level vs. the levels you want |
| location | 15 | position in your city order |
| pay | 15 | posted pay vs. your floor and target (not posted = neutral) |
| freshness | 10 | days since posted |

Unconfirmed jobs are multiplied by 0.85, and a job with fit under 40 is scaled down so pay or
location can't carry a poor match. Excluded companies or keywords, jobs you've applied to, and
pay under your floor remove a job outright.

**Is the order right for you?** `job-hunter labels` writes a sheet of the last run's jobs; mark
each 2 (would apply), 1 (maybe) or 0 (no). `job-hunter eval-rank` then reports how many of the
top 10 you'd apply to, and `--tune` suggests weights that fit your judgment better.

## Tailored resumes and applying (Claude Code)

Say *"tailor for #3"* or *"apply to #2"*. The skill writes each resume from your base resume only,
then runs:

```bash
job-hunter lint   applications/<job>/resume.yaml   # AI-sounding words, and numbers not in your resume
job-hunter render applications/<job>/resume.yaml --pages 2
```

When applying, it opens the employer's application, uploads the tailored PDF, and fills fields
from your saved answers and resume. It **asks you** to create accounts or sign in (it never handles
passwords or codes), **asks you** anything it has no answer for and saves it for next time,
**leaves you** EEO questions and legal attestations, and **stops at the final submit** with a list
of everything it entered. You submit, or tell it "submit the Acme application" after reviewing
that one.

Saved answers live in `answers.yaml`. ID and account numbers, date of birth, passwords and EEO
answers are never saved. Matching is strict on purpose: "authorized to work in the UK" won't reuse
your US answer, and "Reference email" won't get your email.

**Try it safely first:** `evals/` has a fake application site full of traps and a grader. See
`evals/README.md`.

## Run the search every morning

- **macOS / Linux (cron):** `0 9 * * 1-5 cd /path/to/job-hunter && .venv/bin/job-hunter search`
- **Windows (Task Scheduler):** daily task running `C:\path\to\job-hunter\.venv\Scripts\job-hunter.exe`
  with argument `search` and "Start in" set to your job-hunter folder.

Only one search runs at a time per folder; a second one exits with a message.

## Your files stay yours

All personal files are gitignored: `profile.yaml`, `candidate.yaml`, `candidate/`,
`answers.yaml`, `applications.csv`, `applications/`, `companies.yaml`, `results/`, `.env`.
Private files are written owner-only on macOS and Linux; logs mask emails, phones and IDs. See
`SECURITY.md`.

## All commands

```
job-hunter setup [--from answers.yaml] [--force]
job-hunter check
job-hunter search [--sources jobspy,remotive,...] [--no-verify] [--llm]
job-hunter rank
job-hunter health
job-hunter companies add NAME [--url URL] [--track T] | discover [--add] [--fresh] | list | remove NAME
job-hunter boards add URL [--name N] | list | remove URL
job-hunter verify --url U --company C --title T
job-hunter resume FILE [--llm] [--force]
job-hunter render YAML -o OUT.pdf --pages N
job-hunter lint YAML
job-hunter answers match|add|fact|check|list ...
job-hunter track set|list ...
job-hunter labels / eval-rank [--tune]
```

Options for every command: `--profile PATH`, `--out DIR`, `-v`. `job-hunter -h` for details.

## Limits, honestly

- **Job boards change and block scrapers.** `job-hunter health` and the nightly live check in CI
  flag a source that stops working; a run carries on without it.
- **Terms of service.** Many boards restrict automated access. This is built for one person's
  low-volume search; keep the defaults.
- **Verification isn't perfect.** Some custom career sites can't be checked by script; those stay
  `unverified` until the skill or you check them.
- **The ranking starts as a guess.** Use `labels` and `eval-rank` to fit it to you.

## Contributing

See `CONTRIBUTING.md`. MIT licensed (`LICENSE`).
