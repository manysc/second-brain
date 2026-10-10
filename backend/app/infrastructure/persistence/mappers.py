"""Translates between ORM rows and domain entities, in both directions. Database types stop here."""
from __future__ import annotations

from typing import Any

from app.domain.entities.knowledge_item import KnowledgeItem
from app.domain.entities.meeting import Meeting
from app.domain.entities.note import Note
from app.domain.entities.review_candidate import ReviewCandidate
from app.domain.entities.topic import Topic
from app.domain.entities.topic_image import TopicImage
from app.domain.services.topic_priority import TOPIC_PRIORITY_ALGORITHM_VERSION
from app.domain.value_objects.evidence import Evidence
from app.domain.value_objects.priority import (
    HardEscalation,
    ManualPriorityOverride,
    SemanticContribution,
    TopicPriorityHistoryEntry,
    TopicPriorityInfo,
    TopicPrioritySignal,
)
from app.infrastructure.persistence.orm_models import (
    KnowledgeItemRow,
    MeetingRow,
    NoteRow,
    ReviewCandidateRow,
    TopicImageRow,
    TopicPriorityHistoryRow,
    TopicRow,
)

# -- shared -------------------------------------------------------------------------------------------------


def _override(priority: str | None, reason: str | None, at: str | None) -> ManualPriorityOverride | None:
    if priority is None:
        return None
    return ManualPriorityOverride(priority=priority, reason=reason, overridden_at=at or "")  # type: ignore[arg-type]


def _notes(rows: list[NoteRow]) -> list[Note]:
    return [Note(id=row.id, body=row.body, created_at=row.created_at) for row in rows]


def _sync_notes(rows: list[NoteRow], notes: tuple[Note, ...]) -> list[NoteRow] | None:
    """The row list matching `notes`, or None when nothing was added or removed (bodies are updated in place).
    Dropping a row from the list deletes it (delete-orphan)."""
    by_id = {row.id: row for row in rows}
    for note in notes:
        row = by_id.get(note.id)
        if row is not None and row.body != note.body:
            row.body = note.body
    if [row.id for row in rows] == [note.id for note in notes]:
        return None
    return [by_id.get(note.id) or NoteRow(id=note.id, body=note.body, created_at=note.created_at) for note in notes]


# -- priority JSON (stored camelCase, as the API serializes it) ---------------------------------------------


def _signal_from_json(data: dict[str, Any]) -> TopicPrioritySignal:
    return TopicPrioritySignal(
        type=data["type"],
        raw_value=data.get("rawValue", data.get("raw_value")),
        normalized_score=data.get("normalizedScore", data.get("normalized_score")),
        weighted_score=data.get("weightedScore", data.get("weighted_score")),
        max_score=data.get("maxScore", data.get("max_score")),
        explanation=data["explanation"],
        source_knowledge_item_ids=data.get("sourceKnowledgeItemIds", data.get("source_knowledge_item_ids", [])),
    )


def _signal_to_json(signal: TopicPrioritySignal) -> dict[str, Any]:
    return {
        "type": signal.type,
        "rawValue": signal.raw_value,
        "normalizedScore": signal.normalized_score,
        "weightedScore": signal.weighted_score,
        "maxScore": signal.max_score,
        "explanation": signal.explanation,
        "sourceKnowledgeItemIds": list(signal.source_knowledge_item_ids),
    }


def _escalation_from_json(data: dict[str, Any]) -> HardEscalation:
    return HardEscalation(
        rule_id=data.get("ruleId", data.get("rule_id")),
        reason=data["reason"],
        source_knowledge_item_ids=data.get("sourceKnowledgeItemIds", data.get("source_knowledge_item_ids", [])),
    )


def _escalation_to_json(escalation: HardEscalation) -> dict[str, Any]:
    return {
        "ruleId": escalation.rule_id,
        "reason": escalation.reason,
        "sourceKnowledgeItemIds": list(escalation.source_knowledge_item_ids),
    }


def _semantic_from_json(data: dict[str, Any] | None) -> SemanticContribution | None:
    if not data:
        return None
    return SemanticContribution(
        provider=data["provider"],
        model=data["model"],
        scores=data["scores"],
        contribution=data["contribution"],
        disagreement=data["disagreement"],
    )


def _semantic_to_json(semantic: SemanticContribution | None) -> dict[str, Any] | None:
    if semantic is None:
        return None
    return {
        "provider": semantic.provider,
        "model": semantic.model,
        "scores": dict(semantic.scores),
        "contribution": semantic.contribution,
        "disagreement": semantic.disagreement,
    }


