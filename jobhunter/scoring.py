"""Keyword score (0-100) from the profile's scoring section. This is one input to the ranking."""
import re

import pandas as pd


def count(term: str, text: str) -> int:
    # optional plural "s" so "data centers" / "loans" / "underwriters" still match
    return len(re.findall(r"(?<![a-z0-9])" + re.escape(term) + r"s?(?![a-z0-9])", text))


def score_row(row, p) -> pd.Series:
    title = str(row.get("title", "")).lower()
    desc = str(row.get("description", "")).lower()
    raw, hits = 0.0, []
    for kw, w in p.skills.items():
        in_title = count(kw, title)
        in_desc = min(count(kw, desc), 3)  # cap so long posts don't dominate
        if in_title or in_desc:
            raw += w * (3 * min(in_title, 1) + in_desc * 0.5)  # a title match counts 3x
            hits.append(kw)
    for kw, pen in p.negative.items():
        if count(kw, title) or count(kw, desc[:p.desc_window]):
            raw += pen
    for pattern, pen in p.title_negative.items():
        if re.search(pattern, title):
            raw += pen
    for group in p.required_terms.get(row.get("track"), []):
        if not group.intersection(hits):
            raw += p.missing_required_penalty
    if pd.notna(row.get("max_amount")):  # reward a visible salary, mildly
        raw += p.salary_bonus
    score = max(0, min(100, round(100 * raw / p.max_raw)))
    return pd.Series({"fit_score": score, "matched": ", ".join(hits[:12])})
