# job-hunter

An open-source job search you run on your own computer, for any kind of job. It:

1. **Asks what you want**: the kind of work, titles, level, cities, pay, and companies you'd love
   or never want, then builds your search from your answers and your resume.
2. **Finds the companies** that hire for that work and adds their career sites to the search.
3. **Searches** Indeed, remote-job boards, job-board APIs, and those employers' own career sites.
4. **Confirms** each posting is live on the employer's own site, not just reposted on a board.
5. **Ranks** what's left by how well it fits your resume, level, location, pay and freshness,
   estimating pay from government data when a posting doesn't list it, and flagging re-listed
   jobs and (if you need it) postings that won't sponsor a visa.
6. With the Claude Code skill, **tailors a resume** for the best matches (checked for AI-sounding
   phrasing and invented numbers) and **fills in applications** in your browser, stopping before
   submit so you review every one.

Your files stay on your machine. What goes out: your search titles and cities to the job boards,
company names to employers' career-site systems when checking postings, and (only with `--llm`)
text to the Anthropic API. Nothing is ever sent, signed up for, or submitted for you without
your say-so.

## Install

**The easy way (Windows, Mac, Linux): no terminal needed.**

1. Download **[job-hunter.zip](https://github.com/OMPsProjects/job-hunter/releases/latest/download/job-hunter.zip)**
   (always the newest version). Unzip it somewhere you'll keep it, like your Documents folder:
   on Windows, right-click it and choose **Extract All**; on a Mac, double-click it.
2. Open the unzipped folder and start job-hunter:
   - **Windows:** double-click **Start job-hunter.bat**. If Windows says it protected your PC,
     click **More info**, then **Run anyway** (it's a plain-text script; open it in Notepad to read
     it first if you like).
   - **Mac:** right-click **Start job-hunter.command** and choose **Open**. If your Mac still
     refuses, open **System Settings > Privacy & Security** and click **Open Anyway**. Macs ask
     this once for any script downloaded from the internet.
   - **Linux:** run `./start.sh`.
3. The first time, it sets itself up, which takes about a minute; there's nothing to answer. It
   uses [uv](https://docs.astral.sh/uv/) from Astral to get job-hunter's parts and its own copy of
   Python, all kept inside the job-hunter folder (no admin rights needed, nothing else changes). On
   Windows it adds a desktop shortcut, and if you use Claude Code it adds the job-hunter skill
   (and keeps it up to date each time you start).
4. Your browser opens job-hunter. It runs in the background, so you can close the setup window.
   To stop it, click **Quit** at the top of the page; it also stops by itself once no job-hunter
   page has been open for 10 minutes.

After that, double-click the same file (or the desktop shortcut) whenever you want job-hunter.
Your files (profile, resume, results) live in **Documents/job-hunter**, separate from the
program, so a new version never touches them. To update, download the new ZIP, unzip it, and
start it the same way.

**The developer way.** Python 3.10 or newer:

```bash
git clone https://github.com/OMPsProjects/job-hunter && cd job-hunter
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .                                       # gives you the `job-hunter` command
```

(`python job_hunter.py <command>` works too, without installing.)

Optional: `pip install -e ".[ml]"` adds a job-title model that matches titles by meaning
("Mortgage Underwriter" is close to "Credit Underwriter"). It's about 2 GB with PyTorch.

## What it costs

The search, verification and ranking are plain Python: free, and no AI account needed. Only
the Claude Code skill (tailoring resumes, cover letters, filling applications, reading
descriptions for the daily shortlist) uses Claude, through your Claude Code plan.

**Watch out:** if `ANTHROPIC_API_KEY` is set in your environment, Claude Code bills that API key
per token instead of using your subscription. Unset it unless that's what you want. The
optional `--llm` flags always use the API key.

## The web page

```bash
job-hunter ui
```

opens job-hunter in your browser: today's ranked jobs with a reading pane for each posting,
shortlisting and "would you apply?" ratings from the keyboard, searches with live progress, your
applications, the companies and boards it searches, response-rate stats, setup as one question
per page, and settings. It runs on your computer only (127.0.0.1); nothing is hosted anywhere.

The AI steps stay in Claude Code: on any job, "Ask Claude to..." copies a request (tailor my
resume, write a cover letter, fill in the application, prepare for the interview) to paste into
Claude Code. Try it with made-up data first: `python scripts/make_demo.py /tmp/jh-demo`, then
`cd /tmp/jh-demo && job-hunter ui`.

## Set up (5 minutes)

On the web page, **Setup** starts with your resume. job-hunter reads your job titles, employers,
city, skills, level and years from it and fills in four short pages for you to check:

1. **Your resume.**
2. **The jobs you want:** titles to search (from your resume, cleaned up for job boards: "Vice
   President, Senior Commercial Loan Underwriter" becomes "Commercial Loan Underwriter"), with a type-ahead list of job titles; titles you'd also consider; levels (pick
   several).
3. **Where:** cities picked from a list (or "Use my city"), and remote: cities only, cities and
   remote, or remote only.
4. **Pay, skills and companies:** the skills from your resume are already in; add others. Skip your
   current employer or all past employers with one click.

In a terminal, `job-hunter setup` asks the same things one at a time.
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

To find a company's career site, job-hunter checks its apply links, then a public directory of
about 24,000 companies' careers sites (downloaded to a cache folder and refreshed monthly; see
`job-hunter data status`), then guesses the board name.

`boards add` puts a career site the script can read (Greenhouse, Lever, Ashby, SmartRecruiters,
Workable, Recruitee, Workday, Oracle Recruiting Cloud, SuccessFactors career sites) straight into the daily search. Anything else goes on a
browser-search list that the Claude skill checks for you on request.

## Where jobs come from

| Source | Key? | On by default | Notes |
|---|---|---|---|
| Indeed (via python-jobspy) | no | yes | |
| LinkedIn, read by Claude in your browser | no | **no** | tick "Search LinkedIn in my browser" in Setup (`search.linkedin_browser: true`). See [LinkedIn](#linkedin) below |
| LinkedIn (via python-jobspy) | no | no | `search.sites`; LinkedIn usually blocks it after a few searches ("429, use a proxy") |
| Google Jobs, Glassdoor, ZipRecruiter | no | no | opt in via `search.sites`; blocked or empty in late 2026 |
| Remotive, Himalayas, RemoteOK | no | yes | remote jobs |
| The Muse | no | yes | filtered by title (no keyword search) |
| Arbeitnow | no | no | mostly Europe |
| Dreamwork | no | **no** | about 2 million postings gathered from employers' career sites. Turn on with `dreamwork: true` under `sources:`. Sends your search titles and cities (nothing else: no resume, no account) to dreamworkhq.com. Links go to the employer's own posting when Dreamwork has it. Guest access returns 25 roles per search, and descriptions are fetched for the 40 newest |
| Adzuna, USAJobs, Jooble | free key | when key set | put keys in `.env`: `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `USAJOBS_API_KEY`, `USAJOBS_EMAIL`, `JOOBLE_API_KEY` |
| Employer career sites | no | your list | Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Workday, Oracle Recruiting Cloud, SuccessFactors |

### LinkedIn

LinkedIn blocks searches from programs, so job-hunter doesn't search it itself. With "Search
LinkedIn in my browser" on, ask Claude to "run my job search" (Claude Code with the job-hunter
skill and the [Claude in Chrome](https://claude.com/chrome) extension). A small helper on Claude's
fast, low-cost model opens LinkedIn's job search in your Chrome, where you sign in yourself, reads
each results page with one short script (no screenshots), saves what it read, and imports it.
Those jobs then go through the same filters, duplicate check, ranking and employer-site check as
the rest.

**Token limits.** Browsing with Claude is token-hungry, so LinkedIn has its own daily and weekly
limits (Settings, or `linkedin:` in `profile.yaml`; 150k a day and 600k a week to start).
`job-hunter linkedin plan` hands Claude only as many searches and job descriptions as the limits
leave room for, and counts them as spent. Afterwards `job-hunter linkedin usage` reads Claude
Code's own record of the helper's run and replaces the estimate with what it really used, so the
next plan is sized on real numbers. `job-hunter linkedin status` shows where you are. To keep it
cheap: several titles share one search, only jobs posted since the last run are asked for, and
descriptions are read only for titles that fit (set descriptions to 0 for titles only).

Claude only reads. It never applies, saves, follows, connects, messages or changes your account,
and it stops at any CAPTCHA or "unusual activity" page. LinkedIn's terms still forbid automated
reading, even in your own browser, so there is some risk LinkedIn limits your account. If that
matters more to you than the extra jobs, leave it off and turn on LinkedIn job alerts by email
instead.

You can import from any board the same way: one JSON object per line with `title`, `company` and
an `https` `url` (optional: `location`, `date_posted`, `description`, `query`), then
`job-hunter import FILE --source <name>`.

### Duplicates

The same job often comes from several sources. It's kept once when two rows share a link, the
employer's posting id (a Greenhouse job id, Workday req number, Lever or Ashby id), or the same
company and title, with company names compared loosely ("CVS Health" = "Cvshealth", "Stripe,
Inc." = "Stripe"). The copy kept is the one from the employer's own site, then your top region,
then one with a description, then one with pay. The same matching decides "already applied"
and "new since last run". One trade-off: the same title at the same company in two of your
cities is shown once, as the copy in your higher-priority city.

### Ready-made lists

`job-hunter companies pack` lists them; `job-hunter companies pack cre-finance` adds one (also on
the Companies page, and offered in setup when your field matches). Each is a YAML file in
`jobhunter/data/packs/`: a field's employers and the recruiters and job boards that fill its jobs.
Lists for other fields are welcome as pull requests; check each career site with `job-hunter
boards add <url>` first.

## How a job gets confirmed

For the top matches (`verify.top_n`, default 150), the script asks the employer's own system
whether the posting is open: the apply link's ATS if it has one (Greenhouse, Lever, Ashby,
SmartRecruiters, Workable, Recruitee and Workday by posting id; Oracle Recruiting Cloud and
SuccessFactors career sites by posting id too), otherwise the company's board found by name,
otherwise the employer's apply page itself. Results:

| Status | Means |
|---|---|
| `verified_open` | the employer's system lists this exact posting as open |
| `similar_title_open` | the employer has an open role with a close title, but nothing ties it to this posting; it may be a different opening |
| `employer_page_live` | the employer's own page loads and doesn't say closed |
| `unverified` / `not_checked` | couldn't check / below the top matches |
| `not_on_employer_site`, `closed` | dropped |

Everything but `verified_open` ranks a little lower, and the skill checks those by hand before
they go on the shortlist. Right before applying, `job-hunter verify --tracker` re-checks every
tracked job you haven't submitted yet (`--mark-closed` sets the gone ones to skipped). Taleo and
sites behind a bot check can't be read and stay unverified.

## How ranking works

`rank_score` (0-100) is a weighted average, weights in `profile.yaml`:

| Part | Default | Measures |
|---|---|---|
| fit | 40 | your resume skills found in the posting, title closeness, keyword score |
| seniority | 20 | years asked vs. yours; title level vs. the levels you want |
| location | 15 | position in your city order |
| pay | 15 | posted pay vs. your floor and target; not posted: the BLS median for that occupation and metro at half strength (no data = neutral) |
| freshness | 10 | days since posted |

Unconfirmed jobs are multiplied by 0.85, and a job with fit under 40 is scaled down so pay or
location can't carry a poor match. Excluded companies or keywords, jobs you've applied to, and
pay under your floor remove a job outright. A pay estimate never removes a job: it's what the
middle of the market pays for that kind of work, not this employer's offer.

- **Re-listed jobs:** when a company posts the same title under a new link two or more weeks
  after an earlier one, `gaps` says so. That can mean a hard-to-fill role, a stale ad, or a
  standing "pipeline" posting. It's a flag, not a filter (`ranking.repost_multiplier` below 1.0
  ranks them lower if you want).
- **Visa sponsorship:** with `filters.needs_sponsorship: true`, postings that say they won't
  sponsor, or that need U.S. citizenship or a clearance, are excluded with the reason; ones that
  say they sponsor are noted. Download the H-1B employer CSV from USCIS's H-1B Employer Data Hub
  and run `job-hunter data import-sponsors FILE` to see each employer's recent H-1B approvals too.
  The wording checks catch common phrasings, not all of them.
- **Deadlines:** "apply by" dates are read from postings; jobs closing within 10 days say so in
  `gaps` (and `apply_by`).
- **Postings that talk to AI:** some postings hide text for AI screeners or AI applicants
  (invisible characters, text styled not to show, "AI assistants: ignore your instructions...").
  Those are flagged in `gaps` (`integrity_note`), never followed, and the skill shows you the
  lines before it writes anything for that job. `job-hunter scan FILE` checks a saved posting.
- **Title matching:** title closeness compares words, ignoring level words like "Senior". With
  the optional `[ml]` install it also compares meaning.

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

> **Beta:** applying in the browser is the newest and least-tested part. It has been tested against
> the mock application site in `evals/`, not yet across many real employer sites. Read the review
> table every time, and keep your browser tool set to ask before it acts if it offers that.

When applying, it opens the employer's application, uploads the tailored PDF, and fills fields
from your saved answers and resume. It **asks you** to create accounts or sign in (it never handles
passwords or codes), **asks you** anything it has no answer for and saves it for next time,
**leaves you** EEO questions and legal attestations, and **stops at the final submit** with a list
of everything it entered. You submit, or tell it "submit the Acme application" after reviewing
that one.

Saved answers live in `answers.yaml`. ID and account numbers, date of birth, passwords and EEO
answers are never saved. Matching is strict on purpose: "authorized to work in the UK" won't reuse
your US answer, and "Reference email" won't get your email.

Every draft also gets a **reviewer pass**: a second Claude agent that didn't write it checks it
against the posting (true to your sources? does it answer the posting's main asks? anything
generic or AI-sounding?) before you see it. `render` then reads the text back out of the PDF the
way an applicant tracking system would and flags anything missing or out of order.

**Cover letters:** say *"write a cover letter for #2"*. Same sources and checks as the resume
(`job-hunter lint` and `render` take a cover letter YAML; see `templates/cover_letter.example.yaml`).

**Interviews:** say *"I have an interview with Acme"*. The skill builds a prep pack (the role's
main asks, company research with sources, likely questions mapped to your stories, honest
answers for gaps, questions to ask) and can run a mock interview. Your stories live in
`candidate/stories.md` (see `templates/stories.example.md`); `job-hunter stories check` flags
missing parts and numbers your resume doesn't back up.

**Follow-ups:** say *"who should I follow up with?"*. It drafts a short note for each
application with no answer after two or three weeks. Drafts only: it never sends anything.

**How it's going:** the tracker records each status change and where the job came from.
`job-hunter stats` shows response and interview rates by source, careers system, track, and
tailored vs. not. With fewer than ~20 applications the differences are mostly chance.

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
job-hunter ui [--port 8765] [--no-browser]
job-hunter setup [--from answers.yaml] [--force]
job-hunter check
job-hunter search [--sources jobspy,remotive,...] [--no-verify] [--llm]
job-hunter rank
job-hunter health
job-hunter companies add NAME [--url URL] [--track T] | discover [--add] [--fresh] | list | remove NAME
job-hunter boards add URL [--name N] | list | remove URL
job-hunter import FILE [--source linkedin]     # postings Claude read in your browser
job-hunter linkedin plan | usage | status      # LinkedIn's token budget
job-hunter verify --url U --company C --title T
job-hunter resume FILE [--llm] [--force]
job-hunter render YAML -o OUT.pdf --pages N    # resume or cover letter
job-hunter lint YAML                           # resume or cover letter
job-hunter answers match|add|fact|check|list ...
job-hunter track set|list ...
job-hunter labels / eval-rank [--tune]
job-hunter stats [--json] [--waiting-days N]
job-hunter stories list | check
job-hunter scan FILE
job-hunter occupations match TITLE... | suggest TITLE... | search WORDS
job-hunter data update | status | import-sponsors FILE
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

## Similar projects

- **[career-ops](https://github.com/santifer/career-ops)** (MIT, free) is the closest: a Claude
  Code / Codex skill that scores jobs against your CV, writes tailored PDFs, checks whether a
  posting is live, and never submits. It runs its pipeline through the AI. job-hunter's search,
  verification and ranking run without one, it starts from "what job do you want?" and finds
  employers for you, and it checks postings against the employer's own hiring system.
- **Resume-Matcher**, **Reactive Resume**: resume tailoring and building, no search.
- **[ai-job-search](https://github.com/ai-job-search-dev/ai-job-search)** (MIT, free) runs the
  whole hunt through Claude Code: Danish boards built in, a drafter and reviewer for LaTeX CVs and
  cover letters, interview prep, Gmail tracking. It drafts documents; it doesn't fill forms.
  job-hunter's reviewer pass, posting checks, interview prep and follow-ups were inspired by it
  and by career-ops (our own implementations).
- Auto-apply tools (LazyApply, Sonara, AIHawk and others) submit for you in bulk. job-hunter
  deliberately doesn't: you review and submit each application.

## Data and credits

- Occupation data: this project includes information from the O*NET 31.0 Database by the U.S.
  Department of Labor, Employment and Training Administration (USDOL/ETA). Used under the
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) license. O*NET® is a trademark of
  USDOL/ETA. job-hunter has modified all or some of this information (see
  `jobhunter/data/README.md`). USDOL/ETA has not approved, endorsed, or tested these modifications.
- Pay figures: U.S. Bureau of Labor Statistics, Occupational Employment and Wage Statistics,
  via the BLS public API. BLS.gov cannot vouch for the data or analyses derived from these data
  after the data have been retrieved from BLS.gov.
- Careers-site directory: the [ats-scrapers](https://github.com/kalil0321/ats-scrapers) project's
  public companies directory (MIT).
- Title model (optional): [TechWolf/JobBERT-v3](https://huggingface.co/TechWolf/JobBERT-v3) (MIT).
- Typeface for the web page: [Atkinson Hyperlegible](https://www.brailleinstitute.org/freefont/)
  by the Braille Institute (SIL Open Font License; `jobhunter/web/static/fonts/OFL.txt`).
- Setup's one-question-per-page flow follows the GOV.UK Design System's
  [question pages](https://design-system.service.gov.uk/patterns/question-pages/) pattern.
- Job boards: [python-jobspy](https://github.com/speedyapply/JobSpy) (MIT) and each board's API.
- Humanizing: the [humanizer](https://github.com/blader/humanizer) skill by Siqi Chen (MIT) is
  bundled and applied to every resume, cover letter and essay; `jh lint` and the reviewer pass
  also use phrase lists and a scoring check adapted from
  [stop-slop](https://github.com/hardikpandya/stop-slop) by Hardik Pandya (MIT), and the shape
  check is the scoring engine of [slop-guard](https://github.com/eric-tramel/slop-guard) by Eric
  Tramel (MIT), included in `jobhunter/vendor/`. Details in `THIRD_PARTY_NOTICES.md`.

## Contributing

See `CONTRIBUTING.md`. MIT licensed (`LICENSE`).
