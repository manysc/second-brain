"""Ranks existing topics for an item that has none yet (Uncategorized items, pending review
candidates, new-topic proposals).

Scoring is a hybrid of four signals, each in 0..1:

    centroid  cosine similarity between the item and the topic's mean item embedding
    knn       the topic's share of (positive) similarity among the item's nearest categorized items
    name      fraction of the topic's distinctive name/tag tokens that appear in the item's text
    tfidf     lexical cosine between the item's text and the topic's item descriptions - only mixed
              in when no topic centroid reaches DESCRIPTION_MATCH_GATE, i.e. when embeddings alone
              are unsure

Kept DB-free (plain vectors and strings in, ranked topic ids out) so it can be unit-tested and
calibrated without a database (see backend/tests/test_topic_suggestions.py).

Calibration (leave-one-out over 777 categorized items, all-MiniLM-L6-v2): the correct topic ranks
first ~67% of the time and within the top 3 ~85%, vs 62% / 80% for the centroid-only match this
replaced. Larger embedding models (bge-base/large, gte-base) scored within ~1 point, so the gain
comes from the scoring, not the model.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal, Sequence

import numpy as np

SuggestionConfidence = Literal["HIGH", "MEDIUM", "LOW"]

KNN_NEIGHBOURS = 10
DEFAULT_CANDIDATES = 3
# best-centroid similarity below which item descriptions (TF-IDF) join the score
DESCRIPTION_MATCH_GATE = 0.6
# a name/tag token shared by this many topics ("strategy", "engine", ...) doesn't identify any of them
SHARED_TOKEN_TOPIC_COUNT = 3
_STOPWORDS = frozenset({"the", "and", "for", "with", "from"})

_EMBEDDING_WEIGHTS = (0.5, 0.35, 0.15)  # centroid, knn, name
_WITH_DESCRIPTION_WEIGHTS = (0.4, 0.3, 0.1, 0.2)  # centroid, knn, name, tfidf

# score bands, calibrated on the same leave-one-out run: the top suggestion was the right topic
# ~91% of the time in the HIGH band, ~84% in MEDIUM and ~50% in LOW (right topic in the top 3: 98%,
# 94%, 76%)
HIGH_CONFIDENCE_SCORE = 0.60
MEDIUM_CONFIDENCE_SCORE = 0.50


@dataclass(frozen=True)
class TopicProfile:
    topic_id: str
    name: str
    tags: Sequence[str] = ()
    item_embeddings: Sequence[Sequence[float]] = ()
    item_descriptions: Sequence[str] = ()


@dataclass(frozen=True)
class RankedTopic:
    topic_id: str
    score: float
    centroid_similarity: float


def confidence_band(score: float) -> SuggestionConfidence:
    if score >= HIGH_CONFIDENCE_SCORE:
        return "HIGH"
    if score >= MEDIUM_CONFIDENCE_SCORE:
        return "MEDIUM"
    return "LOW"


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3 and w not in _STOPWORDS}


def _normalize_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1, norms)


class TopicRanker:
    """Built from every candidate topic, then ranks any number of items. data._load_topic_ranker
    reuses one instance across requests (and threads) until the topics/items change, so it must stay
    read-only after __init__. Topics with no embedded items are skipped - there is nothing to compare
    against."""

    def __init__(self, profiles: Sequence[TopicProfile]) -> None:
        usable = [p for p in profiles if len(p.item_embeddings)]
        self._ids = [p.topic_id for p in usable]
        self._vectorizer = None
        self._topic_docs: np.ndarray | None = None
        if not usable:
            return
        stacks = [_normalize_rows(np.asarray(p.item_embeddings, dtype=float)) for p in usable]
        self._items = np.vstack(stacks)
        self._item_topic = np.concatenate([np.full(len(s), i) for i, s in enumerate(stacks)])
        self._centroids = _normalize_rows(np.vstack([s.mean(axis=0) for s in stacks]))

        token_sets = [_tokens(" ".join([p.name, *p.tags])) for p in usable]
        topic_count = Counter(w for tokens in token_sets for w in tokens)
        self._name_patterns = [
            [re.compile(rf"\b{re.escape(w)}") for w in sorted(tokens) if topic_count[w] < SHARED_TOKEN_TOPIC_COUNT]
            for tokens in token_sets
        ]
        self._fit_descriptions(usable)

    def _fit_descriptions(self, usable: list[TopicProfile]) -> None:
        from sklearn.feature_extraction.text import TfidfVectorizer

        corpus = [d for p in usable for d in p.item_descriptions if d.strip()]
        if not corpus:
            return
        vectorizer = TfidfVectorizer(sublinear_tf=True, stop_words="english", ngram_range=(1, 2))
        try:
            vectorizer.fit(corpus)
        except ValueError:  # every description was stop-words only - no vocabulary to match on
            return
        docs = np.zeros((len(usable), len(vectorizer.vocabulary_)))
        for i, profile in enumerate(usable):
            if profile.item_descriptions:
                rows = _normalize_rows(vectorizer.transform(profile.item_descriptions).toarray())
                docs[i] = rows.sum(axis=0)
        self._vectorizer = vectorizer
        self._topic_docs = _normalize_rows(docs)

    def rank(self, vector: Sequence[float], text: str, top_n: int = DEFAULT_CANDIDATES) -> list[RankedTopic]:
        return self.rank_many([vector], [text], top_n)[0]

    def rank_many(
        self, vectors: Sequence[Sequence[float]], texts: Sequence[str], top_n: int = DEFAULT_CANDIDATES
    ) -> list[list[RankedTopic]]:
        """Best `top_n` topics per item, highest score first."""
        if not self._ids or not len(vectors):
            return [[] for _ in vectors]
        queries = _normalize_rows(np.asarray(vectors, dtype=float))
        centroid_sims = queries @ self._centroids.T
        item_sims = queries @ self._items.T
        tfidf = None
        if self._vectorizer is not None and self._topic_docs is not None:
            tfidf = _normalize_rows(self._vectorizer.transform(list(texts)).toarray()) @ self._topic_docs.T

        k = min(KNN_NEIGHBOURS, len(self._items))
        results: list[list[RankedTopic]] = []
        for row, text in enumerate(texts):
            centroid = centroid_sims[row]
            nearest = np.argpartition(-item_sims[row], k - 1)[:k]
            votes = np.bincount(
                self._item_topic[nearest], weights=np.clip(item_sims[row][nearest], 0, None), minlength=len(self._ids)
            )
            knn = votes / votes.sum() if votes.sum() > 0 else votes
            lowered = text.lower()
            name = np.array(
                [
                    sum(1 for p in patterns if p.search(lowered)) / len(patterns) if patterns else 0.0
                    for patterns in self._name_patterns
                ]
            )
            if tfidf is not None and centroid.max() < DESCRIPTION_MATCH_GATE:
                wc, wk, wn, wt = _WITH_DESCRIPTION_WEIGHTS
                score = wc * centroid + wk * knn + wn * name + wt * tfidf[row]
            else:
                wc, wk, wn = _EMBEDDING_WEIGHTS
                score = wc * centroid + wk * knn + wn * name
            order = np.argsort(-score)[:top_n]
            results.append([RankedTopic(self._ids[i], float(score[i]), float(centroid[i])) for i in order])
        return results
