"""Read a resume's text into what setup needs: your city, your jobs (title, employer, dates),
your skills, your level and years. No AI: patterns that fit how most resumes are laid out.
Setup shows every result for you to check, so a miss costs a click, not a bad search.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from .candidate import LEVELS, guess_contact, guess_years, title_level
from .common import US_STATE_CODES

_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE = rf"(?:{_MONTH}\s*'?\d{{2,4}}|\d{{1,2}}/(?:19|20)?\d{{2}}|(?:19|20)\d{{2}})"
_RANGE = re.compile(rf"({_DATE})\s*(?:-|–|—|to|through|until)\s*({_DATE}|present|current|now|today)", re.I)

_SECTION = re.compile(
    r"^\s*(?:(?P<exp>(?:professional|work|relevant|employment|career)?\s*(?:experience|employment|history|"
    r"background)(?:\s+history)?)|(?P<skills>(?:technical|core|key)?\s*(?:skills|competencies|expertise|"
    r"proficiencies|tools|technologies)(?:\s*(?:&|and)\s*\w+)?)|(?P<other>education|certifications?|licenses?|"
    r"projects|awards|honors|publications|volunteer(?:ing)?|interests|languages|summary|profile|objective|"
    r"affiliations|references|training|activities))\s*:?\s*(?P<rest>.*)$", re.I)

_TITLE_WORDS = re.compile(
    r"\b(analyst|associate|manager|director|president|vp|officer|underwriter|engineer|developer|specialist|"
    r"coordinator|consultant|lead|head|chief|partner|principal|intern|assistant|administrator|advisor|adviser|"
    r"accountant|nurse|teacher|designer|architect|scientist|representative|executive|supervisor|technician|"
    r"attorney|counsel|banker|broker|originator|staff|operator|agent|controller|auditor|economist|editor|writer|"
    r"producer|planner|strategist|recruiter|therapist|physician|pharmacist|paralegal|clerk|cashier|driver|"
    r"mechanic|electrician|founder|owner|member|fellow|researcher|instructor|professor|programmer|tester|"
    r"marketer|buyer|trader|actuary|appraiser|estimator|superintendent|foreman|chef|cook|server|"
    r"sr\.?|senior|junior|jr\.?)\b", re.I)
_COMPANY_WORDS = re.compile(
    r"\b(inc|llc|l\.l\.c|ltd|corp|corporation|company|co|bank|capital|group|partners|holdings|financial|"
    r"university|college|hospital|health|school|lp|llp|plc|trust|fund|associates|services|solutions|"
    r"technologies|systems|labs|agency|department|foundation)\b\.?", re.I)
_BULLET = re.compile(r"^\s*(?:[-•·*▪●◦‣–]|\d+[.)])\s+")
_STATES = "|".join(sorted(US_STATE_CODES, key=len, reverse=True))
# 'Washington, DC', 'Austin, TX 78701', 'Washington, D.C.'
_CITY = re.compile(rf"\b([A-Z][A-Za-z.'\- ]{{1,30}}?),\s*((?:{_STATES})|D\.C\.)(?=\b|\s|$)(?:\s+\d{{5}})?", re.I)


def _clean(s: str) -> str:
    s = re.sub(r"\(\s*\)|\[\s*\]", " ", str(s or ""))  # brackets left empty once dates or a city are removed
    return re.sub(r"\s+", " ", s).strip(" ,|•·-–—()\t")


def _nice_city(city: str) -> str:
    return city.title() if city.isupper() or city.islower() else city


def find_city(lines: list[str]) -> str:
    """Your city from the contact lines at the top ('Washington, DC 20500' -> 'Washington, DC')."""
    for ln in lines[:12]:
        if _RANGE.search(ln):
            continue
        for m in _CITY.finditer(ln):
            st = m.group(2).upper().replace(".", "")
            if st.lower() not in US_STATE_CODES:
                continue
            # 'Lead Underwriter | Washington' style lines: keep the part after the last separator
            city = re.split(r"\s[|•·]\s|\s{2,}", _clean(m.group(1)))[-1]
            if 1 <= len(city.split()) <= 4 and not _TITLE_WORDS.search(city) and "@" not in city:
                return f"{_nice_city(city)}, {st}"
    return ""


def _strip_location(s: str) -> str:
    s = _CITY.sub("", s)
    return _clean(re.sub(r"\b(remote|hybrid|on-?site)\b", "", s, flags=re.I))


def _is_title(s: str) -> bool:
    return bool(_TITLE_WORDS.search(s)) and not _COMPANY_WORDS.search(s) and len(s.split()) <= 10


def _sections(lines: list[str]):
    """{name: [lines]} for experience and skills, with any text after a header ('Skills: Excel')."""
    out: dict[str, list[str]] = {"exp": [], "skills": []}
    current = None
    for ln in lines:
        m = _SECTION.match(ln)
        short = len(re.sub(r"[^A-Za-z]", "", ln.split(":")[0])) <= 40
        if m and short and (ln.strip().isupper() or ln.strip().endswith(":") or ":" in ln
                            or len(ln.split()) <= 4):
            current = "exp" if m.group("exp") else "skills" if m.group("skills") else None
            if current and m.group("rest").strip():
                out[current].append(m.group("rest"))
            continue
        if current:
            out[current].append(ln)
    return out


def find_jobs(lines: list[str]) -> list[dict]:
    """[{title, company, start, end, current}] from the experience section, most recent first."""
    exp = _sections(lines)["exp"] or lines
    jobs = []
    for i, ln in enumerate(exp):
        m = _RANGE.search(ln)
        if not m or _BULLET.match(ln):
            continue
        rest = _strip_location(ln[:m.start()] + " " + ln[m.end():])
        parts = [p for p in (_clean(x) for x in re.split(r"\s+[|•·]\s+|\s+[—–]\s+|\s+-\s+|\s{2,}|\bat\b", rest)) if p]
        near = []
        for j in (i + 1, i - 1, i + 2):
            if 0 <= j < len(exp):
                cand = exp[j]
                if cand.strip() and not _BULLET.match(cand) and not _RANGE.search(cand) and len(cand.split()) <= 12:
                    near.append(_strip_location(cand))
        near = [n for n in near if n]
        title = next((p for p in parts + near if _is_title(p)), "")
        company = next((p for p in parts + near if p != title and not _is_title(p)), "")
        # 'Senior Underwriter, Acme Bank' on one line: split it only when the part after the comma
        # looks like an employer, or nothing else on or near the line does
        if not title:
            for p in parts:
                if "," in p:
                    a, b = (_clean(x) for x in p.split(",", 1))
                    if _is_title(a) and not _is_title(b):
                        title = a
                        if not company or _COMPANY_WORDS.search(b):
                            company = b
                        break
        elif title in parts and "," in title and not company:
            a, b = (_clean(x) for x in title.split(",", 1))
            if _is_title(a) and not _is_title(b):
                title, company = a, b
        if not title:
            continue
        end = m.group(2)
        jobs.append({"title": title, "company": company, "start": _clean(m.group(1)), "end": _clean(end),
                     "current": not re.search(r"\d", end)})
    # most recent first: current jobs, then by end year
    def year(s):
        y = re.findall(r"(?:19|20)\d{2}", s)
        return int(y[-1]) if y else 9999
    jobs.sort(key=lambda j: (not j["current"], -year(j["end"])))
    return jobs


@lru_cache(maxsize=1)
def _known_skills() -> tuple:
    """Skill names from the occupation data, to recognize skills written anywhere in a resume."""
    try:
        from .occupations import _load
        occ, _, _ = _load()
        names = {s for o in occ.values() for s in o.get("s", []) if 2 < len(s) < 40}
        return tuple(sorted(names, key=len, reverse=True))
    except Exception:
        return ()


def find_skills(lines: list[str], text: str) -> list[str]:
    """The skills section's items, then known skill names found anywhere in the resume."""
    out: list[str] = []
    for ln in _sections(lines)["skills"]:
        ln = _BULLET.sub("", ln)
        if ":" in ln and len(ln.split(":")[0].split()) <= 3:  # 'Technical: Excel, Argus'
            ln = ln.split(":", 1)[1]
        for item in re.split(r"[,;|•·/]|\s{2,}|\band\b", ln):
            item = _clean(item).strip(".")
            if 2 <= len(item) <= 40 and len(item.split()) <= 5 and not re.search(r"\d{4}", item):
                out.append(item)
    low = text.lower()
    for s in _known_skills():
        if re.search(rf"(?<![\w]){re.escape(s.lower())}(?![\w])", low):
            out.append(s)
    seen, uniq = set(), []
    for s in out:
        k = s.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(s)
    return uniq[:40]


def parse_resume(text: str) -> dict:
    lines = [ln.rstrip() for ln in str(text or "").splitlines()]
    lines = [ln for ln in lines if ln.strip()]
    jobs = find_jobs(lines)
    titles = list(dict.fromkeys(j["title"] for j in jobs))
    employers = list(dict.fromkeys(j["company"] for j in jobs if j["company"]))
    lvl = title_level(titles[0]) if titles else None
    return {
        "name": _nice_city(guess_contact(text).get("name", "")),
        "city": find_city(lines),
        "jobs": jobs,
        "titles": titles,
        "current_employers": list(dict.fromkeys(j["company"] for j in jobs if j["current"] and j["company"])),
        "employers": employers,
        "skills": find_skills(lines, text),
        "level": LEVELS[lvl] if lvl is not None else "",
        "years_experience": guess_years(text),
    }


def parse_resume_file(path: Path) -> dict:
    from .candidate import read_resume_text
    return parse_resume(read_resume_text(Path(path)))
