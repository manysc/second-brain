"""Local text embeddings (no external API key required).

Prefers sentence-transformers' all-MiniLM-L6-v2 for real semantic embeddings. If the model
weights can't be downloaded (e.g. a blocked network), falls back to a deterministic offline
hashing vectorizer so the pgvector pipeline still works end-to-end; it upgrades to the real
model automatically once it becomes reachable - no code change needed.
"""
from __future__ import annotations

import sys
from functools import lru_cache

from app.db_models import EMBEDDING_DIM

MODEL_NAME = "all-MiniLM-L6-v2"


class _HashingFallback:
    """Deterministic offline stand-in - NOT a real semantic embedding, only keeps the storage
    and similarity-query plumbing exercisable while the real model is unreachable."""

    def __init__(self, dim: int) -> None:
        from sklearn.feature_extraction.text import HashingVectorizer

        self._vectorizer = HashingVectorizer(n_features=dim, alternate_sign=False, norm="l2")

    def encode(self, texts: list[str], **_kwargs):
        return self._vectorizer.transform(texts).toarray()


@lru_cache(maxsize=1)
def _model():
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(MODEL_NAME)
    except Exception as exc:  # network/model-download failure - degrade gracefully
        print(
            f"warning: could not load '{MODEL_NAME}' ({exc.__class__.__name__}: {exc}); "
            "falling back to offline hashing embeddings",
            file=sys.stderr,
        )
        return _HashingFallback(EMBEDDING_DIM)


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    vectors = _model().encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    return vectors.tolist()

