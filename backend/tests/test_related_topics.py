"""Integration tests for data.related_topics against a real Postgres+pgvector instance.

Auto-skips (module-scoped) if DATABASE_URL isn't reachable, mirroring test_topics.py.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import OperationalError

from app import data, db
from app.db_models import EMBEDDING_DIM, KnowledgeItemRow, MeetingRow


@pytest.fixture(scope="module")
def db_ready():
    try:
        db.init_db()
    except OperationalError:
        pytest.skip("Postgres is not reachable at DATABASE_URL; skipping DB integration tests")
    yield


def _unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _vector(*leading: float) -> list[float]:
    return [*leading, *([0.0] * (EMBEDDING_DIM - len(leading)))]


def _item(meeting_id: str, topic_id: str, embedding: list[float]) -> KnowledgeItemRow:
    return KnowledgeItemRow(
        id=f"REL-{uuid.uuid4().hex[:8]}",
        meeting_id=meeting_id,
        topic_id=topic_id,
        type="IDEA",
        description="Synthetic idea for related-topics tests",
        theme=None,
        status="Open",
        confidence="MEDIUM",
        owner=None,
        stakeholders=[],
        evidence_quote="quote",
        related_ids=[],
        embedding=embedding,
    )


def test_related_topics(db_ready):
    meeting_id = _unique_name("related-meeting")
    target = data.create_topic(_unique_name("related-target"))
    close = data.create_topic(_unique_name("related-close"))
    far = data.create_topic(_unique_name("related-far"))
    empty = data.create_topic(_unique_name("related-empty"))
    try:
        with db.get_session() as session:
            session.add(MeetingRow(id=meeting_id, title="Related test", date="2026-09-01", source_url="https://example.com"))
            session.flush()  # meeting must exist before the items that reference it
            session.add(_item(meeting_id, target.id, _vector(1.0, 0.0)))
            session.add(_item(meeting_id, close.id, _vector(1.0, 0.1)))
            session.add(_item(meeting_id, far.id, _vector(0.0, 1.0)))
            session.commit()

        related = data.related_topics(target.id, limit=100)
        assert related is not None
        ids = [r.id for r in related]
        assert close.id in ids
        assert far.id not in ids
        assert target.id not in ids
        assert empty.id not in ids
        top = next(r for r in related if r.id == close.id)
        assert top.item_count == 1
        assert top.similarity > 0.9
        assert [r.similarity for r in related] == sorted((r.similarity for r in related), reverse=True)

        # a topic without embedded items has nothing to compare
        assert data.related_topics(empty.id) == []
        assert data.related_topics("no-such-topic") is None
    finally:
        with db.get_session() as session:
            meeting = session.get(MeetingRow, meeting_id)
            if meeting is not None:
                session.delete(meeting)  # cascades to the synthetic items
                session.commit()
        for topic in (target, close, far, empty):
            data.delete_topic(topic.id)
