"""Legacy facade over ingestion.

Parsing lives in app.infrastructure.external_services.extraction_parser and the merge rules in
app.application.use_cases.ingestion (with the entities). This module keeps the old session-based entry points
and Pydantic return types for the existing callers until they move over."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app import embeddings, s3_store  # noqa: F401  (tests patch `ingest.embeddings`)
from app.application.dtos import IngestSummary
from app.application.exceptions import ExtractSourceUnavailable
from app.container import get_container
from app.domain.value_objects.evidence import Evidence as _Evidence
from app.domain.value_objects.extraction import ExtractedItem, ExtractedMeeting, ExtractedReviewCandidate
from app.infrastructure.external_services.extraction_parser import parse_extract, parse_single_extract
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from app.models import Evidence, KnowledgeItem, Meeting, ReviewCandidate, Topic

__all__ = [
    "IngestSummary",
    "ingest_all_from_s3",
    "ingest_and_commit",
    "parse_meeting_from_s3",
    "parse_meetings_from_s3",
    "upsert_meeting",
]

# The fields re-ingestion refreshes on an item that already exists. topic_id, theme (kept equal to the topic
# name), suggested_topic, status, tags, notes and priority overrides are deliberately absent: they belong to a
# person (see KnowledgeItem.apply_extraction, which is where this rule now lives).
_ITEM_UPDATE_COLS = (
    "type",
    "description",
    "confidence",
    "owner",
    "stakeholders",
    "due_date",
    "due_date_source_text",
    "rationale",
    "resolution",
    "evidence_speaker",
    "evidence_timestamp",
    "evidence_quote",
    "evidence_context",
    "related_ids",
)


def _evidence(evidence: _Evidence) -> Evidence:
    return Evidence(
        speaker=evidence.speaker, timestamp=evidence.timestamp, quote=evidence.quote, context=evidence.context
    )


def _to_model(extracted: ExtractedMeeting) -> Meeting:
    items = [
        KnowledgeItem(
            id=item.id,
            type=item.type,
            description=item.description,
            theme=item.theme,
            status=item.status,
            confidence=item.confidence,
            owner=item.owner,
            stakeholders=list(item.stakeholders),
            due_date=item.due_date,
            due_date_source_text=item.due_date_source_text,
            rationale=item.rationale,
            resolution=item.resolution,
            evidence=_evidence(item.evidence),
            related_ids=list(item.related_ids),
            meeting_id=item.meeting_id,
        )
        for item in extracted.items
    ]
    topic_map: dict[str, list[KnowledgeItem]] = {}
    for item in items:
        topic_map.setdefault(item.theme or "Uncategorized", []).append(item)
    return Meeting(
        id=extracted.id,
        title=extracted.title,
        date=extracted.date,
        source_url=extracted.source_url,
        items=items,
        review_candidates=[
            ReviewCandidate(
                id=candidate.id,
                type=candidate.type,
                description=candidate.description,
                reason=candidate.reason,
                confidence=candidate.confidence,
                evidence=_evidence(candidate.evidence),
                status="PENDING",
            )
            for candidate in extracted.review_candidates
        ],
        topics=[
            Topic(
                id=f"{extracted.id}:{name}",
                name=name,
                items=topic_items,
                stakeholders=list(dict.fromkeys(s for item in topic_items for s in item.stakeholders)),
            )
            for name, topic_items in topic_map.items()
        ],
    )


def _from_model(meeting: Meeting) -> ExtractedMeeting:
    def evidence(model: Evidence) -> _Evidence:
        return _Evidence(speaker=model.speaker, timestamp=model.timestamp, quote=model.quote, context=model.context)

    return ExtractedMeeting(
        id=meeting.id,
        title=meeting.title,
        date=meeting.date,
        source_url=meeting.source_url,
        items=[
            ExtractedItem(
                id=item.id,
                meeting_id=meeting.id,
                type=item.type,
                description=item.description,
                theme=item.theme,
                status=item.status,
                confidence=item.confidence,
                owner=item.owner,
                stakeholders=item.stakeholders,
                due_date=item.due_date,
                due_date_source_text=item.due_date_source_text,
                rationale=item.rationale,
                resolution=item.resolution,
                evidence=evidence(item.evidence),
                related_ids=item.related_ids,
            )
            for item in meeting.items
        ],
        review_candidates=[
            ExtractedReviewCandidate(
                id=candidate.id,
                type=candidate.type,
                description=candidate.description,
                reason=candidate.reason,
                confidence=candidate.confidence,
                evidence=evidence(candidate.evidence),
            )
            for candidate in meeting.review_candidates
        ],
    )


def parse_meeting_from_s3(key: str) -> Meeting:
    return _to_model(parse_single_extract(key, s3_store.fetch_object_text(key)))


def parse_meetings_from_s3(key: str) -> list[Meeting]:
    return [_to_model(extracted) for extracted in parse_extract(key, s3_store.fetch_object_text(key))]


def upsert_meeting(session: Session, meeting: Meeting) -> bool:
    """Merges one meeting inside the caller's session (the caller commits)."""
    return get_container().ingest_extracts.merge_meeting(SqlAlchemyUnitOfWork(session), _from_model(meeting))


def _ingest_all(session: Session) -> IngestSummary:
    return get_container().ingest_extracts.ingest_into(SqlAlchemyUnitOfWork(session))


def ingest_all_from_s3(session: Session) -> int:
    return _ingest_all(session).processed


def ingest_and_commit() -> IngestSummary:
    """Ingests everything from S3 and commits, then recalculates every topic's priority if anything changed.
    Callers serialize runs themselves (app.main holds the lock)."""
    container = get_container()
    try:
        summary = container.ingest_extracts.ingest_all()
    except ExtractSourceUnavailable as error:
        # existing callers still handle the storage client's own connection errors
        raise (error.__cause__ or error) from None
    if summary.changed:
        container.recalculator.recalculate_all(trigger="ingestion")
    return summary
