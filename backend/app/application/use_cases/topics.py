"""Topic use cases: browse, create, rename, close, delete, merge - and the advisory suggestions (related
topics, merge candidates, topics for uncategorized items) that never move data without a human decision."""
from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from app.application.dtos import (
    ItemTopicSuggestionDTO,
    RelatedTopicDTO,
    TopicCandidateDTO,
    TopicDTO,
    TopicMergeSuggestionDTO,
)
from app.application.interfaces.repositories import UnitOfWorkFactory
from app.application.interfaces.services import IdGenerator, ImageStore
from app.application.services import assembler
from app.application.services.priority_recalculation import PriorityRecalculator
from app.application.services.topic_ranker_cache import TopicRankerCache
from app.domain.entities.knowledge_item import KnowledgeItem
from app.domain.entities.topic import Topic
from app.domain.exceptions import InvalidTopicMerge, TopicNameConflict, TopicNotFound
from app.domain.policies import PROPOSAL_HINT_SIMILARITY
from app.domain.services import similarity
from app.domain.services.topic_ranking import DEFAULT_CANDIDATES, confidence_band

logger = logging.getLogger(__name__)


def delete_stored_images(images: ImageStore, keys: list[str]) -> None:
    """Best-effort: a failed delete leaves an unreferenced object, which is preferable to failing the request."""
    for key in keys:
        try:
            images.delete(key)
        except Exception:
            logger.warning("could not delete image object %s from storage", key, exc_info=True)


@dataclass(frozen=True)
class ListTopics:
    uow: UnitOfWorkFactory

    def __call__(self) -> list[TopicDTO]:
        """All persisted topics, including ones with zero items."""
        with self.uow() as uow:
            topics, items_by_topic = assembler.load_topics(uow)
            return [assembler.topic_dto(topic, items_by_topic[topic.id]) for topic in topics]


@dataclass(frozen=True)
class GetTopic:
    uow: UnitOfWorkFactory

    def __call__(self, topic_id: str) -> TopicDTO:
        with self.uow() as uow:
            topic = uow.topics.get(topic_id)
            if topic is None:
                raise TopicNotFound(topic_id)
            return assembler.load_topic_dto(uow, topic)


@dataclass(frozen=True)
class CreateTopic:
    uow: UnitOfWorkFactory
    ids: IdGenerator

    def __call__(self, name: str) -> TopicDTO:
        with self.uow() as uow:
            if uow.topics.get_by_name(name) is not None:
                raise TopicNameConflict(name)
            topic = Topic(id=self.ids.new_id(), name=name)
            uow.topics.add(topic)
            uow.commit()
            return assembler.topic_dto(topic, [])


@dataclass(frozen=True)
class RenameTopic:
    uow: UnitOfWorkFactory

    def __call__(self, topic_id: str, name: str) -> TopicDTO:
        with self.uow() as uow:
            topic = uow.topics.get(topic_id)
            if topic is None:
                raise TopicNotFound(topic_id)
            holder = uow.topics.get_by_name(name)
            if holder is not None and holder.id != topic_id:
                raise TopicNameConflict(name)
            topic.rename(name)
            uow.topics.save(topic)
            items = uow.items.list_by_topic(topic_id)
            for item in items:
                # the theme is a denormalized copy of the topic name
                item.follow_topic_rename(name)
                uow.items.save(item)
            uow.commit()
            return assembler.topic_dto(topic, items)


@dataclass(frozen=True)
class SetTopicStatus:
    uow: UnitOfWorkFactory

    def __call__(self, topic_id: str, status: str) -> TopicDTO:
        with self.uow() as uow:
            topic = uow.topics.get(topic_id)
            if topic is None:
                raise TopicNotFound(topic_id)
            topic.set_status(status)
            uow.topics.save(topic)
            uow.commit()
            return assembler.load_topic_dto(uow, topic)


@dataclass(frozen=True)
class DeleteTopic:
    uow: UnitOfWorkFactory
    images: ImageStore

    def __call__(self, topic_id: str) -> None:
        with self.uow() as uow:
            topic = uow.topics.get(topic_id)
            if topic is None:
                raise TopicNotFound(topic_id)
            topic.ensure_deletable(uow.items.count_by_topic(topic_id))
            image_keys = [image.key for image in topic.images]
            uow.topics.delete(topic)
            uow.commit()
        delete_stored_images(self.images, image_keys)


@dataclass(frozen=True)
class MergeTopics:
    """Moves every item, note and image out of the source topic into the target, then deletes the now-empty
    source (backs drag-and-drop merging, e.g. "Uncategorized" onto a topic)."""

    uow: UnitOfWorkFactory
    recalculator: PriorityRecalculator

    def __call__(self, source_topic_id: str, target_topic_id: str) -> TopicDTO:
        # a self-merge is rejected before anything is looked up, whether or not the topic exists
        if source_topic_id == target_topic_id:
            raise InvalidTopicMerge()
        with self.uow() as uow:
            source = uow.topics.get(source_topic_id)
            target = uow.topics.get(target_topic_id)
            if source is None or target is None:
                raise TopicNotFound(source_topic_id if source is None else target_topic_id)
            source.ensure_can_merge_into(target)
            uow.topics.merge(source, target)
            uow.commit()

        self.recalculator.recalculate_topics({target_topic_id}, trigger="topic_merge")
        with self.uow() as uow:
            merged = uow.topics.get(target_topic_id)
            assert merged is not None
            return assembler.load_topic_dto(uow, merged)


