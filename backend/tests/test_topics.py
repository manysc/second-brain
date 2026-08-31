"""Integration tests for topic CRUD + item reassignment against a real Postgres+pgvector instance.

Auto-skips (module-scoped) if DATABASE_URL isn't reachable, mirroring test_postgres_ingestion.py.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import OperationalError

from app import data, db


@pytest.fixture(scope="module")
def db_ready():
    try:
        db.init_db()
    except OperationalError:
        pytest.skip("Postgres is not reachable at DATABASE_URL; skipping DB integration tests")
    yield


def _unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_create_update_delete_empty_topic(db_ready):
    name = _unique_name("topic")
    created = data.create_topic(name)
    assert created.items == []

    renamed = data.update_topic(created.id, f"{name}-renamed")
    assert renamed is not None
    assert renamed.name == f"{name}-renamed"

    assert data.delete_topic(created.id) is True
    assert data.get_topic_by_id(created.id) is None


def test_create_topic_rejects_duplicate_name(db_ready):
    name = _unique_name("topic")
    data.create_topic(name)
    with pytest.raises(data.TopicNameConflict):
        data.create_topic(name)


def test_delete_topic_blocked_when_items_assigned(db_ready):
    meetings = data.load_meetings()
    if not data.all_items(meetings):
        pytest.skip("no seeded knowledge items available to attach to a topic")
    item = data.all_items(meetings)[0]
    topic = data.create_topic(_unique_name("topic-with-items"))

    original_topic_id = None
    with db.get_session() as session:
        from app.db_models import KnowledgeItemRow

        row = session.get(KnowledgeItemRow, item.id)
        assert row is not None
        original_topic_id = row.topic_id

    data.assign_item_topic(item.id, topic.id)
    try:
        with pytest.raises(data.TopicHasItems):
            data.delete_topic(topic.id)
    finally:
        data.assign_item_topic(item.id, original_topic_id)
        data.delete_topic(topic.id)


def test_assign_item_topic_moves_item_between_topics(db_ready):
    meetings = data.load_meetings()
    if not data.all_items(meetings):
        pytest.skip("no seeded knowledge items available to move")
    item = data.all_items(meetings)[0]

    with db.get_session() as session:
        from app.db_models import KnowledgeItemRow

        original_topic_id = session.get(KnowledgeItemRow, item.id).topic_id

    topic_a = data.create_topic(_unique_name("topic-a"))
    topic_b = data.create_topic(_unique_name("topic-b"))
    try:
        moved = data.assign_item_topic(item.id, topic_a.id)
        assert moved is not None
        assert moved.theme == topic_a.name
        assert item.id in [i.id for i in data.get_topic_by_id(topic_a.id).items]

        moved_again = data.assign_item_topic(item.id, topic_b.id)
        assert moved_again is not None
        assert item.id not in [i.id for i in data.get_topic_by_id(topic_a.id).items]
        assert item.id in [i.id for i in data.get_topic_by_id(topic_b.id).items]
    finally:
        data.assign_item_topic(item.id, original_topic_id)
        data.delete_topic(topic_a.id)
        data.delete_topic(topic_b.id)


def test_assign_item_topic_rejects_unknown_topic(db_ready):
    meetings = data.load_meetings()
    if not data.all_items(meetings):
        pytest.skip("no seeded knowledge items available")
    item = data.all_items(meetings)[0]
    with pytest.raises(ValueError):
        data.assign_item_topic(item.id, "not-a-real-topic-id")


def test_merge_topics_moves_items_and_deletes_source(db_ready):
    meetings = data.load_meetings()
    if not data.all_items(meetings):
        pytest.skip("no seeded knowledge items available to merge")
    item = data.all_items(meetings)[0]

    from app.db_models import KnowledgeItemRow

    with db.get_session() as session:
        original_topic_id = session.get(KnowledgeItemRow, item.id).topic_id

    source = data.create_topic(_unique_name("source"))
    target = data.create_topic(_unique_name("target"))
    data.assign_item_topic(item.id, source.id)
    try:
        merged = data.merge_topics(source.id, target.id)
        assert merged.id == target.id
        assert item.id in [i.id for i in merged.items]
        assert data.get_topic_by_id(source.id) is None
    finally:
        data.assign_item_topic(item.id, original_topic_id)
        data.delete_topic(target.id)


def test_merge_topics_rejects_self_merge(db_ready):
    topic = data.create_topic(_unique_name("self-merge"))
    try:
        with pytest.raises(ValueError):
            data.merge_topics(topic.id, topic.id)
    finally:
        data.delete_topic(topic.id)


def test_merge_topics_rejects_unknown_topic(db_ready):
    topic = data.create_topic(_unique_name("merge-target"))
    try:
        with pytest.raises(LookupError):
            data.merge_topics("not-a-real-topic-id", topic.id)
    finally:
        data.delete_topic(topic.id)
