"""Tests for manually adding items to a topic. Auto-skips if Postgres isn't reachable."""
from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app import data, db
from app.db_models import KnowledgeItemRow, MeetingRow, TopicRow
from app.models import ItemCreate, ItemUpdate
from tests.test_item_priority import _cleanup as _cleanup_extracted, _make_topic_with_item, db_ready  # noqa: F401


def _cleanup(topic_id: str, item_ids: list[str]) -> None:
    with db.get_session() as session:
        for item_id in item_ids:
            row = session.get(KnowledgeItemRow, item_id)
            if row is not None:
                session.delete(row)
        session.flush()
        topic = session.get(TopicRow, topic_id)
        if topic is not None:
            session.delete(topic)
        session.commit()


@pytest.mark.parametrize("item_type", ["IDEA", "QUESTION", "DECISION", "ACTION"])
def test_create_item_of_each_type(db_ready, item_type):
    topic = data.create_topic(f"manual-items-{uuid.uuid4().hex[:8]}")
    item_ids: list[str] = []
    try:
        item = data.create_item(topic.id, ItemCreate(type=item_type, description="  Try the new thing  "))
        assert item is not None
        item_ids.append(item.id)
        assert item.type == item_type
        assert item.description == "Try the new thing"
        assert item.theme == topic.name
        assert item.status == "Open"
        assert item.meeting_id == data.MANUAL_MEETING_ID

        reloaded = data.get_topic_by_id(topic.id)
        assert reloaded is not None and [i.id for i in reloaded.items] == [item.id]
    finally:
        _cleanup(topic.id, item_ids)


def test_action_keeps_owner_and_due_date(db_ready):
    topic = data.create_topic(f"manual-items-{uuid.uuid4().hex[:8]}")
    item_ids: list[str] = []
    try:
        item = data.create_item(
            topic.id, ItemCreate(type="ACTION", description="Ship it", owner="Ana", dueDate="2026-10-01")
        )
        assert item is not None
        item_ids.append(item.id)
        assert item.owner == "Ana" and item.stakeholders == ["Ana"] and item.due_date == "2026-10-01"
    finally:
        _cleanup(topic.id, item_ids)


def test_manual_meeting_is_created_once_and_reused(db_ready):
    topic = data.create_topic(f"manual-items-{uuid.uuid4().hex[:8]}")
    item_ids: list[str] = []
    try:
        for text in ("first", "second"):
            item = data.create_item(topic.id, ItemCreate(type="IDEA", description=text))
            assert item is not None
            item_ids.append(item.id)
        assert len(set(item_ids)) == 2
        with db.get_session() as session:
            assert session.get(MeetingRow, data.MANUAL_MEETING_ID) is not None
    finally:
        _cleanup(topic.id, item_ids)


def test_create_item_missing_topic_returns_none(db_ready):
    assert data.create_item("does-not-exist", ItemCreate(type="IDEA", description="x")) is None


def test_invalid_payloads_rejected():
    with pytest.raises(ValidationError):
        ItemCreate(type="IDEA", description="   ")
    with pytest.raises(ValidationError):
        ItemCreate(type="IDEA", description="x" * 2001)
    with pytest.raises(ValidationError):
        ItemCreate(type="NOTE", description="x")


def test_update_manual_item_fields(db_ready):
    topic = data.create_topic(f"manual-items-{uuid.uuid4().hex[:8]}")
    item_ids: list[str] = []
    try:
        item = data.create_item(topic.id, ItemCreate(type="IDEA", description="old", owner="Ana", rationale="why"))
        assert item is not None
        item_ids.append(item.id)

        updated = data.update_item(
            item.id, ItemUpdate(type="ACTION", description=" new text ", dueDate="2026-12-01", owner="Bo")
        )
        assert updated is not None
        assert (updated.type, updated.description, updated.due_date) == ("ACTION", "new text", "2026-12-01")
        assert updated.owner == "Bo" and updated.stakeholders == ["Bo"]
        assert updated.rationale == "why"  # untouched because omitted

        cleared = data.update_item(item.id, ItemUpdate(owner="", rationale=None))
        assert cleared is not None and cleared.owner is None and cleared.stakeholders == [] and cleared.rationale is None
    finally:
        _cleanup(topic.id, item_ids)


def test_update_item_rejects_type_change_on_extracted_item(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        with pytest.raises(data.ItemNotEditable):
            data.update_item(item_id, ItemUpdate(type="IDEA" if data.get_topic_by_id(topic.id).items[0].type != "IDEA" else "QUESTION"))
        edited = data.update_item(item_id, ItemUpdate(description="reworded"))
        assert edited is not None and edited.description == "reworded"
    finally:
        _cleanup_extracted(topic.id, meeting_id)


def test_delete_manual_item_and_protect_extracted_items(db_ready):
    topic, meeting_id, extracted_id = _make_topic_with_item()
    try:
        manual = data.create_item(topic.id, ItemCreate(type="QUESTION", description="to be removed"))
        assert manual is not None
        assert data.delete_item(manual.id) is True
        assert manual.id not in [i.id for i in data.get_topic_by_id(topic.id).items]
        assert data.delete_item(manual.id) is False  # already gone

        with pytest.raises(data.ItemNotDeletable):
            data.delete_item(extracted_id)
        assert extracted_id in [i.id for i in data.get_topic_by_id(topic.id).items]
    finally:
        _cleanup_extracted(topic.id, meeting_id)


def test_update_missing_item_returns_none(db_ready):
    assert data.update_item("does-not-exist", ItemUpdate(description="x")) is None
    assert data.delete_item("does-not-exist") is False


def test_invalid_update_payloads_rejected():
    with pytest.raises(ValidationError):
        ItemUpdate()
    with pytest.raises(ValidationError):
        ItemUpdate(description="   ")
    with pytest.raises(ValidationError):
        ItemUpdate(type=None)
