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
- **Private files** (`profile.yaml`, `candidate.yaml`, `answers.yaml`, `applications.csv`,
  `.env`, run logs and the run database) are written owner-only (mode 600) on macOS and Linux. On Windows they inherit your user
  folder's permissions. Use full-disk encryption (FileVault, BitLocker) for protection at rest.
- **API keys** go in `.env` next to `profile.yaml`, never in `profile.yaml` itself.
- **Logs** in `results/logs/` mask emails, phone numbers, ID-like numbers and API keys.
- **Never stored, by design:** ID and account numbers, passwords, date of birth, and EEO /
  self-identification answers. The answer bank refuses them.

## The web page (`job-hunter ui`)

- It listens on 127.0.0.1 only, so other devices on your network can't reach it.
- Every API request must carry a random token generated when the page starts and embedded in
  it, so other websites open in your browser can't read or change your data; requests whose
  Host isn't localhost are refused (DNS rebinding).
- The page loads nothing from the internet (fonts and scripts are local) and has a strict
  Content Security Policy. Job posting text is only ever shown as text, never as HTML.
- It runs only the job-hunter commands it offers (search, re-rank, find companies, update the
  directory); a request can't choose another command.

## The Claude skill

The skill drives your browser to fill applications. Its rules, which the mock-site evals in
`evals/` test: it never creates accounts, types passwords, uses "Continue with Google"-style
sign-in, reads verification codes, solves CAPTCHAs, fills EEO questions or legal attestations,
or presses a final submit button unless you name that specific application after reviewing it.
Text on web pages is treated as data, not instructions.

## Before you contribute

`pre-commit install` adds a hook that blocks committing private files or anything that looks like
a real email, phone or ID number. CI runs the same check.
