"""Verifies that two LLM extracts of the same meeting (via the "<key>--<variant>.json" naming
convention) merge into one meeting, with near-duplicate items reinforced instead of duplicated.

Auto-skips (module-scoped) if DATABASE_URL isn't reachable, mirroring test_postgres_ingestion.py.
"""
from __future__ import annotations

from pathlib import Path

import boto3
import pytest
from moto import mock_aws
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app import data, db, ingest, s3_store
from app.db_models import KnowledgeItemRow, MeetingRow, ReviewCandidateRow, TopicRow

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
BUCKET = "test-multi-source-bucket"
PREFIX = "meetings/"
FILES = ["multi-source-sample--llm-a.json", "multi-source-sample--llm-b.json"]


@pytest.fixture(scope="module")
def db_ready():
    try:
        db.init_db()
    except OperationalError:
        pytest.skip("Postgres is not reachable at DATABASE_URL; skipping DB integration tests")
    yield


@pytest.fixture
def ingested_meeting(db_ready, monkeypatch):
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
        client.create_bucket(Bucket=BUCKET)
        for filename in FILES:
            client.upload_file(str(DATA_DIR / filename), BUCKET, f"{PREFIX}{filename}")
        with db.get_session() as session:
            ingest.ingest_all_from_s3(session)
            session.commit()

    # unlike test_postgres_ingestion.py's seeded_meetings (real sample data meant to stay), this
    # meeting is synthetic and only exists to exercise the merge logic, so clean it back up -
    # topics are only removed if now empty, so a same-named real topic is never touched
    yield "multi-source-sample"

    with db.get_session() as session:
        topic_ids = {
            row_id
            for (row_id,) in session.execute(
                select(KnowledgeItemRow.topic_id).where(
                    KnowledgeItemRow.meeting_id == "multi-source-sample", KnowledgeItemRow.topic_id.is_not(None)
                )
            )
        }
        session.execute(
            ReviewCandidateRow.__table__.delete().where(ReviewCandidateRow.meeting_id == "multi-source-sample")
        )
        session.execute(KnowledgeItemRow.__table__.delete().where(KnowledgeItemRow.meeting_id == "multi-source-sample"))
        session.execute(MeetingRow.__table__.delete().where(MeetingRow.id == "multi-source-sample"))
        if topic_ids:
            still_used = {
                row_id for (row_id,) in session.execute(select(KnowledgeItemRow.topic_id).where(KnowledgeItemRow.topic_id.in_(topic_ids)))
            }
            empty_topic_ids = topic_ids - still_used
            if empty_topic_ids:
                session.execute(TopicRow.__table__.delete().where(TopicRow.id.in_(empty_topic_ids)))
        session.commit()


def test_both_variants_share_one_meeting_row(ingested_meeting):
    with db.get_session() as session:
        rows = session.execute(select(MeetingRow).where(MeetingRow.id == ingested_meeting)).scalars().all()
    assert len(rows) == 1


def test_near_duplicate_decision_merges_into_one_item_with_high_confidence(ingested_meeting):
    with db.get_session() as session:
        rows = (
            session.execute(
                select(KnowledgeItemRow).where(
                    KnowledgeItemRow.meeting_id == ingested_meeting, KnowledgeItemRow.type == "DECISION"
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].confidence == "HIGH"


def test_distinct_actions_from_both_variants_are_both_kept(ingested_meeting):
    with db.get_session() as session:
        rows = (
            session.execute(
                select(KnowledgeItemRow).where(
                    KnowledgeItemRow.meeting_id == ingested_meeting, KnowledgeItemRow.type == "ACTION"
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 2
    assert {row.id for row in rows} == {
        "multi-source-sample:llm-a:A-001",
        "multi-source-sample:llm-b:A-001",
    }


def test_meetings_load_reflects_the_merge(ingested_meeting):
    meetings = data.load_meetings()
    meeting = next(m for m in meetings if m.id == ingested_meeting)
    assert len(meeting.items) == 3  # 1 merged decision + 2 distinct actions (no review candidates)
