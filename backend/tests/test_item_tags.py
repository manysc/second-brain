"""Tests for human-assigned tags on items. Reuses test_item_priority's fixtures
(auto-skips if Postgres isn't reachable)."""
from __future__ import annotations

import pytest

from app import data
from app.ingest import _ITEM_UPDATE_COLS
from app.models import MAX_TAGS
from tests.test_item_priority import _cleanup, _make_topic_with_item, db_ready  # noqa: F401


def test_add_and_remove_item_tags(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        added = data.add_item_tag(item_id, "urgent")
        assert added is not None and added.tags == ["urgent"]
        added = data.add_item_tag(item_id, "Follow Up")
        assert added is not None and added.tags == ["urgent", "follow up"]
        assert data.get_topic_by_id(topic.id).items[0].tags == ["urgent", "follow up"]

        removed = data.remove_item_tag(item_id, "URGENT")
        assert removed is not None and removed.tags == ["follow up"]
    finally:
        _cleanup(topic.id, meeting_id)


def test_duplicate_item_tag_is_a_noop_and_removing_absent_tag_is_too(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        data.add_item_tag(item_id, "q3  launch")
        again = data.add_item_tag(item_id, "Q3 Launch")
        assert again is not None and again.tags == ["q3 launch"]
        after = data.remove_item_tag(item_id, "missing")
        assert after is not None and after.tags == ["q3 launch"]
    finally:
        _cleanup(topic.id, meeting_id)


def test_item_tag_limit(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        for i in range(MAX_TAGS):
            data.add_item_tag(item_id, f"tag-{i}")
        with pytest.raises(data.TooManyTags):
            data.add_item_tag(item_id, "one-too-many")
        assert data.add_item_tag(item_id, "tag-0") is not None
    finally:
        _cleanup(topic.id, meeting_id)


def test_missing_item_returns_none(db_ready):
    assert data.add_item_tag("does-not-exist", "x") is None
    assert data.remove_item_tag("does-not-exist", "x") is None


def test_reingest_does_not_overwrite_tags():
    # upsert_meeting only rewrites the columns listed here on existing rows
    assert "tags" not in _ITEM_UPDATE_COLS
