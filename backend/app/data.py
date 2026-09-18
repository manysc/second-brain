"""Queries Postgres for the meeting knowledge base. Ingestion (S3 -> Postgres) lives in app/ingest.py."""
from __future__ import annotations

import itertools
import uuid
from datetime import date, datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app import db, embeddings, topic_priority
from app.db_models import KnowledgeItemRow, MeetingRow, ReviewCandidateRow, TopicPriorityHistoryRow, TopicRow
from app.models import (
    Evidence,
    FollowUpRelatedItem,
    FollowUpResponse,
    FollowUpTopic,
    GraphData,
    GraphEdge,
    GraphNode,
    HardEscalation,
    ItemTopicSuggestion,
    ItemType,
    KnowledgeItem,
    ManualPriorityOverride,
    Meeting,
    ReviewCandidate,
    ReviewStatus,
    SemanticContribution,
    Topic,
    TopicMergeSuggestion,
    TopicPriorityHistoryEntry,
    TopicPriorityInfo,
    TopicPrioritySignal,
)

# cosine distance (embeddings are normalized, so 0=identical..~2=opposite) below which an
# accepted review candidate is treated as a duplicate of an existing item rather than promoted
DUPLICATE_MATCH_THRESHOLD = 0.2

# ranks used to detect an "escalation" (priority increased) in priority history
_PRIORITY_RANK = {"MINOR": 0, "MAJOR": 1, "CRITICAL": 2}

# search() ranks HIGH-confidence items first, ties broken by semantic distance
_CONFIDENCE_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


class TopicNameConflict(Exception):
    """Raised when creating/renaming a topic to a name that's already taken."""


class ReviewCandidateAlreadyDecided(Exception):
    """Raised when accepting/rejecting a review candidate that isn't PENDING anymore."""


class TopicHasItems(Exception):
    """Raised when deleting a topic that still has knowledge items assigned to it."""

    def __init__(self, item_count: int) -> None:
        super().__init__(item_count)
        self.item_count = item_count


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


def _item_from_row(row: KnowledgeItemRow) -> KnowledgeItem:
    effective_priority, manual_override = _item_effective_priority(row)
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
        effective_priority=effective_priority,
        manual_override=manual_override,
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


def _normalize_item_type(value: str) -> ItemType:
    normalized = value.upper()
    return normalized if normalized in ("IDEA", "DECISION", "ACTION", "QUESTION") else "IDEA"


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
    existing = session.execute(select(TopicRow).where(TopicRow.name == "Uncategorized")).scalar_one_or_none()
    if existing is not None:
        return existing.id
    topic_id = str(uuid.uuid4())
    session.add(TopicRow(id=topic_id, name="Uncategorized"))
    session.flush()
    return topic_id


def set_review_status(candidate_id: str, status: ReviewStatus) -> ReviewCandidate | None:
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
                affected_topic_id = _get_or_create_uncategorized_topic(session)
                session.add(
                    KnowledgeItemRow(
                        id=f"{row.meeting_id}:accepted-{row.id.split(':', 1)[1]}",
                        meeting_id=row.meeting_id,
                        topic_id=affected_topic_id,
                        type=_normalize_item_type(row.type),
                        description=row.description,
                        theme=None,
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
        items=items,
        stakeholders=list(dict.fromkeys(s for item in items for s in item.stakeholders)),
        priority=_priority_info_from_row(row),
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
        session.delete(row)
        session.commit()
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
        session.delete(source)
        session.commit()

    recalculate_priority_for_topics({target_topic_id}, trigger="topic_merge")
    merged = get_topic_by_id(target_topic_id)
    assert merged is not None
    return merged


def _topic_centroids(rows: list[TopicRow]) -> dict[str, np.ndarray]:
    """Mean embedding per topic, skipping topics with no embedded items."""
    centroids: dict[str, np.ndarray] = {}
    for row in rows:
        item_vectors = [np.array(item.embedding) for item in row.items if item.embedding is not None]
        if item_vectors:
            centroids[row.id] = np.mean(item_vectors, axis=0)
    return centroids


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
            similarity = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
            if similarity >= min_similarity:
                suggestions.append(
                    TopicMergeSuggestion(
                        topic_a=topics_by_id[ids[i]], topic_b=topics_by_id[ids[j]], similarity=similarity
                    )
                )
    suggestions.sort(key=lambda s: s.similarity, reverse=True)
    return suggestions[:limit]


def suggested_item_topics(min_similarity: float = 0.6, limit: int = 20) -> list[ItemTopicSuggestion]:
    """Per-item counterpart to suggested_topic_merges: for each item still sitting in
    "Uncategorized", flags the existing topic whose items are semantically closest on average,
    for a human to review and confirm via the normal move-item flow - never assigns automatically."""
    with db.get_session() as session:
        stmt = select(TopicRow).options(selectinload(TopicRow.items))
        rows = session.execute(stmt).scalars().all()
        uncategorized = next((row for row in rows if row.name == "Uncategorized"), None)
        if uncategorized is None or not uncategorized.items:
            return []
        other_rows = [row for row in rows if row.name != "Uncategorized"]
        topics_by_id = {row.id: _topic_from_row(row) for row in other_rows}
        centroids = _topic_centroids(other_rows)
        uncategorized_items = [
            (_item_from_row(item_row), np.array(item_row.embedding))
            for item_row in uncategorized.items
            if item_row.embedding is not None
        ]

    suggestions: list[ItemTopicSuggestion] = []
    for item, vector in uncategorized_items:
        best_topic_id: str | None = None
        best_similarity = -1.0
        for topic_id, centroid in centroids.items():
            similarity = float(np.dot(vector, centroid) / (np.linalg.norm(vector) * np.linalg.norm(centroid)))
            if similarity > best_similarity:
                best_similarity = similarity
                best_topic_id = topic_id
        if best_topic_id is not None and best_similarity >= min_similarity:
            suggestions.append(
                ItemTopicSuggestion(
                    item=item, suggested_topic=topics_by_id[best_topic_id], similarity=best_similarity
                )
            )
    suggestions.sort(key=lambda s: s.similarity, reverse=True)
    return suggestions[:limit]


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
            similarity = float(np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb)))
            if similarity >= min_semantic_similarity:
                _add_edge(a, b, "semantic", weight=similarity)

    return GraphData(nodes=nodes, edges=edges)


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

