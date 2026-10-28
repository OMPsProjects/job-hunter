# Tailoring a resume for one job

`jh` below = `job-hunter`, or `python job_hunter.py` from the repo folder.

One folder per job: `applications/YYYY-MM-DD_<company>_<title>/` (lowercase, hyphens, short).
Into it go `job.md` (the full posting text + employer URL), `resume.yaml`, the PDF, and
`notes.md` (fit, gaps, anything the user should know).

## 1. Read before writing

- The full job description, all of it. List the 5-8 things it actually asks for most, in
  its words.
- `candidate/resume.txt` (the base resume), `candidate/career_facts.md` if it exists, and
  `candidate.yaml`. These are the only sources. Nothing else may appear as a fact.
- `review.resume_rules` in `profile.yaml`. They override anything here.

## 2. Decide length

Follow `review.resume_rules`. Without a rule: 1 page if the posting asks for under 5 years of
experience, 2 pages otherwise.

## 3. Write resume.yaml

Use `templates/resume.example.yaml` for the structure. Start fresh from the base resume each
time; don't edit another job's tailored resume.

- Summary: 2-3 sentences aimed at this job, using its words where they're true.
- Reorder bullets so the ones that answer the posting's top asks come first. Reword using the
  posting's terms when they describe the same thing. Cut bullets that don't help this job.
- Keep titles, employers, dates, numbers, licenses and tools exactly as the sources state them.
- If the job wants something the person doesn't have, leave it out and note it in `notes.md`.
  Don't write around a gap with vague phrasing.

## 4. Humanize (two passes)

1. If the `humanizer` skill is installed (`~/.claude/skills/humanizer`, from
   github.com/blader/humanizer), run it on the summary and every bullet first. Check it
   didn't change any name, number, date or title.
2. Then apply `references/humanizer-rules.md` yourself, and run:

```
jh lint applications/<folder>/resume.yaml
```

Fix every `[error]`. Warnings are judgment calls. An error saying a number isn't in the source
resume means one of two things: you introduced it (remove it), or it's true and derived (ask
the user, then add it to `candidate/career_facts.md` so it passes next time).

## 5. Render and check

```
jh render applications/<folder>/resume.yaml -o "applications/<folder>/<First>_<Last>_Resume_<Company>.pdf" --pages <1|2>
```

It shrinks the font slightly (not below 8.75pt) to fit. If it still overflows, cut the weakest
bullets and render again. Open the PDF (Read tool) and look at it: no orphaned headings,
nothing cut off, dates aligned.

## 6. Record

```
jh track set --status tailored --company "..." --title "..." --resume "<pdf path>"
```

Tell the user what you emphasized, what you left out, and the gaps, in 3-4 lines per job.
