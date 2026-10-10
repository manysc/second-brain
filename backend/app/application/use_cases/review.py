"""Human review: extracted candidates stay pending until a person accepts or rejects them, and proposed
topics are only created when a person says so."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.application.dtos import KnowledgeItemDTO, ReviewCandidateDTO, TopicProposalDTO
from app.application.interfaces.repositories import UnitOfWorkFactory
from app.application.interfaces.services import Embedder, IdGenerator
from app.application.services import assembler
from app.application.services.priority_recalculation import PriorityRecalculator
from app.application.services.topic_ranker_cache import TopicRankerCache
from app.application.services.uncategorized import ensure_uncategorized_topic
from app.domain.entities.knowledge_item import KnowledgeItem
from app.domain.entities.topic import Topic
from app.domain.exceptions import (
    InvalidTopicName,
    ProposalTargetTopicNotFound,
    ReviewCandidateNotFound,
    TopicNotFound,
    TopicProposalNotFound,
)
from app.domain.policies import DUPLICATE_MATCH_THRESHOLD, ITEM_TOPIC_MATCH_SIMILARITY
from app.domain.services import similarity
from app.domain.services.topic_ranking import confident_topic_id
from app.domain.value_objects.status import ReviewStatus


@dataclass(frozen=True)
class ListPendingReview:
    """Candidates still awaiting a decision, newest meeting first. Each carries the best-ranked existing topic
    (when a confident match) to pre-select the review page's topic picker - deliberately looser than the
    strict centroid match applied when a candidate is accepted without a topic, since a human confirms this one."""

    uow: UnitOfWorkFactory
    embedder: Embedder
    rankers: TopicRankerCache

    def __call__(self) -> list[ReviewCandidateDTO]:
        with self.uow() as uow:
            candidates = uow.review_candidates.list_pending()
            if not candidates:
                return []
            descriptions = [candidate.description for candidate in candidates]
            vectors = self.embedder.embed_texts(descriptions)
            ranker = self.rankers.get(uow)
        ranked = ranker.rank_many(vectors, descriptions, top_n=1)
        return [
            assembler.candidate_dto(candidate, suggested_topic_id=confident_topic_id(best))
            for candidate, best in zip(candidates, ranked)
        ]


@dataclass(frozen=True)
class DecideReviewCandidate:
    """Accepts or rejects a pending candidate. `topic_id` only matters when accepting a candidate that isn't a
    duplicate: a topic id files the new item there, "" files it in Uncategorized, and None auto-matches the
    closest existing topic (falling back to Uncategorized). Topics are never created here, except Uncategorized."""

    uow: UnitOfWorkFactory
    embedder: Embedder
    ids: IdGenerator
    recalculator: PriorityRecalculator

    def __call__(self, candidate_id: str, status: ReviewStatus, topic_id: str | None = None) -> ReviewCandidateDTO:
        affected_topic_id: str | None = None
        with self.uow() as uow:
            candidate = uow.review_candidates.get(candidate_id)
            if candidate is None:
                raise ReviewCandidateNotFound(candidate_id)
            candidate.decide(status)

            if status == "ACCEPTED":
                vector = self.embedder.embed_text(candidate.description)
                duplicate = uow.items.find_duplicate(vector, max_distance=DUPLICATE_MATCH_THRESHOLD)
                if duplicate is not None:
                    # merge: a near-duplicate item already exists, so reinforce it instead of duplicating
                    duplicate.reinforce()
                    uow.items.save(duplicate)
                    affected_topic_id = duplicate.topic_id
                else:
                    topic: Topic | None = None
                    if topic_id:
                        topic = uow.topics.get(topic_id)
                        if topic is None:
                            raise TopicNotFound(topic_id)
                    elif topic_id is None:
                        topics, items_by_topic = assembler.load_topics(uow)
                        centroids = similarity.topic_centroids(
                            {
                                t.id: [item.embedding for item in items_by_topic[t.id]]
                                for t in topics
                                if not t.is_uncategorized
                            }
                        )
                        match_id, _ = similarity.closest_topic(np.array(vector), centroids, ITEM_TOPIC_MATCH_SIMILARITY)
                        topic = uow.topics.get(match_id) if match_id else None
                    if topic is None:
                        topic = ensure_uncategorized_topic(uow, self.ids)
                    affected_topic_id = topic.id
                    uow.items.add(
                        KnowledgeItem.from_review_candidate(
                            candidate, topic_id=topic.id, topic_name=topic.name, embedding=vector
                        )
                    )

            uow.review_candidates.save(candidate)
            uow.commit()
            decided = assembler.candidate_dto(candidate)
        if affected_topic_id:
            self.recalculator.recalculate_topics({affected_topic_id}, trigger="review_accepted")
        return decided


@dataclass(frozen=True)
class ListTopicProposals:
    """Groups items awaiting a topic decision by the new-topic name the extractor proposed. Each proposal also
    carries the best-ranked existing topic (when a confident match) as a hint for the reviewer's "use existing
    topic" override."""

    uow: UnitOfWorkFactory
    rankers: TopicRankerCache

    def __call__(self) -> list[TopicProposalDTO]:
        with self.uow() as uow:
            items = uow.items.list_with_proposal()
            if not items:
                return []
            ranker = self.rankers.get(uow)
            topics_by_id = {
                topic.id: topic for topic in uow.topics.list_by_ids(sorted({i.topic_id for i in items if i.topic_id}))
            }
        grouped: dict[str, list[KnowledgeItem]] = {}
        for item in items:
            grouped.setdefault(item.suggested_topic, []).append(item)  # type: ignore[arg-type]
        proposals: list[TopicProposalDTO] = []
        for name, group in grouped.items():
            mean = similarity.centroid(item.embedding for item in group)
            text = " ".join([name, *(item.description for item in group)])
            hint = confident_topic_id(ranker.rank(mean, text, top_n=1)) if mean is not None else None
            proposals.append(
                TopicProposalDTO(
                    name=name, items=assembler.item_dtos(group, topics_by_id), suggested_existing_topic_id=hint
                )
            )
        proposals.sort(key=lambda proposal: (-len(proposal.items), proposal.name))
        return proposals


