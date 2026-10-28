# Interview prep

Use when the person has an interview (tracker status `interviewing`) or asks to prepare.
`jh` = `job-hunter` or `python job_hunter.py`.

## 1. The story bank (once, then keep it growing)

`candidate/stories.md` holds the work stories they'll tell, one per `## heading` with Tags,
Situation, Task, Action, Result (format: `templates/stories.example.md`). If it doesn't exist,
build it with them: read their resume and facts, propose 6-10 stories that cover the usual
themes (a result they're proud of, a disagreement, a mistake, a deadline, leading without
authority, a hard decision, something they changed), and ask them to tell each one in their own
words. Write down what they say, not what sounds better. Then:

```
jh stories check        # missing parts, and numbers that aren't in their resume or facts
```

Never invent a story, a detail, or a number. A story they can't tell truthfully is left out.

## 2. The prep pack

Write `applications/<folder>/interview_prep.md` (the folder from tailoring; make one if needed):

1. **The role in their words:** the posting's five most important asks, and the interview stage
   and format if the person knows it (recruiter screen, hiring manager, panel, case).
2. **The company:** what it does, recent news, size, how this team fits. Use WebSearch; cite
   each fact with its link; only state what a source says. Mark anything older than a year.
   If they name interviewers, look up only their public professional profile (role, background
   in the field). Nothing personal.
3. **Likely questions:** 10-15, from the posting's asks and the stage. Map each to a story from
   the bank (by title) and one line on the angle to take.
4. **Gaps:** each ask they don't fully meet, with an honest answer: what they have that's close,
   and how they'd close the gap. Never a claim of experience they don't have.
5. **Their questions for the interviewer:** 5-6 specific to this role and company.
6. **Logistics** they've shared (time, place or link, who), and what to bring.

Show it in chat in short form and point to the file.

## 3. Practice (if they want it)

Run a mock interview in chat: one question at a time, wait for their answer, then brief
feedback: did they answer the question, was there a specific example and result, how long it
ran. Five or six questions, then a summary of what to tighten. Don't grade them harshly or
flatter them.

## 4. After the interview

Ask how it went and update the tracker (`jh track set --status interviewing|rejected|offer ...`).
If a new story came up that worked, add it to `candidate/stories.md` with them.
