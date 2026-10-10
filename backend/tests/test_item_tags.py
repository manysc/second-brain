"""Tests for human-assigned tags on items. Reuses test_item_priority's fixtures
(auto-skips if Postgres isn't reachable)."""
from __future__ import annotations

import pytest

from app.domain.exceptions import ItemNotFound, TooManyTags
from app.domain.value_objects.tag import MAX_TAGS
from tests.domain import factories as make
from tests.support import brain
from tests.support import cleanup as _cleanup
from tests.support import make_topic_with_item as _make_topic_with_item


def test_add_and_remove_item_tags(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        added = brain.add_item_tag(item_id, "urgent")
        assert added is not None and list(added.tags) == ["urgent"]
        added = brain.add_item_tag(item_id, "Follow Up")
        assert added is not None and list(added.tags) == ["urgent", "follow up"]
        assert list(brain.get_topic(topic.id).items[0].tags) == ["urgent", "follow up"]

        removed = brain.remove_item_tag(item_id, "URGENT")
        assert removed is not None and list(removed.tags) == ["follow up"]
    finally:
        _cleanup(topic.id, meeting_id)


def test_duplicate_item_tag_is_a_noop_and_removing_absent_tag_is_too(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        brain.add_item_tag(item_id, "q3  launch")
        again = brain.add_item_tag(item_id, "Q3 Launch")
        assert again is not None and list(again.tags) == ["q3 launch"]
        after = brain.remove_item_tag(item_id, "missing")
        assert after is not None and list(after.tags) == ["q3 launch"]
    finally:
        _cleanup(topic.id, meeting_id)


def test_item_tag_limit(db_ready):
    topic, meeting_id, item_id = _make_topic_with_item()
    try:
        for i in range(MAX_TAGS):
            brain.add_item_tag(item_id, f"tag-{i}")
        with pytest.raises(TooManyTags):
            brain.add_item_tag(item_id, "one-too-many")
        assert brain.add_item_tag(item_id, "tag-0") is not None
    finally:
        _cleanup(topic.id, meeting_id)


def test_missing_item_is_reported(db_ready):
    with pytest.raises(ItemNotFound):
        brain.add_item_tag("does-not-exist", "x")
    with pytest.raises(ItemNotFound):
        brain.remove_item_tag("does-not-exist", "x")


def test_reingest_does_not_overwrite_tags():
    # re-ingestion only refreshes what the extractor owns; tags belong to a person
    stored = make.item(tags=("keep",))
    stored.apply_extraction(make.extracted(description="reworded by the extractor"))
    assert stored.tags == ("keep",) and stored.description == "reworded by the extractor"