# -- knowledge items ----------------------------------------------------------------------------------------


def item_from_row(row: KnowledgeItemRow, *, with_embedding: bool = True) -> KnowledgeItem:
    """`with_embedding=False` leaves the (possibly deferred) vector column untouched."""
    return KnowledgeItem(
        id=row.id,
        meeting_id=row.meeting_id,
        topic_id=row.topic_id,
        type=row.type,
        description=row.description,
        theme=row.theme,
        suggested_topic=row.suggested_topic,
        status=row.status,
        confidence=row.confidence,
        owner=row.owner,
        stakeholders=row.stakeholders,
        due_date=row.due_date,
        due_date_source_text=row.due_date_source_text,
        rationale=row.rationale,
        resolution=row.resolution,
        evidence=Evidence(
            speaker=row.evidence_speaker,
            timestamp=row.evidence_timestamp,
            quote=row.evidence_quote,
            context=row.evidence_context,
        ),
        related_ids=row.related_ids,
        embedding=row.embedding if with_embedding else None,
        manual_override=_override(row.manual_priority_override, row.manual_override_reason, row.manual_override_at),
        tags=row.tags or [],
        notes=_notes(row.notes),
    )


def _set_list(row: Any, column: str, values: tuple[str, ...]) -> None:
    # list columns are reassigned, never mutated: SQLAlchemy doesn't track in-place changes to ARRAY columns
    if list(getattr(row, column) or []) != list(values):
        setattr(row, column, list(values))


def apply_item(item: KnowledgeItem, row: KnowledgeItemRow, *, write_embedding: bool, write_override: bool) -> None:
    row.meeting_id = item.meeting_id
    row.topic_id = item.topic_id
    row.type = item.type
    row.description = item.description
    row.theme = item.theme
    row.suggested_topic = item.suggested_topic
    row.status = item.status
    row.confidence = item.confidence
    row.owner = item.owner
    _set_list(row, "stakeholders", item.stakeholders)
    row.due_date = item.due_date
    row.due_date_source_text = item.due_date_source_text
    row.rationale = item.rationale
    row.resolution = item.resolution
    row.evidence_speaker = item.evidence.speaker
    row.evidence_timestamp = item.evidence.timestamp
    row.evidence_quote = item.evidence.quote
    row.evidence_context = item.evidence.context
    _set_list(row, "related_ids", item.related_ids)
    _set_list(row, "tags", item.tags)
    if write_embedding:
        row.embedding = item.embedding  # type: ignore[assignment]
    if write_override:
        override = item.manual_override
        row.manual_priority_override = override.priority if override else None
        row.manual_override_reason = override.reason if override else None
        row.manual_override_at = override.overridden_at if override else None
    synced = _sync_notes(row.notes, item.notes)
    if synced is not None:
        row.notes = synced


def new_item_row(item: KnowledgeItem) -> KnowledgeItemRow:
    row = KnowledgeItemRow(id=item.id, stakeholders=[], related_ids=[], tags=[])
    apply_item(item, row, write_embedding=True, write_override=True)
    return row


# -- topics -------------------------------------------------------------------------------------------------


def _calculation(row: TopicRow) -> TopicPriorityInfo | None:
    if row.calculated_priority is None or row.calculated_priority_score is None:
        return None
    return TopicPriorityInfo(
        calculated_priority=row.calculated_priority,  # type: ignore[arg-type]
        calculated_score=row.calculated_priority_score,
        effective_priority=row.calculated_priority,  # type: ignore[arg-type]
        confidence=row.priority_confidence or "LOW",  # type: ignore[arg-type]
        signals=[_signal_from_json(signal) for signal in (row.priority_signals or [])],
        hard_escalations=[_escalation_from_json(e) for e in (row.priority_hard_escalations or [])],
        explanation=row.priority_explanation or "",
        calculated_at=row.priority_calculated_at or "",
        algorithm_version=row.priority_algorithm_version or TOPIC_PRIORITY_ALGORITHM_VERSION,
        semantic_contribution=_semantic_from_json(row.priority_semantic_contribution),
    )


def topic_from_row(row: TopicRow) -> Topic:
    return Topic(
        id=row.id,
        name=row.name,
        status=row.status,
        tags=row.tags or [],
        notes=_notes(row.notes),
        images=[
            TopicImage(
                id=image.id,
                key=image.key,
                filename=image.filename,
                content_type=image.content_type,
                size=image.size,
                created_at=image.created_at,
            )
            for image in row.images
        ],
        calculation=_calculation(row),
        manual_override=_override(row.manual_priority_override, row.manual_override_reason, row.manual_override_at),
    )


