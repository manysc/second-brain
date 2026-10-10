"""Local text embeddings (no external API key required).

Prefers sentence-transformers' all-MiniLM-L6-v2 for real semantic embeddings. If the model
weights can't be downloaded (e.g. a blocked network), falls back to a deterministic offline
hashing vectorizer so the pgvector pipeline still works end-to-end; it upgrades to the real
model automatically once it becomes reachable - no code change needed.
"""
from __future__ import annotations

import sys
import threading
from collections import OrderedDict
from functools import lru_cache

from app.infrastructure.persistence.orm_models import EMBEDDING_DIM

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


# Memo keyed by the exact text: the review page re-embeds every pending candidate on each load and
# accepting one embeds its description again, so repeat texts skip the model entirely.
_CACHE_SIZE = 4096
_cache: OrderedDict[str, list[float]] = OrderedDict()
_cache_lock = threading.Lock()


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    found: dict[str, list[float]] = {}
    with _cache_lock:
        for text in texts:
            if text in _cache:
                _cache.move_to_end(text)
                found[text] = _cache[text]
    misses = list(dict.fromkeys(text for text in texts if text not in found))
    if misses:
        vectors = _model().encode(misses, convert_to_numpy=True, normalize_embeddings=True).tolist()
        found.update(zip(misses, vectors))
        with _cache_lock:
            for text, vector in zip(misses, vectors):
                _cache[text] = vector
                _cache.move_to_end(text)
            while len(_cache) > _CACHE_SIZE:
                _cache.popitem(last=False)
    # copies, so a caller mutating its result can't corrupt the cached vector
    return [list(found[text]) for text in texts]



class SentenceTransformerEmbedder:
    """The application's Embedder port, backed by this module's cached model and memo."""

    def embed_text(self, text: str) -> list[float]:
        return embed_text(text)

    def embed_texts(self, texts) -> list[list[float]]:
        return embed_texts(list(texts))
