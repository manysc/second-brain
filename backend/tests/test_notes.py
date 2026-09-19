"""Tests for notes on items and topics. Reuses test_item_priority's fixtures
(auto-skips if Postgres isn't reachable)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app import data
from app.db_models import NoteRow
from app.models import NoteCreate
from tests.test_item_priority import _cleanup, _make_topic_with_item, db_ready  # noqa: F401


def test_item_notes_add_list_delete(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        first = data.add_item_note(item_id, "first")
        assert first is not None and [n.body for n in first.notes] == ["first"]
        second = data.add_item_note(item_id, "second")
        assert second is not None and [n.body for n in second.notes] == ["first", "second"]

        after = data.delete_item_note(item_id, second.notes[0].id)
        assert after is not None and [n.body for n in after.notes] == ["second"]
        assert [n.body for n in data.get_topic_by_id(topic.id).items[0].notes] == ["second"]
    finally:
        _cleanup(topic.id, meeting_id)


def test_topic_notes_add_list_delete(db_ready):
    topic, meeting_id, _ = _make_topic_with_item()
    try:
        added = data.add_topic_note(topic.id, "topic note")
        assert added is not None and [n.body for n in added.notes] == ["topic note"]
        after = data.delete_topic_note(topic.id, added.notes[0].id)
        assert after is not None and after.notes == []
    finally:
        _cleanup(topic.id, meeting_id)


def test_missing_parent_returns_none(db_ready):
    assert data.add_item_note("does-not-exist", "x") is None
    assert data.delete_item_note("does-not-exist", "n") is None
    assert data.add_topic_note("does-not-exist", "x") is None
    assert data.delete_topic_note("does-not-exist", "n") is None


def test_empty_note_rejected():
    with pytest.raises(ValidationError):
        NoteCreate(body="   ")


def test_notes_removed_with_parents(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    data.add_item_note(item_id, "a")
    data.add_topic_note(topic.id, "b")
    _cleanup(topic.id, meeting_id)
    with data.db.get_session() as session:
        remaining = [n for n in session.query(NoteRow).all() if n.item_id == item_id or n.topic_id == topic.id]
        assert remaining == []


def test_notes_can_be_edited(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        item = data.add_item_note(item_id, "old")
        edited = data.update_item_note(item_id, item.notes[0].id, "new")
        assert edited is not None and [n.body for n in edited.notes] == ["new"]

        t = data.add_topic_note(topic.id, "old")
        t_edited = data.update_topic_note(topic.id, t.notes[0].id, "new")
        assert t_edited is not None and [n.body for n in t_edited.notes] == ["new"]

        assert data.update_item_note("does-not-exist", "n", "x") is None
        assert data.update_topic_note("does-not-exist", "n", "x") is None
    finally:
        _cleanup(topic.id, meeting_id)
