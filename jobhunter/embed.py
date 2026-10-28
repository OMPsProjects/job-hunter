"""Optional: compare job titles by meaning with TechWolf's JobBERT-v3 model (MIT license,
huggingface.co/TechWolf/JobBERT-v3), so 'Mortgage Underwriter' counts as close to 'Credit
Underwriter' even though only one word matches.

Install with `pip install -e ".[ml]"` (about 2 GB with PyTorch; the model itself is ~1.1 GB and
downloads from Hugging Face on first use). Without it, ranking uses word overlap only. Turn it off
with `ranking.title_model: off` in profile.yaml.
"""
from __future__ import annotations

import functools
import threading

from .logs import log

MODEL = "TechWolf/JobBERT-v3"
# JobBERT cosine scores run from about 0.1 (unrelated) to 0.9 (same job). Mapped onto 0..1 so they
# sit on the same scale as the word-overlap score they're combined with.
LOW, HIGH = 0.2, 0.85

_lock = threading.Lock()
_state: dict = {"model": None, "failed": False}


def available() -> bool:
    try:
        import sentence_transformers  # noqa: F401
        import torch  # noqa: F401
    except Exception:
        return False
    return True


def _model():
    with _lock:
        if _state["model"] is None and not _state["failed"]:
            try:
                from sentence_transformers import SentenceTransformer
                log.info("Loading the job-title model (first time: ~1 GB download)...")
                _state["model"] = SentenceTransformer(MODEL, device="cpu")
            except Exception as e:
                _state["failed"] = True
                log.warning(f"title model unavailable, using word overlap only ({e})")
        return _state["model"]


def _encode(model, texts):
    import numpy as np
    import torch
    from sentence_transformers.util import batch_to_device
    out = []
    for i in range(0, len(texts), 32):
        batch = texts[i:i + 32]
        tok = getattr(model, "preprocess", None) or model.tokenize
        features = batch_to_device(tok(batch), model.device)
        features["text_keys"] = ["anchor"]  # JobBERT-v3 has separate heads; titles use 'anchor'
        with torch.no_grad():
            emb = model.forward(features)["sentence_embedding"].cpu().numpy()
        out.append(emb / np.linalg.norm(emb, axis=1, keepdims=True))
    return np.concatenate(out) if out else np.zeros((0, 1024))


class TitleSimilarity:
    """Similarity (0..1) between job titles and your titles, computed in one batch."""

    def __init__(self, your_titles, job_titles):
        self.ok = False
        self.scores: dict = {}
        model = _model()
        if model is None or not your_titles or not job_titles:
            return
        try:
            mine = list(dict.fromkeys(str(t) for t in your_titles))
            jobs = list(dict.fromkeys(str(t) for t in job_titles))
            a, b = _encode(model, mine), _encode(model, jobs)
            sims = b @ a.T
            for title, row in zip(jobs, sims, strict=True):
                self.scores[title] = scale(float(row.max()))
            self.ok = True
        except Exception as e:
            log.warning(f"title model failed, using word overlap only ({e})")

    def get(self, title):
        return self.scores.get(str(title))


def scale(cos: float) -> float:
    return max(0.0, min(1.0, (cos - LOW) / (HIGH - LOW)))


@functools.lru_cache(maxsize=1)
def wanted(setting) -> bool:
    """profile ranking.title_model: 'auto' (use it if installed, the default), 'on', or 'off'."""
    s = str(setting).lower()
    if s in ("off", "false", "no", "0"):
        return False
    if s in ("on", "true", "yes", "1") and not available():
        log.warning('ranking.title_model is on but the model isn\'t installed: pip install -e ".[ml]"')
    return available()
