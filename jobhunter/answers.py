"""Answer bank: application answers you've given once, reused on the next application.

Lives in answers.yaml (gitignored). Two parts:
  facts:    simple fields every form asks for (name, email, phone, address, links)
  answers:  question -> answer pairs, matched on meaning-bearing words, so "Do you require
            sponsorship?" finds "Will you now or in the future require visa sponsorship?"

Never stored, whatever the source:
  - ID and account numbers (SSN, driver's license, passport, bank/card numbers) and passwords
  - date of birth
  - EEO / voluntary self-identification answers (race, ethnicity, gender, orientation, veteran or
    military status, disability). Those are answered by the person, fresh, on every application.

Matching is deliberately strict: a question that adds a country, city, negation, skill or another
person ("reference email") doesn't reuse an answer. A miss means you get asked; a wrong match
would put a wrong answer on an application.
"""
import datetime as dt
import difflib
import re
from pathlib import Path

import yaml

from .common import norm
from .fileio import write_text_atomic

BLOCK_ID = re.compile(
    r"social security|\bssn\b|\bsin\b|driver'?s?\s+licen[cs]e|passport|government[- ]issued id|national id|"
    r"tax id|\bitin\b|\btin\b|routing number|account number|acct\.? ?(no|number|#)|bank account|\biban\b|"
    r"swift (code|bic)|credit card|debit card|card number|\bcvv\b|\bcvc\b|password|passcode|\bpin\b(?!\s*pad)|"
    r"security question|mother'?s maiden|date of birth|birth ?date|\bdob\b|\bborn\b|birthday|how old are you|"
    r"what is your age|your age\b|national insurance|\bnino?\b|social insurance|alien (registration )?number|"
    r"\ba number\b(?! of| between| from| to)|uscis|aadhaa?r|\bpan card\b|medicare|medicaid|health insurance (number|id)|member id|"
    r"verification code|one[- ]time (code|password|passcode)|\botp\b|security code|access code|username|user name|"
    r"login (id|name)|\bpasscode\b", re.I)
BLOCK_EEO = re.compile(
    r"\brace\b|ethnic|hispanic|latin[oax]|gender|\bsex\b|sexual orientation|transgender|\blgbt|queer|pronoun|"
    r"veteran|military status|armed forces|military service|disabilit|self[- ]identif|"
    r"voluntary (self|disclosure)|\beeo\b|equal employment|affirmative action|\bofccp\b|religio|faith|"
    r"marital|married|spouse'?s? name|pregnan|maternity|national origin|citizenship of|caste|criminal|"
    r"arrest|convicted|conviction|felony|union member|political", re.I)
BLOCK_VALUE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\b(?:\d[ -]?){13,19}\b")  # SSN or card-like number

MATCH_THRESHOLD = 0.85
_FILLER = re.compile(r"\b(please|kindly|do you|are you|have you|will you|would you|can you|you|your|the|a|an|"
                     r"currently|now|ever|of|in|to|for|this|position|role|job|company|what|is|are|desired|"
                     r"expected|expectations?|requirements?|preferred|provide|enter|indicate|specify|"
                     r"how|many|much|or|will|future|be|at|on|with|by|any|if|so|yes|no)\b")
_SYNONYMS = {"compensation": "salary", "pay": "salary", "wage": "salary", "wages": "salary",
             "relocation": "relocate", "sponsor": "sponsorship", "authorised": "authorized", "e": "",
             "mail": "email", "telephone": "phone", "mobile": "phone", "cell": "phone", "surname": "last",
             "family": "last", "given": "first", "zipcode": "zip", "postal": "zip", "url": "", "profile": "",
             "address": "", "number": ""}
# Words a question may carry that a saved answer doesn't, without changing its meaning.
_GENERIC = {"legally", "eligible", "eligibility", "employment", "status", "visa", "work", "working", "united",
            "states", "u", "s", "usa", "america", "american", "need", "require", "required", "experience",
            "years", "year", "total", "relevant", "professional", "field", "industry", "salary",
            "base", "annual", "expectation", "expectations", "range", "start", "date", "earliest", "available",
            "availability", "notice", "period", "hear", "heard", "about", "learn", "find", "highest", "level",
            "education", "degree", "completed", "obtained", "willing", "open", "able", "authorized", "full",
            "name", "legal", "preferred", "email", "phone"}
# Words that mean the question is about someone or something else, so a personal fact doesn't fit.
_OTHER_PARTY = {"reference", "references", "referee", "manager", "supervisor", "emergency", "spouse", "partner",
                "employer", "school", "university", "college", "company", "recruiter", "referrer", "referred",
                "referral", "parent", "guardian", "relative", "friend", "colleague", "hiring", "previous", "former",
                "work", "business", "office", "corporate", "alternate", "secondary", "other"}
_NEGATIONS = {"not", "never", "unwilling", "unable", "unauthorized", "without", "cannot", "dont", "don"}


