"""Integration tests for topic CRUD + item reassignment against a real Postgres+pgvector instance.

Auto-skips (module-scoped) if DATABASE_URL isn't reachable, mirroring test_postgres_ingestion.py.
"""
from __future__ import annotations

import uuid

import pytest

from app.application.services.uncategorized import ensure_uncategorized_topic
from app.domain.exceptions import (
    InvalidTopicMerge,
    ItemsNotFound,
    TopicHasItems,
    TopicNameConflict,
    TopicNotFound,
)
from app.infrastructure.persistence import database as db
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.support import brain


def _unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _items(meetings):
    return [item for meeting in meetings for item in meeting.items]


def test_create_update_delete_empty_topic(db_ready):
    name = _unique_name("topic")
    created = brain.create_topic(name)
    assert created.items == ()

    renamed = brain.rename_topic(created.id, f"{name}-renamed")
    assert renamed.name == f"{name}-renamed"

    brain.delete_topic(created.id)
    with pytest.raises(TopicNotFound):
        brain.get_topic(created.id)
    with pytest.raises(TopicNotFound):
        brain.delete_topic(created.id)


def test_create_topic_rejects_duplicate_name(db_ready):
    name = _unique_name("topic")
    created = brain.create_topic(name)
    try:
        with pytest.raises(TopicNameConflict):
            brain.create_topic(name)
    finally:
        brain.delete_topic(created.id)


def test_delete_topic_blocked_when_items_assigned(db_ready):
    meetings = brain.list_meetings()
    if not _items(meetings):
        pytest.skip("no seeded knowledge items available to attach to a topic")
    item = _items(meetings)[0]
    topic = brain.create_topic(_unique_name("topic-with-items"))

    original_topic_id = None
    with db.get_session() as session:
        from app.infrastructure.persistence.orm_models import KnowledgeItemRow

        row = session.get(KnowledgeItemRow, item.id)
        assert row is not None
        original_topic_id = row.topic_id

    brain.assign_item_topic(item.id, topic.id)
    try:
        with pytest.raises(TopicHasItems):
            brain.delete_topic(topic.id)
    finally:
        brain.assign_item_topic(item.id, original_topic_id)
        brain.delete_topic(topic.id)


def test_assign_item_topic_moves_item_between_topics(db_ready):
    meetings = brain.list_meetings()
    if not _items(meetings):
        pytest.skip("no seeded knowledge items available to move")
    item = _items(meetings)[0]

    with db.get_session() as session:
        from app.infrastructure.persistence.orm_models import KnowledgeItemRow

        original_topic_id = session.get(KnowledgeItemRow, item.id).topic_id

    topic_a = brain.create_topic(_unique_name("topic-a"))
    topic_b = brain.create_topic(_unique_name("topic-b"))
    try:
        moved = brain.assign_item_topic(item.id, topic_a.id)
        assert moved.theme == topic_a.name
        assert item.id in [i.id for i in brain.get_topic(topic_a.id).items]

        moved_again = brain.assign_item_topic(item.id, topic_b.id)
        assert item.id not in [i.id for i in brain.get_topic(topic_a.id).items]
        assert item.id in [i.id for i in brain.get_topic(topic_b.id).items]
    finally:
        brain.assign_item_topic(item.id, original_topic_id)
        brain.delete_topic(topic_a.id)
        brain.delete_topic(topic_b.id)


def test_assign_item_topic_rejects_unknown_topic(db_ready):
    meetings = brain.list_meetings()
    if not _items(meetings):
        pytest.skip("no seeded knowledge items available")
    item = _items(meetings)[0]
    with pytest.raises(TopicNotFound):
        brain.assign_item_topic(item.id, "not-a-real-topic-id")


def test_assign_items_topic_bulk_moves_multiple_items(db_ready):
    meetings = brain.list_meetings()
    items = _items(meetings)
    if len(items) < 2:
        pytest.skip("need at least 2 seeded knowledge items to bulk-move")
    item_a, item_b = items[0], items[1]

    from app.infrastructure.persistence.orm_models import KnowledgeItemRow

    with db.get_session() as session:
        original_topic_ids = {
            item_a.id: session.get(KnowledgeItemRow, item_a.id).topic_id,
            item_b.id: session.get(KnowledgeItemRow, item_b.id).topic_id,
        }

    topic = brain.create_topic(_unique_name("bulk-target"))
    try:
        moved = brain.assign_items_topic([item_a.id, item_b.id], topic.id)
        assert {i.id for i in moved} == {item_a.id, item_b.id}
        assert all(i.theme == topic.name for i in moved)
        topic_item_ids = {i.id for i in brain.get_topic(topic.id).items}
        assert item_a.id in topic_item_ids
        assert item_b.id in topic_item_ids
    finally:
        for item_id, original_topic_id in original_topic_ids.items():
            brain.assign_item_topic(item_id, original_topic_id)
        brain.delete_topic(topic.id)