@dataclass(frozen=True)
class GetRelatedTopics:
    """Topics whose items are semantically closest on average to the given topic's, most similar first.
    Excludes "Uncategorized" (a catch-all whose centroid isn't meaningful) and topics with no embedded items."""

    uow: UnitOfWorkFactory

    def __call__(
        self, topic_id: str, min_similarity: float = PROPOSAL_HINT_SIMILARITY, limit: int = 5
    ) -> list[RelatedTopicDTO]:
        with self.uow() as uow:
            topics, items_by_topic = assembler.load_topics(uow)
        return related_topics(topics, items_by_topic, topic_id, min_similarity, limit)


def all_topic_centroids(
    topics: Sequence[Topic], items_by_topic: Mapping[str, Sequence[KnowledgeItem]]
) -> dict[str, np.ndarray]:
    return similarity.topic_centroids(
        {topic.id: [item.embedding for item in items_by_topic[topic.id]] for topic in topics}
    )


def related_topics(
    topics: Sequence[Topic],
    items_by_topic: Mapping[str, Sequence[KnowledgeItem]],
    topic_id: str,
    min_similarity: float = PROPOSAL_HINT_SIMILARITY,
    limit: int = 5,
    centroids: Mapping[str, np.ndarray] | None = None,
) -> list[RelatedTopicDTO]:
    by_id = {topic.id: topic for topic in topics}
    if topic_id not in by_id:
        raise TopicNotFound(topic_id)
    if centroids is None:
        centroids = all_topic_centroids(topics, items_by_topic)
    candidates = {
        topic.id: centroids.get(topic.id) for topic in topics if topic.id != topic_id and not topic.is_uncategorized
    }
    return [
        RelatedTopicDTO(
            id=other_id,
            name=by_id[other_id].name,
            status=by_id[other_id].status,
            similarity=score,
            item_count=len(items_by_topic[other_id]),
        )
        for other_id, score in similarity.most_similar(centroids.get(topic_id), candidates, min_similarity, limit)
    ]


@dataclass(frozen=True)
class SuggestTopicMerges:
    """Flags pairs of topics whose items are semantically close on average, for a human to review and merge -
    never merges automatically. Excludes "Uncategorized" (a heterogeneous catch-all with its own drag-to-merge
    flow), topics with no embedded items, and topics that already have `max_related_items` or more items
    (large, already-established topics don't need further consolidation suggestions)."""

    uow: UnitOfWorkFactory

    def __call__(
        self, min_similarity: float = 0.5, limit: int = 10, max_related_items: int = 5
    ) -> list[TopicMergeSuggestionDTO]:
        with self.uow() as uow:
            topics, items_by_topic = assembler.load_topics(uow)
        small = [
            topic for topic in topics if not topic.is_uncategorized and len(items_by_topic[topic.id]) < max_related_items
        ]
        dtos = {topic.id: assembler.topic_dto(topic, items_by_topic[topic.id]) for topic in small}
        centroids = similarity.topic_centroids(
            {topic.id: [item.embedding for item in items_by_topic[topic.id]] for topic in small}
        )
        return [
            TopicMergeSuggestionDTO(topic_a=dtos[a], topic_b=dtos[b], similarity=score)
            for a, b, score in similarity.similar_pairs(centroids, min_similarity, limit)
        ]


@dataclass(frozen=True)
class SuggestItemTopics:
    """Per-item counterpart to SuggestTopicMerges: for each item still sitting in "Uncategorized", ranks the
    existing topics it most likely belongs to (best first, with a confidence band), for a human to review and
    confirm via the normal move-item flow - never assigns automatically."""

    uow: UnitOfWorkFactory
    rankers: TopicRankerCache

    def __call__(
        self, min_score: float = 0.0, limit: int | None = None, candidates: int = DEFAULT_CANDIDATES
    ) -> list[ItemTopicSuggestionDTO]:
        with self.uow() as uow:
            topics, items_by_topic = assembler.load_topics(uow)
            uncategorized = next((topic for topic in topics if topic.is_uncategorized), None)
            if uncategorized is None or not items_by_topic[uncategorized.id]:
                return []
            ranker = self.rankers.get(uow)
        names = {topic.id: (topic.name, len(items_by_topic[topic.id])) for topic in topics}
        embedded = [item for item in items_by_topic[uncategorized.id] if item.embedding is not None]
        ranked = ranker.rank_many([item.embedding for item in embedded], [item.description for item in embedded], candidates)
        # the cached ranker can see a topic created/deleted after the topics were read - skip unknown ones
        ranked = [[r for r in best if r.topic_id in names] for best in ranked]

        suggestions = [
            ItemTopicSuggestionDTO(
                item=assembler.item_dto(item, uncategorized),
                candidates=tuple(
                    TopicCandidateDTO(
                        topic_id=r.topic_id,
                        topic_name=names[r.topic_id][0],
                        item_count=names[r.topic_id][1],
                        score=r.score,
                        centroid_similarity=r.centroid_similarity,
                    )
                    for r in best
                ),
                score=best[0].score,
                confidence=confidence_band(best[0].score),
            )
            for item, best in zip(embedded, ranked)
            if best and best[0].score >= min_score
        ]
        suggestions.sort(key=lambda suggestion: suggestion.score, reverse=True)
        return suggestions if limit is None else suggestions[:limit]
