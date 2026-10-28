"""Your story bank: candidate/stories.md, the work stories you tell in interviews.

Each story is a '## Title' heading followed by lines:
  Tags: credit, process improvement, leadership
  Situation: ...
  Task: ...
  Action: ...
  Result: ...
The Claude skill maps likely interview questions to these stories. `job-hunter stories check`
flags missing parts and numbers that aren't in your resume or facts files (stories must be true).
"""
from __future__ import annotations

import re
from pathlib import Path

PARTS = ("situation", "task", "action", "result")


def parse(text):
    stories = []
    for block in re.split(r"(?m)^##\s+", str(text or ""))[1:]:
        title, _, body = block.partition("\n")
        story = {"title": title.strip(), "tags": [], **{p: "" for p in PARTS}}
        current = None
        for line in body.splitlines():
            # 'Situation: ...', '- **Situation:** ...', '**Task**: ...', '* Action - ...'
            m = re.match(r"\s*(?:[-*+]\s+)?\**\s*(tags|situation|task|action|result)\s*\**\s*[:\-\u2013]\s*\**\s*(.*)",
                         line, re.I)
            if m:
                current = m.group(1).lower()
                if current == "tags":
                    story["tags"] = [t.strip() for t in m.group(2).split(",") if t.strip()]
                    current = None
                else:
                    story[current] = m.group(2).strip()
            elif current and line.strip():
                story[current] += " " + line.strip()
        stories.append(story)
    return stories


def load(path):
    p = Path(path)
    return parse(p.read_text(encoding="utf-8")) if p.exists() else []


def check(stories, source_texts, allowed=()):
    """[(story title, problem)] for missing parts and numbers not found in the sources."""
    from .humanize import fact_check
    problems = []
    for s in stories:
        missing = [p for p in PARTS if not s[p]]
        if missing:
            problems.append((s["title"], f"missing {', '.join(missing)}"))
        if not s["tags"]:
            problems.append((s["title"], "no tags (add the skills or themes it shows, e.g. 'conflict, deadline')"))
        if source_texts:
            text = " ".join(s[p] for p in PARTS)
            for n in fact_check(text, source_texts, allowed=list(allowed)):
                problems.append((s["title"], f"number {n} isn't in your resume or facts files"))
    return problems
