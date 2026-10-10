"""Queries Postgres for the meeting knowledge base. Ingestion (S3 -> Postgres) lives in app/ingest.py."""
from __future__ import annotations

import itertools
import logging
import threading
import uuid
from datetime import date, datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session, selectinload

from app import db, embeddings, s3_store, topic_priority, topic_suggestions
from app.db_models import (
    KnowledgeItemRow,
    MeetingRow,
    NoteRow,
    ReviewCandidateRow,
    TopicImageRow,
    TopicPriorityHistoryRow,
    TopicRow,
)
from app.models import (
    MAX_TAGS,
    Evidence,
    FollowUpRelatedItem,
    FollowUpResponse,
    FollowUpTopic,
    GraphData,
    GraphTopic,
    GraphEdge,
    GraphNode,
    HardEscalation,
    ItemCreate,
    ItemTopicSuggestion,
    ItemUpdate,
    ItemType,
    KnowledgeItem,
    ManualPriorityOverride,
    Meeting,
    Note,
    RelatedTopic,
    ReviewCandidate,
    ReviewStatus,
    SemanticContribution,
    Topic,
    TopicCandidate,
    TopicLink,
    TopicMergeSuggestion,
    TopicPriorityHistoryEntry,
    TopicImage,
    TopicPriorityInfo,
    TopicPrioritySignal,
    TopicProposal,
    normalize_tag,
)

logger = logging.getLogger(__name__)

# Business constants, rules and exceptions now live in app.domain; the names below are kept so existing
# callers (REST routes, MCP server, tests) keep working until they move to the application layer.
from app.domain.exceptions import (  # noqa: E402,F401
    ImageTooLarge,
    ItemNotDeletable,
    ItemNotEditable,
    ReviewCandidateAlreadyDecided,
    TooManyTags,
    TopicHasItems,
    TopicNameConflict,
    UnsupportedImageType,
)
from app.domain.policies import (  # noqa: E402,F401
    DUPLICATE_MATCH_THRESHOLD,
    ITEM_TOPIC_MATCH_SIMILARITY,
    MANUAL_MEETING_ID,
    PROPOSAL_HINT_SIMILARITY,
    UNCATEGORIZED_TOPIC,
)
from app.domain.services import similarity  # noqa: E402
from app.domain.services.similarity import cosine_similarity as similarity_of  # noqa: E402
from app.domain.services.similarity import closest_topic as _closest_topic  # noqa: E402,F401
from app.domain.services.topic_ranking import confident_topic_id as _confident_topic_id  # noqa: E402
from app.domain.value_objects.confidence import CONFIDENCE_RANK as _CONFIDENCE_RANK  # noqa: E402
from app.domain.value_objects.image_upload import (  # noqa: E402,F401
    MAX_IMAGE_BYTES,
    display_filename as _display_filename,
    sniff_image_type as _sniff_image_type,
)
from app.domain.value_objects.item_type import normalize_item_type as _normalize_item_type  # noqa: E402
from app.domain.value_objects.priority import PRIORITY_RANK as _PRIORITY_RANK  # noqa: E402
from app.domain.value_objects.tag import with_tag as _with_tag, without_tag as _without_tag  # noqa: E402


def _item_effective_priority(row: KnowledgeItemRow) -> tuple[str | None, ManualPriorityOverride | None]:
    """Option A: an item has no automatic scoring of its own - its own override wins, else it
    inherits its owning Topic's effective priority. Shared by _item_from_row and build_graph so
    the precedence rule only lives in one place."""
    if row.manual_priority_override is not None:
        override = ManualPriorityOverride(
            priority=row.manual_priority_override,
            reason=row.manual_override_reason,
            overridden_at=row.manual_override_at or "",
        )
        return row.manual_priority_override, override
    topic = row.topic
    if topic is not None:
        return topic.manual_priority_override or topic.calculated_priority, None
    return None, None


def _note_from_row(row: NoteRow) -> Note:
    return Note(id=row.id, body=row.body, created_at=row.created_at)


