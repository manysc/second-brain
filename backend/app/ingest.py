"""Parses raw meeting extraction JSON (from S3) into domain models, and upserts them into Postgres.

Moved from app/data.py, which now only queries Postgres.
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app import db, embeddings, s3_store
from app.db_models import KnowledgeItemRow, MeetingRow, ReviewCandidateRow, TopicRow
from app.models import (
    Confidence,
    Evidence,
    ItemType,
    KnowledgeItem,
    Meeting,
    RawCandidate,
    RawEvidence,
    RawExtraction,
    ReviewCandidate,
    Topic,
)


def _normalize_confidence(value: str) -> Confidence:
    normalized = value.upper()
    return normalized if normalized in ("HIGH", "LOW") else "MEDIUM"


def _normalize_evidence(raw: RawEvidence) -> Evidence:
    return Evidence(speaker=raw.speaker, timestamp=raw.timestamp, quote=raw.quote, context=raw.context)


def _normalize_item(candidate: RawCandidate, item_type: ItemType, meeting_id: str) -> KnowledgeItem:
    owner = candidate.owner or candidate.proposed_by or candidate.decision_owner
    speaker = candidate.evidence.speaker
    stakeholders = list(dict.fromkeys(value for value in (owner, speaker) if value))
    return KnowledgeItem(
        id=f"{meeting_id}:{candidate.candidate_id}",
        type=item_type,
        description=candidate.description,
        theme=candidate.theme,
        status=candidate.status,
        confidence=_normalize_confidence(candidate.confidence),
        owner=owner,
        stakeholders=stakeholders,
        due_date=candidate.due_date,
        due_date_source_text=candidate.due_date_source_text,
        rationale=candidate.rationale,
        resolution=candidate.resolution,
        evidence=_normalize_evidence(candidate.evidence),
        related_ids=candidate.related_candidate_ids,
        meeting_id=meeting_id,
    )


def _repair_json(text: str) -> dict:
    original = text.strip()
    # the source file is sometimes missing its enclosing braces
    repaired = original if original.startswith("{") else f"{{{original}}}"
    return json.loads(repaired)


def _derive_meeting_id(key: str) -> str:
    # the extraction JSON's own meeting_id is sometimes blank or duplicated across files;
    # the S3 key is always unique, so it's the source of truth for id-namespacing
    stem = Path(key).stem
    return re.sub(r"[^A-Za-z0-9_-]", "-", stem)


def _normalize_extraction(parsed: RawExtraction, meeting_id: str) -> Meeting:
    items = [
        *(_normalize_item(c, "IDEA", meeting_id) for c in parsed.ideas),
        *(_normalize_item(c, "DECISION", meeting_id) for c in parsed.decisions),
        *(_normalize_item(c, "ACTION", meeting_id) for c in parsed.actions),
        *(_normalize_item(c, "QUESTION", meeting_id) for c in parsed.questions),
    ]

    review_candidates = [
        ReviewCandidate(
            id=f"{meeting_id}:review-{index + 1}",
            type=candidate.candidate_type,
            description=candidate.description,
            reason=candidate.reason_for_review,
            confidence=_normalize_confidence(candidate.confidence),
            evidence=_normalize_evidence(candidate.evidence),
            status="PENDING",
        )
        for index, candidate in enumerate(parsed.review_candidates)
    ]

    topic_map: dict[str, list[KnowledgeItem]] = {}
    for item in items:
        topic_map.setdefault(item.theme or "Uncategorized", []).append(item)

    topics = [
        Topic(
            id=f"{meeting_id}:{name}",
            name=name,
            items=topic_items,
            stakeholders=list(dict.fromkeys(s for item in topic_items for s in item.stakeholders)),
        )
        for name, topic_items in topic_map.items()
    ]

    return Meeting(
        id=meeting_id,
        title=parsed.meeting.title,
        date=parsed.meeting.date,
        source_url=parsed.meeting.source_url,
        items=items,
        review_candidates=review_candidates,
        topics=topics,
    )


def parse_meeting_from_s3(key: str) -> Meeting:
    parsed = RawExtraction.model_validate(_repair_json(s3_store.fetch_object_text(key)))
    return _normalize_extraction(parsed, _derive_meeting_id(key))


def _resolve_topic_id(session: Session, theme: str | None, cache: dict[str, str]) -> str:
    name = theme or "Uncategorized"
    if name in cache:
        return cache[name]
    existing = session.execute(select(TopicRow).where(TopicRow.name == name)).scalar_one_or_none()
    topic_id = existing.id if existing is not None else str(uuid.uuid4())
    if existing is None:
        session.add(TopicRow(id=topic_id, name=name))
        session.flush()
    cache[name] = topic_id
    return topic_id


def upsert_meeting(session: Session, meeting: Meeting) -> None:
    meeting_stmt = pg_insert(MeetingRow).values(
        id=meeting.id, title=meeting.title, date=meeting.date, source_url=meeting.source_url
    )
    meeting_stmt = meeting_stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={"title": meeting_stmt.excluded.title, "date": meeting_stmt.excluded.date, "source_url": meeting_stmt.excluded.source_url},
    )
    session.execute(meeting_stmt)

    if meeting.items:
        item_vectors = embeddings.embed_texts([item.description for item in meeting.items])
        topic_cache: dict[str, str] = {}
        existing_ids = {
            row_id
            for (row_id,) in session.execute(
                select(KnowledgeItemRow.id).where(KnowledgeItemRow.id.in_([item.id for item in meeting.items]))
            )
        }
        for item, vector in zip(meeting.items, item_vectors):
            # only resolve/create a topic for genuinely new items - re-ingesting an item that
            # already exists must never resurrect a topic the user deliberately deleted
            topic_id = None if item.id in existing_ids else _resolve_topic_id(session, item.theme, topic_cache)
            item_stmt = pg_insert(KnowledgeItemRow).values(
                id=item.id,
                meeting_id=meeting.id,
                topic_id=topic_id,
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
                evidence_speaker=item.evidence.speaker,
                evidence_timestamp=item.evidence.timestamp,
                evidence_quote=item.evidence.quote,
                evidence_context=item.evidence.context,
                related_ids=item.related_ids,
                embedding=vector,
            )
            update_cols = {
                col: getattr(item_stmt.excluded, col)
                for col in (
                    # topic_id intentionally excluded: preserves manual topic reassignments across re-ingestion
                    "type",
                    "description",
                    "theme",
                    "status",
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
                    "embedding",
                )
            }
            item_stmt = item_stmt.on_conflict_do_update(index_elements=["id"], set_=update_cols)
            session.execute(item_stmt)

    for candidate in meeting.review_candidates:
        candidate_stmt = pg_insert(ReviewCandidateRow).values(
            id=candidate.id,
            meeting_id=meeting.id,
            type=candidate.type,
            description=candidate.description,
            reason=candidate.reason,
            confidence=candidate.confidence,
            evidence_speaker=candidate.evidence.speaker,
            evidence_timestamp=candidate.evidence.timestamp,
            evidence_quote=candidate.evidence.quote,
            evidence_context=candidate.evidence.context,
            status=candidate.status,
        )
        update_cols = {
            col: getattr(candidate_stmt.excluded, col)
            for col in (
                "type",
                "description",
                "reason",
                "confidence",
                "evidence_speaker",
                "evidence_timestamp",
                "evidence_quote",
                "evidence_context",
                # status is intentionally excluded: ingestion must not clobber a human review decision
            )
        }
        candidate_stmt = candidate_stmt.on_conflict_do_update(index_elements=["id"], set_=update_cols)
        session.execute(candidate_stmt)


def ingest_all_from_s3(session: Session) -> int:
    count = 0
    for key in s3_store.list_extract_keys():
        meeting = parse_meeting_from_s3(key)
        upsert_meeting(session, meeting)
        count += 1
    return count


def ingest_and_commit() -> int:
    """Opens a session, ingests everything from S3, and commits. Shared by the FastAPI startup
    hook and the manual scripts/ingest_to_postgres.py CLI entrypoint."""
    with db.get_session() as session:
        count = ingest_all_from_s3(session)
        session.commit()
    return count
