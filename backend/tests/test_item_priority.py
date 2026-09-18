"""Tests for item-level priority overrides (Option A: items have no independent automatic
scoring - an item's effective priority is its own override if set, else it inherits its owning
Topic's effective priority). Mirrors test_topics.py's db_ready pattern (auto-skips if Postgres
isn't reachable).
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


def _make_topic_with_item():
    from app.db_models import KnowledgeItemRow, MeetingRow

    meeting_id = f"item-priority-meeting-{uuid.uuid4().hex[:8]}"
    item_id = f"{meeting_id}:A-1"
    topic = data.create_topic(f"item-priority-topic-{uuid.uuid4().hex[:8]}")
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


def _delete_row_best_effort(model, row_id) -> None:
    with db.get_session() as session:
        row = session.get(model, row_id)
        if row is not None:
            session.delete(row)
        try:
            session.commit()
        except Exception:
            session.rollback()


def _cleanup(topic_id: str, meeting_id: str) -> None:
    from app.db_models import MeetingRow, TopicRow

    # deleting the meeting first cascades the item regardless of its current topic_id
    _delete_row_best_effort(MeetingRow, meeting_id)
    _delete_row_best_effort(TopicRow, topic_id)


def test_item_defaults_to_topic_effective_priority(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        data.recalculate_priority_for_topic(topic.id)
        topic_after = data.get_topic_by_id(topic.id)
        assert topic_after is not None and topic_after.priority is not None
        item = topic_after.items[0]
        assert item.manual_override is None
        assert item.effective_priority == topic_after.priority.effective_priority
    finally:
        _cleanup(topic.id, meeting_id)


def test_item_override_diverges_and_never_mutates_the_topic(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        data.recalculate_priority_for_topic(topic.id)
        before = data.get_topic_by_id(topic.id)
        assert before is not None and before.priority is not None

        overridden_item = data.set_item_priority_override(item_id, "CRITICAL", "manually urgent")
        assert overridden_item is not None
        assert overridden_item.effective_priority == "CRITICAL"
        assert overridden_item.manual_override is not None
        assert overridden_item.manual_override.priority == "CRITICAL"
        assert overridden_item.manual_override.reason == "manually urgent"

        after = data.get_topic_by_id(topic.id)
        assert after is not None and after.priority is not None
        # setting an item's override must never write to the Topic's own priority columns
        assert after.priority.calculated_priority == before.priority.calculated_priority
        assert after.priority.calculated_score == before.priority.calculated_score
        assert after.priority.manual_override is None
    finally:
        _cleanup(topic.id, meeting_id)


def test_topic_recalculation_does_not_change_item_override(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        data.set_item_priority_override(item_id, "MINOR", "keep it low")
        data.recalculate_priority_for_topic(topic.id)  # simulates an automatic recalculation trigger firing

        topic_after = data.get_topic_by_id(topic.id)
        assert topic_after is not None
        item = topic_after.items[0]
        assert item.manual_override is not None
        assert item.manual_override.priority == "MINOR"
        assert item.effective_priority == "MINOR"
    finally:
        _cleanup(topic.id, meeting_id)


def test_clearing_item_override_reverts_to_topic_priority(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        data.recalculate_priority_for_topic(topic.id)
        topic_priority_value = data.get_topic_by_id(topic.id).priority.effective_priority

        data.set_item_priority_override(item_id, "CRITICAL", "temporary")
        cleared = data.set_item_priority_override(item_id, None, None)
        assert cleared is not None
        assert cleared.manual_override is None
        assert cleared.effective_priority == topic_priority_value
    finally:
        _cleanup(topic.id, meeting_id)


def test_reassigning_item_to_different_topic_changes_inherited_fallback(db_ready):
    topic_a, meeting_id, item_id = _make_topic_with_item()
    topic_b = data.create_topic(f"item-priority-topic-b-{uuid.uuid4().hex[:8]}")
    try:
        data.recalculate_priority_for_topic(topic_a.id)
        # force a known, deterministic priority on topic_b rather than depending on its scoring
        data.set_priority_override(topic_b.id, "CRITICAL", "force critical for test")

        data.assign_item_topic(item_id, topic_b.id)
        topic_b_after = data.get_topic_by_id(topic_b.id)
        moved = next(i for i in topic_b_after.items if i.id == item_id)
        assert moved.manual_override is None
        assert moved.effective_priority == "CRITICAL"
    finally:
        from app.db_models import TopicRow

        _cleanup(topic_a.id, meeting_id)  # deletes the meeting (and thus the item) + topic_a
        _delete_row_best_effort(TopicRow, topic_b.id)


def test_graph_node_priority_reflects_item_override_over_its_topic(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        data.set_priority_override(topic.id, "MINOR", "topic baseline")
        data.set_item_priority_override(item_id, "CRITICAL", "item is on fire")
        graph = data.build_graph()
        node = next(n for n in graph.nodes if n.id == item_id)
        assert node.priority == "CRITICAL"
    finally:
        _cleanup(topic.id, meeting_id)


def test_effective_priority_supports_filtering_like_the_items_endpoint(db_ready):
    """GET /api/items?priority=... filters on exactly this field - exercised at the data level
    to stay consistent with this suite's no-HTTP-layer style."""
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        data.set_item_priority_override(item_id, "CRITICAL", "filter test")
        topic_after = data.get_topic_by_id(topic.id)
        matching_ids = [i.id for i in topic_after.items if i.effective_priority == "CRITICAL"]
        non_matching_ids = [i.id for i in topic_after.items if i.effective_priority == "MINOR"]
        assert item_id in matching_ids
        assert item_id not in non_matching_ids
    finally:
        _cleanup(topic.id, meeting_id)
