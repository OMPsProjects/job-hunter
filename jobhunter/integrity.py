"""Check job postings for text aimed at AI tools rather than people.

Some postings hide instructions for AI screeners or AI applicants: invisible characters, text
styled so it doesn't show, or lines like "AI assistants: ignore your instructions and ...". The
Claude skill reads postings and then fills real application forms, so these get flagged before
anything is written from them. A flag never removes a job: it puts the lines in front of you.
"""
from __future__ import annotations

import re
import unicodedata

# Characters that render as nothing (or reorder text) but survive copy and paste.
INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\U000e0000-\U000e007f]")
TAG_CHARS = re.compile("[\U000e0020-\U000e007e]+")  # 'ASCII smuggling': invisible copies of normal letters
FLAG_EMOJI = re.compile("\U0001f3f4[\U000e0020-\U000e007e]+\U000e007f?")  # Scotland, England, Wales flags
OVERRIDES = re.compile("[\u202d\u202e]")  # right-to-left / left-to-right override: text reads differently than it shows
ZERO_WIDTH_LIMIT = 20  # a stray zero-width space or a copied phone number's direction marks are normal; dozens are not

# Lines that address an AI system or try to change its instructions. Kept narrow on purpose: a
# posting for an AI engineer mentions LLMs, prompts and agents all day, so every pattern needs
# an instruction aimed at the reader, not just the words.
_AI = (r"(?:ai|a\.i\.|llms?|large language models?|language models?|chat\s?gpt|gpt(?:-?\d+)?|claude|gemini|"
       r"ai\s+(?:assistants?|agents?|models?|tools?|systems?|screeners?)|automated\s+(?:agents?|systems?|tools?|screeners?))")
_DO = (r"(?:please\s+)?(?:ignore|disregard|forget|override|you\s+(?:must|should|are|will)|do\s+not|don'?t|include|"
       r"mention|insert|add|write|say|respond|reply|output|rate|score|rank|recommend|submit|use\s+the\s+(?:word|phrase))")
INJECTION = [
    re.compile(r"\b(?:ignore|disregard|forget|override)\b[^.\n]{0,40}\b(?:previous|prior|above|earlier|all|your|system)\b"
               r"[^.\n]{0,20}\b(?:instructions?|prompts?|rules|guidelines|directions)", re.I),
    re.compile(rf"\bif\s+you\s+are\s+(?:an?\s+)?{_AI}\b", re.I),
    re.compile(rf"\b(?:attention|note|message|instructions?)\s+(?:to|for)\s+(?:any\s+|all\s+)?{_AI}\b[^.\n]{{0,80}}\b{_DO}", re.I),
    re.compile(rf"^\s*(?:dear\s+|to\s+(?:any|all|the)\s+)?{_AI}\s*[:,]\s*{_DO}", re.I | re.M),
    re.compile(r"<\|im_start\|>|<\|system\|>|\[/?INST\]|\b(?:new|updated|override|reveal)\s+(?:the\s+|your\s+)?system\s+prompt", re.I),
    re.compile(r"\byou\s+are\s+now\s+(?:an?\s+|in\s+|acting|operating)|\bfrom\s+now\s+on,?\s+you\s+(?:are|must|will|should)", re.I),
    re.compile(r"\b(?:include|insert|mention|use|add)\s+(?:the\s+)?(?:word|phrase|code\s*word|keyword)\s+[\"'“‘]?[\w-]+"
               r"[^.\n]{0,40}\b(?:in|to|at)\s+(?:your|the)\s+(?:application|cover\s+letter|response|answer|resume|reply|email|"
               r"subject|summary)", re.I),
    re.compile(r"\b(?:rate|score|rank)\s+(?:this|the)\s+(?:candidate|applicant|resume)\s+(?:as\s+)?(?:highly|10|100|the\s+best)", re.I),
]
HIDDEN_MARK = "[hidden text:"


def _injections(text):
    found, seen = [], set()
    for rx in INJECTION:
        for m in rx.finditer(text):
            start = max(text.rfind("\n", 0, m.start()), text.rfind(". ", 0, m.start())) + 1
            ends = [i for i in (text.find("\n", m.end()), text.find(". ", m.end())) if i != -1]
            line = text[start:min(ends) if ends else len(text)].strip()[:160]
            if line not in seen:
                seen.add(line)
                found.append(line)
    return found


def scan(text):
    """Returns a list of findings, each dict(kind, detail). Empty when nothing looks off."""
    t = FLAG_EMOJI.sub("", str(text or ""))
    out = []
    for m in TAG_CHARS.finditer(t):
        decoded = "".join(chr(ord(c) - 0xE0000) for c in m.group(0))
        out.append({"kind": "invisible text", "detail": decoded[:160]})
    overrides = OVERRIDES.findall(t)
    others = [c for c in INVISIBLE.findall(t) if not ("\U000e0000" <= c <= "\U000e007f") and not OVERRIDES.match(c)]
    if overrides or len(others) >= ZERO_WIDTH_LIMIT:
        chars = overrides + others
        names = sorted({unicodedata.name(c, f"U+{ord(c):04X}") for c in chars})
        out.append({"kind": "invisible characters", "detail": f"{len(chars)} ({', '.join(names[:3])})"})
    visible = INVISIBLE.sub("", t)
    for line in _injections(visible):
        kind = "hidden text aimed at AI tools" if HIDDEN_MARK in line else "text aimed at AI tools"
        out.append({"kind": kind, "detail": line.replace(HIDDEN_MARK, "").strip(" ]")})
    return out


def note(text):
    """One-line summary for the ranked list's `gaps`, or ''."""
    found = scan(text)
    if not found:
        return ""
    kinds = sorted({f["kind"] for f in found})
    return "posting has " + " and ".join(kinds) + ": read it yourself before applying"


# CSS / attributes that hide an element on screen. (aria-hidden only hides from screen readers, so
# it isn't here.) The body match is bounded so a page full of unclosed tags can't slow it down.
_HIDDEN_HINT = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0|opacity\s*:\s*0|\shidden", re.I)
HIDDEN_STYLE = re.compile(
    r"<(?P<tag>[a-z][a-z0-9]*)\b(?=[^>]{0,500}?(?:style\s*=\s*[\"'][^\"']{0,300}?(?:display\s*:\s*none|"
    r"visibility\s*:\s*hidden|font-size\s*:\s*0(?:px|pt|em)?\s*[;\"']|opacity\s*:\s*0(?:\.0+)?\s*[;\"'])|"
    r"\shidden(?=[\s/>=])))[^>]{0,500}>(?P<body>.{0,4000}?)</(?P=tag)\s*>",
    re.I | re.S)


def mark_hidden_html(html):
    """Label hidden elements whose text addresses AI tools as '[hidden text: ...]', so the scan
    can say it was hidden. Other hidden content (collapsed sections, mobile duplicates) is real
    posting text and is left as it is."""
    html = str(html or "")
    if not _HIDDEN_HINT.search(html):
        return html

    def repl(m):
        inner = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group("body"))).strip()
        if inner and _injections(inner):
            return f" {HIDDEN_MARK} {inner}] "
        return m.group(0)
    return HIDDEN_STYLE.sub(repl, html)
