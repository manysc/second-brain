"""Tests for Open/Closed status on items and topics. Reuses test_item_priority's fixtures
(auto-skips if Postgres isn't reachable)."""
from __future__ import annotations

from app import data
from tests.test_item_priority import _cleanup, _make_topic_with_item, db_ready  # noqa: F401


def test_new_topic_defaults_to_open_and_can_be_closed_and_reopened(db_ready):
    topic, meeting_id, _ = _make_topic_with_item()
    try:
        assert topic.status == "Open"
        closed = data.set_topic_status(topic.id, "Closed")
        assert closed is not None and closed.status == "Closed"
        reopened = data.set_topic_status(topic.id, "Open")
        assert reopened is not None and reopened.status == "Open"
    finally:
        _cleanup(topic.id, meeting_id)


def test_item_can_be_closed_and_reopened(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        closed = data.set_item_status(item_id, "Closed")
        assert closed is not None and closed.status == "Closed"
        reopened = data.set_item_status(item_id, "Open")
        assert reopened is not None and reopened.status == "Open"
    finally:
        _cleanup(topic.id, meeting_id)


def test_legacy_resolved_status_reads_as_closed(db_ready):
    from app.db_models import KnowledgeItemRow

    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        with data.db.get_session() as session:
            session.get(KnowledgeItemRow, item_id).status = "Answered"
            session.commit()
        topic_after = data.get_topic_by_id(topic.id)
        assert topic_after is not None and topic_after.items[0].status == "Closed"
    finally:
        _cleanup(topic.id, meeting_id)


def test_missing_ids_return_none(db_ready):
    assert data.set_item_status("does-not-exist", "Closed") is None
    assert data.set_topic_status("does-not-exist", "Closed") is None
