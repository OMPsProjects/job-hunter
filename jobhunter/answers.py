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
import unicodedata
from pathlib import Path

import yaml

from .common import fold_lookalikes, norm
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
# The lists above miss rewordings and other languages, and the employer writes the question.
# These catch the common ones; the rule stays "when in doubt, don't save".
BLOCK_ID_MORE = re.compile(
    r"\bss ?#|\bs ?s ?n\b|\bsocial sec|\bsocial insurance|year of birth|birth ?year|\bbirth\b|"
    r"^\s*(your |current )?age\s*[:?*]?\s*$|\bage (range|group|bracket)\b|\byour age|\bcurrent age|"
    r"\bd\.? ?l\.? ?(number|no|#)|driving licen|driver licen|"
    r"identity (card|number|document)|\bid (card|number|no\b|#)|\bidentification (number|no|#)|"
    r"\bcpf\b|\bdni\b|\bnie\b|\bnif\b|\bcurp\b|\brfc\b|\bpesel\b|\bbsn\b|personnummer|codice fiscale|"
    r"tax (file|identification|reference) number|\bsort code\b|bank (details|info|information|name and)|"
    r"direct deposit|"
    r"fecha de nacimiento|date de naissance|data di nascita|geburtsdatum|\bedad\b|\bâge\b|\bwie alt\b|"
    r"seguro social|seguridad social|s[ée]curit[ée] sociale|sozialversicherung|steuer ?id|"
    r"pasaporte|passeport|reisepass|f[üu]hrerschein|permis de conduire|licencia de conducir", re.I)
BLOCK_EEO_MORE = re.compile(
    r"disab|handicap|impairment|\bracial|\bracially|ancestry|heritage|\bethni|"
    r"\bserved\b.*\b(military|armed|army|navy|air force|marines?|coast guard|forces)\b|\bmilitary\b|"
    r"\bgay\b|lesbian|bisexual|heterosexual|asexual|\btrans\b|non ?binary|intersex|\bsexual|"
    r"\bmale\b|\bfemale\b|man or (a )?woman|woman or (a )?man|\bnationality|"
    r"\bsexe\b|\bgenre\b|geschlecht|g[ée]nero|\braza\b|\betnia\b|\bethnie\b|ethnizit|behinderung|"
    r"discapacidad|minusval|religi[oó]n|confession|orientaci[oó]n|orientation sexuelle|"
    r"\bestado civil\b|situation familiale|familienstand", re.I)
BLOCK_VALUE = re.compile(
    r"\b\d{3}([ -]?)\d{2}\1\d{4}\b"   # SSN, with or without dashes/spaces
    r"|\b(?:\d[ -]?){13,19}\b")       # card-like number
BLOCK_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}\b")  # case-sensitive on purpose

def _canon(s):
    """Text as a person reads it: no invisible characters, lookalikes folded, S.S.N. -> SSN."""
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = "".join(ch for ch in s if unicodedata.category(ch) not in ("Cf", "Mn", "Cc") or ch in "\n\t")
    s = fold_lookalikes(s)
    s = re.sub(r"(?<=\b[A-Za-z])\.(?=[A-Za-z]\b)", "", s)   # S.S.N. -> SSN., D.L. -> DL.
    return re.sub(r"[_\-]+", " ", s)

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
    q = _canon(question)
    if BLOCK_ID.search(q) or BLOCK_ID_MORE.search(q):
        return "ID or account number, login, code, birth date or age question"
    if BLOCK_EEO.search(q) or BLOCK_EEO_MORE.search(q):
        return "EEO, self-identification or other protected-information question (answer it yourself each time)"
    a = _canon(answer).replace(".", " ")
    if BLOCK_VALUE.search(a) or BLOCK_IBAN.search(a):
        return "answer looks like an ID, card or bank account number"
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
            if blocked(a.get("question", ""), a.get("answer", "")):
                continue  # saved by an older version before the check caught this wording: never reuse it
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
            names = [a.get("question", "")] + list(a.get("aliases") or [])
            # Same rule as match(): a question that adds a negation, country or skill is a different
            # question, so it gets its own entry instead of overwriting this one.
            same = any(similarity(question, n) >= 0.92 and compatible(question, n) and compatible(n, question)
                       for n in names)
            if same or (alias_of and a.get("question") == alias_of):
                existing = a
                break
        if existing:
            before = existing.get("answer")
            if existing.get("question") != question and question not in (existing.get("aliases") or []):
                existing.setdefault("aliases", []).append(question)
            existing.update({"answer": answer, "source": source, "updated": today})
            self.save()
            changed = f" (was: {before})" if before not in (None, answer) else ""
            return True, f"updated: {existing['question']}{changed}"
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