def test_assign_items_topic_rejects_unknown_topic(db_ready):
    meetings = brain.list_meetings()
    items = _items(meetings)
    if not items:
        pytest.skip("no seeded knowledge items available")
    with pytest.raises(TopicNotFound):
        brain.assign_items_topic([items[0].id], "not-a-real-topic-id")


def test_assign_items_topic_rejects_unknown_item(db_ready):
    topic = brain.create_topic(_unique_name("bulk-missing-item"))
    try:
        with pytest.raises(ItemsNotFound, match="not-a-real-item-id"):
            brain.assign_items_topic(["not-a-real-item-id"], topic.id)
    finally:
        brain.delete_topic(topic.id)


def test_merge_topics_moves_items_and_deletes_source(db_ready):
    meetings = brain.list_meetings()
    if not _items(meetings):
        pytest.skip("no seeded knowledge items available to merge")
    item = _items(meetings)[0]

    from app.infrastructure.persistence.orm_models import KnowledgeItemRow

    with db.get_session() as session:
        original_topic_id = session.get(KnowledgeItemRow, item.id).topic_id

    source = brain.create_topic(_unique_name("source"))
    target = brain.create_topic(_unique_name("target"))
    brain.assign_item_topic(item.id, source.id)
    try:
        merged = brain.merge_topics(source.id, target.id)
        assert merged.id == target.id
        assert item.id in [i.id for i in merged.items]
        with pytest.raises(TopicNotFound):
            brain.get_topic(source.id)
    finally:
        brain.assign_item_topic(item.id, original_topic_id)
        brain.delete_topic(target.id)


def test_merge_topics_rejects_self_merge(db_ready):
    topic = brain.create_topic(_unique_name("self-merge"))
    try:
        with pytest.raises(InvalidTopicMerge):
            brain.merge_topics(topic.id, topic.id)
    finally:
        brain.delete_topic(topic.id)


def test_merge_topics_rejects_unknown_topic(db_ready):
    topic = brain.create_topic(_unique_name("merge-target"))
    try:
        with pytest.raises(TopicNotFound):
            brain.merge_topics("not-a-real-topic-id", topic.id)
    finally:
        brain.delete_topic(topic.id)


def test_suggested_topic_merges_flags_similar_topics(db_ready):
    meetings = brain.list_meetings()
    items = _items(meetings)
    if len(items) < 2:
        pytest.skip("need at least 2 seeded knowledge items with embeddings")
    item_a, item_b = items[0], items[1]

    from app.infrastructure.persistence.orm_models import KnowledgeItemRow

    with db.get_session() as session:
        original_a = session.get(KnowledgeItemRow, item_a.id).topic_id
        original_b = session.get(KnowledgeItemRow, item_b.id).topic_id

    topic_a = brain.create_topic(_unique_name("sim-a"))
    topic_b = brain.create_topic(_unique_name("sim-b"))
    brain.assign_item_topic(item_a.id, topic_a.id)
    brain.assign_item_topic(item_b.id, topic_b.id)
    try:
        # min_similarity=-1 guarantees the pair is included regardless of actual similarity,
        # since this only asserts the pair is computed/returned correctly - not a specific score
        suggestions = brain.suggest_topic_merges(min_similarity=-1.0, limit=1000)
        pair = frozenset((topic_a.id, topic_b.id))
        match = next((s for s in suggestions if frozenset((s.topic_a.id, s.topic_b.id)) == pair), None)
        assert match is not None
        assert -1.0 <= match.similarity <= 1.0
    finally:
        brain.assign_item_topic(item_a.id, original_a)
        brain.assign_item_topic(item_b.id, original_b)
        brain.delete_topic(topic_a.id)
        brain.delete_topic(topic_b.id)


def test_suggested_topic_merges_excludes_uncategorized(db_ready):
    meetings = brain.list_meetings()
    if not _items(meetings):
        pytest.skip("no seeded knowledge items available")
    suggestions = brain.suggest_topic_merges(min_similarity=-1.0, limit=1000)
    assert all(s.topic_a.name != "Uncategorized" and s.topic_b.name != "Uncategorized" for s in suggestions)


