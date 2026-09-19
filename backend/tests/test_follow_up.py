"""Integration tests for data.get_follow_up() against a real Postgres+pgvector instance.

Mirrors test_topics.py's / test_topic_priority.py's db_ready pattern (auto-skips if Postgres
isn't reachable) and seeds synthetic meetings/topics/items directly at the row level so
inclusion/exclusion/ordering/cross-topic behavior is deterministic regardless of whatever real
data is already in the database.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import OperationalError

from app import data, db
from app.db_models import KnowledgeItemRow, MeetingRow, TopicRow


@pytest.fixture(scope="module")
def db_ready():
    try:
        db.init_db()
    except OperationalError:
        pytest.skip("Postgres is not reachable at DATABASE_URL; skipping DB integration tests")
    yield


def _item_row(
    item_id: str,
    meeting_id: str,
    topic_id: str,
    type_: str,
    status: str,
    due_date: str | None = None,
    related_ids: list[str] | None = None,
) -> KnowledgeItemRow:
    return KnowledgeItemRow(
        id=item_id,
        meeting_id=meeting_id,
        topic_id=topic_id,
        type=type_,
        description=f"Synthetic {type_} for follow-up tests",
        theme=None,
        status=status,
        confidence="MEDIUM",
        owner="Ada",
        stakeholders=["Ada"],
        due_date=due_date,
        due_date_source_text=None,
        rationale=None,
        resolution=None,
        evidence_speaker="Ada",
        evidence_timestamp="00:01:00",
        evidence_quote="quote",
        evidence_context=None,
        related_ids=related_ids or [],
        embedding=None,
    )


@pytest.fixture
def follow_up_scenario(db_ready):
    """Seeds two qualifying topics (A, B, cross-linked) and one non-qualifying topic (C)."""
    meeting_id = f"follow-up-meeting-{uuid.uuid4().hex[:8]}"
    topic_ids: list[str] = []
    try:
        # setup is inside the try so topics created before a later setup step fails still get cleaned up
        topic_a = data.create_topic(f"follow-up-topic-a-{uuid.uuid4().hex[:8]}")
        topic_ids.append(topic_a.id)
        topic_b = data.create_topic(f"follow-up-topic-b-{uuid.uuid4().hex[:8]}")
        topic_ids.append(topic_b.id)
        topic_c = data.create_topic(f"follow-up-topic-c-{uuid.uuid4().hex[:8]}")
        topic_ids.append(topic_c.id)

        q1 = f"{meeting_id}:Q-1"
        d1 = f"{meeting_id}:D-1"
        a_overdue = f"{meeting_id}:A-OVERDUE"
        a_resolved = f"{meeting_id}:A-RESOLVED"
        a_dependent = f"{meeting_id}:A-DEPENDENT"
        q_resolved = f"{meeting_id}:Q-RESOLVED"

        with db.get_session() as session:
            session.add(MeetingRow(id=meeting_id, title="Follow-up test meeting", date="2026-09-01", source_url="https://example.com"))
            session.add(_item_row(q1, meeting_id, topic_a.id, "QUESTION", "Open"))
            session.add(_item_row(d1, meeting_id, topic_a.id, "DECISION", "Open"))
            session.add(_item_row(a_overdue, meeting_id, topic_a.id, "ACTION", "Open", due_date="2020-01-01"))
            session.add(_item_row(a_resolved, meeting_id, topic_a.id, "ACTION", "Resolved"))
            # references D-1 (topic A) from topic B, and is itself unresolved (no due date)
            session.add(_item_row(a_dependent, meeting_id, topic_b.id, "ACTION", "Open", related_ids=["D-1"]))
            session.add(_item_row(q_resolved, meeting_id, topic_c.id, "QUESTION", "Answered"))
            session.commit()

        yield {
            "meeting_id": meeting_id,
            "topic_a": topic_a.id,
            "topic_b": topic_b.id,
            "topic_c": topic_c.id,
            "q1": q1,
            "d1": d1,
            "a_overdue": a_overdue,
            "a_resolved": a_resolved,
            "a_dependent": a_dependent,
            "q_resolved": q_resolved,
        }
    finally:
        # one transaction, errors not swallowed: items are deleted first (they reference both the meeting and
        # the topics), topic priority history cascades with the topic
        with db.get_session() as session:
            session.execute(delete(KnowledgeItemRow).where(KnowledgeItemRow.meeting_id == meeting_id))
            session.execute(delete(MeetingRow).where(MeetingRow.id == meeting_id))
            session.execute(delete(TopicRow).where(TopicRow.id.in_(topic_ids)))
            session.commit()


def _topics_by_id(response, topic_id: str):
    return next((t for t in response.topics if t.topic.id == topic_id), None)


def test_excludes_topic_with_only_resolved_items(follow_up_scenario):
    response = data.get_follow_up(limit=1000)
    assert _topics_by_id(response, follow_up_scenario["topic_c"]) is None


def test_includes_unresolved_question_and_overdue_action(follow_up_scenario):
    response = data.get_follow_up(limit=1000)
    topic_a = _topics_by_id(response, follow_up_scenario["topic_a"])
    assert topic_a is not None
    follow_up_ids = {item.id for item in topic_a.follow_up_items}
    assert follow_up_scenario["q1"] in follow_up_ids
    assert follow_up_scenario["a_overdue"] in follow_up_ids
    assert follow_up_scenario["a_resolved"] not in follow_up_ids


def test_decision_included_only_with_unresolved_dependent(follow_up_scenario):
    response = data.get_follow_up(limit=1000)
    topic_a = _topics_by_id(response, follow_up_scenario["topic_a"])
    assert topic_a is not None
    follow_up_ids = {item.id for item in topic_a.follow_up_items}
    # D-1 qualifies because A-DEPENDENT (in topic B) references it and is itself unresolved
    assert follow_up_scenario["d1"] in follow_up_ids


def test_follow_up_items_ordered_questions_then_actions_then_decisions(follow_up_scenario):
    response = data.get_follow_up(limit=1000)
    topic_a = _topics_by_id(response, follow_up_scenario["topic_a"])
    assert topic_a is not None
    ordered_ids = [item.id for item in topic_a.follow_up_items]
    assert ordered_ids.index(follow_up_scenario["q1"]) < ordered_ids.index(follow_up_scenario["a_overdue"])
    assert ordered_ids.index(follow_up_scenario["a_overdue"]) < ordered_ids.index(follow_up_scenario["d1"])


def test_cross_topic_related_item_surfaced(follow_up_scenario):
    response = data.get_follow_up(limit=1000)
    topic_a = _topics_by_id(response, follow_up_scenario["topic_a"])
    assert topic_a is not None
    related_ids = {r.item.id for r in topic_a.related_from_other_topics}
    assert follow_up_scenario["a_dependent"] in related_ids
    related = next(r for r in topic_a.related_from_other_topics if r.item.id == follow_up_scenario["a_dependent"])
    assert related.topic_id == follow_up_scenario["topic_b"]


def test_limit_truncates_ranked_topics(follow_up_scenario):
    response = data.get_follow_up(limit=1)
    assert len(response.topics) == 1
