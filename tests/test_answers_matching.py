"""Answer-matching regressions: a wrong match is worse than a miss."""
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jobhunter.answers import AnswerBank, blocked  # noqa: E402


@pytest.fixture
def bank(tmp_path):
    shutil.copy(ROOT / "answers.example.yaml", tmp_path / "answers.yaml")
    return AnswerBank(tmp_path / "answers.yaml")


SHOULD_MATCH = {
    "Are you legally authorized to work in the United States?": "Yes",
    "Do you require sponsorship?": "No",
    "Do you now, or will you in the future, require sponsorship for employment visa status?": "No",
    "Are you willing to relocate?": "Yes, to New York or Denver",
    "Desired salary": "$135,000 base, flexible depending on the full package",
    "Compensation expectations": "$135,000 base, flexible depending on the full package",
    "Email address": "jordan.rivera@example.com",
    "Current email": "jordan.rivera@example.com",
    "Mobile phone": "(312) 555-0199",
    "First name": "Jordan",
    "Last name": "Rivera",
    "City": "Chicago",
    "State": "IL",
    "LinkedIn profile URL": "https://linkedin.com/in/jordan-rivera-example",
}
SHOULD_MISS = [
    "Are you authorized to work in the UK?",
    "Are you authorized to work in the United Kingdom?",
    "Will you require visa sponsorship to work in Canada?",
    "Are you willing to relocate to London?",
    "Are you unwilling to relocate?",
    "Years of CRE sales experience",
    "Years of residential underwriting experience",
    "What is your current salary?",
    "What was your last salary?",
    "Reference email address",
    "Hiring manager email",
    "Emergency contact phone",
    "First name of reference",
    "Last name of your supervisor",
    "School city",
    "Velocity",
    "What is your capacity?",
    "Are you willing to travel?",
]
BLOCKED = ["Military status", "Have you served in the armed forces?", "LGBTQ+", "Date of Birth", "dob",
           "drivers_license", "bank_routing_number", "tax_id_number", "Gender", "Race/Ethnicity",
           "Protected veteran status", "Disability status", "Social Security Number", "Password"]


@pytest.mark.parametrize("q,expected", SHOULD_MATCH.items())
def test_matches(bank, q, expected):
    hit = bank.match(q)
    assert hit is not None, q
    assert hit["answer"] == expected


@pytest.mark.parametrize("q", SHOULD_MISS)
def test_misses(bank, q):
    assert bank.match(q) is None, (q, bank.match(q))


@pytest.mark.parametrize("q", BLOCKED)
def test_blocked(bank, q):
    assert blocked(q)
    assert bank.match(q) is None
    assert bank.add(q, "something")[0] is False
    assert bank.set_fact(q, "something")[0] is False


def test_not_blocked_false_positives():
    for q in ["Swift", "PIN pad experience?", "Are you at least 18 years of age?", "Years of experience"]:
        assert blocked(q) is None, q


def test_empty_rejected(bank):
    assert bank.add("", "")[0] is False
    assert bank.add("Question", "")[0] is False
    assert bank.set_fact("", "x")[0] is False


@pytest.mark.parametrize("q", ["When were you born?", "Birthday", "What is your age?", "National Insurance number",
                               "Enter the verification code we sent", "Username", "Religion", "Marital status",
                               "Have you been convicted of a felony?", "A-Number"])
def test_more_never_stored(bank, q):
    assert blocked(q) and bank.add(q, "x")[0] is False


def test_minimum_salary_and_work_email_not_reused(bank):
    assert bank.match("What's your minimum salary?") is None
    assert bank.match("Work email") is None


# Security review 2026-10: rewordings, other languages and lookalike letters must not slip past.
@pytest.mark.parametrize("q,a", [
    ("Are you disabled?", "Yes"), ("What is your racial background?", "x"), ("Have you served in the military?", "Yes"),
    ("Are you gay, lesbian or bisexual?", "No"), ("Sexe", "F"), ("Geschlecht", "x"), ("Género", "x"),
    ("Raza / etnia", "x"), ("Behinderung", "nein"), ("Gеnder", "Woman"), ("Year of birth", "1985"), ("Age", "40"),
    ("SS#", "x"), ("S.S.N.", "x"), ("DL number", "x"), ("CPF", "x"), ("Bank details for payroll", "x"),
    ("Place of birth", "x"), ("Male or female?", "x"), ("Nationality", "x"), ("Fecha de nacimiento", "x"),
    ("Anything else?", "123456789"), ("Anything else?", "123 45 6789"), ("Notes", "DE89370400440532013000"),
])
def test_reworded_never_stored(bank, q, a):
    assert blocked(q, a), (q, a)
    assert bank.add(q, a)[0] is False


@pytest.mark.parametrize("q,a", [("Mobile phone", "3125550199"), ("Zip", "20003-1234"), ("Phone", "+1 312 555 0199"),
                                 ("Summary", "FY24 revenue grew 20 percent"), ("Are you a US citizen?", "Yes")])
def test_ordinary_answers_still_saved(q, a):
    assert blocked(q, a) is None


def test_negated_question_does_not_overwrite(bank):
    q = "Are you legally authorized to work in the United States?"
    assert bank.match(q)["answer"] == "Yes"
    bank.add("Are you not legally authorized to work in the United States?", "No")
    assert bank.match(q)["answer"] == "Yes"
