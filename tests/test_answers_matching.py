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
