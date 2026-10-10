"""Tests for notes on items and topics. Reuses test_item_priority's fixtures
(auto-skips if Postgres isn't reachable)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.infrastructure.persistence import database as db
from app.domain.exceptions import ItemNotFound, TopicNotFound
from tests.support import brain
from app.infrastructure.persistence.orm_models import NoteRow
from app.presentation.api.schemas import NoteCreate
from tests.support import cleanup as _cleanup
from tests.support import make_topic_with_item as _make_topic_with_item


def test_item_notes_add_list_delete(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        first = brain.add_item_note(item_id, "first")
        assert first is not None and [n.body for n in first.notes] == ["first"]
        second = brain.add_item_note(item_id, "second")
        assert second is not None and [n.body for n in second.notes] == ["first", "second"]

        after = brain.delete_item_note(item_id, second.notes[0].id)
        assert after is not None and [n.body for n in after.notes] == ["second"]
        assert [n.body for n in brain.get_topic(topic.id).items[0].notes] == ["second"]
    finally:
        _cleanup(topic.id, meeting_id)


def test_topic_notes_add_list_delete(db_ready):
    topic, meeting_id, _ = _make_topic_with_item()
    try:
        added = brain.add_topic_note(topic.id, "topic note")
        assert added is not None and [n.body for n in added.notes] == ["topic note"]
        after = brain.delete_topic_note(topic.id, added.notes[0].id)
        assert after is not None and list(after.notes) == []
    finally:
        _cleanup(topic.id, meeting_id)


def test_missing_parent_is_reported(db_ready):
    for call in (brain.add_item_note, brain.delete_item_note):
        with pytest.raises(ItemNotFound):
            call("does-not-exist", "x")
    for call in (brain.add_topic_note, brain.delete_topic_note):
        with pytest.raises(TopicNotFound):
            call("does-not-exist", "x")


def test_empty_note_rejected():
    with pytest.raises(ValidationError):
        NoteCreate(body="   ")


def test_notes_removed_with_parents(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    brain.add_item_note(item_id, "a")
    brain.add_topic_note(topic.id, "b")
    _cleanup(topic.id, meeting_id)
    with db.get_session() as session:
        remaining = [n for n in session.query(NoteRow).all() if n.item_id == item_id or n.topic_id == topic.id]
        assert remaining == []


def test_notes_can_be_edited(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        item = brain.add_item_note(item_id, "old")
        edited = brain.edit_item_note(item_id, item.notes[0].id, "new")
        assert edited is not None and [n.body for n in edited.notes] == ["new"]

        t = brain.add_topic_note(topic.id, "old")
        t_edited = brain.edit_topic_note(topic.id, t.notes[0].id, "new")
        assert t_edited is not None and [n.body for n in t_edited.notes] == ["new"]

        with pytest.raises(ItemNotFound):
            brain.edit_item_note("does-not-exist", "n", "x")
        with pytest.raises(TopicNotFound):
            brain.edit_topic_note("does-not-exist", "n", "x")
    finally:
        _cleanup(topic.id, meeting_id)
