"""Resume lint: catches the words and patterns that make a resume read as AI-written, and numbers
that don't appear anywhere in your source material (a sign something was invented).

This is the built-in half of humanizing. The skill also runs the `humanizer` skill
(github.com/blader/humanizer) first when it's installed. This check runs either way.
"""
import contextlib
import re
from pathlib import Path

# Words/phrases that are either AI tells or resume filler. (phrase, why)
BANNED = {
    "spearheaded": "AI tell; say what you did (led, ran, built)",
    "leveraged": "AI tell; say 'used' or name the tool",
    "leveraging": "AI tell",
    "robust": "vague", "seamless": "vague", "seamlessly": "vague", "dynamic": "vague",
    "passionate": "filler", "results-driven": "filler", "results-oriented": "filler",
    "proven track record": "filler; show the record instead", "track record of": "filler",
    "cutting-edge": "vague", "synergy": "filler", "synergies": "filler",
    "fostered": "AI tell", "fostering": "AI tell", "navigated": "AI tell", "navigating": "AI tell",
    "pivotal": "AI tell", "delve": "AI tell", "tapestry": "AI tell", "landscape": "AI tell",
    "ensuring": "AI tell (participle tail)", "showcasing": "AI tell", "underscoring": "AI tell",
    "underscores": "AI tell", "highlighting": "AI tell (participle tail)", "utilize": "say 'use'",
    "utilized": "say 'used'", "orchestrated": "AI tell", "championed": "AI tell", "empowered": "AI tell",
    "elevate": "AI tell", "elevated": "AI tell", "embark": "AI tell", "realm": "AI tell",
    "resonate": "AI tell", "harness": "AI tell", "harnessed": "AI tell", "unlock": "AI tell",
    "meticulous": "AI tell", "meticulously": "AI tell", "holistic": "vague", "transformative": "vague",
    "unwavering": "AI tell", "testament": "AI tell", "in today's": "AI tell", "fast-paced": "filler",
    "game-changer": "filler", "world-class": "filler", "best-in-class": "filler", "thought leader": "filler",
    "detail-oriented": "filler; show it", "team player": "filler", "self-starter": "filler",
    "hard-working": "filler", "hardworking": "filler", "go-getter": "filler",
    "responsible for": "weak; start with what you did", "duties included": "weak", "helped to": "weak",
    "various": "vague; name them", "innovative": "vague", "visionary": "filler", "strategic thinker": "filler",
    "excellent communication skills": "filler", "seasoned": "filler",
}
WARN = {
    "streamlined": "fine once; overused", "comprehensive": "often filler", "crucial": "often filler",
    "vital": "often filler", "key": "often filler as an adjective", "successfully": "usually cut it",
    "effectively": "usually cut it", "strong": "often filler", "extensive": "often filler",
}


def _find(word, text):
    return [m.start() for m in re.finditer(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", text, re.I)]


def lint_text(text, bullets=None):
    """Returns list of (level, message). level is 'error' or 'warn'."""
    issues = []
    for w, why in BANNED.items():
        n = len(_find(w, text))
        if n:
            issues.append(("error", f"'{w}' x{n}: {why}"))
    for w, why in WARN.items():
        n = len(_find(w, text))
        if n >= 2:
            issues.append(("warn", f"'{w}' x{n}: {why}"))
    if "—" in text:
        issues.append(("error", f"em dash x{text.count('—')}: use a comma, colon or period"))
    if re.search(r"[a-z] – [a-z]", text, re.I):
        issues.append(("error", "spaced en dash used as a dash: rewrite"))
    if "!" in text:
        issues.append(("error", "exclamation mark"))
    if re.search(r"(?m)^\s*[-•*]?\s*I\b", text):
        issues.append(("warn", "bullet starts with 'I'"))
    if re.search(r"\bnot only\b.*\bbut also\b", text, re.I):
        issues.append(("warn", "'not only ... but also' construction"))
    if re.search(r"\b(\w+), (\w+),? and (\w+) (?:solutions|outcomes|results|growth|value)\b", text, re.I):
        issues.append(("warn", "rule-of-three list ending in an abstract noun"))
    for b in bullets or []:
        if len(b.split()) > 38:
            issues.append(("warn", f"long bullet ({len(b.split())} words): {b[:60]}..."))
        if re.search(r",\s+\w+ing\b[^,]*$", b) and not re.search(r"\b(including|totaling|representing)\b", b):
            issues.append(("warn", f"bullet ends in an '-ing' tail: {b[:60]}..."))
    if bullets:
        firsts = [b.split()[0].lower().strip(",.") for b in bullets if b.split()]
        for verb in set(firsts):
            if firsts.count(verb) >= 3:
                issues.append(("warn", f"{firsts.count(verb)} bullets start with '{verb}'"))
    return issues


# ----------------------------- fact check -----------------------------------

_MONEY = re.compile(r"\$\s?(\d+(?:[.,]\d+)*)\s*(k|m|mm|b|bn|million|billion|thousand)?\b", re.I)
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s?%")
_NUM = re.compile(r"(?<![\w$.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\w%])")
_MULT = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}


def _money_values(text):
    out = set()
    for num, unit in _MONEY.findall(text):
        try:
            v = float(num.replace(",", "")) * _MULT.get((unit or "").lower(), 1)
        except ValueError:
            continue
        out.add(round(v, -3) if v >= 1e4 else v)
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(million|billion)\b", text, re.I):
        v = float(m.group(1)) * _MULT[m.group(2).lower()]
        out.add(round(v, -3))
    return out


def numbers_in(text):
    money = _money_values(text)
    pct = {float(x) for x in _PCT.findall(text)}
    plain = set()
    stripped = _MONEY.sub(" ", _PCT.sub(" ", text))
    for x in _NUM.findall(stripped):
        with contextlib.suppress(ValueError):
            plain.add(float(x.replace(",", "")))
    return money, pct, plain


def fact_check(tailored_text, source_texts, allowed=()):
    """Numbers in the tailored resume that appear in none of the sources. `allowed` adds numbers
    that are true but derived (e.g. years of experience from date ranges). Returns list of strings."""
    src = "\n".join(source_texts)
    sm, sp, sn = numbers_in(src)
    tm, tp, tn = numbers_in(tailored_text)
    missing = []
    for v in sorted(tm - sm):
        missing.append(f"${v:,.0f}")
    for v in sorted(tp - sp):
        missing.append(f"{v:g}%")
    for v in sorted(tn - sn - sp - {x for x in sm} - {float(a) for a in allowed if a is not None}):
        if v in (0, 1, 2) or (1900 <= v <= 2100 and str(int(v)) in src):
            continue
        missing.append(f"{v:g}")
    return missing


def read_sources(paths):
    texts = []
    for p in paths:
        p = Path(p)
        if not p.exists():
            continue
        if p.suffix.lower() in (".pdf", ".docx"):
            from .candidate import read_resume_text
            texts.append(read_resume_text(p))
        else:
            texts.append(p.read_text(encoding="utf-8", errors="ignore"))
    return texts
