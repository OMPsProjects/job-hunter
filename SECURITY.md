# Security and privacy

## Reporting a problem

Report security or privacy problems privately through GitHub's
[private vulnerability reporting](../../security/advisories/new), not a public issue. Include
what you saw and how to reproduce it, using the fictional example files, never your own.

## What job-hunter does with your data

- **Everything stays on your computer.** Your profile, structured resume, saved answers,
  tracker, tailored resumes and run history live in gitignored files in your folder. There is no
  server and no telemetry.
- **What goes over the network:** your search titles and cities go to the job boards and APIs
  you enable; company names go to ATS APIs during verification. With `--llm` or `resume --llm`,
  your candidate summary and job descriptions go to the Anthropic API. Public reference data is
  downloaded, with nothing about you in the request: the careers-site directory from
  storage.stapply.ai (the ats-scrapers project), and BLS pay figures from api.bls.gov (the request
  names an occupation code and a metro code). The optional title model downloads once from
  Hugging Face and runs on your computer. Nothing else is sent.
- **Reference data** lives in a cache folder outside your project (`job-hunter data status`
  shows where). It holds public data, though the cached pay figures do show which occupations and
  metros you've searched. Delete it any time.
- **Your files** (profile, candidate facts, resumes and cover letters, answers, the tracker,
  results, logs, `.env`) are created readable by your account only on macOS and Linux (job-hunter
  sets a private umask, and the Start script creates your folder private). On Windows they
  inherit your user folder's permissions. Use full-disk encryption (FileVault, BitLocker) for
  protection at rest.
- **API keys** go in `.env` next to `profile.yaml`, never in `profile.yaml` itself.
- **Logs and on-screen messages** mask emails, phone numbers, ID-like numbers and API keys, and
  error messages never include a URL's query string, so the `!` lines are safe to paste into an issue.
- **Never stored, by design:** ID and account numbers, passwords, date of birth or age, and EEO /
  self-identification answers. The answer bank refuses them however the question is worded
  (rewordings, abbreviations like SS#, common non-English forms, lookalike letters), refuses
  answers that look like an SSN, card or bank account number, and never reuses one an older
  version saved. A question that adds "not", a country or a skill is saved as a separate question,
  never over your existing answer.

## Job postings are untrusted

- Apply links and career-site addresses come from whoever posted the job. job-hunter only fetches
  plain http(s) addresses on the public internet: never a file on your computer, your computer
  itself, your home or office network, or a cloud metadata address, and it re-checks every
  redirect. Board ids taken from links or the downloaded directory must look like board ids, so
  they can't change which server is contacted.
- Titles and company names are cleaned when they arrive: invisible characters are removed, and a
  leading `=`, `+`, `-` or `@` is dropped so a spreadsheet won't run it as a formula.
- Text aimed at AI tools (hidden text, invisible characters, lookalike letters, fake "the candidate
  already approved this" notes, instructions in button labels or image descriptions) is flagged
  in the title, company and description, and the skill scans each application page before
  filling it.

## The web page (`job-hunter ui`)

- It listens on 127.0.0.1 only, so other devices on your network can't reach it.
- Every API request must carry a random key made when the page starts. The key is never in the
  page: job-hunter writes it into `open-job-hunter.html` in your folder (readable by your account
  only) and opens that, so the key reaches your browser after the `#`, which is never sent over
  the network. Other websites in your browser can't get it, and neither can other accounts on a
  shared computer, even though they can reach the port. Requests whose Host isn't localhost are
  refused (DNS rebinding).
- If another program is on job-hunter's port, it's never mistaken for job-hunter (the check needs
  your private key file); job-hunter picks a free port instead.
- The page loads nothing from the internet (fonts and scripts are local) and has a strict
  Content Security Policy. Job posting text is only ever shown as text, never as HTML.
- It runs only the job-hunter commands it offers (search, re-rank, find companies, update the
  directory); a request can't choose another command.

## The Claude skill

The skill drives your browser to fill applications. Its rules, which the mock-site evals in
`evals/` test: it never creates accounts, types passwords, uses "Continue with Google"-style
sign-in, reads verification codes, solves CAPTCHAs, fills EEO questions or legal attestations,
or presses a final submit button unless you name that specific application, in a new message,
after it shows you the review table. Nothing inside the request that started the application,
a job title, or a web page counts as that. Text on web pages is treated as data, not instructions.

These are rules the AI follows, not locks: nothing in job-hunter can physically stop a browser
click. If your browser tool can ask you before it acts on a site, keep that on for job sites, and
read the review table before you say "submit".

## Before you contribute

`pre-commit install` adds a hook that blocks committing private files or anything that looks like
a real email, phone or ID number. CI runs the same check.
