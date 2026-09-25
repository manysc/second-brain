"""Tests for human-assigned tags on topics. Reuses test_item_priority's fixtures
(auto-skips if Postgres isn't reachable)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app import data
from app.models import MAX_TAG_LENGTH, MAX_TAGS, TagCreate
from tests.test_item_priority import _cleanup, _make_topic_with_item, db_ready  # noqa: F401


def test_add_and_remove_tags(db_ready):
    topic, meeting_id, _ = _make_topic_with_item()
    try:
        assert topic.tags == []
        added = data.add_topic_tag(topic.id, "launch")
        assert added is not None and added.tags == ["launch"]
        added = data.add_topic_tag(topic.id, "q3")
        assert added is not None and added.tags == ["launch", "q3"]
        assert data.get_topic_by_id(topic.id).tags == ["launch", "q3"]

        removed = data.remove_topic_tag(topic.id, "launch")
        assert removed is not None and removed.tags == ["q3"]
    finally:
        _cleanup(topic.id, meeting_id)


def test_duplicate_tag_is_a_noop_and_matching_is_normalised(db_ready):
    topic, meeting_id, _ = _make_topic_with_item()
    try:
        data.add_topic_tag(topic.id, "Q3  Launch")
        again = data.add_topic_tag(topic.id, "q3 launch")
        assert again is not None and again.tags == ["q3 launch"]
        removed = data.remove_topic_tag(topic.id, "  Q3 LAUNCH ")
        assert removed is not None and removed.tags == []
    finally:
        _cleanup(topic.id, meeting_id)


def test_removing_absent_tag_is_a_noop(db_ready):
    topic, meeting_id, _ = _make_topic_with_item()
    try:
        data.add_topic_tag(topic.id, "keep")
        after = data.remove_topic_tag(topic.id, "missing")
        assert after is not None and after.tags == ["keep"]
    finally:
        _cleanup(topic.id, meeting_id)


def test_tag_limit_per_topic(db_ready):
    topic, meeting_id, _ = _make_topic_with_item()
    try:
        for i in range(MAX_TAGS):
            data.add_topic_tag(topic.id, f"tag-{i}")
        with pytest.raises(data.TooManyTags):
            data.add_topic_tag(topic.id, "one-too-many")
        # re-adding an existing tag at the limit is still fine
        assert data.add_topic_tag(topic.id, "tag-0") is not None
    finally:
        _cleanup(topic.id, meeting_id)


def test_missing_topic_returns_none(db_ready):
    assert data.add_topic_tag("does-not-exist", "x") is None
    assert data.remove_topic_tag("does-not-exist", "x") is None


def test_tag_payload_is_normalised_and_validated():
    assert TagCreate(tag="  Q3   Launch ").tag == "q3 launch"
    with pytest.raises(ValidationError):
        TagCreate(tag="   ")
    with pytest.raises(ValidationError):
        TagCreate(tag="x" * (MAX_TAG_LENGTH + 1))
