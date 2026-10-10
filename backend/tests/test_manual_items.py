"""Tests for manually adding, editing and deleting items. Auto-skips if Postgres isn't reachable.

Requests are validated and normalized by the API schemas (ItemCreate / ItemUpdate) before they reach the use
cases, so the tests go through the same conversion the REST and MCP adapters use."""
from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.domain.exceptions import ItemNotDeletable, ItemNotEditable, ItemNotFound, TopicNotFound
from app.domain.policies import MANUAL_MEETING_ID
from app.infrastructure.persistence import database as db
from app.infrastructure.persistence.orm_models import KnowledgeItemRow, MeetingRow, TopicRow
from app.presentation.api.schemas import ItemCreate, ItemUpdate
from tests.support import brain
from tests.support import cleanup as _cleanup_extracted
from tests.support import make_topic_with_item as _make_topic_with_item


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


def _create(topic_id: str, **fields):
    return brain.create_item(topic_id, ItemCreate(**fields).to_new_item())


def _update(item_id: str, **fields):
    return brain.update_item(item_id, ItemUpdate(**fields).to_item_edit())


@pytest.mark.parametrize("item_type", ["IDEA", "QUESTION", "DECISION", "ACTION"])
def test_create_item_of_each_type(db_ready, item_type):
    topic = brain.create_topic(f"manual-items-{uuid.uuid4().hex[:8]}")
    item_ids: list[str] = []
    try:
        item = _create(topic.id, type=item_type, description="  Try the new thing  ")
        item_ids.append(item.id)
        assert item.type == item_type
        assert item.description == "Try the new thing"
        assert item.theme == topic.name
        assert item.status == "Open"
        assert item.meeting_id == MANUAL_MEETING_ID

        reloaded = brain.get_topic(topic.id)
        assert [i.id for i in reloaded.items] == [item.id]
    finally:
        _cleanup(topic.id, item_ids)


def test_action_keeps_owner_and_due_date(db_ready):
    topic = brain.create_topic(f"manual-items-{uuid.uuid4().hex[:8]}")
    item_ids: list[str] = []
    try:
        item = _create(topic.id, type="ACTION", description="Ship it", owner="Ana", dueDate="2026-10-01")
        item_ids.append(item.id)
        assert item.owner == "Ana" and list(item.stakeholders) == ["Ana"] and item.due_date == "2026-10-01"
    finally:
        _cleanup(topic.id, item_ids)


def test_manual_meeting_is_created_once_and_reused(db_ready):
    topic = brain.create_topic(f"manual-items-{uuid.uuid4().hex[:8]}")
    item_ids: list[str] = []
    try:
        for text in ("first", "second"):
            item_ids.append(_create(topic.id, type="IDEA", description=text).id)
        assert len(set(item_ids)) == 2
        with db.get_session() as session:
            assert session.get(MeetingRow, MANUAL_MEETING_ID) is not None
    finally:
        _cleanup(topic.id, item_ids)


def test_create_item_in_a_missing_topic_is_reported(db_ready):
    with pytest.raises(TopicNotFound):
        _create("does-not-exist", type="IDEA", description="x")


def test_invalid_payloads_rejected():
    with pytest.raises(ValidationError):
        ItemCreate(type="IDEA", description="   ")
    with pytest.raises(ValidationError):
        ItemCreate(type="IDEA", description="x" * 2001)
    with pytest.raises(ValidationError):
        ItemCreate(type="NOTE", description="x")


def test_update_manual_item_fields(db_ready):
    topic = brain.create_topic(f"manual-items-{uuid.uuid4().hex[:8]}")
    item_ids: list[str] = []
    try:
        item = _create(topic.id, type="IDEA", description="old", owner="Ana", rationale="why")
        item_ids.append(item.id)

        updated = _update(item.id, type="ACTION", description=" new text ", dueDate="2026-12-01", owner="Bo")
        assert (updated.type, updated.description, updated.due_date) == ("ACTION", "new text", "2026-12-01")
        assert updated.owner == "Bo" and list(updated.stakeholders) == ["Bo"]
        assert updated.rationale == "why"  # untouched because omitted

        cleared = _update(item.id, owner="", rationale=None)
        assert cleared.owner is None and list(cleared.stakeholders) == [] and cleared.rationale is None
    finally:
        _cleanup(topic.id, item_ids)


def test_update_item_rejects_type_change_on_extracted_item(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        current_type = brain.get_topic(topic.id).items[0].type
        with pytest.raises(ItemNotEditable):
            _update(item_id, type="IDEA" if current_type != "IDEA" else "QUESTION")
        assert _update(item_id, description="reworded").description == "reworded"
    finally:
        _cleanup_extracted(topic.id, meeting_id)


def test_delete_manual_item_and_protect_extracted_items(db_ready):
    topic, meeting_id, extracted_id = _make_topic_with_item()
    try:
        manual = _create(topic.id, type="QUESTION", description="to be removed")
        brain.delete_item(manual.id)
        assert manual.id not in [i.id for i in brain.get_topic(topic.id).items]
        with pytest.raises(ItemNotFound):
            brain.delete_item(manual.id)  # already gone

        with pytest.raises(ItemNotDeletable):
            brain.delete_item(extracted_id)
        assert extracted_id in [i.id for i in brain.get_topic(topic.id).items]
    finally:
        _cleanup_extracted(topic.id, meeting_id)


def test_updating_or_deleting_a_missing_item_is_reported(db_ready):
    with pytest.raises(ItemNotFound):
        _update("does-not-exist", description="x")
    with pytest.raises(ItemNotFound):
        brain.delete_item("does-not-exist")


def test_invalid_update_payloads_rejected():
    with pytest.raises(ValidationError):
        ItemUpdate()
    with pytest.raises(ValidationError):
        ItemUpdate(description="   ")
    with pytest.raises(ValidationError):
        ItemUpdate(type=None)
