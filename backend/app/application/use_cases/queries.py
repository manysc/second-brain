"""Read-only views over the whole knowledge base: meetings, search, the relationship graph and follow-ups."""
from __future__ import annotations

from dataclasses import dataclass

from app.application.dtos import (
    FollowUpDTO,
    FollowUpRelatedItemDTO,
    FollowUpTopicDTO,
    GraphDTO,
    GraphEdgeDTO,
    GraphNodeDTO,
    GraphTopicDTO,
    MeetingDTO,
    SearchResultDTO,
    TopicLinkDTO,
)
from app.application.interfaces.repositories import UnitOfWorkFactory
from app.application.interfaces.services import Clock, Embedder
from app.application.services import assembler
from app.application.use_cases.priority import recent_escalations
from app.application.use_cases.topics import all_topic_centroids, related_topics
from app.domain.entities.knowledge_item import KnowledgeItem
from app.domain.exceptions import MeetingNotFound, NoMeetingsAvailable
from app.domain.services.follow_up import select_follow_ups
from app.domain.services.item_graph import build_item_edges
from app.domain.services.search_ranking import rank_search_hits

ESCALATION_WINDOW_DAYS = 14


@dataclass(frozen=True)
class ListMeetings:
    uow: UnitOfWorkFactory

    def __call__(self) -> list[MeetingDTO]:
        """Every meeting with its items and review candidates, newest first."""
        with self.uow() as uow:
            return assembler.load_meetings(uow)


@dataclass(frozen=True)
class GetMeeting:
    uow: UnitOfWorkFactory

    def __call__(self, meeting_id: str) -> MeetingDTO:
        with self.uow() as uow:
            meeting = next((m for m in assembler.load_meetings(uow) if m.id == meeting_id), None)
        if meeting is None:
            raise MeetingNotFound(meeting_id)
        return meeting


@dataclass(frozen=True)
class GetMostRecentMeeting:
    uow: UnitOfWorkFactory

    def __call__(self) -> MeetingDTO:
        with self.uow() as uow:
            meetings = assembler.load_meetings(uow)
        if not meetings:
            raise NoMeetingsAvailable()
        return meetings[0]


@dataclass(frozen=True)
class SearchKnowledge:
    """Free-text search: finds the `limit` nearest items by embedding, then ranks that candidate set by
    confidence (HIGH first), using distance as a tiebreak - plus the topics that own them, each topic carrying
    all of its items, not just the match."""

    uow: UnitOfWorkFactory
    embedder: Embedder

    def __call__(self, query: str, limit: int = 20) -> SearchResultDTO:
        vector = self.embedder.embed_text(query)
        with self.uow() as uow:
            items = rank_search_hits(uow.items.nearest(vector, limit))
            topic_ids = list(dict.fromkeys(item.topic_id for item in items if item.topic_id is not None))
            topics_by_id = {topic.id: topic for topic in uow.topics.list_by_ids(topic_ids)}
            items_by_topic: dict[str, list[KnowledgeItem]] = {topic_id: [] for topic_id in topics_by_id}
            for item in uow.items.list_by_topics(list(topics_by_id)):
                items_by_topic[item.topic_id].append(item)  # type: ignore[index]
        return SearchResultDTO(
            items=assembler.item_dtos(items, topics_by_id),
            topics=tuple(
                assembler.topic_dto(topics_by_id[topic_id], items_by_topic[topic_id])
                for topic_id in topic_ids
                if topic_id in topics_by_id
            ),
        )


@dataclass(frozen=True)
class BuildGraph:
    """The full item-to-item graph (see domain.services.item_graph) plus the topics and the links between
    the most related ones."""

    uow: UnitOfWorkFactory

    def __call__(self, min_semantic_similarity: float = 0.35) -> GraphDTO:
        with self.uow() as uow:
            topics, items_by_topic = assembler.load_topics(uow)
            items = uow.items.list_all()
        topics_by_id = {topic.id: topic for topic in topics}

        nodes = []
        for item in items:
            topic = topics_by_id.get(item.topic_id) if item.topic_id else None
            nodes.append(
                GraphNodeDTO(
                    id=item.id,
                    type=item.type,
                    description=item.description,
                    confidence=item.confidence,
                    owner=item.owner,
                    topic_id=item.topic_id,
                    topic_name=topic.name if topic is not None else None,
                    meeting_id=item.meeting_id,
                    priority=item.effective_priority(topic),
                )
            )
        edges = [
            GraphEdgeDTO(source=edge.source, target=edge.target, kind=edge.kind, weight=edge.weight)
            for edge in build_item_edges(items, topics_by_id, min_semantic_similarity)
        ]

        named_topics = [topic for topic in topics if not topic.is_uncategorized]
        centroids = all_topic_centroids(topics, items_by_topic)
        topic_links = [
            TopicLinkDTO(source=topic.id, target=related.id, similarity=related.similarity)
            for topic in named_topics
            for related in related_topics(topics, items_by_topic, topic.id, centroids=centroids)
        ]
        return GraphDTO(
            nodes=tuple(nodes),
            edges=tuple(edges),
            topics=tuple(
                GraphTopicDTO(id=topic.id, name=topic.name, item_count=len(items_by_topic[topic.id]))
                for topic in named_topics
            ),
            topic_links=tuple(topic_links),
        )


@dataclass(frozen=True)
class GetFollowUp:
    """Ranks topics by priority/score and surfaces only the items worth raising at the next meeting
    (see domain.services.follow_up)."""

    uow: UnitOfWorkFactory
    clock: Clock

    def __call__(self, limit: int = 5, due_soon_days: int = 7) -> FollowUpDTO:
        with self.uow() as uow:
            topics, items_by_topic = assembler.load_topics(uow)
            escalations = recent_escalations(uow, self.clock, ESCALATION_WINDOW_DAYS)
        now = self.clock.now()
        selected = select_follow_ups(
            topics, items_by_topic, escalations, reference_date=now.date(), limit=limit, due_soon_days=due_soon_days
        )
        topics_by_id = {topic.id: topic for topic in topics}
        return FollowUpDTO(
            topics=tuple(
                FollowUpTopicDTO(
                    topic=assembler.topic_dto(follow_up.topic, items_by_topic[follow_up.topic.id]),
                    follow_up_items=tuple(assembler.item_dto(item, follow_up.topic) for item in follow_up.follow_up_items),
                    escalated_recently=follow_up.escalated_recently,
                    escalation_drivers=follow_up.escalation_drivers,
                    related_from_other_topics=tuple(
                        FollowUpRelatedItemDTO(
                            item=assembler.item_dto(related.item, topics_by_id.get(related.topic_id)),
                            topic_id=related.topic_id,
                            topic_name=related.topic_name,
                            reason=related.reason,
                        )
                        for related in follow_up.related_from_other_topics
                    ),
                )
                for follow_up in selected
            ),
            generated_at=now.isoformat(),
        )
