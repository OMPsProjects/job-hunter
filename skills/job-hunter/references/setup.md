# Setup: from "what job do you want?" to a working search

Do this the first time, when someone wants a different kind of job, or when they hand you a new
resume. It works for any field. Ask in small batches (2-4 questions per message), not all at once
and not one at a time. `jh` = `job-hunter` or `python job_hunter.py`.

## 1. Understand what they want

Start with the work, not the resume. Ask:

1. **What kind of work do you want?** The field or industry, in their words ("hospital nursing",
   "B2B software sales", "commercial real estate lending", "high school teaching").
2. **What job titles would you apply to tomorrow?** If they're unsure, propose 5-8 real titles
   people in that field search for, and let them pick. Then ask about **adjacent** titles (same
   skills, different seat) and any **career-change** titles. To suggest adjacent titles and
   skills from standard occupation data, run `jh occupations suggest "Title 1" "Title 2"`: it
   shows which occupation each title maps to, job titles from related occupations, and skills
   postings in those occupations ask for. Check the mapping makes sense (a "Commercial Real
   Estate Underwriter" maps to Insurance Underwriters, which is wrong; `jh occupations search
   "loan underwriter"` finds better ones) and offer only suggestions that fit their field.
3. **What level?** One or more of: intern, entry, mid, senior, manager, director, vp, executive.
   Years of experience in this field.
4. **Where?** Cities in order of preference, and whether remote is OK (and whether remote should
   rank as high as their first city).
5. **Pay:** lowest base they'd take, and what they're aiming for.
6. **Hard no's:** companies (current employer, places they've left) and kinds of roles or words
   that rule a job out.
7. **Companies they'd love to work for**, if any.

## 2. Their resume

Ask for it (PDF, DOCX, TXT or MD). Copy it into their folder as `candidate/base_resume.<ext>`.
It's the only source of facts for tailored resumes; anything true but missing goes in
`candidate/career_facts.md`, one fact per line, in their words. Ask once: "Anything true that
isn't on your resume and could go on one: projects, tools, results?"

Pull their main skills from the resume, worded the way job postings in their field say them
("credit memo", "patient assessment", "pipeline management"), 8-20 of them. Show the list and let
them correct it.

## 3. Build the profile

Write their answers to `candidate/setup_answers.yaml` (private) with these keys, then run setup:

```yaml
resume: candidate/base_resume.pdf
field: hospital nursing
titles: [Registered Nurse, ICU Nurse]
adjacent_titles: [Charge Nurse]
pivot_titles: []
levels: [mid, senior]
years_experience: 6
skills: [critical care, patient assessment, telemetry, Epic]
locations: ["Denver, CO", "Austin, TX"]      # quote each "City, ST"
remote: no
remote_like_top_city: no
pay_floor: 85000
pay_target: 110000
avoid_companies: [Current Employer Inc]
avoid_keywords: [travel nurse]
target_companies: [Denver Health, UCHealth]
discover_companies: yes
needs_sponsorship: no                        # ask if relevant; see §6
occupations: {core: "29-1141.00"}            # optional: track -> occupation code for pay estimates,
                                             #   when a title maps to the wrong one
```

```
jh setup --from candidate/setup_answers.yaml        # add --force to replace an existing profile
```

It writes `profile.yaml`, `candidate.yaml`, `candidate/resume.txt`, and adds their target
companies to `companies.yaml` (it reports any it can't find a readable career site for). Then
fill in what setup can't know, in `candidate.yaml`: `past_titles` (from the resume), more
`skills` split into `core`/`other`, `summary` (3 plain sentences). Run `jh check`.

A person at a terminal can run `jh setup` and answer the same questions themselves.

## 4. Find companies that hire for this

Two ways, use both:

**From the job market (after the first search).** `jh companies discover` lists employers that
posted roles like theirs in the last run and have a career site the script can read (it finds
the site from their apply links, then a public directory of ~24,000 companies' careers sites,
then by guessing the board name), with how many open roles each has and how many look like theirs. Show the list; add the ones they want with `jh companies discover --add`, or
`jh companies add "Name"` for individual ones. Staffing agencies are skipped.

**From research.** Use WebSearch to build a list of 15-30 employers known for this kind of work
in their cities and remote: the biggest employers in the field, fast-growing ones, and well-regarded
ones. Show the list with one line each on why, let them cut it, then add each:

```
jh companies add "Company Name"                     # finds their career site by name
jh boards add https://careers.company.com --name "Company Name"   # if you have the careers URL
```

`boards add` puts a readable career site (Greenhouse, Lever, Ashby, SmartRecruiters, Workable,
Recruitee, Workday) into the daily search; anything else goes on the browser-search list that
you check by hand when they ask for a full sweep. Tell them which happened for each.

**Job boards they mention** ("I use SelectLeaders", "there's a nursing board..."): `jh boards add <url>`.

## 5. Seed the answer bank

Save facts straight from the resume (these become reusable form answers):

```
jh answers fact first_name "..."          # also last_name, email, phone
jh answers fact street "..."              # mailing address: street, city, state, zip
jh answers fact linkedin "..."            # and website, if any
jh answers add "Highest level of education completed" "BSN" --source resume
jh answers add "Years of relevant experience" "6" --source resume
```

Then ask once and save each with `jh answers add` (source `you`): work authorization, sponsorship
now or in future, willing to relocate (where), salary expectation, earliest start date / notice
period, how they heard about roles (default "Company website"), whether they've worked for each
excluded company before (yes/no only).

Don't ask for or save ID numbers, account numbers, date of birth, passwords, or EEO answers
(race, ethnicity, gender, orientation, veteran or military status, disability). The script
refuses them; don't try another wording, and don't write them in any other file either.

## 6. Optional extras

- **Visa sponsorship:** if they need it now or later, set `filters.needs_sponsorship: true` in
  `profile.yaml`. Postings that say they won't sponsor (or need U.S. citizenship or a clearance)
  are then excluded, with the reason in `excluded.csv`. For employers' H-1B history, they download
  the CSV from USCIS's H-1B Employer Data Hub in their browser and run
  `jh data import-sponsors <file>`.
- **Pay estimates** for postings without pay come from BLS (on by default). Without a key BLS
  allows 25 requests a day per network, which is usually enough because results are cached for
  months. A free key (`BLS_API_KEY` in `.env`, from data.bls.gov/registrationEngine) raises it.
- **Smarter title matching:** `pip install -e ".[ml]"` adds the JobBERT title model (about 2 GB
  with PyTorch). Worth it if their field uses many different titles for the same job.

- **More sources:** free API keys for Adzuna, USAJobs and Jooble go in `.env` next to
  `profile.yaml` (`ADZUNA_APP_ID=...`). `jh check` shows which sources are on.
- **LinkedIn** is off by default because its terms forbid automated access and it may limit the
  account. Only add `linkedin` to `search.sites` if they say they accept that.
- **Schedule:** the README has cron and Windows Task Scheduler steps for a daily `jh search`.
- **Before the first real application,** suggest they run the mock application eval
  (`evals/README.md`) so they can see how the apply step behaves on a fake site.
