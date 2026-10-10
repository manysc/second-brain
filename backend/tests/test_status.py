"""Tests for Open/Closed status on items and topics. Reuses test_item_priority's fixtures
(auto-skips if Postgres isn't reachable)."""
from __future__ import annotations

import pytest

from app.domain.exceptions import ItemNotFound, TopicNotFound
from app.infrastructure.persistence import database as db
from tests.support import brain
from tests.support import cleanup as _cleanup
from tests.support import make_topic_with_item as _make_topic_with_item


def test_new_topic_defaults_to_open_and_can_be_closed_and_reopened(db_ready):
    topic, meeting_id, _ = _make_topic_with_item()
    try:
        assert topic.status == "Open"
        closed = brain.set_topic_status(topic.id, "Closed")
        assert closed is not None and closed.status == "Closed"
        reopened = brain.set_topic_status(topic.id, "Open")
        assert reopened is not None and reopened.status == "Open"
    finally:
        _cleanup(topic.id, meeting_id)


def test_item_can_be_closed_and_reopened(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        closed = brain.set_item_status(item_id, "Closed")
        assert closed is not None and closed.status == "Closed"
        reopened = brain.set_item_status(item_id, "Open")
        assert reopened is not None and reopened.status == "Open"
    finally:
        _cleanup(topic.id, meeting_id)


def test_legacy_resolved_status_reads_as_closed(db_ready):
    from app.infrastructure.persistence.orm_models import KnowledgeItemRow

    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        with db.get_session() as session:
            session.get(KnowledgeItemRow, item_id).status = "Answered"
            session.commit()
        topic_after = brain.get_topic(topic.id)
        assert topic_after is not None and topic_after.items[0].status == "Closed"
    finally:
        _cleanup(topic.id, meeting_id)


def test_missing_ids_are_reported(db_ready):
    with pytest.raises(ItemNotFound):
        brain.set_item_status("does-not-exist", "Closed")
    with pytest.raises(TopicNotFound):
        brain.set_topic_status("does-not-exist", "Closed")
