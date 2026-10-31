"""Vector math over item embeddings: cosine similarity, topic centroids and the closest candidates."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

import numpy as np


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def centroid(vectors: Iterable[Sequence[float] | np.ndarray | None]) -> np.ndarray | None:
    """Mean embedding, ignoring missing vectors; None when there is nothing to average."""
    present = [np.array(vector) for vector in vectors if vector is not None]
    return np.mean(present, axis=0) if present else None


def topic_centroids(
    embeddings_by_topic: Mapping[str, Iterable[Sequence[float] | np.ndarray | None]],
) -> dict[str, np.ndarray]:
    """Mean embedding per topic, skipping topics with no embedded items."""
    centroids: dict[str, np.ndarray] = {}
    for topic_id, vectors in embeddings_by_topic.items():
        mean = centroid(vectors)
        if mean is not None:
            centroids[topic_id] = mean
    return centroids


def most_similar(
    target: np.ndarray | None,
    candidates: Mapping[str, np.ndarray | None],
    min_similarity: float,
    limit: int,
) -> list[tuple[str, float]]:
    """(id, similarity) of the candidates closest to `target`, most similar first. Candidates without a
    centroid are skipped; a missing target matches nothing."""
    if target is None:
        return []
    scored: list[tuple[str, float]] = []
    for candidate_id, vector in candidates.items():
        if vector is None:
            continue
        score = cosine_similarity(target, vector)
        if score >= min_similarity:
            scored.append((candidate_id, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:limit]


def similar_pairs(
    centroids: Mapping[str, np.ndarray], min_similarity: float, limit: int
) -> list[tuple[str, str, float]]:
    """Every pair of centroids at least `min_similarity` alike, most similar first."""
    ids = list(centroids.keys())
    pairs: list[tuple[str, str, float]] = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            score = cosine_similarity(centroids[ids[i]], centroids[ids[j]])
            if score >= min_similarity:
                pairs.append((ids[i], ids[j], score))
    pairs.sort(key=lambda pair: pair[2], reverse=True)
    return pairs[:limit]
