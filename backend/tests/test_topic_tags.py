"""Tests for human-assigned tags on topics. Reuses test_item_priority's fixtures
(auto-skips if Postgres isn't reachable)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.exceptions import TooManyTags, TopicNotFound
from tests.support import brain
from app.domain.value_objects.tag import MAX_TAG_LENGTH, MAX_TAGS
from app.presentation.api.schemas import TagCreate
from tests.support import cleanup as _cleanup
from tests.support import make_topic_with_item as _make_topic_with_item


def test_add_and_remove_tags(db_ready):
    topic, meeting_id, _ = _make_topic_with_item()
    try:
        assert list(topic.tags) == []
        added = brain.add_topic_tag(topic.id, "launch")
        assert added is not None and list(added.tags) == ["launch"]
        added = brain.add_topic_tag(topic.id, "q3")
        assert added is not None and list(added.tags) == ["launch", "q3"]
        assert list(brain.get_topic(topic.id).tags) == ["launch", "q3"]

        removed = brain.remove_topic_tag(topic.id, "launch")
        assert removed is not None and list(removed.tags) == ["q3"]
    finally:
        _cleanup(topic.id, meeting_id)


def test_duplicate_tag_is_a_noop_and_matching_is_normalised(db_ready):
    topic, meeting_id, _ = _make_topic_with_item()
    try:
        brain.add_topic_tag(topic.id, "Q3  Launch")
        again = brain.add_topic_tag(topic.id, "q3 launch")
        assert again is not None and list(again.tags) == ["q3 launch"]
        removed = brain.remove_topic_tag(topic.id, "  Q3 LAUNCH ")
        assert removed is not None and list(removed.tags) == []
    finally:
        _cleanup(topic.id, meeting_id)


def test_removing_absent_tag_is_a_noop(db_ready):
    topic, meeting_id, _ = _make_topic_with_item()
    try:
        brain.add_topic_tag(topic.id, "keep")
        after = brain.remove_topic_tag(topic.id, "missing")
        assert after is not None and list(after.tags) == ["keep"]
    finally:
        _cleanup(topic.id, meeting_id)


def test_tag_limit_per_topic(db_ready):
    topic, meeting_id, _ = _make_topic_with_item()
    try:
        for i in range(MAX_TAGS):
            brain.add_topic_tag(topic.id, f"tag-{i}")
        with pytest.raises(TooManyTags):
            brain.add_topic_tag(topic.id, "one-too-many")
        # re-adding an existing tag at the limit is still fine
        assert brain.add_topic_tag(topic.id, "tag-0") is not None
    finally:
        _cleanup(topic.id, meeting_id)


def test_missing_topic_is_reported(db_ready):
    with pytest.raises(TopicNotFound):
        brain.add_topic_tag("does-not-exist", "x")
    with pytest.raises(TopicNotFound):
        brain.remove_topic_tag("does-not-exist", "x")


def test_tag_payload_is_normalised_and_validated():
    assert TagCreate(tag="  Q3   Launch ").tag == "q3 launch"
    with pytest.raises(ValidationError):
        TagCreate(tag="   ")
    with pytest.raises(ValidationError):
        TagCreate(tag="x" * (MAX_TAG_LENGTH + 1))
