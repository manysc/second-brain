"""The REST API over in-memory fakes: status codes, error wording and payload shapes, with no database or S3.
The OpenAPI document itself is pinned by tests/test_contracts.py."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.application.exceptions import MalformedExtract
from app.domain.entities.meeting import Meeting
from app.domain.value_objects.extraction import ExtractedMeeting
from app.presentation.api.app_factory import create_app, run_startup_ingest
from tests.application.fakes import World
from tests.domain import factories as make

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
BILLING, HIRING = [1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]


@pytest.fixture
def world() -> World:
    world = World({"Export invoices as parquet": BILLING, "Open a backend role": HIRING})
    world.db.seed(
        Meeting(id="m1", title="Sync", date="2026-06-01", source_url="sync.json"),
        make.topic("billing", "Billing"),
        make.topic("hiring", "Hiring"),
        make.item("m1:A-1", description="Export invoices as parquet", topic_id="billing", theme="Billing", embedding=BILLING),
        make.item("m1:A-2", description="Open a backend role", topic_id="hiring", theme="Hiring", embedding=HIRING),
        make.candidate("m1:review-1", description="Plan the offsite"),
    )
    return world


@pytest.fixture
def client(world: World) -> TestClient:
    # no `with`: the lifespan (storage bootstrap, warm-up, startup ingestion) does not run
    return TestClient(create_app(world.app, ingest_on_startup=False))


def detail(response) -> str:
    return response.json()["detail"]


# -- payload shape ---------------------------------------------------------------------------------------


def test_items_are_serialized_camel_case_with_open_closed_status(client, world):
    world.app.set_item_status("m1:A-1", "Answered in follow-up")
    [item] = [i for i in client.get("/api/items").json() if i["id"] == "m1:A-1"]
    assert item["status"] == "Closed" and item["topicId"] == "billing" and item["topicName"] == "Billing"
    assert set(item) >= {"dueDate", "dueDateSourceText", "relatedIds", "meetingId", "effectivePriority", "manualOverride"}
    assert item["evidence"] == {"speaker": "Ana", "timestamp": "00:01", "quote": "we ship", "context": "planning"}


def test_item_filters_use_query_aliases(client):
    assert [i["id"] for i in client.get("/api/items", params={"type": "ACTION", "status": "Open"}).json()] == ["m1:A-1", "m1:A-2"]
    assert client.get("/api/items", params={"type": "BOGUS"}).status_code == 422
    assert client.get("/api/items", params={"priority": "MAJOR"}).json() == []


def test_topic_payload_carries_priority_notes_tags_and_images_without_storage_keys(client, world):
    client.post("/api/topics/billing/recalculate-priority")
    client.post("/api/topics/billing/notes", json={"body": "  hello  "})
    client.post("/api/topics/billing/tags", json={"tag": " Q3  Launch "})
    client.post("/api/topics/billing/images", files={"file": ("C:\\pics\\a.png", PNG, "image/png")})
    topic = client.get("/api/topics/billing").json()
    assert topic["priority"]["calculatedPriority"] == "MINOR" and topic["priority"]["effectivePriority"] == "MINOR"
    assert {"signals", "hardEscalations", "calculatedAt", "algorithmVersion", "manualOverride"} <= set(topic["priority"])
    assert [n["body"] for n in topic["notes"]] == ["hello"] and topic["tags"] == ["q3 launch"]
    [image] = topic["images"]
    assert set(image) == {"id", "filename", "contentType", "size", "createdAt"} and image["filename"] == "a.png"

    served = client.get(f"/api/topics/billing/images/{image['id']}")
    assert served.content == PNG and served.headers["content-type"] == "image/png"
    assert served.headers["cache-control"] == "private, max-age=3600"


# -- not found -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body", "expected"),
    [
        ("get", "/api/topics/nope", None, "Topic not found"),
        ("get", "/api/topics/nope/related", None, "Topic not found"),
        ("get", "/api/topics/nope/priority-history", None, "Topic not found"),
        ("patch", "/api/topics/nope", {"name": "x"}, "Topic not found"),
        ("delete", "/api/topics/nope", None, "Topic not found"),
        ("patch", "/api/topics/nope/status", {"status": "Closed"}, "Topic not found"),
        ("post", "/api/topics/nope/notes", {"body": "x"}, "Topic not found"),
        ("post", "/api/topics/nope/tags", {"tag": "x"}, "Topic not found"),
        ("post", "/api/topics/nope/items", {"type": "IDEA", "description": "x"}, "Topic not found"),
        ("post", "/api/topics/nope/recalculate-priority", None, "Topic not found"),
        ("patch", "/api/topics/nope/priority-override", {"priority": "MAJOR"}, "Topic not found"),
        ("post", "/api/topics/billing/merge", {"targetTopicId": "nope"}, "Topic not found"),
        ("get", "/api/topics/billing/images/nope", None, "Image not found"),
        ("get", "/api/items/nope", None, "Item not found"),
        ("patch", "/api/items/nope", {"description": "x"}, "Item not found"),
        ("delete", "/api/items/nope", None, "Item not found"),
        ("patch", "/api/items/nope/status", {"status": "Closed"}, "Item not found"),
        ("patch", "/api/items/nope/priority-override", {"priority": None}, "Item not found"),
        ("patch", "/api/items/nope/topic", {"topicId": "billing"}, "Item not found"),
        ("patch", "/api/items/m1:A-1/topic", {"topicId": "nope"}, "Topic not found"),
        ("post", "/api/items/nope/notes", {"body": "x"}, "Item not found"),
        ("post", "/api/items/nope/tags", {"tag": "x"}, "Item not found"),
        ("get", "/api/meetings/nope", None, "Meeting not found"),
        ("patch", "/api/review/nope", {"status": "REJECTED"}, "Review candidate not found"),
        ("patch", "/api/review/m1:review-1", {"status": "ACCEPTED", "topicId": "nope"}, "Topic not found"),
        ("post", "/api/review/topic-proposals/accept", {"suggestedName": "nope"}, "Topic proposal not found"),
        ("post", "/api/review/topic-proposals/reject", {"suggestedName": "nope"}, "Topic proposal not found"),
    ],
)
def test_missing_resources_are_404_with_their_own_wording(client, method, path, body, expected):
    response = client.request(method, path, json=body)
    assert (response.status_code, detail(response)) == (404, expected)


def test_no_meetings_yet_is_a_404():
    response = TestClient(create_app(World().app, ingest_on_startup=False)).get("/api/meeting")
    assert (response.status_code, detail(response)) == (404, "No meetings available")


# -- conflicts and invalid requests ----------------------------------------------------------------------


def test_topic_conflicts(client):
    created = client.post("/api/topics", json={"name": "Finance"})
    assert created.status_code == 201 and created.json()["name"] == "Finance"
    duplicate = client.post("/api/topics", json={"name": "Billing"})
    assert (duplicate.status_code, detail(duplicate)) == (409, "Topic 'Billing' already exists")
    renamed = client.patch("/api/topics/hiring", json={"name": "Billing"})
    assert (renamed.status_code, detail(renamed)) == (409, "Topic 'Billing' already exists")
    busy = client.delete("/api/topics/billing")
    assert (busy.status_code, detail(busy)) == (409, "Topic still has 1 item(s) assigned; reassign them before deleting")
    assert client.delete(f"/api/topics/{created.json()['id']}").status_code == 204
    self_merge = client.post("/api/topics/billing/merge", json={"targetTopicId": "billing"})
    assert (self_merge.status_code, detail(self_merge)) == (400, "cannot merge a topic into itself")


def test_bulk_move_validation(client):
    empty = client.patch("/api/items/topic", json={"itemIds": [], "topicId": "billing"})
    assert (empty.status_code, detail(empty)) == (400, "itemIds must not be empty")
    missing_topic = client.patch("/api/items/topic", json={"itemIds": ["m1:A-1"], "topicId": "nope"})
    assert (missing_topic.status_code, detail(missing_topic)) == (404, "topic not found")
    missing_item = client.patch("/api/items/topic", json={"itemIds": ["m1:A-1", "ghost"], "topicId": "hiring"})
    assert (missing_item.status_code, detail(missing_item)) == (404, "items not found: ['ghost']")
    moved = client.patch("/api/items/topic", json={"itemIds": ["m1:A-1"], "topicId": "hiring"})
    assert moved.status_code == 200 and moved.json()[0]["topicId"] == "hiring"


def test_item_edit_and_delete_rules(client):
    fixed_type = client.patch("/api/items/m1:A-1", json={"type": "IDEA"})
    assert (fixed_type.status_code, detail(fixed_type)) == (400, "The type of an item extracted from a meeting cannot be changed")
    extracted = client.delete("/api/items/m1:A-1")
    assert (extracted.status_code, detail(extracted)) == (409, "Only manually added items can be deleted")
    assert client.patch("/api/items/m1:A-1", json={}).status_code == 422  # an edit must set at least one field
    manual = client.post("/api/topics/billing/items", json={"type": "ACTION", "description": " Call ", "dueDate": " "})
    assert manual.status_code == 201 and manual.json()["description"] == "Call" and manual.json()["dueDate"] is None
    assert client.delete(f"/api/items/{manual.json()['id']}").status_code == 204


def test_tag_limits_are_worded_per_resource(client, world):
    for index in range(20):
        world.app.add_item_tag("m1:A-1", f"t{index}")
        world.app.add_topic_tag("billing", f"t{index}")
    item = client.post("/api/items/m1:A-1/tags", json={"tag": "one more"})
    assert (item.status_code, detail(item)) == (400, "An item can have at most 20 tags")
    topic = client.post("/api/topics/billing/tags", json={"tag": "one more"})
    assert (topic.status_code, detail(topic)) == (400, "A topic can have at most 20 tags")
    assert client.post("/api/topics/billing/tags", json={"tag": "x" * 41}).status_code == 422
    removed = client.delete("/api/topics/billing/tags", params={"tag": "T0"})
    assert removed.status_code == 200 and "t0" not in removed.json()["tags"]


def test_image_upload_errors(client):
    not_an_image = client.post("/api/topics/billing/images", files={"file": ("a.png", b"hello", "image/png")})
    assert (not_an_image.status_code, detail(not_an_image)) == (415, "Only PNG, JPEG, GIF and WebP images are supported")
    too_large = client.post("/api/topics/billing/images", files={"file": ("a.png", PNG + b"x" * (5 * 1024 * 1024), "image/png")})
    assert (too_large.status_code, detail(too_large)) == (413, "Image is larger than 5 MB")


def test_review_and_proposal_decisions(client, world):
    accepted = client.patch("/api/review/m1:review-1", json={"status": "ACCEPTED", "topicId": "hiring"})
    assert accepted.status_code == 200 and accepted.json()["status"] == "ACCEPTED"
    again = client.patch("/api/review/m1:review-1", json={"status": "REJECTED"})
    assert (again.status_code, detail(again)) == (409, "Review candidate already decided")

    world.db.seed(make.topic("unc", "Uncategorized"), make.item("m1:P-1", topic_id="unc", suggested_topic="Offsite", embedding=HIRING))
    bad_target = client.post("/api/review/topic-proposals/accept", json={"suggestedName": "Offsite", "existingTopicId": "ghost"})
    assert (bad_target.status_code, detail(bad_target)) == (400, "topic not found")
    blank = client.post("/api/review/topic-proposals/accept", json={"suggestedName": "Offsite", "topicName": "  "})
    assert (blank.status_code, detail(blank)) == (400, "topic name must not be empty")
    filed = client.post("/api/review/topic-proposals/accept", json={"suggestedName": "Offsite", "topicName": "Team offsite"})
    assert filed.status_code == 200 and filed.json()[0]["topicName"] == "Team offsite"
    assert client.post("/api/review/topic-proposals/reject", json={"suggestedName": "Offsite"}).status_code == 404


def test_priority_endpoints(client):
    assert client.post("/api/topics/recalculate-priority").json() == {"recalculated": 2}
    overridden = client.patch("/api/topics/billing/priority-override", json={"priority": "CRITICAL", "reason": "exec ask"})
    assert overridden.json()["priority"]["effectivePriority"] == "CRITICAL"
    assert overridden.json()["priority"]["manualOverride"]["reason"] == "exec ask"
    assert client.get("/api/topics/billing/priority-history").json() == []
    assert client.get("/api/priority-history/recent", params={"days": 0}).status_code == 422


def test_search_graph_and_follow_up_respond(client, world):
    world.embedder.vectors["invoices"] = BILLING
    result = client.get("/api/search", params={"q": "invoices"}).json()
    assert result["items"][0]["id"] == "m1:A-1" and [t["id"] for t in result["topics"]] == ["billing", "hiring"]
    assert client.get("/api/search").status_code == 422
    graph = client.get("/api/graph", params={"minSimilarity": 0.5}).json()
    assert set(graph) == {"nodes", "edges", "topics", "topicLinks"} and len(graph["nodes"]) == 2
    follow_up = client.get("/api/follow-up", params={"limit": 1, "dueSoonDays": 3}).json()
    assert len(follow_up["topics"]) == 1 and "generatedAt" in follow_up
    assert client.get("/api/follow-up", params={"limit": 0}).status_code == 422


# -- ingestion -------------------------------------------------------------------------------------------


def extract(meeting_id: str) -> list[ExtractedMeeting]:
    return [ExtractedMeeting(id=meeting_id, title="t", date="2026-06-10", source_url=f"{meeting_id}.json")]


def test_ingest_reports_new_updated_and_unchanged_meetings(client, world):
    world.source.extracts = {"m1.json": extract("m1"), "m8.json": extract("m8"), "m9.json": extract("m9")}
    world.db.seed(Meeting(id="m8", title="t", date="2026-06-10", source_url="m8.json"))
    response = client.post("/api/ingest")
    assert response.status_code == 200
    # m1 existed with other details (updated), m8 is identical (unchanged), m9 is new
    assert response.json() == {"meetings": 3, "new": 1, "updated": 1, "unchanged": 1}


def test_ingest_rejects_an_overlapping_run(client, world):
    with world.app.ingest_extracts._lock:
        response = client.post("/api/ingest")
    assert (response.status_code, detail(response)) == (409, "Ingestion is already running")


def test_ingest_with_unreachable_storage_is_a_503(client, world):
    world.source.unreachable = True
    response = client.post("/api/ingest")
    assert (response.status_code, detail(response)) == (503, "Could not reach SeaweedFS")


def test_a_malformed_extract_is_a_422_and_releases_the_lock(client, world, monkeypatch):
    def malformed(key: str):
        raise MalformedExtract(f"'{key}' is not a recognized single-meeting or bundle extraction file")

    world.source.extracts = {"bad.json": extract("bad")}
    monkeypatch.setattr(world.source, "load", malformed)
    response = client.post("/api/ingest")
    assert response.status_code == 422 and "bad.json" in detail(response)

    monkeypatch.undo()
    assert client.post("/api/ingest").json()["new"] == 1


def test_startup_ingest_retries_while_storage_is_unreachable_then_gives_up_quietly(world):
    waits: list[float] = []
    world.source.unreachable = True
    run_startup_ingest(world.app, sleep=waits.append)
    assert waits == [3.0, 6.0, 12.0, 24.0]  # four retries, backing off, then it stops without raising

    world.source.unreachable = False
    world.source.extracts = {"m9.json": extract("m9")}
    run_startup_ingest(world.app, sleep=waits.append)
    assert "m9" in world.db.state.meetings and len(waits) == 4
