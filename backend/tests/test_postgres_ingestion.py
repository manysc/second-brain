"""Integration tests against a real Postgres+pgvector instance.

Auto-skips (module-scoped) if DATABASE_URL isn't reachable, so `pytest` stays runnable without
Docker up.
"""
from __future__ import annotations

from pathlib import Path

import boto3
import pytest
from moto import mock_aws
from sqlalchemy import delete, select

from app.application.dtos import IngestSummary, KnowledgeItemDTO
from app.infrastructure.external_services import embeddings
from app.infrastructure.external_services import s3_storage as s3_store
from app.infrastructure.persistence import database as db
from app.infrastructure.persistence.orm_models import (
    KnowledgeItemRow,
    MeetingRow,
    ReviewCandidateRow,
    TopicRow,
)
from tests.support import brain, ingest_everything

DATA_DIR = Path(__file__).resolve().parent / "fixtures"
BUCKET = "test-bucket"
PREFIX = "meetings/"
FILES = [
    "synthetic-extract.json",
    "synthetic-sync-a.json",
    "synthetic-sync-b.json",
]


@pytest.fixture(scope="module", autouse=True)
def _remove_fixture_meetings(db_ready):
    # fixtures are synthetic and their file names can't collide with real meeting ids, so once the module
    # is done drop them - otherwise their items (and "suggested new topics") linger in the dev database
    yield
    meeting_ids = [Path(name).stem for name in FILES]
    with db.get_session() as session:
        topic_ids = {
            topic_id
            for (topic_id,) in session.execute(
                select(KnowledgeItemRow.topic_id).where(
                    KnowledgeItemRow.meeting_id.in_(meeting_ids), KnowledgeItemRow.topic_id.is_not(None)
                )
            )
        }
        session.execute(delete(ReviewCandidateRow).where(ReviewCandidateRow.meeting_id.in_(meeting_ids)))
        session.execute(delete(KnowledgeItemRow).where(KnowledgeItemRow.meeting_id.in_(meeting_ids)))
        session.execute(delete(MeetingRow).where(MeetingRow.id.in_(meeting_ids)))
        if topic_ids:
            # only topics left empty are removed, so a real topic is never touched
            still_used = set(session.execute(select(KnowledgeItemRow.topic_id).where(KnowledgeItemRow.topic_id.in_(topic_ids))).scalars())
            if topic_ids - still_used:
                session.execute(delete(TopicRow).where(TopicRow.id.in_(topic_ids - still_used)))
        session.commit()


def _items(meetings):
    return [item for meeting in meetings for item in meeting.items]


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
            count = ingest_everything(session).processed
            session.commit()

    # rows stay for the rest of the module (ingestion is idempotent); _remove_fixture_meetings cleans up
    yield count


def test_ingest_all_from_s3_populates_postgres(seeded_meetings):
    assert seeded_meetings == 3
    meetings = brain.list_meetings()
    # the shared dev database may already hold other meetings, so only require ours to be present
    assert {Path(name).stem.replace(".", "-") for name in FILES} <= {meeting.id for meeting in meetings}
    assert len(_items(meetings)) > 0
    assert any(meeting.review_candidates for meeting in meetings)


def test_embeddings_are_populated_with_expected_dimension(seeded_meetings):
    with db.get_session() as session:
        rows = session.execute(select(KnowledgeItemRow)).scalars().all()
    assert rows
    for row in rows:
        assert row.embedding is not None
        assert len(row.embedding) == 384


def test_semantic_similar_items_excludes_self_and_respects_limit(seeded_meetings):
    meetings = brain.list_meetings()
    item = _items(meetings)[0]
    similar = brain.find_similar_items(item, limit=3)
    assert len(similar) <= 3
    assert all(candidate.id != item.id for candidate in similar)


def test_search_returns_closest_matches_and_related_topics(seeded_meetings):
    meetings = brain.list_meetings()
    item = _items(meetings)[0]
    result = brain.search(item.description, limit=3)
    items, topics = result.items, result.topics
    assert len(items) <= 3
    assert all(isinstance(candidate, KnowledgeItemDTO) for candidate in items)
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
            ingest_everything(session).processed
            session.commit()

    with db.get_session() as session:
        after = len(session.execute(select(KnowledgeItemRow)).scalars().all())
    assert before == after


def _reingest_fixtures(session) -> IngestSummary:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        _upload_fixtures(client)
        result = ingest_everything(session)
        session.commit()
    return result


def _record_embeddings(monkeypatch) -> list[list[str]]:
    embedded: list[list[str]] = []
    real_embed = embeddings.embed_texts
    monkeypatch.setattr(embeddings, "embed_texts", lambda texts: embedded.append(texts) or real_embed(texts))
    return embedded


def test_reingesting_unchanged_meetings_skips_stored_items_and_reports_no_change(seeded_meetings, monkeypatch):
    embedded = _record_embeddings(monkeypatch)
    with db.get_session() as session:
        stored = {row.description for row in session.execute(select(KnowledgeItemRow)).scalars()}
        summary = _reingest_fixtures(session)
    assert summary.processed == 3
    assert (summary.new, summary.updated, summary.unchanged) == (0, 0, 3)
    assert summary.changed is False
    # only near-duplicates of another extract's items (never stored, so re-detected each run) may be embedded
    assert not stored & {text for batch in embedded for text in batch}


def test_reingesting_edited_description_reembeds_only_that_item(seeded_meetings, monkeypatch):
    with db.get_session() as session:
        row = session.execute(
            select(KnowledgeItemRow).where(KnowledgeItemRow.meeting_id == "synthetic-extract").limit(1)
        ).scalar_one()
        item_id, original = row.id, row.description
        row.description = "stale description"
        session.commit()

    embedded = _record_embeddings(monkeypatch)
    with db.get_session() as session:
        summary = _reingest_fixtures(session)
    assert summary.changed is True
    assert (summary.new, summary.updated) == (0, 1)
    assert original in {text for batch in embedded for text in batch}
    with db.get_session() as session:
        assert session.get(KnowledgeItemRow, item_id).description == original


def test_reingesting_reports_a_deleted_meeting_as_new(seeded_meetings):
    meeting_id = Path(FILES[-1]).stem
    with db.get_session() as session:
        session.execute(delete(ReviewCandidateRow).where(ReviewCandidateRow.meeting_id == meeting_id))
        session.execute(delete(KnowledgeItemRow).where(KnowledgeItemRow.meeting_id == meeting_id))
        session.execute(delete(MeetingRow).where(MeetingRow.id == meeting_id))
        session.commit()

    with db.get_session() as session:
        summary = _reingest_fixtures(session)
    assert summary.new == 1
    assert summary.new + summary.updated + summary.unchanged == 3
    with db.get_session() as session:
        assert session.get(MeetingRow, meeting_id) is not None
