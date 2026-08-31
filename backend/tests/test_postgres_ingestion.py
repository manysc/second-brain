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

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
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
    assert len(meetings) == 3
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
