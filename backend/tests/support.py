"""Shared helpers for the integration tests, which run the real application against Postgres.

`brain` is the production Container (use cases wired to the real adapters), resolved lazily so importing a test
module never needs a database. Tests act through it and may reach into the infrastructure only to arrange or
inspect stored rows."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.application.dtos import IngestSummary, TopicDTO
from app.container import Container, get_container
from app.domain.entities.knowledge_item import ItemEdit
from app.domain.value_objects.extraction import ExtractedMeeting
from app.infrastructure.persistence import database as db
from app.infrastructure.persistence.orm_models import (
    KnowledgeItemRow,
    MeetingRow,
    TopicRow,
)
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork


class _Application:
    def __getattr__(self, name: str) -> Any:
        return getattr(get_container(), name)


brain: Container = _Application()  # type: ignore[assignment]


def edit(**fields: Any) -> ItemEdit:
    """An ItemEdit touching exactly the given fields, e.g. edit(description="x", owner=None)."""
    return ItemEdit(fields=frozenset(fields), **fields)


def ingest_everything(session: Session) -> IngestSummary:
    """Runs one ingestion of every extract inside the caller's session (the caller commits)."""
    return brain.ingest_extracts.ingest_into(SqlAlchemyUnitOfWork(session))


def merge_extract(session: Session, extracted: ExtractedMeeting) -> bool:
    """Merges one extracted meeting inside the caller's session; returns whether anything changed."""
    return brain.ingest_extracts.merge_meeting(SqlAlchemyUnitOfWork(session), extracted)


def make_topic_with_item(prefix: str = "item-priority") -> tuple[TopicDTO, str, str]:
    """A fresh topic holding one meeting-extracted action. Returns (topic, meeting id, item id)."""
    meeting_id = f"{prefix}-meeting-{uuid.uuid4().hex[:8]}"
    item_id = f"{meeting_id}:A-1"
    topic = brain.create_topic(f"{prefix}-topic-{uuid.uuid4().hex[:8]}")
    with db.get_session() as session:
        session.add(
            MeetingRow(id=meeting_id, title="Item priority test meeting", date="2026-09-01", source_url="https://example.com")
        )
        session.add(
            KnowledgeItemRow(
                id=item_id,
                meeting_id=meeting_id,
                topic_id=topic.id,
                type="ACTION",
                description="Ship the release",
                theme=topic.name,
                status="Open",
                confidence="HIGH",
                owner="Ada",
                stakeholders=["Ada"],
                due_date=None,
                due_date_source_text=None,
                rationale=None,
                resolution=None,
                evidence_speaker="Ada",
                evidence_timestamp="00:01:00",
                evidence_quote="We'll ship it",
                evidence_context=None,
                related_ids=[],
                embedding=None,
            )
        )
        session.commit()
    return topic, meeting_id, item_id


def delete_row_best_effort(model: type, row_id: str) -> None:
    with db.get_session() as session:
        row = session.get(model, row_id)
        if row is not None:
            session.delete(row)
        try:
            session.commit()
        except Exception:
            session.rollback()


def cleanup(topic_id: str, meeting_id: str) -> None:
    # deleting the meeting first cascades the item regardless of its current topic_id
    delete_row_best_effort(MeetingRow, meeting_id)
    delete_row_best_effort(TopicRow, topic_id)