def _item_from_row(row: KnowledgeItemRow) -> KnowledgeItem:
    effective_priority, manual_override = _item_effective_priority(row)
    topic = row.topic if row.topic is not None and row.topic.name != UNCATEGORIZED_TOPIC else None
    return KnowledgeItem(
        id=row.id,
        type=row.type,
        description=row.description,
        theme=row.theme,
        topic_id=topic.id if topic else None,
        topic_name=topic.name if topic else None,
        # legacy free-text statuses ("Answered", "Resolved", ...) collapse to the binary Open/Closed
        status="Closed" if topic_priority.is_resolved_status(row.status) else "Open",
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
        effective_priority=effective_priority,
        manual_override=manual_override,
        notes=[_note_from_row(n) for n in row.notes],
        tags=list(row.tags or []),
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


def find_item(item_id: str, meetings: list[Meeting]) -> KnowledgeItem | None:
    return next((candidate for candidate in all_items(meetings) if candidate.id == item_id), None)


def filter_items(
    items: list[KnowledgeItem],
    item_type: str | None = None,
    status: str | None = None,
    priority: str | None = None,
) -> list[KnowledgeItem]:
    """Shared by the REST API and the MCP server so the filter semantics live in one place."""
    if item_type is not None:
        items = [item for item in items if item.type == item_type]
    if status is not None:
        items = [item for item in items if item.status == status]
    if priority is not None:
        items = [item for item in items if item.effective_priority == priority]
    return items


def all_review_candidates(meetings: list[Meeting]) -> list[ReviewCandidate]:
    return [candidate for meeting in meetings for candidate in meeting.review_candidates]


def pending_review_candidates() -> list[ReviewCandidate]:
    """Candidates still awaiting a decision, newest meeting first. Queries the candidates directly
    instead of going through load_meetings, which would also load every meeting's items."""
    with db.get_session() as session:
        stmt = (
            select(ReviewCandidateRow)
            .join(MeetingRow)
            .where(ReviewCandidateRow.status == "PENDING")
            .order_by(MeetingRow.date.desc(), ReviewCandidateRow.id)
        )
        return [_review_candidate_from_row(row) for row in session.execute(stmt).scalars().all()]


def _matching_topic_centroids(session: Session) -> dict[str, np.ndarray]:
    rows = [
        row
        for row in session.execute(select(TopicRow).options(selectinload(TopicRow.items))).scalars().all()
        if row.name != UNCATEGORIZED_TOPIC
    ]
    return _topic_centroids(rows)


def _topic_ranker(rows: list[TopicRow]) -> topic_suggestions.TopicRanker:
    """Ranker over every topic except "Uncategorized" (a catch-all whose items aren't a topic signal).
    `rows` must have `items` loaded."""
    return topic_suggestions.TopicRanker(
        [
            topic_suggestions.TopicProfile(
                topic_id=row.id,
                name=row.name,
                tags=list(row.tags or []),
                item_embeddings=[item.embedding for item in row.items if item.embedding is not None],
                item_descriptions=[item.description for item in row.items],
            )
            for row in rows
            if row.name != UNCATEGORIZED_TOPIC
        ]
    )


# Building the ranker (loading every topic's items + fitting TF-IDF) takes ~1.4s, and every /review render
# needs it twice, so the last one built is reused until _ranker_fingerprint changes.
_ranker_cache: tuple[str, topic_suggestions.TopicRanker] | None = None
_ranker_lock = threading.Lock()

# Covers exactly what _topic_ranker reads (topic id/name/tags, item id/description/embedding), so any
# write changes it - including ones the MCP server makes from another process.
_RANKER_FINGERPRINT_SQL = text(
    """
    select md5(coalesce(string_agg(
        concat_ws('|', t.id, t.name, array_to_string(t.tags, ','), i.id, md5(i.description), md5(i.embedding::text)),
        ',' order by t.id, i.id
    ), ''))
    from topics t left join knowledge_items i on i.topic_id = t.id
    where t.name <> :uncategorized
    """
)


def _ranker_fingerprint(session: Session) -> str:
    return session.execute(_RANKER_FINGERPRINT_SQL, {"uncategorized": UNCATEGORIZED_TOPIC}).scalar_one()


def _load_topic_ranker(session: Session) -> topic_suggestions.TopicRanker:
    global _ranker_cache
    fingerprint = _ranker_fingerprint(session)
    # held while building, so concurrent requests wait for one build instead of each doing their own
    with _ranker_lock:
        if _ranker_cache is not None and _ranker_cache[0] == fingerprint:
            return _ranker_cache[1]
        rows = session.execute(select(TopicRow).options(selectinload(TopicRow.items))).scalars().all()
        ranker = _topic_ranker(list(rows))
        _ranker_cache = (fingerprint, ranker)
        return ranker


def with_suggested_topics(candidates: list[ReviewCandidate]) -> list[ReviewCandidate]:
    """Fills `suggested_topic_id` (the best-ranked existing topic, when a confident match) on each
    candidate to pre-select the review page's topic picker. Deliberately looser than the strict
    centroid match set_review_status applies when a candidate is accepted without an explicit topic,
    since a human confirms this one."""
    if not candidates:
        return candidates
    descriptions = [candidate.description for candidate in candidates]
    vectors = embeddings.embed_texts(descriptions)
    with db.get_session() as session:
        ranker = _load_topic_ranker(session)
    ranked = ranker.rank_many(vectors, descriptions, top_n=1)
    return [
        candidate.model_copy(update={"suggested_topic_id": _confident_topic_id(best)})
        for candidate, best in zip(candidates, ranked)
    ]


def _find_similar_item(session: Session, embedding: list[float]) -> KnowledgeItemRow | None:
    distance_expr = KnowledgeItemRow.embedding.cosine_distance(embedding)
    stmt = (
        select(KnowledgeItemRow, distance_expr)
        .where(KnowledgeItemRow.embedding.is_not(None))
        .order_by(distance_expr)
        .limit(1)
    )
    result = session.execute(stmt).first()
    if result is None:
        return None
    row, distance = result
    return row if distance < DUPLICATE_MATCH_THRESHOLD else None


def _get_or_create_uncategorized_topic(session: Session) -> str:
    existing = session.execute(select(TopicRow).where(TopicRow.name == UNCATEGORIZED_TOPIC)).scalar_one_or_none()
    if existing is not None:
        return existing.id
    topic_id = str(uuid.uuid4())
    session.add(TopicRow(id=topic_id, name=UNCATEGORIZED_TOPIC))
    session.flush()
    return topic_id


def set_review_status(
    candidate_id: str, status: ReviewStatus, topic_id: str | None = None
) -> ReviewCandidate | None:
    """`topic_id` only matters when accepting a candidate that isn't a duplicate: a topic id files the
    new item there, "" files it in Uncategorized, and None auto-matches the closest existing topic
    (falling back to Uncategorized). Topics are never created here."""
    affected_topic_id: str | None = None
    with db.get_session() as session:
        row = session.get(ReviewCandidateRow, candidate_id)
        if row is None:
            return None
        if row.status != "PENDING":
            raise ReviewCandidateAlreadyDecided(candidate_id)

        if status == "ACCEPTED":
            vector = embeddings.embed_text(row.description)
            existing = _find_similar_item(session, vector)
            if existing is not None:
                # merge: a near-duplicate item already exists, so reinforce it instead of duplicating
                existing.confidence = "HIGH"
                affected_topic_id = existing.topic_id
            else:
                owner = row.evidence_speaker
                topic_row: TopicRow | None = None
                if topic_id:
                    topic_row = session.get(TopicRow, topic_id)
                    if topic_row is None:
                        raise ValueError("topic not found")
                elif topic_id is None:
                    match_id, _ = _closest_topic(
                        np.array(vector), _matching_topic_centroids(session), ITEM_TOPIC_MATCH_SIMILARITY
                    )
                    topic_row = session.get(TopicRow, match_id) if match_id else None
                if topic_row is not None:
                    affected_topic_id, topic_name = topic_row.id, topic_row.name
                else:
                    affected_topic_id, topic_name = _get_or_create_uncategorized_topic(session), UNCATEGORIZED_TOPIC
                session.add(
                    KnowledgeItemRow(
                        id=f"{row.meeting_id}:accepted-{row.id.split(':', 1)[1]}",
                        meeting_id=row.meeting_id,
                        topic_id=affected_topic_id,
                        type=_normalize_item_type(row.type),
                        description=row.description,
                        theme=topic_name,
                        status="Open",
                        confidence="HIGH",
                        owner=owner,
                        stakeholders=[owner] if owner else [],
                        due_date=None,
                        due_date_source_text=None,
                        rationale=row.reason,
                        resolution=None,
                        evidence_speaker=row.evidence_speaker,
                        evidence_timestamp=row.evidence_timestamp,
                        evidence_quote=row.evidence_quote,
                        evidence_context=row.evidence_context,
                        related_ids=[],
                        embedding=vector,
                    )
                )

        row.status = status
        session.commit()
        session.refresh(row)
        result = _review_candidate_from_row(row)
    if affected_topic_id:
        recalculate_priority_for_topics({affected_topic_id}, trigger="review_accepted")
    return result


def _priority_info_from_row(row: TopicRow) -> TopicPriorityInfo | None:
    if row.calculated_priority is None or row.calculated_priority_score is None:
        return None
    manual_override = None
    if row.manual_priority_override is not None:
        manual_override = ManualPriorityOverride(
            priority=row.manual_priority_override,
            reason=row.manual_override_reason,
            overridden_at=row.manual_override_at or "",
        )
    return TopicPriorityInfo(
        calculated_priority=row.calculated_priority,
        calculated_score=row.calculated_priority_score,
        effective_priority=row.manual_priority_override or row.calculated_priority,
        confidence=row.priority_confidence or "LOW",
        signals=[TopicPrioritySignal.model_validate(s) for s in (row.priority_signals or [])],
        hard_escalations=[HardEscalation.model_validate(e) for e in (row.priority_hard_escalations or [])],
        explanation=row.priority_explanation or "",
        calculated_at=row.priority_calculated_at or "",
        algorithm_version=row.priority_algorithm_version or topic_priority.TOPIC_PRIORITY_ALGORITHM_VERSION,
        semantic_contribution=(
            SemanticContribution.model_validate(row.priority_semantic_contribution)
            if row.priority_semantic_contribution
            else None
        ),
        manual_override=manual_override,
    )


def _topic_from_row(row: TopicRow) -> Topic:
    items = [_item_from_row(item_row) for item_row in row.items]
    return Topic(
        id=row.id,
        name=row.name,
        status=row.status,
        items=items,
        stakeholders=list(dict.fromkeys(s for item in items for s in item.stakeholders)),
        priority=_priority_info_from_row(row),
        notes=[_note_from_row(n) for n in row.notes],
        tags=list(row.tags or []),
        images=[
            TopicImage(
                id=i.id, filename=i.filename, content_type=i.content_type, size=i.size, created_at=i.created_at
            )
            for i in row.images
        ],
    )


def all_topics() -> list[Topic]:
    """All persisted topics, including ones with zero items (unlike the old theme-grouping)."""
    with db.get_session() as session:
        stmt = select(TopicRow).options(selectinload(TopicRow.items))
        rows = session.execute(stmt).scalars().all()
        return [_topic_from_row(row) for row in rows]


def get_topic_by_id(topic_id: str) -> Topic | None:
    with db.get_session() as session:
        stmt = select(TopicRow).where(TopicRow.id == topic_id).options(selectinload(TopicRow.items))
        row = session.execute(stmt).scalar_one_or_none()
        return _topic_from_row(row) if row is not None else None


def _priority_history_entry_from_row(row: TopicPriorityHistoryRow) -> TopicPriorityHistoryEntry:
    return TopicPriorityHistoryEntry(
        id=row.id,
        topic_id=row.topic_id,
        previous_priority=row.previous_priority,
        new_priority=row.new_priority,
        previous_score=row.previous_score,
        new_score=row.new_score,
        changed_at=row.changed_at,
        algorithm_version=row.algorithm_version,
        primary_drivers=list(row.primary_drivers),
        trigger=row.trigger,
        source_knowledge_item_ids=list(row.source_knowledge_item_ids),
    )


def _persist_priority_result(session: Session, row: TopicRow, result: TopicPriorityInfo, trigger: str) -> None:
    """Writes the calculated result onto the TopicRow and appends a history row iff the
    category changed. Never touches manual_priority_override/manual_override_reason/at."""
    previous_priority = row.calculated_priority
    previous_score = row.calculated_priority_score

    row.calculated_priority = result.calculated_priority
    row.calculated_priority_score = result.calculated_score
    row.priority_confidence = result.confidence
    row.priority_signals = [s.model_dump(by_alias=True) for s in result.signals]
    row.priority_hard_escalations = [e.model_dump(by_alias=True) for e in result.hard_escalations]
    row.priority_explanation = result.explanation
    row.priority_algorithm_version = result.algorithm_version
    row.priority_semantic_contribution = (
        result.semantic_contribution.model_dump(by_alias=True) if result.semantic_contribution else None
    )
    row.priority_calculated_at = result.calculated_at

    if previous_priority is not None and previous_priority != result.calculated_priority:
        top_drivers = sorted(
            (s for s in result.signals if s.weighted_score > 0), key=lambda s: s.weighted_score, reverse=True
        )[:3]
        source_ids = sorted({iid for s in result.signals for iid in s.source_knowledge_item_ids})
        session.add(
            TopicPriorityHistoryRow(
                id=str(uuid.uuid4()),
                topic_id=row.id,
                previous_priority=previous_priority,
                new_priority=result.calculated_priority,
                previous_score=previous_score,
                new_score=result.calculated_score,
                changed_at=result.calculated_at,
                algorithm_version=result.algorithm_version,
                primary_drivers=[d.explanation for d in top_drivers],
                trigger=trigger,
                source_knowledge_item_ids=source_ids,
            )
        )


def _calculate_priority_for_row(session: Session, row: TopicRow) -> TopicPriorityInfo:
    facts = topic_priority.TopicPrioritySignalExtractor().extract(session, row)
    previous = None
    if row.calculated_priority is not None and row.calculated_priority_score is not None:
        previous = topic_priority.PreviousPriorityState(priority=row.calculated_priority, score=row.calculated_priority_score)
    classifier = topic_priority.get_semantic_classifier()
    semantic = classifier.classify(topic_priority.build_semantic_context(row, facts))
    return topic_priority.TopicPriorityScorer().score(facts, previous, semantic)


def recalculate_priority_for_topic(topic_id: str, trigger: str = "manual") -> Topic | None:
    with db.get_session() as session:
        stmt = select(TopicRow).where(TopicRow.id == topic_id).options(selectinload(TopicRow.items))
        row = session.execute(stmt).scalar_one_or_none()
        if row is None:
            return None
        result = _calculate_priority_for_row(session, row)
        _persist_priority_result(session, row, result, trigger)
        session.commit()
        session.refresh(row)
        return _topic_from_row(row)


def recalculate_priority_for_topics(topic_ids: set[str], trigger: str) -> None:
    """Recomputes only the given (affected) topics - not every Topic in the system."""
    for topic_id in topic_ids:
        if topic_id:
            recalculate_priority_for_topic(topic_id, trigger=trigger)


def recalculate_all_topic_priorities(trigger: str = "recalculate_all") -> int:
    with db.get_session() as session:
        rows = session.execute(select(TopicRow).options(selectinload(TopicRow.items))).scalars().all()
        for row in rows:
            result = _calculate_priority_for_row(session, row)
            _persist_priority_result(session, row, result, trigger)
        session.commit()
        return len(rows)


def set_priority_override(topic_id: str, priority: str | None, reason: str | None) -> Topic | None:
    with db.get_session() as session:
        row = session.get(TopicRow, topic_id)
        if row is None:
            return None
        row.manual_priority_override = priority
        row.manual_override_reason = reason if priority is not None else None
        row.manual_override_at = datetime.now(timezone.utc).isoformat() if priority is not None else None
        session.commit()
    return get_topic_by_id(topic_id)


def set_item_priority_override(item_id: str, priority: str | None, reason: str | None) -> KnowledgeItem | None:
    """Sets/clears a manual priority override directly on an item - independent of, and never
    touched by, its Topic's automatic priority recalculation (see _item_effective_priority)."""
    with db.get_session() as session:
        row = session.get(KnowledgeItemRow, item_id)
        if row is None:
            return None
        row.manual_priority_override = priority
        row.manual_override_reason = reason if priority is not None else None
        row.manual_override_at = datetime.now(timezone.utc).isoformat() if priority is not None else None
        session.commit()
        session.refresh(row)
        return _item_from_row(row)


def set_item_status(item_id: str, status: str) -> KnowledgeItem | None:
    with db.get_session() as session:
        row = session.get(KnowledgeItemRow, item_id)
        if row is None:
            return None
        row.status = status
        session.commit()
        session.refresh(row)
        return _item_from_row(row)


def set_topic_status(topic_id: str, status: str) -> Topic | None:
    with db.get_session() as session:
        row = session.get(TopicRow, topic_id)
        if row is None:
            return None
        row.status = status
        session.commit()
    return get_topic_by_id(topic_id)


def add_item_note(item_id: str, body: str) -> KnowledgeItem | None:
    with db.get_session() as session:
        row = session.get(KnowledgeItemRow, item_id)
        if row is None:
            return None
        row.notes.append(NoteRow(id=uuid.uuid4().hex, body=body, created_at=datetime.now(timezone.utc).isoformat()))
        session.commit()
        session.refresh(row)
        return _item_from_row(row)


def delete_item_note(item_id: str, note_id: str) -> KnowledgeItem | None:
    with db.get_session() as session:
        row = session.get(KnowledgeItemRow, item_id)
        if row is None:
            return None
        row.notes = [n for n in row.notes if n.id != note_id]
        session.commit()
        session.refresh(row)
        return _item_from_row(row)


def update_item_note(item_id: str, note_id: str, body: str) -> KnowledgeItem | None:
    with db.get_session() as session:
        row = session.get(KnowledgeItemRow, item_id)
        if row is None:
            return None
        for note in row.notes:
            if note.id == note_id:
                note.body = body
        session.commit()
        session.refresh(row)
        return _item_from_row(row)


def update_topic_note(topic_id: str, note_id: str, body: str) -> Topic | None:
    with db.get_session() as session:
        row = session.get(TopicRow, topic_id)
        if row is None:
            return None
        for note in row.notes:
            if note.id == note_id:
                note.body = body
        session.commit()
    return get_topic_by_id(topic_id)


def add_topic_note(topic_id: str, body: str) -> Topic | None:
    with db.get_session() as session:
        row = session.get(TopicRow, topic_id)
        if row is None:
            return None
        row.notes.append(NoteRow(id=uuid.uuid4().hex, body=body, created_at=datetime.now(timezone.utc).isoformat()))
        session.commit()
    return get_topic_by_id(topic_id)


def delete_topic_note(topic_id: str, note_id: str) -> Topic | None:
    with db.get_session() as session:
        row = session.get(TopicRow, topic_id)
        if row is None:
            return None
        row.notes = [n for n in row.notes if n.id != note_id]
        session.commit()
    return get_topic_by_id(topic_id)


def _delete_image_objects(keys: list[str]) -> None:
    """Best-effort: a failed delete leaves an unreferenced object, which is preferable to failing the request."""
    for key in keys:
        try:
            s3_store.delete_object(key)
        except Exception:
            logger.warning("could not delete image object %s from S3", key, exc_info=True)


def add_topic_image(topic_id: str, filename: str | None, body: bytes) -> Topic | None:
    """Stores the image in S3 and records it on the topic. None if the topic is missing."""
    if len(body) > MAX_IMAGE_BYTES:
        raise ImageTooLarge(MAX_IMAGE_BYTES)
    sniffed = _sniff_image_type(body)
    if sniffed is None:
        raise UnsupportedImageType()
    content_type, extension = sniffed
    with db.get_session() as session:
        row = session.get(TopicRow, topic_id)
        if row is None:
            return None
        image_id = uuid.uuid4().hex
        key = s3_store.topic_image_key(topic_id, image_id, extension)
        s3_store.put_object(key, body, content_type)
        try:
            row.images.append(
                TopicImageRow(
                    id=image_id,
                    key=key,
                    filename=_display_filename(filename),
                    content_type=content_type,
                    size=len(body),
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            _delete_image_objects([key])
            raise
    return get_topic_by_id(topic_id)


def delete_topic_image(topic_id: str, image_id: str) -> Topic | None:
    """Removes the image row and its S3 object. None if the topic is missing; a missing image is a no-op."""
    with db.get_session() as session:
        row = session.get(TopicRow, topic_id)
        if row is None:
            return None
        doomed = [i for i in row.images if i.id == image_id]
        keys = [i.key for i in doomed]
        row.images = [i for i in row.images if i.id != image_id]
        session.commit()
    _delete_image_objects(keys)
    return get_topic_by_id(topic_id)


def get_topic_image(topic_id: str, image_id: str) -> tuple[bytes, str] | None:
    """(bytes, content type) of a topic's image, or None if the topic has no such image."""
    with db.get_session() as session:
        image = session.get(TopicImageRow, image_id)
        if image is None or image.topic_id != topic_id:
            return None
        key, content_type = image.key, image.content_type
    return s3_store.get_object_bytes(key), content_type


# Tag lists are reassigned (never appended to) below: SQLAlchemy doesn't track in-place mutation of ARRAY columns.
def add_topic_tag(topic_id: str, tag: str) -> Topic | None:
    with db.get_session() as session:
        row = session.get(TopicRow, topic_id)
        if row is None:
            return None
        row.tags = _with_tag(row.tags, tag)
        session.commit()
    return get_topic_by_id(topic_id)


def remove_topic_tag(topic_id: str, tag: str) -> Topic | None:
    with db.get_session() as session:
        row = session.get(TopicRow, topic_id)
        if row is None:
            return None
        row.tags = _without_tag(row.tags, tag)
        session.commit()
    return get_topic_by_id(topic_id)


def add_item_tag(item_id: str, tag: str) -> KnowledgeItem | None:
    with db.get_session() as session:
        row = session.get(KnowledgeItemRow, item_id)
        if row is None:
            return None
        row.tags = _with_tag(row.tags, tag)
        session.commit()
        session.refresh(row)
        return _item_from_row(row)


def remove_item_tag(item_id: str, tag: str) -> KnowledgeItem | None:
    with db.get_session() as session:
        row = session.get(KnowledgeItemRow, item_id)
        if row is None:
            return None
        row.tags = _without_tag(row.tags, tag)
        session.commit()
        session.refresh(row)
        return _item_from_row(row)


def get_priority_history(topic_id: str) -> list[TopicPriorityHistoryEntry]:
    with db.get_session() as session:
        stmt = (
            select(TopicPriorityHistoryRow)
            .where(TopicPriorityHistoryRow.topic_id == topic_id)
            .order_by(TopicPriorityHistoryRow.changed_at.desc())
        )
        rows = session.execute(stmt).scalars().all()
    return [_priority_history_entry_from_row(row) for row in rows]


def get_recent_priority_escalations(days: int = 14) -> list[TopicPriorityHistoryEntry]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with db.get_session() as session:
        stmt = (
            select(TopicPriorityHistoryRow)
            .where(TopicPriorityHistoryRow.changed_at >= cutoff)
            .order_by(TopicPriorityHistoryRow.changed_at.desc())
        )
        rows = session.execute(stmt).scalars().all()
    entries = [_priority_history_entry_from_row(row) for row in rows]
    return [
        entry
        for entry in entries
        if entry.previous_priority is not None
        and _PRIORITY_RANK.get(entry.new_priority, 0) > _PRIORITY_RANK.get(entry.previous_priority, 0)
    ]


def create_topic(name: str) -> Topic:
    with db.get_session() as session:
        existing = session.execute(select(TopicRow).where(TopicRow.name == name)).scalar_one_or_none()
        if existing is not None:
            raise TopicNameConflict(name)
        row = TopicRow(id=str(uuid.uuid4()), name=name)
        session.add(row)
        session.commit()
        session.refresh(row)
        return _topic_from_row(row)


def create_item(topic_id: str, payload: ItemCreate) -> KnowledgeItem | None:
    """Files a manually written item under a topic. Manual items hang off a synthetic "Manual entries"
    meeting because knowledge_items.meeting_id is NOT NULL. Returns None if the topic doesn't exist."""
    with db.get_session() as session:
        topic_row = session.get(TopicRow, topic_id)
        if topic_row is None:
            return None
        if session.get(MeetingRow, MANUAL_MEETING_ID) is None:
            session.add(
                MeetingRow(
                    id=MANUAL_MEETING_ID,
                    title="Manual entries",
                    date=datetime.now(timezone.utc).date().isoformat(),
                    source_url="",
                )
            )
        row = KnowledgeItemRow(
            id=f"{MANUAL_MEETING_ID}:{uuid.uuid4()}",
            meeting_id=MANUAL_MEETING_ID,
            topic_id=topic_id,
            type=payload.type,
            description=payload.description,
            theme=topic_row.name,
            status="Open",
            confidence="HIGH",
            owner=payload.owner,
            stakeholders=[payload.owner] if payload.owner else [],
            due_date=payload.due_date,
            due_date_source_text=None,
            rationale=payload.rationale,
            resolution=None,
            evidence_speaker=None,
            evidence_timestamp=None,
            evidence_quote="Added manually",
            evidence_context=None,
            related_ids=[],
            embedding=embeddings.embed_text(payload.description),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        item = _item_from_row(row)
    recalculate_priority_for_topics({topic_id}, trigger="item_added")
    return item


def is_manual_item(row: KnowledgeItemRow) -> bool:
    return row.meeting_id == MANUAL_MEETING_ID


def update_item(item_id: str, payload: ItemUpdate) -> KnowledgeItem | None:
    """Edits description/owner/due date/rationale (and type, manual items only). Returns None if missing."""
    fields = payload.model_fields_set
    with db.get_session() as session:
        row = session.get(KnowledgeItemRow, item_id)
        if row is None:
            return None
        if "type" in fields and payload.type != row.type and not is_manual_item(row):
            raise ItemNotEditable("The type of an item extracted from a meeting cannot be changed")
        if "type" in fields:
            row.type = payload.type
        if "description" in fields and payload.description != row.description:
            row.description = payload.description
            row.embedding = embeddings.embed_text(payload.description)
        if "owner" in fields:
            row.owner = payload.owner
            row.stakeholders = [payload.owner] if payload.owner else []
        if "due_date" in fields:
            row.due_date = payload.due_date
            row.due_date_source_text = None
        if "rationale" in fields:
            row.rationale = payload.rationale
        session.commit()
        session.refresh(row)
        item, topic_id = _item_from_row(row), row.topic_id
    if topic_id:
        recalculate_priority_for_topics({topic_id}, trigger="item_edited")
    return item


def delete_item(item_id: str) -> bool:
    """Deletes a manually added item (its notes cascade). False if missing; ItemNotDeletable for
    meeting-extracted items, which the next ingest would simply re-create."""
    with db.get_session() as session:
        row = session.get(KnowledgeItemRow, item_id)
        if row is None:
            return False
        if not is_manual_item(row):
            raise ItemNotDeletable(item_id)
        topic_id = row.topic_id
        session.delete(row)
        session.commit()
    if topic_id:
        recalculate_priority_for_topics({topic_id}, trigger="item_deleted")
    return True


def update_topic(topic_id: str, name: str) -> Topic | None:
    with db.get_session() as session:
        row = session.get(TopicRow, topic_id)
        if row is None:
            return None
        conflict = session.execute(
            select(TopicRow).where(TopicRow.name == name, TopicRow.id != topic_id)
        ).scalar_one_or_none()
        if conflict is not None:
            raise TopicNameConflict(name)
        row.name = name
        for item_row in session.execute(
            select(KnowledgeItemRow).where(KnowledgeItemRow.topic_id == topic_id)
        ).scalars():
            item_row.theme = name
        session.commit()
        session.refresh(row)
        return _topic_from_row(row)


def delete_topic(topic_id: str) -> bool:
    with db.get_session() as session:
        stmt = select(TopicRow).where(TopicRow.id == topic_id).options(selectinload(TopicRow.items))
        row = session.execute(stmt).scalar_one_or_none()
        if row is None:
            return False
        if row.items:
            raise TopicHasItems(len(row.items))
        image_keys = [i.key for i in row.images]
        session.delete(row)
        session.commit()
    _delete_image_objects(image_keys)
    return True


def assign_item_topic(item_id: str, topic_id: str | None) -> KnowledgeItem | None:
    with db.get_session() as session:
        item_row = session.get(KnowledgeItemRow, item_id)
        if item_row is None:
            return None
        old_topic_id = item_row.topic_id
        topic_name = None
        if topic_id is not None:
            topic_row = session.get(TopicRow, topic_id)
            if topic_row is None:
                raise ValueError("topic not found")
            topic_name = topic_row.name
        item_row.topic_id = topic_id
        item_row.theme = topic_name
        session.commit()
        session.refresh(item_row)
        result = _item_from_row(item_row)
    recalculate_priority_for_topics({old_topic_id, topic_id}, trigger="item_topic_reassigned")
    return result


def assign_items_topic(item_ids: list[str], topic_id: str | None) -> list[KnowledgeItem]:
    """Bulk version of assign_item_topic - one transaction and one priority recalc pass
    for all affected items, instead of looping the single-item version per id."""
    with db.get_session() as session:
        topic_name = None
        if topic_id is not None:
            topic_row = session.get(TopicRow, topic_id)
            if topic_row is None:
                raise ValueError("topic not found")
            topic_name = topic_row.name
        item_rows = session.execute(
            select(KnowledgeItemRow).where(KnowledgeItemRow.id.in_(item_ids))
        ).scalars().all()
        found_ids = {row.id for row in item_rows}
        missing = set(item_ids) - found_ids
        if missing:
            raise ValueError(f"items not found: {sorted(missing)}")
        old_topic_ids = {row.topic_id for row in item_rows}
        for row in item_rows:
            row.topic_id = topic_id
            row.theme = topic_name
        session.commit()
        for row in item_rows:
            session.refresh(row)
        results = [_item_from_row(row) for row in item_rows]
    recalculate_priority_for_topics(old_topic_ids | {topic_id}, trigger="items_topic_bulk_reassigned")
    return results


def merge_topics(source_topic_id: str, target_topic_id: str) -> Topic:
    """Moves every item out of the source topic into the target topic, then deletes the
    now-empty source topic (backs drag-and-drop merging, e.g. "Uncategorized" onto a topic)."""
    if source_topic_id == target_topic_id:
        raise ValueError("cannot merge a topic into itself")
    with db.get_session() as session:
        source = session.get(TopicRow, source_topic_id)
        target = session.get(TopicRow, target_topic_id)
        if source is None or target is None:
            raise LookupError("topic not found")
        session.execute(
            update(KnowledgeItemRow)
            .where(KnowledgeItemRow.topic_id == source_topic_id)
            .values(topic_id=target_topic_id, theme=target.name)
        )
        # keep the source topic's notes: repoint them before the delete cascades over them
        session.execute(update(NoteRow).where(NoteRow.topic_id == source_topic_id).values(topic_id=target_topic_id))
        # same for images: the S3 objects stay where they are, only the owning topic changes
        session.execute(
            update(TopicImageRow).where(TopicImageRow.topic_id == source_topic_id).values(topic_id=target_topic_id)
        )
        session.expire(source)
        session.delete(source)
        session.commit()

    recalculate_priority_for_topics({target_topic_id}, trigger="topic_merge")
    merged = get_topic_by_id(target_topic_id)
    assert merged is not None
    return merged


def _topic_centroids(rows: list[TopicRow]) -> dict[str, np.ndarray]:
    """Mean embedding per topic, skipping topics with no embedded items."""
    return similarity.topic_centroids({row.id: [item.embedding for item in row.items] for row in rows})


def suggested_topic_merges(
    min_similarity: float = 0.5, limit: int = 10, max_related_items: int = 5
) -> list[TopicMergeSuggestion]:
    """Flags pairs of topics whose items are semantically close on average, for a human to review
    and merge - never merges automatically. Excludes "Uncategorized" (a heterogeneous catch-all
    with its own dedicated drag-to-merge flow), topics with no embedded items, and topics that
    already have `max_related_items` or more items (large, already-established topics don't need
    further consolidation suggestions)."""
    with db.get_session() as session:
        stmt = select(TopicRow).options(selectinload(TopicRow.items))
        rows = [
            row
            for row in session.execute(stmt).scalars().all()
            if row.name != "Uncategorized" and len(row.items) < max_related_items
        ]
        topics_by_id = {row.id: _topic_from_row(row) for row in rows}
        vectors = _topic_centroids(rows)

    suggestions: list[TopicMergeSuggestion] = []
    ids = list(vectors.keys())
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = vectors[ids[i]], vectors[ids[j]]
            similarity = similarity_of(a, b)
            if similarity >= min_similarity:
                suggestions.append(
                    TopicMergeSuggestion(
                        topic_a=topics_by_id[ids[i]], topic_b=topics_by_id[ids[j]], similarity=similarity
                    )
                )
    suggestions.sort(key=lambda s: s.similarity, reverse=True)
    return suggestions[:limit]


def related_topics(
    topic_id: str, min_similarity: float = PROPOSAL_HINT_SIMILARITY, limit: int = 5
) -> list[RelatedTopic] | None:
    """Topics whose items are semantically closest on average to the given topic's, most similar
    first. Returns None if the topic doesn't exist; excludes "Uncategorized" (a catch-all whose
    centroid isn't meaningful) and topics with no embedded items."""
    with db.get_session() as session:
        stmt = select(TopicRow).options(selectinload(TopicRow.items))
        rows = session.execute(stmt).scalars().all()
        if not any(row.id == topic_id for row in rows):
            return None
        candidates = {row.id: row for row in rows if row.id != topic_id and row.name != UNCATEGORIZED_TOPIC}
        vectors = _topic_centroids(rows)
        target = vectors.get(topic_id)
        if target is None:
            return []
        related = []
        for other_id, row in candidates.items():
            other = vectors.get(other_id)
            if other is None:
                continue
            similarity = similarity_of(target, other)
            if similarity >= min_similarity:
                related.append(
                    RelatedTopic(
                        id=row.id, name=row.name, status=row.status, similarity=similarity, item_count=len(row.items)
                    )
                )
    related.sort(key=lambda r: r.similarity, reverse=True)
    return related[:limit]


def suggested_item_topics(
    min_score: float = 0.0, limit: int | None = None, candidates: int = topic_suggestions.DEFAULT_CANDIDATES
) -> list[ItemTopicSuggestion]:
    """Per-item counterpart to suggested_topic_merges: for each item still sitting in
    "Uncategorized", ranks the existing topics it most likely belongs to (best first, with a
    confidence band), for a human to review and confirm via the normal move-item flow - never
    assigns automatically."""
    with db.get_session() as session:
        stmt = select(TopicRow).options(selectinload(TopicRow.items))
        rows = list(session.execute(stmt).scalars().all())
        uncategorized = next((row for row in rows if row.name == UNCATEGORIZED_TOPIC), None)
        if uncategorized is None or not uncategorized.items:
            return []
        ranker = _load_topic_ranker(session)
        names = {row.id: (row.name, len(row.items)) for row in rows}
        embedded = [item_row for item_row in uncategorized.items if item_row.embedding is not None]
        items = [_item_from_row(item_row) for item_row in embedded]
        ranked = ranker.rank_many(
            [item_row.embedding for item_row in embedded], [item_row.description for item_row in embedded], candidates
        )
        # the cached ranker can see a topic created/deleted after `rows` was read - skip ones not in `rows`
        ranked = [[r for r in best if r.topic_id in names] for best in ranked]

    suggestions = [
        ItemTopicSuggestion(
            item=item,
            candidates=[
                TopicCandidate(
                    topic_id=r.topic_id,
                    topic_name=names[r.topic_id][0],
                    item_count=names[r.topic_id][1],
                    score=r.score,
                    centroid_similarity=r.centroid_similarity,
                )
                for r in best
            ],
            score=best[0].score,
            confidence=topic_suggestions.confidence_band(best[0].score),
        )
        for item, best in zip(items, ranked)
        if best and best[0].score >= min_score
    ]
    suggestions.sort(key=lambda s: s.score, reverse=True)
    return suggestions if limit is None else suggestions[:limit]


def topic_proposals() -> list[TopicProposal]:
    """Groups items awaiting a topic decision by the new-topic name the extractor proposed. Each
    proposal also carries the best-ranked existing topic (when a confident match) as a hint for the
    reviewer's "use existing topic" override."""
    with db.get_session() as session:
        item_rows = session.execute(
            select(KnowledgeItemRow)
            .where(KnowledgeItemRow.suggested_topic.is_not(None))
            .options(selectinload(KnowledgeItemRow.topic))
            .order_by(KnowledgeItemRow.id)
        ).scalars().all()
        if not item_rows:
            return []
        ranker = _load_topic_ranker(session)
        grouped: dict[str, list[KnowledgeItemRow]] = {}
        for row in item_rows:
            grouped.setdefault(row.suggested_topic, []).append(row)
        proposals: list[TopicProposal] = []
        for name, rows in grouped.items():
            vectors = [np.array(row.embedding) for row in rows if row.embedding is not None]
            text = " ".join([name, *(row.description for row in rows)])
            hint = _confident_topic_id(ranker.rank(np.mean(vectors, axis=0), text, top_n=1)) if vectors else None
            proposals.append(
                TopicProposal(
                    name=name,
                    items=[_item_from_row(row) for row in rows],
                    suggested_existing_topic_id=hint,
                )
            )
    proposals.sort(key=lambda proposal: (-len(proposal.items), proposal.name))
    return proposals


def accept_topic_proposal(
    suggested_name: str, topic_name: str | None = None, existing_topic_id: str | None = None
) -> list[KnowledgeItem]:
    """Human decision on a proposal: files its items under `existing_topic_id` (override), or under a
    topic named `topic_name` (default: the suggested name), creating that topic only now."""
    with db.get_session() as session:
        item_rows = session.execute(
            select(KnowledgeItemRow).where(KnowledgeItemRow.suggested_topic == suggested_name)
        ).scalars().all()
        if not item_rows:
            raise LookupError(suggested_name)
        if existing_topic_id is not None:
            target = session.get(TopicRow, existing_topic_id)
            if target is None:
                raise ValueError("topic not found")
        else:
            name = (topic_name or suggested_name).strip()
            if not name:
                raise ValueError("topic name must not be empty")
            target = session.execute(select(TopicRow).where(TopicRow.name == name)).scalar_one_or_none()
            if target is None:
                target = TopicRow(id=str(uuid.uuid4()), name=name)
                session.add(target)
        target_id, target_name = target.id, target.name
        old_topic_ids = {row.topic_id for row in item_rows}
        for row in item_rows:
            row.topic_id = target_id
            row.theme = target_name
            row.suggested_topic = None
        session.commit()
        results = [_item_from_row(row) for row in item_rows]
    recalculate_priority_for_topics(old_topic_ids | {target_id}, trigger="topic_proposal_accepted")
    return results


def reject_topic_proposal(suggested_name: str) -> int:
    """Dismisses a proposal: its items stay where ingestion put them (Uncategorized)."""
    with db.get_session() as session:
        item_rows = session.execute(
            select(KnowledgeItemRow).where(KnowledgeItemRow.suggested_topic == suggested_name)
        ).scalars().all()
        for row in item_rows:
            row.suggested_topic = None
        session.commit()
        return len(item_rows)


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


def search(query: str, limit: int = 20) -> tuple[list[KnowledgeItem], list[Topic]]:
    """Free-text search: finds the `limit` nearest items by pgvector cosine distance, then
    ranks that candidate set by confidence (HIGH first), using distance as a tiebreak - plus the
    topics that own them, each topic carrying all of its items, not just the match."""
    vector = embeddings.embed_text(query)
    with db.get_session() as session:
        distance = KnowledgeItemRow.embedding.cosine_distance(vector)
        stmt = (
            select(KnowledgeItemRow, distance.label("distance"))
            .order_by(distance)
            .limit(limit)
        )
        rows_with_distance = session.execute(stmt).all()
        rows_with_distance.sort(key=lambda pair: (_CONFIDENCE_RANK.get(pair[0].confidence, 99), pair[1]))
        rows = [row for row, _ in rows_with_distance]
        items = [_item_from_row(row) for row in rows]

        topic_ids = list(dict.fromkeys(row.topic_id for row in rows if row.topic_id is not None))
        topics: list[Topic] = []
        if topic_ids:
            topic_stmt = (
                select(TopicRow).where(TopicRow.id.in_(topic_ids)).options(selectinload(TopicRow.items))
            )
            topic_rows = session.execute(topic_stmt).scalars().all()
            topics_by_id = {row.id: _topic_from_row(row) for row in topic_rows}
            topics = [topics_by_id[tid] for tid in topic_ids if tid in topics_by_id]

    return items, topics


def build_graph(min_semantic_similarity: float = 0.35) -> GraphData:
    """Computes the full item-to-item graph: nodes are all knowledge items, edges come from three
    sources layered by confidence - evidence-grounded `related_ids` (certain), shared topic
    membership (structural), and embedding cosine similarity above `min_semantic_similarity`
    (a possible-relationship discovery layer, never an assertion). Each pair gets at most one
    edge, preferring the most-confident kind available for that pair."""
    with db.get_session() as session:
        stmt = select(KnowledgeItemRow).options(selectinload(KnowledgeItemRow.topic))
        rows = session.execute(stmt).scalars().all()

    all_ids = {row.id for row in rows}
    nodes = [
        GraphNode(
            id=row.id,
            type=row.type,
            description=row.description,
            confidence=row.confidence,
            owner=row.owner,
            topic_id=row.topic_id,
            topic_name=row.topic.name if row.topic is not None else None,
            meeting_id=row.meeting_id,
            priority=_item_effective_priority(row)[0],
        )
        for row in rows
    ]

    edges: list[GraphEdge] = []
    seen_pairs: set[frozenset[str]] = set()

    def _add_edge(a: str, b: str, kind: str, weight: float = 1.0) -> None:
        pair = frozenset((a, b))
        if a == b or pair in seen_pairs:
            return
        seen_pairs.add(pair)
        edges.append(GraphEdge(source=a, target=b, kind=kind, weight=weight))

    for row in rows:
        for raw_id in row.related_ids:
            target = next(
                (candidate for candidate in all_ids if candidate.split(":", 1)[-1] == raw_id or candidate == raw_id),
                None,
            )
            if target is not None:
                _add_edge(row.id, target, "related")

    topic_groups: dict[str, list[str]] = {}
    for row in rows:
        if row.topic_id is None or row.topic is None or row.topic.name == "Uncategorized":
            continue
        topic_groups.setdefault(row.topic_id, []).append(row.id)
    for group_ids in topic_groups.values():
        for a, b in itertools.combinations(sorted(group_ids), 2):
            _add_edge(a, b, "topic")

    vectors = {row.id: np.array(row.embedding) for row in rows if row.embedding is not None}
    vector_ids = list(vectors.keys())
    for i in range(len(vector_ids)):
        for j in range(i + 1, len(vector_ids)):
            a, b = vector_ids[i], vector_ids[j]
            va, vb = vectors[a], vectors[b]
            similarity = similarity_of(va, vb)
            if similarity >= min_semantic_similarity:
                _add_edge(a, b, "semantic", weight=similarity)

    with db.get_session() as session:
        topic_rows = session.execute(select(TopicRow).options(selectinload(TopicRow.items))).scalars().all()
    topics = [
        GraphTopic(id=row.id, name=row.name, item_count=len(row.items))
        for row in topic_rows
        if row.name != UNCATEGORIZED_TOPIC
    ]
    topic_links = [
        TopicLink(source=topic.id, target=related.id, similarity=related.similarity)
        for topic in topics
        for related in related_topics(topic.id) or []
    ]

    return GraphData(nodes=nodes, edges=edges, topics=topics, topic_links=topic_links)


def _resolve_related_item_id(raw_id: str, item_by_id: dict[str, KnowledgeItem], suffix_to_id: dict[str, str]) -> str | None:
    """related_ids values may be a bare suffix (e.g. "D-004") or a full "meeting:id" - same
    dual-format handling as related_items()/build_graph() above."""
    if raw_id in item_by_id:
        return raw_id
    return suffix_to_id.get(raw_id)


def _is_follow_up_action_due(item: KnowledgeItem, ref_date: date, due_soon_days: int) -> bool:
    if item.due_date is None:
        return True  # missing due date is itself a follow-up signal (ambiguous commitment)
    due = topic_priority.parse_iso_date(item.due_date)
    if due is None:
        return True  # unparseable/ambiguous source text gets the same treatment as missing
    return due <= ref_date + timedelta(days=due_soon_days)


def _follow_up_sort_key(item: KnowledgeItem) -> tuple[int, date, str]:
    """Questions first, then actions (overdue/undated first via ascending due date), then decisions."""
    type_rank = {"QUESTION": 0, "ACTION": 1, "DECISION": 2}.get(item.type, 3)
    due = topic_priority.parse_iso_date(item.due_date) or date.min
    return (type_rank, due, item.id)


def get_follow_up(limit: int = 5, due_soon_days: int = 7) -> FollowUpResponse:
    """Ranks topics by priority/score and surfaces only the items worth raising at the next
    meeting: open questions, due-soon/overdue/undated actions, and decisions with an unresolved
    dependent - plus items pulled in from other topics via related_ids."""
    topics = all_topics()
    ref_date = datetime.now(timezone.utc).date()

    item_by_id: dict[str, KnowledgeItem] = {}
    topic_id_by_item_id: dict[str, str] = {}
    topic_name_by_id: dict[str, str] = {}
    for topic in topics:
        topic_name_by_id[topic.id] = topic.name
        for item in topic.items:
            item_by_id[item.id] = item
            topic_id_by_item_id[item.id] = topic.id
    suffix_to_id: dict[str, str] = {}
    for item_id in item_by_id:
        suffix_to_id.setdefault(item_id.split(":", 1)[-1], item_id)

    # reverse related_ids map: item id -> ids of items that list it in their own related_ids
    referenced_by: dict[str, list[str]] = {}
    for item in item_by_id.values():
        for raw_id in item.related_ids:
            target_id = _resolve_related_item_id(raw_id, item_by_id, suffix_to_id)
            if target_id is not None:
                referenced_by.setdefault(target_id, []).append(item.id)

    follow_up_ids: set[str] = set()
    for item in item_by_id.values():
        if item.type == "QUESTION":
            if not topic_priority.is_resolved_status(item.status):
                follow_up_ids.add(item.id)
        elif item.type == "ACTION":
            if not topic_priority.is_resolved_status(item.status) and _is_follow_up_action_due(
                item, ref_date, due_soon_days
            ):
                follow_up_ids.add(item.id)
        elif item.type == "DECISION":
            dependents = referenced_by.get(item.id, [])
            if any(
                not topic_priority.is_resolved_status(item_by_id[dep_id].status)
                for dep_id in dependents
                if dep_id in item_by_id
            ):
                follow_up_ids.add(item.id)

    escalations_by_topic: dict[str, list[TopicPriorityHistoryEntry]] = {}
    for entry in get_recent_priority_escalations(14):
        escalations_by_topic.setdefault(entry.topic_id, []).append(entry)

    ranked: list[tuple[Topic, list[KnowledgeItem]]] = []
    for topic in topics:
        follow_up_items = sorted(
            (item for item in topic.items if item.id in follow_up_ids), key=_follow_up_sort_key
        )
        if follow_up_items:
            ranked.append((topic, follow_up_items))

    ranked.sort(
        key=lambda pair: (
            _PRIORITY_RANK.get(pair[0].priority.effective_priority, -1) if pair[0].priority else -1,
            pair[0].priority.calculated_score if pair[0].priority else 0.0,
        ),
        reverse=True,
    )
    selected = ranked[:limit]

    follow_up_topics: list[FollowUpTopic] = []
    for topic, follow_up_items in selected:
        topic_item_ids = {item.id for item in topic.items}
        candidates: list[tuple[str, str]] = []
        for item in topic.items:
            for raw_id in item.related_ids:
                target_id = _resolve_related_item_id(raw_id, item_by_id, suffix_to_id)
                if target_id is not None:
                    candidates.append((target_id, f"Related to {item.id} in this topic"))
            for referencing_id in referenced_by.get(item.id, []):
                candidates.append((referencing_id, f"References {item.id} in this topic"))

        related: list[FollowUpRelatedItem] = []
        seen_related_ids: set[str] = set()
        for other_id, reason in candidates:
            if other_id in topic_item_ids or other_id in seen_related_ids or other_id not in follow_up_ids:
                continue
            other_topic_id = topic_id_by_item_id.get(other_id)
            if other_topic_id is None or other_topic_id == topic.id:
                continue
            seen_related_ids.add(other_id)
            related.append(
                FollowUpRelatedItem(
                    item=item_by_id[other_id],
                    topic_id=other_topic_id,
                    topic_name=topic_name_by_id.get(other_topic_id, ""),
                    reason=reason,
                )
            )
            if len(related) >= 5:
                break

        topic_escalations = escalations_by_topic.get(topic.id, [])
        follow_up_topics.append(
            FollowUpTopic(
                topic=topic,
                follow_up_items=follow_up_items,
                escalated_recently=bool(topic_escalations),
                escalation_drivers=topic_escalations[0].primary_drivers if topic_escalations else [],
                related_from_other_topics=related,
            )
        )

    return FollowUpResponse(topics=follow_up_topics, generated_at=datetime.now(timezone.utc).isoformat())

