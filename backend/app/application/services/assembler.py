"""Builds the read DTOs from entities. The reading rules live here once: Uncategorized is never shown as an
item's topic, statuses collapse to Open/Closed, and an item's priority is its own override or its topic's."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from app.application.dtos import (
    KnowledgeItemDTO,
    MeetingDTO,
    NoteDTO,
    ReviewCandidateDTO,
    TopicDTO,
    TopicImageDTO,
)
from app.application.interfaces.repositories import UnitOfWork
from app.domain.entities.knowledge_item import KnowledgeItem
from app.domain.entities.meeting import Meeting
from app.domain.entities.note import Note
from app.domain.entities.review_candidate import ReviewCandidate
from app.domain.entities.topic import Topic
from app.domain.policies import UNCATEGORIZED_TOPIC


def note_dtos(notes: Iterable[Note]) -> tuple[NoteDTO, ...]:
    return tuple(NoteDTO(id=note.id, body=note.body, created_at=note.created_at) for note in notes)


def item_dto(item: KnowledgeItem, topic: Topic | None) -> KnowledgeItemDTO:
    """`topic` is the topic the item is filed under (None when it has none)."""
    shown_topic = topic if topic is not None and not topic.is_uncategorized else None
    return KnowledgeItemDTO(
        id=item.id,
        type=item.type,
        description=item.description,
        theme=item.theme,
        topic_id=shown_topic.id if shown_topic else None,
        topic_name=shown_topic.name if shown_topic else None,
        status=item.open_closed,
        confidence=item.confidence,
        owner=item.owner,
        stakeholders=item.stakeholders,
        due_date=item.due_date,
        due_date_source_text=item.due_date_source_text,
        rationale=item.rationale,
        resolution=item.resolution,
        evidence=item.evidence,
        related_ids=item.related_ids,
        meeting_id=item.meeting_id,
        effective_priority=item.effective_priority(topic),
        manual_override=item.manual_override,
        notes=note_dtos(item.notes),
        tags=item.tags,
    )


def item_dtos(items: Iterable[KnowledgeItem], topics_by_id: Mapping[str, Topic]) -> tuple[KnowledgeItemDTO, ...]:
    return tuple(item_dto(item, topics_by_id.get(item.topic_id) if item.topic_id else None) for item in items)


def _unique_stakeholders(items: Iterable[KnowledgeItemDTO]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(name for item in items for name in item.stakeholders))


def topic_dto(topic: Topic, items: Sequence[KnowledgeItem]) -> TopicDTO:
    """`items` are the items filed under this topic."""
    dtos = tuple(item_dto(item, topic) for item in items)
    return TopicDTO(
        id=topic.id,
        name=topic.name,
        status=topic.status,
        items=dtos,
        stakeholders=_unique_stakeholders(dtos),
        priority=topic.priority,
        notes=note_dtos(topic.notes),
        tags=topic.tags,
        images=tuple(
            TopicImageDTO(
                id=image.id,
                filename=image.filename,
                content_type=image.content_type,
                size=image.size,
                created_at=image.created_at,
            )
            for image in topic.images
        ),
    )


def candidate_dto(candidate: ReviewCandidate, suggested_topic_id: str | None = None) -> ReviewCandidateDTO:
    return ReviewCandidateDTO(
        id=candidate.id,
        type=candidate.type,
        description=candidate.description,
        reason=candidate.reason,
        confidence=candidate.confidence,
        evidence=candidate.evidence,
        status=candidate.status,
        suggested_topic_id=suggested_topic_id,
    )


def theme_topics(meeting_id: str, items: Sequence[KnowledgeItemDTO]) -> tuple[TopicDTO, ...]:
    """A meeting's own items grouped by theme: a per-meeting view, not the persisted topics."""
    grouped: dict[str, list[KnowledgeItemDTO]] = {}
    for item in items:
        grouped.setdefault(item.theme or UNCATEGORIZED_TOPIC, []).append(item)
    return tuple(
        TopicDTO(
            id=f"{meeting_id}:{name}",
            name=name,
            status="Open",
            items=tuple(topic_items),
            stakeholders=_unique_stakeholders(topic_items),
        )
        for name, topic_items in grouped.items()
    )


def meeting_dto(
    meeting: Meeting,
    items: Sequence[KnowledgeItem],
    candidates: Sequence[ReviewCandidate],
    topics_by_id: Mapping[str, Topic],
) -> MeetingDTO:
    dtos = item_dtos(items, topics_by_id)
    return MeetingDTO(
        id=meeting.id,
        title=meeting.title,
        date=meeting.date,
        source_url=meeting.source_url,
        items=dtos,
        review_candidates=tuple(candidate_dto(candidate) for candidate in candidates),
        topics=theme_topics(meeting.id, dtos),
    )


def load_meetings(uow: UnitOfWork) -> list[MeetingDTO]:
    """Every meeting with its items and review candidates, newest first."""
    topics_by_id = {topic.id: topic for topic in uow.topics.list_all()}
    items_by_meeting: dict[str, list[KnowledgeItem]] = {}
    for item in uow.items.list_all():
        items_by_meeting.setdefault(item.meeting_id, []).append(item)
    candidates_by_meeting: dict[str, list[ReviewCandidate]] = {}
    for candidate in uow.review_candidates.list_all():
        candidates_by_meeting.setdefault(candidate.meeting_id, []).append(candidate)
    meetings = [
        meeting_dto(
            meeting, items_by_meeting.get(meeting.id, ()), candidates_by_meeting.get(meeting.id, ()), topics_by_id
        )
        for meeting in uow.meetings.list_all()
    ]
    return sorted(meetings, key=lambda meeting: meeting.date, reverse=True)


def load_topics(uow: UnitOfWork) -> tuple[list[Topic], dict[str, list[KnowledgeItem]]]:
    """Every topic (including empty ones) and the items filed under each."""
    topics = uow.topics.list_all()
    items_by_topic: dict[str, list[KnowledgeItem]] = {topic.id: [] for topic in topics}
    for item in uow.items.list_all():
        if item.topic_id in items_by_topic:
            items_by_topic[item.topic_id].append(item)
    return topics, items_by_topic


def load_topic_dto(uow: UnitOfWork, topic: Topic) -> TopicDTO:
    return topic_dto(topic, uow.items.list_by_topic(topic.id))


def load_item_dto(uow: UnitOfWork, item: KnowledgeItem) -> KnowledgeItemDTO:
    return item_dto(item, uow.topics.get(item.topic_id) if item.topic_id else None)
