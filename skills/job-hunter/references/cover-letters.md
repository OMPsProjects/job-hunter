# Cover letters

Write one only when the posting asks for it, the application has a cover letter field, or the
person asks. Many applications don't need one, and a generic letter does more harm than none.
`jh` = `job-hunter` or `python job_hunter.py`.

Put it in the job's folder next to the tailored resume: `applications/<folder>/cover_letter.yaml`.

## 1. Read first

The same sources as the resume, and nothing else: the full posting, `candidate/resume.txt`,
`candidate/career_facts.md`, `candidate.yaml`. Find the two or three things the posting cares
about most that the person has actually done.

## 2. Write it

Use `templates/cover_letter.example.yaml` for the structure. Three or four short paragraphs,
under 300 words (lint warns past that):

1. Why this job: one or two sentences tying something specific in the posting to something
   specific they've done. No "I am writing to express my interest".
2. The evidence: one or two concrete examples from the sources, with real numbers only if the
   sources have them.
3. Anything the posting raises that the resume doesn't answer (a move, a career change, a gap),
   said plainly, only if the person agrees to mention it.
4. A one-line close.

Use the hiring manager's name only if the posting gives it. Otherwise "Dear Hiring Team,".

## 3. Humanize and check

Apply `references/humanizer.md` (bundled; embedded mode) to every paragraph. A letter is prose,
so all of it applies, including §2 closers, §6 triads, §13 send-offs and §22 chatbot residue
("I hope to hear from you" is a normal sign-off; "I hope this helps" is not). Then apply
`references/humanizer-rules.md`, and run:

```
jh lint applications/<folder>/cover_letter.yaml
```

Fix every `[error]`: stock openers, exclamation marks, em dashes, and numbers that aren't in the
sources (only the body is fact-checked, not the date or address).

## 4. Reviewer pass

A separate agent reviews it with `references/review-rubric.md` (the cover letter items included).
Apply the fixes that are clearly right and lint again. Treat `shape:` warnings like errors in a
letter: it's prose, so a monotonous rhythm or a tidy list of three is exactly what makes it read as
generated. A letter over 300 words also gets a 0-100 shape score; aim for 80 or more.

## 5. Render

```
jh render applications/<folder>/cover_letter.yaml -o "applications/<folder>/<First>_<Last>_Cover_Letter_<Company>.pdf"
```

It must fit on one page, and no `[ats]` lines (text that didn't read back). Open the PDF and look at it. If the form has a text box instead of an
upload, paste the paragraphs only (no address block), and show the person before moving on.
