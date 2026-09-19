"""Ports scripts/verify-ingestion.mjs: sanity-checks the raw extraction files and app.data loading."""
import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from app import ingest, s3_store

DATA_DIR = Path(__file__).resolve().parent / "fixtures"
BUCKET = "test-bucket"
PREFIX = "meetings/"

EXPECTED_COUNTS = {"ideas": 2, "decisions": 5, "actions": 10, "questions": 7, "review_candidates": 4}
EXPECTED_RELATIONS = [
    ("A-007", "I-002"),
    ("D-001", "A-002"),
    ("D-001", "Q-001"),
    ("D-004", "A-001"),
    ("D-004", "A-009"),
    ("D-004", "A-010"),
]


def _raw_data(filename: str = "synthetic-extract.json") -> dict:
    original = (DATA_DIR / filename).read_text(encoding="utf8").strip()
    repaired = original if original.startswith("{") else f"{{{original}}}"
    return json.loads(repaired)


def test_candidate_counts_match_expected():
    raw = _raw_data()
    for key, count in EXPECTED_COUNTS.items():
        assert len(raw[key]) == count, f"{key}: expected {count}, got {len(raw[key])}"


def test_related_candidate_links_are_preserved():
    raw = _raw_data()
    all_candidates = [*raw["ideas"], *raw["decisions"], *raw["actions"], *raw["questions"]]
    by_id = {candidate["candidate_id"]: candidate for candidate in all_candidates}
    for source_id, target_id in EXPECTED_RELATIONS:
        assert target_id in by_id[source_id]["related_candidate_ids"], f"{source_id} -> {target_id} missing"


def test_ambiguous_due_dates_are_not_fabricated():
    raw = _raw_data()
    all_candidates = [*raw["ideas"], *raw["decisions"], *raw["actions"], *raw["questions"]]
    by_id = {candidate["candidate_id"]: candidate for candidate in all_candidates}
    assert by_id["A-009"]["due_date"] == "2026-08-25"
    assert by_id["A-010"]["due_date"] is None


def test_review_candidates_are_neither_promoted_nor_lost():
    raw = _raw_data()
    assert len(raw["review_candidates"]) == 4


@pytest.fixture
def s3_env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("S3_BUCKET", BUCKET)
    monkeypatch.setenv("S3_PREFIX", PREFIX)
    # moto only intercepts requests that match a real AWS endpoint pattern
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://s3.amazonaws.com")
    monkeypatch.setenv("S3_REGION", "us-east-1")
    s3_store.clear_client_cache()
    yield
    s3_store.clear_client_cache()


def _upload(client, filename: str) -> None:
    client.upload_file(str(DATA_DIR / filename), BUCKET, f"{PREFIX}{filename}")


def test_parse_meeting_from_s3_normalizes_the_same_counts(s3_env):
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        _upload(client, "synthetic-extract.json")

        keys = s3_store.list_extract_keys()
        assert len(keys) == 1
        meeting = ingest.parse_meeting_from_s3(keys[0])
        assert len(meeting.items) == sum(
            EXPECTED_COUNTS[key] for key in ("ideas", "decisions", "actions", "questions")
        )
        assert len(meeting.review_candidates) == EXPECTED_COUNTS["review_candidates"]


def test_parse_meeting_from_s3_derives_unique_ids_from_s3_key_when_source_ids_collide(s3_env):
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        # these fixtures share/omit meeting_id in their own JSON (real data-quality issue)
        _upload(client, "synthetic-sync-a.json")
        _upload(client, "synthetic-sync-b.json")

        meetings = [ingest.parse_meeting_from_s3(key) for key in s3_store.list_extract_keys()]
        assert len(meetings) == 2
        assert meetings[0].id != meetings[1].id

        all_ids = [item.id for meeting in meetings for item in meeting.items]
        assert len(all_ids) == len(set(all_ids))

