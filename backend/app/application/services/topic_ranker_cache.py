from __future__ import annotations

import threading

from app.application.interfaces.repositories import UnitOfWork
from app.domain.services.topic_ranking import DescriptionIndexFactory, TopicRanker


class TopicRankerCache:
    """Building the ranker (every topic's items plus fitting the description index) takes over a second, and
    one review page render needs it twice - so the last one built is reused until the data it was built from
    changes. One instance is shared by every use case that ranks topics."""

    def __init__(self, description_index_factory: DescriptionIndexFactory | None = None) -> None:
        self._description_index_factory = description_index_factory
        self._cached: tuple[str, TopicRanker] | None = None
        self._lock = threading.Lock()

    def get(self, uow: UnitOfWork) -> TopicRanker:
        version = uow.topics.ranking_version()
        # held while building, so concurrent requests wait for one build instead of each doing their own
        with self._lock:
            if self._cached is not None and self._cached[0] == version:
                return self._cached[1]
            ranker = TopicRanker(uow.topics.ranking_profiles(), self._description_index_factory)
            self._cached = (version, ranker)
            return ranker

    def clear(self) -> None:
        with self._lock:
            self._cached = None