@dataclass(frozen=True)
class AcceptTopicProposal:
    """Human decision on a proposal: files its items under `existing_topic_id` (override), or under a topic
    named `topic_name` (default: the suggested name), creating that topic only now."""

    uow: UnitOfWorkFactory
    ids: IdGenerator
    recalculator: PriorityRecalculator

    def __call__(
        self, suggested_name: str, topic_name: str | None = None, existing_topic_id: str | None = None
    ) -> list[KnowledgeItemDTO]:
        with self.uow() as uow:
            items = uow.items.list_with_proposal(suggested_name)
            if not items:
                raise TopicProposalNotFound(suggested_name)
            if existing_topic_id is not None:
                target = uow.topics.get(existing_topic_id)
                if target is None:
                    raise ProposalTargetTopicNotFound(existing_topic_id)
            else:
                name = (topic_name or suggested_name).strip()
                if not name:
                    raise InvalidTopicName()
                target = uow.topics.get_by_name(name)
                if target is None:
                    target = Topic(id=self.ids.new_id(), name=name)
                    uow.topics.add(target)
            old_topic_ids = {item.topic_id for item in items}
            for item in items:
                item.accept_proposal(target)
                uow.items.save(item)
            uow.commit()
            filed = [assembler.item_dto(item, target) for item in items]
        self.recalculator.recalculate_topics(old_topic_ids | {target.id}, trigger="topic_proposal_accepted")
        return filed


@dataclass(frozen=True)
class RejectTopicProposal:
    """Dismisses a proposal: its items stay where ingestion put them (Uncategorized)."""

    uow: UnitOfWorkFactory

    def __call__(self, suggested_name: str) -> int:
        """Returns how many items the proposal covered."""
        with self.uow() as uow:
            items = uow.items.list_with_proposal(suggested_name)
            if not items:
                raise TopicProposalNotFound(suggested_name)
            for item in items:
                item.dismiss_proposal()
                uow.items.save(item)
            uow.commit()
            return len(items)
