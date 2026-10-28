"""Is the ranking any good? Measure it against your own judgment, and suggest better weights.

1. `job-hunter labels` writes results/labels.csv from the last run with an empty `label` column.
2. Fill it in: 2 = would apply, 1 = maybe, 0 = no. Label at least 30 jobs, ideally 50+.
3. `job-hunter eval-rank` reports:
     precision@10  share of the top 10 you'd apply to (label 2) or consider (1 counts half)
     ndcg@10       how close the top 10's order is to the best possible order (1.0 = perfect)
   and, with --tune, searches weight combinations and shows the best few.
"""
from __future__ import annotations

import itertools
import math

import pandas as pd

PARTS = ["fit", "seniority", "location", "pay", "freshness"]
PART_COLS = {"fit": "fit", "seniority": "seniority", "location": "location_score", "pay": "pay_score",
             "freshness": "freshness"}


SHEET_COLS = ["job_url", "title", "company", "location", "fit", "seniority", "location_score", "pay_score",
              "freshness"]


def clean_labels(series) -> pd.Series:
    """'2', '2.0', ' 1 ' -> '2', '2', '1'; anything else -> ''."""
    def one(x):
        try:
            v = int(float(str(x).strip()))
        except ValueError:
            return ""
        return str(v) if v in (0, 1, 2) else ""
    return series.map(one)


def make_label_sheet(ranked: pd.DataFrame, n=60, existing: pd.DataFrame | None = None) -> pd.DataFrame:
    """A sheet to label. Keeps every job's part scores, so it still works after later searches.
    With `existing`, labeled rows are kept and only jobs not already on the sheet are added."""
    fresh = ranked[[c for c in SHEET_COLS if c in ranked]].head(n).copy()
    fresh.insert(0, "label", "")
    if existing is not None and len(existing):
        fresh = fresh[~fresh["job_url"].isin(existing["job_url"])]
        sheet = pd.concat([existing, fresh], ignore_index=True)
    else:
        sheet = fresh
    # shuffle the order so the current ranking doesn't sway your labels
    return sheet.sample(frac=1, random_state=7).reset_index(drop=True)


def _gains(labels):
    return [{2: 1.0, 1: 0.5}.get(int(x), 0.0) for x in labels]


def precision_at(labels_in_rank_order, k=10):
    g = _gains(labels_in_rank_order[:k])
    return sum(g) / max(1, min(k, len(g)))


def ndcg_at(labels_in_rank_order, k=10):
    def dcg(xs):
        return sum((2 ** x - 1) / math.log2(i + 2) for i, x in enumerate(xs[:k]))
    rel = [int(x) for x in labels_in_rank_order]
    ideal = dcg(sorted(rel, reverse=True))
    return dcg(rel) / ideal if ideal else 0.0


def score_with(df: pd.DataFrame, weights: dict, low_fit_threshold=40.0) -> pd.Series:
    tot = sum(weights.values()) or 1
    s = sum(df[PART_COLS[k]].astype(float) * w for k, w in weights.items()) / tot
    fit = df["fit"].astype(float)
    penalty = (0.6 + 0.4 * fit / low_fit_threshold).where(fit < low_fit_threshold, 1.0)
    return s * penalty


def evaluate(ranked: pd.DataFrame | None, labels: pd.DataFrame, weights: dict, k=10, low_fit_threshold=40.0):
    """Uses the part scores saved in the label sheet; falls back to ranked.csv for older sheets."""
    labels = labels.assign(label=clean_labels(labels["label"]))
    lab = labels[labels["label"] != ""]
    if all(c in lab for c in PART_COLS.values()):
        df = lab.copy()
    elif ranked is not None:
        df = ranked.merge(lab[["job_url", "label"]], on="job_url", how="inner")
    else:
        return None
    if df.empty:
        return None
    df = df.assign(_s=score_with(df, weights, low_fit_threshold)).sort_values("_s", ascending=False)
    order = df["label"].astype(int).tolist()
    return {"labeled": len(df), "precision@10": round(precision_at(order, k), 3),
            "ndcg@10": round(ndcg_at(order, k), 3), "apply_in_top10": order[:k].count(2)}


def tune(ranked, labels, low_fit_threshold=40.0, step=10, top=5):
    """Grid search over weights summing to 100 in `step` increments. Returns best combos."""
    results = []
    vals = range(0, 101, step)
    for combo in itertools.product(vals, repeat=len(PARTS)):
        if sum(combo) != 100:
            continue
        w = dict(zip(PARTS, combo, strict=True))
        r = evaluate(ranked, labels, w, low_fit_threshold=low_fit_threshold)
        if r:
            results.append((r["ndcg@10"], r["precision@10"], w))
    results.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return results[:top]
