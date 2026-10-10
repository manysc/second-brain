"""TF-IDF implementation of the topic ranker's lexical signal (scikit-learn)."""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def _normalize_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1, norms)


class TfidfDescriptionIndex:
    def __init__(self, vectorizer, topic_docs: np.ndarray) -> None:
        self._vectorizer = vectorizer
        self._topic_docs = topic_docs

    def similarities(self, texts: Sequence[str]) -> np.ndarray:
        return _normalize_rows(self._vectorizer.transform(list(texts)).toarray()) @ self._topic_docs.T


def build_tfidf_description_index(topic_descriptions: Sequence[Sequence[str]]) -> TfidfDescriptionIndex | None:
    """One document vector per topic (the sum of its items' normalized TF-IDF rows). None when there are no
    descriptions, or every description is stop-words only and so there is no vocabulary to match on."""
    from sklearn.feature_extraction.text import (
        TfidfVectorizer,  # lazy: fitting is only needed with data
    )

    corpus = [d for descriptions in topic_descriptions for d in descriptions if d.strip()]
    if not corpus:
        return None
    vectorizer = TfidfVectorizer(sublinear_tf=True, stop_words="english", ngram_range=(1, 2))
    try:
        vectorizer.fit(corpus)
    except ValueError:
        return None
    docs = np.zeros((len(topic_descriptions), len(vectorizer.vocabulary_)))
    for i, descriptions in enumerate(topic_descriptions):
        if descriptions:
            rows = _normalize_rows(vectorizer.transform(list(descriptions)).toarray())
            docs[i] = rows.sum(axis=0)
    return TfidfDescriptionIndex(vectorizer, _normalize_rows(docs))