def test_suggested_topic_merges_excludes_topics_with_many_items(db_ready):
    meetings = brain.list_meetings()
    items = _items(meetings)
    if len(items) < 6:
        pytest.skip("need at least 6 seeded knowledge items with embeddings")
    item_a, *bulk_items = items[:6]

    from app.infrastructure.persistence.orm_models import KnowledgeItemRow

    with db.get_session() as session:
        original_topics = {item.id: session.get(KnowledgeItemRow, item.id).topic_id for item in items[:6]}

    topic_a = brain.create_topic(_unique_name("bulk-a"))
    topic_b = brain.create_topic(_unique_name("bulk-b"))
    brain.assign_item_topic(item_a.id, topic_a.id)
    for item in bulk_items:
        brain.assign_item_topic(item.id, topic_b.id)
    try:
        pair = frozenset((topic_a.id, topic_b.id))
        # default threshold (5) excludes topic_b, which now has 5 items
        default_suggestions = brain.suggest_topic_merges(min_similarity=-1.0, limit=1000)
        assert not any(frozenset((s.topic_a.id, s.topic_b.id)) == pair for s in default_suggestions)

        # raising the threshold lets the pair back in
        raised_suggestions = brain.suggest_topic_merges(min_similarity=-1.0, limit=1000, max_related_items=6)
        assert any(frozenset((s.topic_a.id, s.topic_b.id)) == pair for s in raised_suggestions)
    finally:
        for item in items[:6]:
            brain.assign_item_topic(item.id, original_topics[item.id])
        brain.delete_topic(topic_a.id)
        brain.delete_topic(topic_b.id)


def test_suggested_item_topics_flags_similar_topic(db_ready):
    meetings = brain.list_meetings()
    items = _items(meetings)
    if len(items) < 2:
        pytest.skip("need at least 2 seeded knowledge items with embeddings")
    item_a, item_b = items[0], items[1]

    from app.infrastructure.persistence.orm_models import KnowledgeItemRow

    with db.get_session() as session:
        row_a = session.get(KnowledgeItemRow, item_a.id)
        row_b = session.get(KnowledgeItemRow, item_b.id)
        if row_a.embedding is None or row_b.embedding is None:
            pytest.skip("seeded items need embeddings")
        original_a_topic = row_a.topic_id
        original_b_topic = row_b.topic_id
        original_a_embedding = row_a.embedding
        # force an exact embedding match so topic_a is unambiguously the closest centroid to
        # item_b (cosine similarity to itself is the global max of 1.0), regardless of whatever
        # other topics already exist in the shared dev DB
        row_a.embedding = row_b.embedding
        uncategorized_id = ensure_uncategorized_topic(SqlAlchemyUnitOfWork(session), brain.ids).id
        session.commit()

    topic_a = brain.create_topic(_unique_name("item-sim-a"))
    brain.assign_item_topic(item_a.id, topic_a.id)
    brain.assign_item_topic(item_b.id, uncategorized_id)
    try:
        suggestions = brain.suggest_item_topics()
        match = next((s for s in suggestions if s.item.id == item_b.id), None)
        assert match is not None
        assert topic_a.id in [c.topic_id for c in match.candidates]
        top = next(c for c in match.candidates if c.topic_id == topic_a.id)
        assert top.topic_name == topic_a.name
        assert top.item_count == 1
        assert top.centroid_similarity == pytest.approx(1.0, abs=1e-4)
        assert 1 <= len(match.candidates) <= 3
        assert match.score == match.candidates[0].score
        assert [c.score for c in match.candidates] == sorted((c.score for c in match.candidates), reverse=True)
    finally:
        brain.assign_item_topic(item_a.id, original_a_topic)
        brain.assign_item_topic(item_b.id, original_b_topic)
        with db.get_session() as session:
            session.get(KnowledgeItemRow, item_a.id).embedding = original_a_embedding
            session.commit()
        brain.delete_topic(topic_a.id)


def test_suggested_item_topics_never_suggests_uncategorized(db_ready):
    meetings = brain.list_meetings()
    if not _items(meetings):
        pytest.skip("no seeded knowledge items available")
    suggestions = brain.suggest_item_topics()
    uncategorized_ids = {t.id for t in brain.list_topics() if t.name == "Uncategorized"}
    assert all(c.topic_id not in uncategorized_ids for s in suggestions for c in s.candidates)
    assert all(c.topic_name != "Uncategorized" for s in suggestions for c in s.candidates)
    assert len(brain.suggest_item_topics(limit=1)) <= 1
