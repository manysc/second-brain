"""Tests for item-level priority overrides (Option A: items have no independent automatic
scoring - an item's effective priority is its own override if set, else it inherits its owning
Topic's effective priority). Mirrors test_topics.py's db_ready pattern (auto-skips if Postgres
isn't reachable).
"""
from __future__ import annotations

import uuid

from app.infrastructure.persistence.orm_models import TopicRow
from tests.support import brain
from tests.support import cleanup as _cleanup
from tests.support import delete_row_best_effort as _delete_row_best_effort
from tests.support import make_topic_with_item as _make_topic_with_item


def test_item_defaults_to_topic_effective_priority(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        brain.recalculate_topic_priority(topic.id)
        topic_after = brain.get_topic(topic.id)
        assert topic_after.priority is not None
        item = topic_after.items[0]
        assert item.manual_override is None
        assert item.effective_priority == topic_after.priority.effective_priority
    finally:
        _cleanup(topic.id, meeting_id)


def test_item_override_diverges_and_never_mutates_the_topic(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        brain.recalculate_topic_priority(topic.id)
        before = brain.get_topic(topic.id)
        assert before.priority is not None

        overridden_item = brain.set_item_priority_override(item_id, "CRITICAL", "manually urgent")
        assert overridden_item.effective_priority == "CRITICAL"
        assert overridden_item.manual_override is not None
        assert overridden_item.manual_override.priority == "CRITICAL"
        assert overridden_item.manual_override.reason == "manually urgent"

        after = brain.get_topic(topic.id)
        assert after.priority is not None
        # setting an item's override must never write to the Topic's own priority columns
        assert after.priority.calculated_priority == before.priority.calculated_priority
        assert after.priority.calculated_score == before.priority.calculated_score
        assert after.priority.manual_override is None
    finally:
        _cleanup(topic.id, meeting_id)


def test_topic_recalculation_does_not_change_item_override(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        brain.set_item_priority_override(item_id, "MINOR", "keep it low")
        brain.recalculate_topic_priority(topic.id)  # simulates an automatic recalculation trigger firing

        topic_after = brain.get_topic(topic.id)
        item = topic_after.items[0]
        assert item.manual_override is not None
        assert item.manual_override.priority == "MINOR"
        assert item.effective_priority == "MINOR"
    finally:
        _cleanup(topic.id, meeting_id)


def test_clearing_item_override_reverts_to_topic_priority(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        brain.recalculate_topic_priority(topic.id)
        topic_priority_value = brain.get_topic(topic.id).priority.effective_priority

        brain.set_item_priority_override(item_id, "CRITICAL", "temporary")
        cleared = brain.set_item_priority_override(item_id, None, None)
        assert cleared.manual_override is None
        assert cleared.effective_priority == topic_priority_value
    finally:
        _cleanup(topic.id, meeting_id)


def test_reassigning_item_to_different_topic_changes_inherited_fallback(db_ready):
    topic_a, meeting_id, item_id = _make_topic_with_item()
    topic_b = brain.create_topic(f"item-priority-topic-b-{uuid.uuid4().hex[:8]}")
    try:
        brain.recalculate_topic_priority(topic_a.id)
        # force a known, deterministic priority on topic_b rather than depending on its scoring
        brain.set_topic_priority_override(topic_b.id, "CRITICAL", "force critical for test")

        brain.assign_item_topic(item_id, topic_b.id)
        topic_b_after = brain.get_topic(topic_b.id)
        moved = next(i for i in topic_b_after.items if i.id == item_id)
        assert moved.manual_override is None
        assert moved.effective_priority == "CRITICAL"
    finally:
        _cleanup(topic_a.id, meeting_id)  # deletes the meeting (and thus the item) + topic_a
        _delete_row_best_effort(TopicRow, topic_b.id)


def test_graph_node_priority_reflects_item_override_over_its_topic(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        brain.set_topic_priority_override(topic.id, "MINOR", "topic baseline")
        brain.set_item_priority_override(item_id, "CRITICAL", "item is on fire")
        graph = brain.build_graph()
        node = next(n for n in graph.nodes if n.id == item_id)
        assert node.priority == "CRITICAL"
    finally:
        _cleanup(topic.id, meeting_id)


def test_effective_priority_supports_filtering_like_the_items_endpoint(db_ready):
    """GET /api/items?priority=... filters on exactly this field - exercised at the data level
    to stay consistent with this suite's no-HTTP-layer style."""
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        brain.set_item_priority_override(item_id, "CRITICAL", "filter test")
        topic_after = brain.get_topic(topic.id)
        matching_ids = [i.id for i in topic_after.items if i.effective_priority == "CRITICAL"]
        non_matching_ids = [i.id for i in topic_after.items if i.effective_priority == "MINOR"]
        assert item_id in matching_ids
        assert item_id not in non_matching_ids
    finally:
        _cleanup(topic.id, meeting_id)
