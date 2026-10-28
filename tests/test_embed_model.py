"""The real JobBERT title model. Slow and a ~1 GB download, so it only runs with
JOBHUNTER_TEST_MODEL=1 and the [ml] extra installed."""
import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("JOBHUNTER_TEST_MODEL") != "1", reason="set JOBHUNTER_TEST_MODEL=1")


def test_jobbert_orders_titles_sensibly(monkeypatch):
    pytest.importorskip("sentence_transformers")
    from jobhunter import embed
    monkeypatch.setattr(embed, "available", lambda: True)
    sim = embed.TitleSimilarity(["Commercial Real Estate Underwriter"],
                                ["Mortgage Underwriter", "Real Estate Credit Analyst", "Backend Developer", "Barista"])
    assert sim.ok
    s = sim.scores
    assert s["Mortgage Underwriter"] > 0.8
    assert s["Real Estate Credit Analyst"] > 0.6
    assert s["Backend Developer"] < 0.1 and s["Barista"] < 0.1