def blocked(question, answer=""):
    """Reason string if this Q/A must not be saved, else None."""
    q = re.sub(r"[_\-]+", " ", str(question or ""))
    if BLOCK_ID.search(q):
        return "ID or account number, login, code, birth date or age question"
    if BLOCK_EEO.search(q):
        return "EEO, self-identification or other protected-information question (answer it yourself each time)"
    if BLOCK_VALUE.search(str(answer or "")):
        return "answer looks like an ID or card number"
    return None


def _tokens(q):
    words = _FILLER.sub(" ", norm(q)).split()
    return [w for w in (_SYNONYMS.get(w, w) for w in words) if w]


def _key(q):
    return " ".join(_tokens(q))


def similarity(a, b):
    ka, kb = _key(a), _key(b)
    if not ka or not kb:
        return 0.0
    seq = difflib.SequenceMatcher(None, ka, kb).ratio()
    ta, tb = set(ka.split()), set(kb.split())
    tok = len(ta & tb) / max(1, len(ta | tb))
    contain = len(ta & tb) / max(1, min(len(ta), len(tb)))
    return max(seq, 0.5 * tok + 0.5 * contain if min(len(ta), len(tb)) >= 2 else tok)


def compatible(question, saved):
    """False when the new question says something the saved one doesn't: another country or city,
    a negation, another skill or field. A miss is cheap; a wrong answer on an application isn't."""
    qt, st = set(_tokens(question)), set(_tokens(saved))
    extra = qt - st
    if extra & _NEGATIONS or (st & _NEGATIONS) - qt:
        return False
    return not (extra - _GENERIC)


class AnswerBank:
    def __init__(self, path: Path):
        self.path = Path(path)
        data: dict = {}
        if self.path.exists():
            data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        self.facts = data.get("facts", {}) or {}
        self.answers = data.get("answers", []) or []

    def save(self):
        header = ("# answers.yaml - saved application answers, reused across applications.\n"
                  "# Private: gitignored. Never put ID numbers, account numbers, passwords or EEO answers here.\n")
        body = yaml.safe_dump({"facts": self.facts, "answers": self.answers}, sort_keys=False, allow_unicode=True, width=1000)
        write_text_atomic(self.path, header + body, private=True)

    def match(self, question):
        """Best saved answer for a question: dict(question, answer, score, source) or None."""
        if blocked(question) or not str(question or "").strip():
            return None
        best, best_s = None, 0.0
        for a in self.answers:
            for q in [a.get("question", "")] + list(a.get("aliases", []) or []):
                if not compatible(question, q):
                    continue
                s = similarity(question, q)
                if set(_tokens(q)) and set(_tokens(q)) <= set(_tokens(question)):
                    s = max(s, 0.9)  # every meaning word of the saved question is here; extras are generic
                if s > best_s:
                    best, best_s = a, s
        # Simple facts ("First name", "Email address", "LinkedIn profile URL"): whole-word match only,
        # and never when the question is about someone else ("Reference email", "Supervisor phone").
        qt = set(_tokens(question))
        if not (set(norm(question).split()) & _OTHER_PARTY):
            for field, val in self.facts.items():
                ft = set(_tokens(field.replace("_", " ")))
                allowed_extra = _GENERIC | {"current", "home", "primary", "personal", "linkedin", "website",
                                            "portfolio", "github"}
                if ft and ft <= qt and not (qt - ft - allowed_extra):
                    s = 0.95 if qt == ft else 0.9
                    if s > best_s:
                        best, best_s = {"question": field, "answer": val, "source": "facts"}, s
        if best and best_s >= MATCH_THRESHOLD:
            return {**best, "score": round(best_s, 2)}
        return None

    def add(self, question, answer, source="you", alias_of=None):
        """Save an answer. Returns (saved: bool, message)."""
        if not str(question or "").strip() or not str(answer or "").strip():
            return False, "not saved: question and answer are both required"
        reason = blocked(question, answer)
        if reason:
            return False, f"not saved: {reason}"
        today = dt.date.today().isoformat()
        existing = None
        for a in self.answers:
            if similarity(question, a.get("question", "")) >= 0.92 or (alias_of and a.get("question") == alias_of):
                existing = a
                break
        if existing:
            if existing.get("question") != question and question not in (existing.get("aliases") or []):
                existing.setdefault("aliases", []).append(question)
            existing.update({"answer": answer, "source": source, "updated": today})
            self.save()
            return True, f"updated: {existing['question']}"
        self.answers.append({"question": question, "answer": answer, "aliases": [], "source": source, "updated": today})
        self.save()
        return True, "added"

    def set_fact(self, field, value):
        if not str(field or "").strip() or not str(value or "").strip():
            return False, "not saved: field and value are both required"
        reason = blocked(field, value)
        if reason:
            return False, f"not saved: {reason}"
        self.facts[field] = value
        self.save()
        return True, f"fact {field} saved"
