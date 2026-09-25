"""Tests for images attached to topics: metadata in Postgres, bytes in S3 (moto stands in for SeaweedFS).
Reuses test_item_priority's db_ready fixture (auto-skips if Postgres isn't reachable)."""
from __future__ import annotations

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from app import data, db, s3_store
from app.db_models import TopicImageRow
from app.main import app
from tests.test_item_priority import _cleanup, _make_topic_with_item, db_ready  # noqa: F401

BUCKET = "test-second-brain"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("S3_BUCKET", BUCKET)
    monkeypatch.setenv("S3_PREFIX", "meetings/")
    monkeypatch.delenv("S3_IMAGES_PREFIX", raising=False)
    # moto only intercepts requests that match a real AWS endpoint pattern
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://s3.amazonaws.com")
    monkeypatch.setenv("S3_REGION", "us-east-1")
    s3_store.clear_client_cache()
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client
    s3_store.clear_client_cache()


def _keys(client) -> list[str]:
    return [o["Key"] for o in client.list_objects_v2(Bucket=BUCKET).get("Contents", [])]


def test_add_and_delete_image(db_ready, s3):
    topic, meeting_id, _ = _make_topic_with_item()
    try:
        added = data.add_topic_image(topic.id, "C:\\pics\\diagram.png", PNG)
        assert added is not None and len(added.images) == 1
        image = added.images[0]
        assert (image.filename, image.content_type, image.size) == ("diagram.png", "image/png", len(PNG))

        assert _keys(s3) == [f"images/topics/{topic.id}/{image.id}.png"]
        assert data.get_topic_image(topic.id, image.id) == (PNG, "image/png")

        after = data.delete_topic_image(topic.id, image.id)
        assert after is not None and after.images == []
        assert _keys(s3) == []
        assert data.get_topic_image(topic.id, image.id) is None
    finally:
        _cleanup(topic.id, meeting_id)


def test_content_type_comes_from_the_bytes_not_the_client(db_ready, s3):
    topic, meeting_id, _ = _make_topic_with_item()
    try:
        added = data.add_topic_image(topic.id, "photo.png", JPEG)
        assert added is not None
        assert added.images[0].content_type == "image/jpeg"
        assert _keys(s3)[0].endswith(".jpg")
    finally:
        _cleanup(topic.id, meeting_id)


def test_rejects_non_images_and_oversize(db_ready, s3):
    topic, meeting_id, _ = _make_topic_with_item()
    try:
        with pytest.raises(data.UnsupportedImageType):
            data.add_topic_image(topic.id, "notes.png", b"just some text, not a png")
        with pytest.raises(data.ImageTooLarge):
            data.add_topic_image(topic.id, "big.png", PNG + b"\x00" * data.MAX_IMAGE_BYTES)
        assert _keys(s3) == []
        assert data.get_topic_by_id(topic.id).images == []
    finally:
        _cleanup(topic.id, meeting_id)


def test_missing_topic_returns_none(db_ready, s3):
    assert data.add_topic_image("no-such-topic", "a.png", PNG) is None
    assert data.delete_topic_image("no-such-topic", "whatever") is None
    assert _keys(s3) == []


def test_image_of_another_topic_is_not_served(db_ready, s3):
    topic, meeting_id, _ = _make_topic_with_item()
    other = data.create_topic("image-other-topic")
    try:
        added = data.add_topic_image(topic.id, "a.png", PNG)
        assert data.get_topic_image(other.id, added.images[0].id) is None
    finally:
        data.delete_topic(other.id)
        _cleanup(topic.id, meeting_id)


def test_deleting_a_topic_removes_its_objects(db_ready, s3):
    topic = data.create_topic("image-doomed-topic")
    data.add_topic_image(topic.id, "a.png", PNG)
    assert len(_keys(s3)) == 1
    assert data.delete_topic(topic.id) is True
    assert _keys(s3) == []
    with db.get_session() as session:
        assert session.query(TopicImageRow).filter_by(topic_id=topic.id).count() == 0


def test_merge_moves_images_to_the_target(db_ready, s3):
    source = data.create_topic("image-merge-source")
    target = data.create_topic("image-merge-target")
    try:
        data.add_topic_image(source.id, "a.png", PNG)
        merged = data.merge_topics(source.id, target.id)
        assert [i.filename for i in merged.images] == ["a.png"]
        assert len(_keys(s3)) == 1  # the object is kept: merging is not a delete
    finally:
        data.delete_topic(target.id)


def test_image_routes(db_ready, s3):
    client = TestClient(app)  # no `with`: skips the startup ingestion
    topic = data.create_topic("image-route-topic")
    try:
        url = f"/api/topics/{topic.id}/images"
        assert client.post("/api/topics/nope/images", files={"file": ("a.png", PNG, "image/png")}).status_code == 404
        assert client.post(url, files={"file": ("a.png", b"not an image", "image/png")}).status_code == 415
        too_big = PNG + b"\x00" * data.MAX_IMAGE_BYTES
        assert client.post(url, files={"file": ("a.png", too_big, "image/png")}).status_code == 413

        created = client.post(url, files={"file": ("a.png", PNG, "image/png")})
        assert created.status_code == 200
        image_id = created.json()["images"][0]["id"]

        fetched = client.get(f"{url}/{image_id}")
        assert fetched.status_code == 200
        assert fetched.headers["content-type"] == "image/png" and fetched.content == PNG
        assert client.get(f"{url}/missing").status_code == 404

        deleted = client.delete(f"{url}/{image_id}")
        assert deleted.status_code == 200 and deleted.json()["images"] == []
        assert client.get(f"{url}/{image_id}").status_code == 404
    finally:
        data.delete_topic(topic.id)
