"""SQLAlchemy implementations of the persistence ports. Every repository of one unit of work shares its session,
so queries see what earlier calls added or changed (the session autoflushes before each query)."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, defer, selectinload

from app.domain.entities.knowledge_item import Embedding, KnowledgeItem
from app.domain.entities.meeting import Meeting
from app.domain.entities.review_candidate import ReviewCandidate
from app.domain.entities.topic import Topic
from app.domain.exceptions import TopicNameConflict
from app.domain.policies import UNCATEGORIZED_TOPIC
from app.domain.services.topic_ranking import TopicProfile
from app.domain.value_objects.priority import TopicPriorityHistoryEntry
from app.infrastructure.persistence import mappers
from app.infrastructure.persistence.orm_models import (
    KnowledgeItemRow,
    MeetingRow,
    NoteRow,
    ReviewCandidateRow,
    TopicImageRow,
    TopicPriorityHistoryRow,
    TopicRow,
)

_NOT_LOADED: Any = object()


def is_topic_name_conflict(error: IntegrityError) -> bool:
    constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    return constraint == "topics_name_key"


class SqlAlchemyMeetingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, meeting_id: str) -> Meeting | None:
        row = self._session.get(MeetingRow, meeting_id)
        return mappers.meeting_from_row(row) if row is not None else None

    def list_all(self) -> list[Meeting]:
        return [mappers.meeting_from_row(row) for row in self._session.execute(select(MeetingRow)).scalars().all()]

    def dates_by_id(self, meeting_ids: Sequence[str]) -> dict[str, str]:
        rows = self._session.execute(
            select(MeetingRow.id, MeetingRow.date).where(MeetingRow.id.in_(list(meeting_ids)))
        ).all()
        return {row.id: row.date for row in rows}

    def add(self, meeting: Meeting) -> None:
        row = MeetingRow(id=meeting.id)
        mappers.apply_meeting(meeting, row)
        self._session.add(row)

    def save(self, meeting: Meeting) -> None:
        row = self._session.get(MeetingRow, meeting.id)
        if row is None:
            raise LookupError(f"meeting {meeting.id!r} is not stored; add it first")
        mappers.apply_meeting(meeting, row)


class SqlAlchemyKnowledgeItemRepository:
    def __init__(self, session: Session) -> None:
        self._session = session
        # what each item looked like when it was handed out: (embedding, manual override). Saving writes those
        # two only when the entity now holds a different object, so a vector that was never loaded is never
        # overwritten and an untouched override keeps its stored timestamp.
        self._loaded: dict[str, tuple[Any, Any]] = {}

    def _entity(self, row: KnowledgeItemRow, *, with_embedding: bool = True) -> KnowledgeItem:
        item = mappers.item_from_row(row, with_embedding=with_embedding)
        self._loaded[item.id] = (item.embedding if with_embedding else _NOT_LOADED, item.manual_override)
        return item

    def _entities(self, rows: Sequence[KnowledgeItemRow], *, with_embeddings: bool = True) -> list[KnowledgeItem]:
        return [self._entity(row, with_embedding=with_embeddings) for row in rows]

    def get(self, item_id: str) -> KnowledgeItem | None:
        row = self._session.get(KnowledgeItemRow, item_id)
        return self._entity(row) if row is not None else None

    def list_all(self) -> list[KnowledgeItem]:
        return self._entities(self._session.execute(select(KnowledgeItemRow)).scalars().all())

    def list_by_ids(self, item_ids: Sequence[str], *, with_embeddings: bool = True) -> list[KnowledgeItem]:
        stmt = select(KnowledgeItemRow).where(KnowledgeItemRow.id.in_(list(item_ids)))
        if not with_embeddings:
            stmt = stmt.options(defer(KnowledgeItemRow.embedding))
        return self._entities(self._session.execute(stmt).scalars().all(), with_embeddings=with_embeddings)

    def list_by_topic(self, topic_id: str) -> list[KnowledgeItem]:
        stmt = select(KnowledgeItemRow).where(KnowledgeItemRow.topic_id == topic_id)
        return self._entities(self._session.execute(stmt).scalars().all())

    def list_by_topics(self, topic_ids: Sequence[str]) -> list[KnowledgeItem]:
        if not topic_ids:
            return []
        stmt = select(KnowledgeItemRow).where(KnowledgeItemRow.topic_id.in_(list(topic_ids)))
        return self._entities(self._session.execute(stmt).scalars().all())

    def list_with_proposal(self, suggested_topic: str | None = None) -> list[KnowledgeItem]:
        if suggested_topic is None:
            stmt = (
                select(KnowledgeItemRow)
                .where(KnowledgeItemRow.suggested_topic.is_not(None))
                .order_by(KnowledgeItemRow.id)
            )
        else:
            stmt = select(KnowledgeItemRow).where(KnowledgeItemRow.suggested_topic == suggested_topic)
        return self._entities(self._session.execute(stmt).scalars().all())

    def count_by_topic(self, topic_id: str) -> int:
        stmt = select(func.count()).select_from(KnowledgeItemRow).where(KnowledgeItemRow.topic_id == topic_id)
        return self._session.execute(stmt).scalar_one()

    def topic_ids_of(self, item_ids: Sequence[str]) -> list[str]:
        stmt = select(KnowledgeItemRow.topic_id).where(
            KnowledgeItemRow.id.in_(list(item_ids)), KnowledgeItemRow.topic_id.is_not(None)
        )
        return [topic_id for (topic_id,) in self._session.execute(stmt)]

    def link_index(self) -> tuple[dict[str, str | None], dict[str, tuple[str, ...]]]:
        rows = self._session.execute(
            select(KnowledgeItemRow.id, KnowledgeItemRow.topic_id, KnowledgeItemRow.related_ids)
        ).all()
        return (
            {row.id: row.topic_id for row in rows},
            {row.id: tuple(row.related_ids or []) for row in rows},
        )

    def find_duplicate(
        self, embedding: Embedding, *, max_distance: float, meeting_id: str | None = None
    ) -> KnowledgeItem | None:
        distance = KnowledgeItemRow.embedding.cosine_distance(embedding)
        conditions = [KnowledgeItemRow.embedding.is_not(None)]
        if meeting_id is not None:
            # scoped to one meeting so two LLM extracts of the same meeting merge, without risking
            # false merges against unrelated meetings the way a global similarity search would
            conditions.append(KnowledgeItemRow.meeting_id == meeting_id)
        result = self._session.execute(
            select(KnowledgeItemRow, distance).where(*conditions).order_by(distance).limit(1)
        ).first()
        if result is None:
            return None
        row, found_distance = result
        # handed out without its vector: callers only reinforce a duplicate, and the row may have been
        # loaded with the vector deferred
        return self._entity(row, with_embedding=False) if found_distance < max_distance else None

    def nearest(
        self, embedding: Embedding, limit: int, *, exclude_ids: Sequence[str] = ()
    ) -> list[tuple[KnowledgeItem, float]]:
        distance = KnowledgeItemRow.embedding.cosine_distance(embedding)
        stmt = select(KnowledgeItemRow, distance.label("distance"))
        if exclude_ids:
            stmt = stmt.where(KnowledgeItemRow.id.notin_(list(exclude_ids)))
        rows = self._session.execute(stmt.order_by(distance).limit(limit)).all()
        return [(self._entity(row), found_distance) for row, found_distance in rows]

    def add(self, item: KnowledgeItem) -> None:
        self._session.add(mappers.new_item_row(item))
        self._loaded[item.id] = (item.embedding, item.manual_override)

    def save(self, item: KnowledgeItem) -> None:
        row = self._session.get(KnowledgeItemRow, item.id)
        if row is None:
            raise LookupError(f"item {item.id!r} is not stored; add it first")
        loaded_embedding, loaded_override = self._loaded.get(item.id, (_NOT_LOADED, _NOT_LOADED))
        mappers.apply_item(
            item,
            row,
            write_embedding=item.embedding is not None and item.embedding is not loaded_embedding,
            write_override=item.manual_override is not loaded_override,
        )
        self._loaded[item.id] = (
            item.embedding if item.embedding is not None else loaded_embedding,
            item.manual_override,
        )

    def delete(self, item: KnowledgeItem) -> None:
        row = self._session.get(KnowledgeItemRow, item.id)
        if row is not None:
            self._session.delete(row)
        self._loaded.pop(item.id, None)


# Covers exactly what ranking_profiles() reads (topic id/name/tags, item id/description/embedding), so any
# write changes it - including ones another process makes.
_RANKING_VERSION_SQL = text(
    """
    select md5(coalesce(string_agg(
        concat_ws('|', t.id, t.name, array_to_string(t.tags, ','), i.id, md5(i.description), md5(i.embedding::text)),
        ',' order by t.id, i.id
    ), ''))
    from topics t left join knowledge_items i on i.topic_id = t.id
    where t.name <> :uncategorized
    """
)


class SqlAlchemyTopicRepository:
    def __init__(self, session: Session) -> None:
        self._session = session
        # (calculation, manual override) as handed out; see SqlAlchemyKnowledgeItemRepository._loaded
        self._loaded: dict[str, tuple[Any, Any]] = {}

    def _entity(self, row: TopicRow) -> Topic:
        topic = mappers.topic_from_row(row)
        self._loaded[topic.id] = (topic.calculation, topic.manual_override)
        return topic

    def get(self, topic_id: str) -> Topic | None:
        row = self._session.get(TopicRow, topic_id)
        return self._entity(row) if row is not None else None

    def get_by_name(self, name: str) -> Topic | None:
        row = self._session.execute(select(TopicRow).where(TopicRow.name == name)).scalar_one_or_none()
        return self._entity(row) if row is not None else None

    def list_all(self) -> list[Topic]:
        return [self._entity(row) for row in self._session.execute(select(TopicRow)).scalars().all()]

    def list_by_ids(self, topic_ids: Sequence[str]) -> list[Topic]:
        if not topic_ids:
            return []
        stmt = select(TopicRow).where(TopicRow.id.in_(list(topic_ids)))
        return [self._entity(row) for row in self._session.execute(stmt).scalars().all()]

    def _flush(self, topic: Topic) -> None:
        try:
            self._session.flush()
        except IntegrityError as error:
            self._session.rollback()
            if is_topic_name_conflict(error):
                raise TopicNameConflict(topic.name) from error
            raise

    def add(self, topic: Topic) -> None:
        self._session.add(mappers.new_topic_row(topic))
        self._loaded[topic.id] = (topic.calculation, topic.manual_override)
        self._flush(topic)

    def save(self, topic: Topic) -> None:
        row = self._session.get(TopicRow, topic.id)
        if row is None:
            raise LookupError(f"topic {topic.id!r} is not stored; add it first")
        loaded_calculation, loaded_override = self._loaded.get(topic.id, (_NOT_LOADED, _NOT_LOADED))
        renamed = row.name != topic.name
        mappers.apply_topic(
            topic,
            row,
            write_calculation=topic.calculation is not loaded_calculation,
            write_override=topic.manual_override is not loaded_override,
        )
        self._loaded[topic.id] = (topic.calculation, topic.manual_override)
        if renamed:
            self._flush(topic)

    def delete(self, topic: Topic) -> None:
        row = self._session.get(TopicRow, topic.id)
        if row is not None:
            self._session.delete(row)
        self._loaded.pop(topic.id, None)

    def merge(self, source: Topic, target: Topic) -> None:
        session = self._session
        session.execute(
            update(KnowledgeItemRow)
            .where(KnowledgeItemRow.topic_id == source.id)
            .values(topic_id=target.id, theme=target.name)
        )
        # keep the source topic's notes: repoint them before the delete cascades over them
        session.execute(update(NoteRow).where(NoteRow.topic_id == source.id).values(topic_id=target.id))
        # same for images: the stored objects stay where they are, only the owning topic changes
        session.execute(update(TopicImageRow).where(TopicImageRow.topic_id == source.id).values(topic_id=target.id))
        source_row = session.get(TopicRow, source.id)
        if source_row is not None:
            # reload its collections first, so the cascade does not delete what was just moved
            session.expire(source_row)
            session.delete(source_row)
        target_row = session.get(TopicRow, target.id)
        if target_row is not None:
            session.expire(target_row)
        self._loaded.pop(source.id, None)

    def ranking_version(self) -> str:
        return self._session.execute(_RANKING_VERSION_SQL, {"uncategorized": UNCATEGORIZED_TOPIC}).scalar_one()

    def ranking_profiles(self) -> list[TopicProfile]:
        rows = self._session.execute(select(TopicRow).options(selectinload(TopicRow.items))).scalars().all()
        return [
            TopicProfile(
                topic_id=row.id,
                name=row.name,
                tags=list(row.tags or []),
                item_embeddings=[item.embedding for item in row.items if item.embedding is not None],
                item_descriptions=[item.description for item in row.items],
            )
            for row in rows
            if row.name != UNCATEGORIZED_TOPIC
        ]


class SqlAlchemyReviewCandidateRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, candidate_id: str) -> ReviewCandidate | None:
        row = self._session.get(ReviewCandidateRow, candidate_id)
        return mappers.candidate_from_row(row) if row is not None else None

    def list_all(self) -> list[ReviewCandidate]:
        rows = self._session.execute(select(ReviewCandidateRow)).scalars().all()
        return [mappers.candidate_from_row(row) for row in rows]

    def list_pending(self) -> list[ReviewCandidate]:
        stmt = (
            select(ReviewCandidateRow)
            .join(MeetingRow)
            .where(ReviewCandidateRow.status == "PENDING")
            .order_by(MeetingRow.date.desc(), ReviewCandidateRow.id)
        )
        return [mappers.candidate_from_row(row) for row in self._session.execute(stmt).scalars().all()]

    def list_by_ids(self, candidate_ids: Sequence[str]) -> list[ReviewCandidate]:
        stmt = select(ReviewCandidateRow).where(ReviewCandidateRow.id.in_(list(candidate_ids)))
        return [mappers.candidate_from_row(row) for row in self._session.execute(stmt).scalars().all()]

    def add(self, candidate: ReviewCandidate) -> None:
        row = ReviewCandidateRow(id=candidate.id)
        mappers.apply_candidate(candidate, row)
        self._session.add(row)

    def save(self, candidate: ReviewCandidate) -> None:
        row = self._session.get(ReviewCandidateRow, candidate.id)
        if row is None:
            raise LookupError(f"review candidate {candidate.id!r} is not stored; add it first")
        mappers.apply_candidate(candidate, row)


class SqlAlchemyPriorityHistoryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, entry: TopicPriorityHistoryEntry) -> None:
        self._session.add(mappers.history_row(entry))

    def list_for_topic(self, topic_id: str) -> list[TopicPriorityHistoryEntry]:
        stmt = (
            select(TopicPriorityHistoryRow)
            .where(TopicPriorityHistoryRow.topic_id == topic_id)
            .order_by(TopicPriorityHistoryRow.changed_at.desc())
        )
        return [mappers.history_from_row(row) for row in self._session.execute(stmt).scalars().all()]

    def list_since(self, cutoff_iso: str) -> list[TopicPriorityHistoryEntry]:
        stmt = (
            select(TopicPriorityHistoryRow)
            .where(TopicPriorityHistoryRow.changed_at >= cutoff_iso)
            .order_by(TopicPriorityHistoryRow.changed_at.desc())
        )
        return [mappers.history_from_row(row) for row in self._session.execute(stmt).scalars().all()]
