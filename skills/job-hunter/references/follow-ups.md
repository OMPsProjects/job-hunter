# Follow-ups

When the person asks "who should I follow up with?", or `jh stats` lists applications with no
answer: `jh stats --json --waiting-days 14` gives `waiting_items` (company, title, days since
submitting, links).

For each one they want to follow up on, write a draft to `applications/<folder>/followup.md`.
**Drafts only. Never send an email or message, and never look up a personal email address.**

- To: the recruiter or hiring manager only if the person has their contact from the
  application or a conversation; otherwise say where it could go (the company's careers contact,
  a LinkedIn message they send themselves).
- Three or four sentences: the role and when they applied, one specific reason they fit (from
  the tailored resume), a short ask ("Is the role still open, and is there anything else I can
  send?"). No pressure, no apology, no exclamation marks.
- Apply `references/humanizer.md` (embedded mode) and `references/humanizer-rules.md`; run
  nothing through lint that isn't a resume or letter.

One follow-up per application is plenty. If there's still no answer two weeks later, suggest
marking it `skipped` and moving on.
