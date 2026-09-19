"""Integration tests against a real Postgres+pgvector instance.

Auto-skips (module-scoped) if DATABASE_URL isn't reachable, so `pytest` stays runnable without
Docker up.
"""
from __future__ import annotations

from pathlib import Path

import boto3
import pytest
from moto import mock_aws
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app import data, db, ingest, s3_store
from app.db_models import KnowledgeItemRow

DATA_DIR = Path(__file__).resolve().parent / "fixtures"
BUCKET = "test-bucket"
PREFIX = "meetings/"
FILES = [
    "meeting-extract.json",
    "MS-PS_1-1_Meeting-Extract_082126.json",
    "MS-PS_1-1_Meeting-Extract_082726.json",
]


@pytest.fixture(scope="module")
def db_ready():
    try:
        db.init_db()
    except OperationalError:
        pytest.skip("Postgres is not reachable at DATABASE_URL; skipping DB integration tests")
    yield


def _upload_fixtures(client) -> None:
    client.create_bucket(Bucket=BUCKET)
    for filename in FILES:
        client.upload_file(str(DATA_DIR / filename), BUCKET, f"{PREFIX}{filename}")


@pytest.fixture
def seeded_meetings(db_ready, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("S3_BUCKET", BUCKET)
    monkeypatch.setenv("S3_PREFIX", PREFIX)
    # moto only intercepts requests that match a real AWS endpoint pattern
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://s3.amazonaws.com")
    monkeypatch.setenv("S3_REGION", "us-east-1")
    s3_store.clear_client_cache()

    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        _upload_fixtures(client)
        with db.get_session() as session:
            count = ingest.ingest_all_from_s3(session)
            session.commit()

    # no teardown: ingestion is upsert-based/idempotent, and this fixture ingests the same
    # meeting fixture files the dev-ingestion script uses, so leaving rows in place keeps the
    # shared local Postgres instance populated instead of wiping it out after each test run
    yield count


def test_ingest_all_from_s3_populates_postgres(seeded_meetings):
    assert seeded_meetings == 3
    meetings = data.load_meetings()
    # the shared dev database may already hold other meetings, so only require ours to be present
    assert {Path(name).stem.replace(".", "-") for name in FILES} <= {meeting.id for meeting in meetings}
    assert len(data.all_items(meetings)) > 0
    assert len(data.all_review_candidates(meetings)) > 0


def test_embeddings_are_populated_with_expected_dimension(seeded_meetings):
    with db.get_session() as session:
        rows = session.execute(select(KnowledgeItemRow)).scalars().all()
    assert rows
    for row in rows:
        assert row.embedding is not None
        assert len(row.embedding) == 384


def test_semantic_similar_items_excludes_self_and_respects_limit(seeded_meetings):
    meetings = data.load_meetings()
    item = data.all_items(meetings)[0]
    similar = data.semantic_similar_items(item, limit=3)
    assert len(similar) <= 3
    assert all(candidate.id != item.id for candidate in similar)


def test_search_returns_closest_matches_and_related_topics(seeded_meetings):
    meetings = data.load_meetings()
    item = data.all_items(meetings)[0]
    items, topics = data.search(item.description, limit=3)
    assert len(items) <= 3
    assert all(isinstance(candidate, type(item)) for candidate in items)
    assert item.id in {candidate.id for candidate in items}
    # results are ranked confidence-first (HIGH before MEDIUM before LOW)
    confidence_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    ranks = [confidence_rank[candidate.confidence] for candidate in items]
    assert ranks == sorted(ranks)
    # each returned topic must own at least one of the matched items, not just an unrelated one
    matched_item_ids = {candidate.id for candidate in items}
    for topic in topics:
        assert any(topic_item.id in matched_item_ids for topic_item in topic.items)


def test_ingestion_is_idempotent(seeded_meetings):
    with db.get_session() as session:
        before = len(session.execute(select(KnowledgeItemRow)).scalars().all())

    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        _upload_fixtures(client)
        with db.get_session() as session:
            ingest.ingest_all_from_s3(session)
            session.commit()

    with db.get_session() as session:
        after = len(session.execute(select(KnowledgeItemRow)).scalars().all())
    assert before == after


def _reingest_fixtures(session) -> tuple[int, bool]:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        _upload_fixtures(client)
        result = ingest._ingest_all(session)
        session.commit()
    return result


def _record_embeddings(monkeypatch) -> list[list[str]]:
    embedded: list[list[str]] = []
    real_embed = ingest.embeddings.embed_texts
    monkeypatch.setattr(ingest.embeddings, "embed_texts", lambda texts: embedded.append(texts) or real_embed(texts))
    return embedded


def test_reingesting_unchanged_meetings_skips_stored_items_and_reports_no_change(seeded_meetings, monkeypatch):
    embedded = _record_embeddings(monkeypatch)
    with db.get_session() as session:
        stored = {row.description for row in session.execute(select(KnowledgeItemRow)).scalars()}
        count, changed = _reingest_fixtures(session)
    assert count == 3
    assert changed is False
    # only near-duplicates of another extract's items (never stored, so re-detected each run) may be embedded
    assert not stored & {text for batch in embedded for text in batch}


def test_reingesting_edited_description_reembeds_only_that_item(seeded_meetings, monkeypatch):
    with db.get_session() as session:
        row = session.execute(
            select(KnowledgeItemRow).where(KnowledgeItemRow.meeting_id == "meeting-extract").limit(1)
        ).scalar_one()
        item_id, original = row.id, row.description
        row.description = "stale description"
        session.commit()

    embedded = _record_embeddings(monkeypatch)
    with db.get_session() as session:
        _, changed = _reingest_fixtures(session)
    assert changed is True
    assert original in {text for batch in embedded for text in batch}
    with db.get_session() as session:
        assert session.get(KnowledgeItemRow, item_id).description == original
