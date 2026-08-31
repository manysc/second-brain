"""Queries Postgres for the meeting knowledge base. Ingestion (S3 -> Postgres) lives in app/ingest.py."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import db
from app.db_models import KnowledgeItemRow, MeetingRow, ReviewCandidateRow
from app.models import Evidence, KnowledgeItem, Meeting, ReviewCandidate, Topic


def _item_from_row(row: KnowledgeItemRow) -> KnowledgeItem:
    return KnowledgeItem(
        id=row.id,
        type=row.type,
        description=row.description,
        theme=row.theme,
        status=row.status,
        confidence=row.confidence,
        owner=row.owner,
        stakeholders=list(row.stakeholders),
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
        related_ids=list(row.related_ids),
        meeting_id=row.meeting_id,
    )


def _review_candidate_from_row(row: ReviewCandidateRow) -> ReviewCandidate:
    return ReviewCandidate(
        id=row.id,
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


def _topics_for_items(meeting_id: str, items: list[KnowledgeItem]) -> list[Topic]:
    topic_map: dict[str, list[KnowledgeItem]] = {}
    for item in items:
        topic_map.setdefault(item.theme or "Uncategorized", []).append(item)

    return [
        Topic(
            id=f"{meeting_id}:{name}",
            name=name,
            items=topic_items,
            stakeholders=list(dict.fromkeys(s for item in topic_items for s in item.stakeholders)),
        )
        for name, topic_items in topic_map.items()
    ]


def _meeting_from_row(row: MeetingRow) -> Meeting:
    items = [_item_from_row(item_row) for item_row in row.items]
    return Meeting(
        id=row.id,
        title=row.title,
        date=row.date,
        source_url=row.source_url,
        items=items,
        review_candidates=[_review_candidate_from_row(c) for c in row.review_candidates],
        topics=_topics_for_items(row.id, items),
    )


def load_meetings() -> list[Meeting]:
    with db.get_session() as session:
        stmt = select(MeetingRow).options(
            selectinload(MeetingRow.items), selectinload(MeetingRow.review_candidates)
        )
        rows = session.execute(stmt).scalars().all()
        meetings = [_meeting_from_row(row) for row in rows]
    return sorted(meetings, key=lambda meeting: meeting.date, reverse=True)


def get_meeting(meeting_id: str) -> Meeting | None:
    return next((meeting for meeting in load_meetings() if meeting.id == meeting_id), None)


def most_recent_meeting() -> Meeting | None:
    meetings = load_meetings()
    return meetings[0] if meetings else None


def all_items(meetings: list[Meeting]) -> list[KnowledgeItem]:
    return [item for meeting in meetings for item in meeting.items]


def all_review_candidates(meetings: list[Meeting]) -> list[ReviewCandidate]:
    return [candidate for meeting in meetings for candidate in meeting.review_candidates]


def all_topics(meetings: list[Meeting]) -> list[Topic]:
    topic_map: dict[str, list[KnowledgeItem]] = {}
    for meeting in meetings:
        for topic in meeting.topics:
            topic_map.setdefault(topic.name, []).extend(topic.items)

    return [
        Topic(
            id=f"topic:{name}",
            name=name,
            items=items,
            stakeholders=list(dict.fromkeys(s for item in items for s in item.stakeholders)),
        )
        for name, items in topic_map.items()
    ]


def related_items(item: KnowledgeItem, meetings: list[Meeting]) -> list[KnowledgeItem]:
    ids = set(item.related_ids)
    return [
        candidate
        for candidate in all_items(meetings)
        if candidate.id.split(":", 1)[1] in ids or candidate.id in ids
    ]


def semantic_similar_items(item: KnowledgeItem, limit: int = 5) -> list[KnowledgeItem]:
    """Nearest neighbors by pgvector cosine distance - a supplement to (not a replacement for)
    the evidence-grounded `related_ids` links, so callers must keep the two clearly separate."""
    excluded_ids = {item.id, *item.related_ids, *(f"{item.meeting_id}:{rid}" for rid in item.related_ids)}
    with db.get_session() as session:
        source_row = session.get(KnowledgeItemRow, item.id)
        if source_row is None or source_row.embedding is None:
            return []
        stmt = (
            select(KnowledgeItemRow)
            .where(KnowledgeItemRow.id.notin_(excluded_ids))
            .order_by(KnowledgeItemRow.embedding.cosine_distance(source_row.embedding))
            .limit(limit)
        )
        rows = session.execute(stmt).scalars().all()
        return [_item_from_row(row) for row in rows]