def apply_topic(topic: Topic, row: TopicRow, *, write_calculation: bool, write_override: bool) -> None:
    row.name = topic.name
    row.status = topic.status
    _set_list(row, "tags", topic.tags)
    if write_override:
        override = topic.manual_override
        row.manual_priority_override = override.priority if override else None
        row.manual_override_reason = override.reason if override else None
        row.manual_override_at = override.overridden_at if override else None
    if write_calculation:
        result = topic.calculation
        row.calculated_priority = result.calculated_priority if result else None
        row.calculated_priority_score = result.calculated_score if result else None
        row.priority_confidence = result.confidence if result else None
        row.priority_signals = [_signal_to_json(signal) for signal in result.signals] if result else None
        row.priority_hard_escalations = [_escalation_to_json(e) for e in result.hard_escalations] if result else None
        row.priority_explanation = result.explanation if result else None
        row.priority_algorithm_version = result.algorithm_version if result else None
        row.priority_semantic_contribution = _semantic_to_json(result.semantic_contribution) if result else None
        row.priority_calculated_at = result.calculated_at if result else None
    synced = _sync_notes(row.notes, topic.notes)
    if synced is not None:
        row.notes = synced
    if [image.id for image in row.images] != [image.id for image in topic.images]:
        by_id = {image.id: image for image in row.images}
        row.images = [
            by_id.get(image.id)
            or TopicImageRow(
                id=image.id,
                key=image.key,
                filename=image.filename,
                content_type=image.content_type,
                size=image.size,
                created_at=image.created_at,
            )
            for image in topic.images
        ]


def new_topic_row(topic: Topic) -> TopicRow:
    row = TopicRow(id=topic.id, tags=[])
    apply_topic(topic, row, write_calculation=topic.calculation is not None, write_override=topic.manual_override is not None)
    return row


# -- meetings, review candidates, priority history ----------------------------------------------------------


def meeting_from_row(row: MeetingRow) -> Meeting:
    return Meeting(id=row.id, title=row.title, date=row.date, source_url=row.source_url)


def apply_meeting(meeting: Meeting, row: MeetingRow) -> None:
    row.title = meeting.title
    row.date = meeting.date
    row.source_url = meeting.source_url


def candidate_from_row(row: ReviewCandidateRow) -> ReviewCandidate:
    return ReviewCandidate(
        id=row.id,
        meeting_id=row.meeting_id,
        type=row.type,
        description=row.description,
        reason=row.reason,
        confidence=row.confidence,
        evidence=Evidence(
            speaker=row.evidence_speaker,
            timestamp=row.evidence_timestamp,
            quote=row.evidence_quote,
            context=row.evidence_context,
        ),
        status=row.status,
    )


def apply_candidate(candidate: ReviewCandidate, row: ReviewCandidateRow) -> None:
    row.meeting_id = candidate.meeting_id
    row.type = candidate.type
    row.description = candidate.description
    row.reason = candidate.reason
    row.confidence = candidate.confidence
    row.evidence_speaker = candidate.evidence.speaker
    row.evidence_timestamp = candidate.evidence.timestamp
    row.evidence_quote = candidate.evidence.quote
    row.evidence_context = candidate.evidence.context
    row.status = candidate.status


def history_from_row(row: TopicPriorityHistoryRow) -> TopicPriorityHistoryEntry:
    return TopicPriorityHistoryEntry(
        id=row.id,
        topic_id=row.topic_id,
        previous_priority=row.previous_priority,  # type: ignore[arg-type]
        new_priority=row.new_priority,  # type: ignore[arg-type]
        previous_score=row.previous_score,
        new_score=row.new_score,
        changed_at=row.changed_at,
        algorithm_version=row.algorithm_version,
        primary_drivers=row.primary_drivers,
        trigger=row.trigger,
        source_knowledge_item_ids=row.source_knowledge_item_ids,
    )


def history_row(entry: TopicPriorityHistoryEntry) -> TopicPriorityHistoryRow:
    return TopicPriorityHistoryRow(
        id=entry.id,
        topic_id=entry.topic_id,
        previous_priority=entry.previous_priority,
        new_priority=entry.new_priority,
        previous_score=entry.previous_score,
        new_score=entry.new_score,
        changed_at=entry.changed_at,
        algorithm_version=entry.algorithm_version,
        primary_drivers=list(entry.primary_drivers),
        trigger=entry.trigger,
        source_knowledge_item_ids=list(entry.source_knowledge_item_ids),
    )
