"""Legacy import path: the ranker now lives in app.domain.services.topic_ranking, with its TF-IDF signal in
app.infrastructure. Kept until the remaining callers move to the application layer."""
from __future__ import annotations

from typing import Sequence

from app.domain.services import topic_ranking as _ranking
from app.domain.services.topic_ranking import (  # noqa: F401  (re-exported)
    DEFAULT_CANDIDATES,
    DESCRIPTION_MATCH_GATE,
    HIGH_CONFIDENCE_SCORE,
    KNN_NEIGHBOURS,
    MEDIUM_CONFIDENCE_SCORE,
    SHARED_TOKEN_TOPIC_COUNT,
    RankedTopic,
    SuggestionConfidence,
    TopicProfile,
    confidence_band,
)
from app.infrastructure.external_services.tfidf_description_index import build_tfidf_description_index


class TopicRanker(_ranking.TopicRanker):
    """The domain ranker wired with the TF-IDF description index, as before the split."""

    def __init__(self, profiles: Sequence[TopicProfile]) -> None:
        super().__init__(profiles, build_tfidf_description_index)
