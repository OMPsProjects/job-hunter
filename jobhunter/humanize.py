"""Resume lint: catches the words and patterns that make a resume read as AI-written, and numbers
that don't appear anywhere in your source material (a sign something was invented).

This is the mechanical half of humanizing. The skill always applies the humanizer
(github.com/blader/humanizer, bundled as skills/job-hunter/references/humanizer.md) first, and a
separate reviewer scores the draft after. This check catches what's left.
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


# Phrases from two MIT-licensed lists of AI-writing tells: the humanizer skill (bundled in
# skills/job-hunter/references/humanizer.md, by Siqi Chen) and stop-slop (Hardik Pandya,
# github.com/hardikpandya/stop-slop). See THIRD_PARTY_NOTICES.md. Errors: rewrite the line.
TELLS = {
    # stock AI words (humanizer §12)
    "enhance": "say what improved, and by how much", "enhanced": "say what improved", "enhancing": "AI tell",
    "garner": "AI tell", "garnered": "say 'got' or 'won'", "intricate": "AI tell", "bolstered": "AI tell",
    "interplay": "AI tell", "vibrant": "AI tell", "showcase": "AI tell", "showcased": "AI tell",
    "underscore": "AI tell", "additionally": "AI tell; just say it", "deep dive": "jargon",
    "enduring": "AI tell", "align with": "AI tell", "aligns with": "AI tell",
    # sales language and inflated significance (humanizer §13, §16)
    "nestled": "sales language", "in the heart of": "sales language", "renowned": "sales language",
    "breathtaking": "sales language", "stunning": "sales language", "diverse array": "sales language",
    "commitment to excellence": "sales language", "plays a key role": "inflated; say what it does",
    "stands as": "say 'is'", "boasts": "say 'has'", "the future looks bright": "send-off; end on a fact",
    "exciting times": "send-off; end on a fact", "setting the stage for": "inflated significance",
    # run-ups, throat-clearing and emphasis crutches (humanizer §4, stop-slop)
    "here's the thing": "throat-clearing; state the point", "here's why": "throat-clearing",
    "here's what": "throat-clearing", "the truth is": "throat-clearing", "the reality is": "throat-clearing",
    "let me be clear": "throat-clearing", "it turns out": "throat-clearing", "let's dive": "run-up",
    "without further ado": "run-up", "make no mistake": "emphasis crutch", "let that sink in": "emphasis crutch",
    "full stop": "emphasis crutch", "at its core": "filler", "it's worth noting": "filler",
    "at the end of the day": "filler", "when it comes to": "filler", "in a world where": "filler",
    "the stakes are high": "vague; name the stake", "the implications are significant": "vague; name it",
    # business jargon (stop-slop)
    "lean into": "jargon", "double down": "jargon", "circle back": "jargon", "moving forward": "jargon",
    "game changer": "jargon", "unpack": "jargon",
    # chatbot residue (humanizer §22)
    "i hope this helps": "chatbot residue", "great question": "chatbot residue", "certainly!": "chatbot residue",
}
# Intensifiers: one is fine; a few in one document reads machine-made (stop-slop's adverb list).
INTENSIFIERS = ("truly", "genuinely", "deeply", "incredibly", "honestly", "literally", "fundamentally",
                "inherently", "simply", "really")
# "Not X but Y" and its variants (humanizer §1): weight without a claim.
CONTRAST = [
    re.compile(r"\bnot\s+(?:just|only|merely|simply)\b[^.;!?]{0,80}?\bbut\b", re.I),
    re.compile(r"\b(?:it'?s|this is|that'?s|this was|it was)\s+not\s+(?:about\s+)?[^.;!?]{1,50}[,;]\s*"
               r"(?:it'?s|this is|that'?s|it was|but)\b", re.I),
    re.compile(r"\b(?:isn'?t|wasn'?t|is not|was not)\s+(?:just\s+)?(?:about\s+)?[^.;!?]{1,50}\.\s+(?:it'?s|it is|it was)\b", re.I),
]


def _find(word, text):
    return [m.start() for m in re.finditer(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", text, re.I)]


def lint_text(text, bullets=None):
    """Returns list of (level, message). level is 'error' or 'warn'."""
    issues = []
    for w, why in BANNED.items():
        n = len(_find(w, text))
        if n:
            issues.append(("error", f"'{w}' x{n}: {why}"))
    for w, why in TELLS.items():
        n = len(_find(w, text))
        if n:
            issues.append(("error", f"'{w}' x{n}: {why}"))
    for rx in CONTRAST:
        for m in rx.finditer(text):
            issues.append(("error", f"'not X but Y' contrast: \"{m.group(0)[:60]}\": state Y directly"))
    hits = sum(len(_find(w, text)) for w in INTENSIFIERS)
    if hits >= 3:
        issues.append(("warn", f"{hits} intensifiers (truly, deeply, really...): cut most of them"))
    for w, why in WARN.items():
        n = len(_find(w, text))
        if n >= 2:
            issues.append(("warn", f"'{w}' x{n}: {why}"))
    if "—" in text:
        issues.append(("error", f"em dash x{text.count('—')}: use a comma, colon or period"))
    en = len(re.findall(r"(?<!\d)\s*–\s*(?!\d)", text))  # 2019–2022 is a range; anything else is a dash
    if en:
        issues.append(("error", f"en dash x{en} used as a dash: use a comma, colon or period"))
    if re.search(r"\s--\s", text):
        issues.append(("error", "double hyphen used as a dash: use a comma, colon or period"))
    if "!" in text:
        issues.append(("error", "exclamation mark"))
    if re.search(r"(?m)^\s*[-•*]?\s*I\b", text):
        issues.append(("warn", "bullet starts with 'I'"))
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


LETTER_OPENERS = re.compile(
    r"^\s*(i am writing to (express|apply)|i am (excited|thrilled|eager) to apply|please accept (this|my) "
    r"(letter|application)|i would like to (express|apply)|it is with (great )?(enthusiasm|excitement))", re.I)


def lint_letter(paragraphs):
    """Cover-letter checks on top of lint_text: length, and openers every reader has seen before."""
    paras = [str(x) for x in paragraphs or [] if str(x).strip()]
    text = "\n".join(paras)
    issues = [i for i in lint_text(text) if "bullet starts with" not in i[1]]  # letters may start with 'I'
    words = len(text.split())
    if words > 300:
        issues.append(("warn", f"{words} words: keep a cover letter under 300"))
    if len(paras) > 5:
        issues.append(("warn", f"{len(paras)} paragraphs: 3 or 4 is plenty"))
    if paras and LETTER_OPENERS.search(paras[0]):
        issues.append(("error", "stock opening line: start with why this job, or what you did that fits it"))
    starts_i = sum(1 for p in paras if re.match(r"\s*I\b", p))
    if starts_i >= 3:
        issues.append(("warn", f"{starts_i} paragraphs start with 'I'"))
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


# ----------------------------- shape check (slop-guard) ---------------------
# The scoring engine of slop-guard (MIT, Eric Tramel; copied into jobhunter/vendor/slop_guard)
# looks at the shape of the writing, not just words: sentences all the same length, tidy lists of
# three, "X. But Y." setups, one-line closers, repeated phrases, colon and dash habits. Its
# markdown rules (bullet/blockquote/bold/horizontal-rule density) are left out: they'd flag every
# resume. Findings are warnings with the engine's own advice. Its 0-100 score is shown only for
# texts long enough for it to mean something: on a 100-word letter, one hit drops it to single
# digits.

_SHAPE_SKIP = {"BulletDensityRule", "BlockquoteDensityRule", "BoldTermBulletRunRule",
               "HorizontalRuleOveruseRule", "IntrasentenceKeywordBoldRule"}
_SHAPE_SKIP_RESUME = _SHAPE_SKIP | {"ParagraphBalanceRule", "ParagraphCVRule"}  # bullets aren't paragraphs
SHAPE_SCORE_MIN_WORDS = 300
_pipelines: dict = {}


def _shape_pipeline(kind):
    if kind not in _pipelines:
        from .vendor.slop_guard.rules.pipeline import Pipeline
        skip = _SHAPE_SKIP_RESUME if kind == "resume" else _SHAPE_SKIP
        full = Pipeline.from_jsonl()
        _pipelines[kind] = Pipeline([r for r in full.rules if type(r).__name__ not in skip])
    return _pipelines[kind]


def resume_prose(summary, bullets):
    """A resume as the shape check should read it: the summary, then each bullet as a sentence."""
    parts = [str(summary or "").strip()]
    for b in bullets or []:
        b = str(b).strip()
        if b:
            parts.append(b if b.endswith((".", "!", "?")) else b + ".")
    return "\n".join(p for p in parts if p)


def shape_check(text, kind="letter"):
    """dict(score, band, words, issues=[(level, message)]). score is None when the text is too
    short for it to mean anything. Never raises: a broken check must not block a resume."""
    try:
        from .vendor.slop_guard.engine import analyze_text
        out = analyze_text(str(text or ""), pipeline=_shape_pipeline(kind))
    except Exception as e:  # pragma: no cover - defensive
        return {"score": None, "band": None, "words": 0, "issues": [("warn", f"shape check didn't run: {e}")]}
    seen, issues = set(), []
    for v in out["violations"]:
        key = (v["rule"], v["match"])
        if key in seen:
            continue
        seen.add(key)
        ctx = " ".join(str(v.get("context") or "").split())[:90]
        issues.append(("warn", f"shape: {v['rule'].replace('_', ' ')} ({v['match']}): {ctx}"))
    issues += [("warn", f"shape advice: {a}") for a in out["advice"][:6]]
    long_enough = out["word_count"] >= SHAPE_SCORE_MIN_WORDS
    return {"score": out["score"] if long_enough else None, "band": out["band"] if long_enough else None,
            "words": out["word_count"], "issues": issues}
