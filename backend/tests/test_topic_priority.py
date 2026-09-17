"""Tests for automatic Topic priority classification (backend/app/topic_priority.py).

Most tests exercise TopicPriorityScorer.score() directly - it's a pure function (no DB), which
is what makes it calibratable/unit-testable per the design doc. The final test class integrates
against a real Postgres instance (mirrors backend/tests/test_topics.py's db_ready pattern).
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy.exc import OperationalError

from app import data, db, topic_priority
from app.models import SemanticContribution
from app.topic_priority import ItemFact, TopicPriorityFacts, TopicPriorityScorer

REF_DATE = date(2026, 9, 16)


def _item(
    id_: str = "item-1",
    type_: str = "ACTION",
    status_text: str = "Open",
    confidence: str = "MEDIUM",
    due_date: date | None = None,
    ambiguous: bool = False,
    stakeholders: int = 1,
    heuristic_text: str = "Some ordinary discussion happened.",
) -> ItemFact:
    return ItemFact(
        id=id_,
        type=type_,
        status_text=status_text,
        confidence=confidence,
        due_date=due_date,
        has_ambiguous_due_date=ambiguous,
        stakeholder_count=stakeholders,
        heuristic_text=heuristic_text,
    )


def _facts(**kwargs) -> TopicPriorityFacts:
    kwargs.setdefault("topic_id", "topic-1")
    kwargs.setdefault("reference_date", REF_DATE)
    return TopicPriorityFacts(**kwargs)


def test_minor_topic_low_signal():
    facts = _facts(
        items=[_item(stakeholders=1)],
        distinct_meeting_ages_days=[3],
        decision_count=0,
        stakeholder_total=1,
        external_dependency_reach=0,
    )
    result = TopicPriorityScorer().score(facts)
    assert result.calculated_priority == "MINOR"
    assert result.calculated_score < topic_priority.PRIORITY_CONFIG["thresholds"]["major"]


def test_major_topic_material_active_work():
    items = [_item(id_=f"a-{i}", type_="ACTION") for i in range(5)]
    items[0] = _item(id_="a-0", type_="ACTION", due_date=date(2026, 9, 18))  # due in 2 days, not overdue
    facts = _facts(
        items=items,
        distinct_meeting_ages_days=[2, 4, 6, 10, 13],
        decision_count=3,
        stakeholder_total=6,
        external_dependency_reach=2,
    )
    result = TopicPriorityScorer().score(facts)
    assert result.calculated_priority == "MAJOR"
    thresholds = topic_priority.PRIORITY_CONFIG["thresholds"]
    assert thresholds["major"] <= result.calculated_score < thresholds["critical"]


def test_critical_topic_confirmed_blocker_and_imminent_deadline():
    facts = _facts(
        items=[_item(status_text="Blocked", due_date=date(2026, 9, 15))],  # 1 day overdue
        distinct_meeting_ages_days=[1],
        decision_count=0,
        stakeholder_total=1,
        external_dependency_reach=0,
    )
    result = TopicPriorityScorer().score(facts)
    assert result.calculated_priority == "CRITICAL"
    assert result.hard_escalations
    assert result.hard_escalations[0].rule_id == "confirmed-block-imminent-deadline"


def test_ambiguous_due_date_grants_no_urgency():
    facts = _facts(
        items=[_item(due_date=None, ambiguous=True)],
        distinct_meeting_ages_days=[1],
    )
    result = TopicPriorityScorer().score(facts)
    urgency_signal = next(s for s in result.signals if s.type == "urgency_due_date")
    ambiguous_signal = next(s for s in result.signals if s.type == "urgency_ambiguous_due_date_ignored")
    assert urgency_signal.weighted_score == 0
    assert ambiguous_signal.source_knowledge_item_ids == ["item-1"]
    assert result.calculated_priority != "CRITICAL"


def test_old_recurring_topic_does_not_become_critical():
    facts = _facts(
        items=[_item(id_=f"i-{i}") for i in range(6)],
        distinct_meeting_ages_days=[200] * 12,  # many old meetings, nothing recent
        decision_count=1,
        stakeholder_total=2,
    )
    result = TopicPriorityScorer().score(facts)
    momentum_signal = next(s for s in result.signals if s.type == "momentum_recency_weighted_meetings")
    assert momentum_signal.weighted_score < 2  # decayed to near-zero despite 12 meetings
    assert result.calculated_priority == "MINOR"


def test_high_volume_minor_topic_counts_are_capped():
    few = _facts(items=[_item(id_=f"i-{i}") for i in range(6)])
    many = _facts(items=[_item(id_=f"i-{i}") for i in range(60)])
    result_few = TopicPriorityScorer().score(few)
    result_many = TopicPriorityScorer().score(many)
    exec_few = next(s for s in result_few.signals if s.type == "execution_unresolved_volume").weighted_score
    exec_many = next(s for s in result_many.signals if s.type == "execution_unresolved_volume").weighted_score
    # diminishing returns: 60 items must not score meaningfully higher than 6 (never raw-linear)
    assert exec_many - exec_few < 1.5
    assert result_many.calculated_priority != "CRITICAL"


def test_single_severe_blocker_escalates_despite_low_item_count():
    facts = _facts(
        items=[_item(status_text="blocker", due_date=REF_DATE)],  # due today
        distinct_meeting_ages_days=[0],
        decision_count=0,
        stakeholder_total=1,
    )
    result = TopicPriorityScorer().score(facts)
    assert result.calculated_priority == "CRITICAL"
    assert result.hard_escalations


def test_structural_status_weighted_more_than_keyword_heuristic():
    structural = _facts(items=[_item(status_text="Blocked", heuristic_text="Nothing unusual.")])
    heuristic = _facts(
        items=[_item(status_text="Open", heuristic_text="This is at risk of being blocked, escalating soon.")]
    )
    risk_structural = TopicPriorityScorer().score(structural)
    risk_heuristic = TopicPriorityScorer().score(heuristic)
    structural_score = next(s for s in risk_structural.signals if s.type == "risk_structural_blocked_status").weighted_score
    heuristic_score = next(s for s in risk_heuristic.signals if s.type == "risk_keyword_heuristic").weighted_score
    assert structural_score > heuristic_score


def test_semantic_disagreement_is_bounded_and_recorded():
    facts = _facts(items=[_item()], distinct_meeting_ages_days=[3])
    semantic = SemanticContribution(
        provider="test", model="test-model", scores={"critical": 0.9, "major": 0.07, "minor": 0.03}, contribution=0, disagreement=False
    )
    result = TopicPriorityScorer().score(facts, semantic=semantic)
    max_adjustment = topic_priority.PRIORITY_CONFIG["semantic_max_adjustment"]
    assert result.semantic_contribution is not None
    assert abs(result.semantic_contribution.contribution) <= max_adjustment
    assert result.semantic_contribution.disagreement is True
    # bounded: a MINOR-level deterministic score must not jump straight to CRITICAL
    assert result.calculated_priority != "CRITICAL"


def test_hysteresis_prevents_thrashing_near_the_demote_threshold():
    scorer = TopicPriorityScorer()
    thresholds = topic_priority.PRIORITY_CONFIG["thresholds"]
    hysteresis = topic_priority.PRIORITY_CONFIG["hysteresis"]
    # score dropped from 76 to 72; demote-below is 70, so it must remain CRITICAL
    assert scorer._classify(72, "CRITICAL") == "CRITICAL"
    assert scorer._classify(hysteresis["critical_demote_below"] - 1, "CRITICAL") == (
        "MAJOR" if hysteresis["critical_demote_below"] - 1 >= thresholds["major"] else "MINOR"
    )
    # a brand new MINOR topic should promote immediately once it crosses the threshold - no delay
    assert scorer._classify(thresholds["critical"], "MINOR") == "CRITICAL"


@pytest.fixture(scope="module")
def db_ready():
    """Mirrors test_topics.py's db_ready pattern (auto-skips if Postgres isn't reachable)."""
    try:
        db.init_db()
    except OperationalError:
        pytest.skip("Postgres is not reachable at DATABASE_URL; skipping DB integration tests")
    yield


def test_recalculate_creates_history_and_preserves_override(db_ready):
    from app.db_models import KnowledgeItemRow, MeetingRow, TopicRow

    meeting_id = f"priority-meeting-{uuid.uuid4().hex[:8]}"
    item_id = f"{meeting_id}:A-1"
    topic = data.create_topic(f"priority-topic-{uuid.uuid4().hex[:8]}")

    try:
        with db.get_session() as session:
            session.add(MeetingRow(id=meeting_id, title="Priority test meeting", date="2026-09-01", source_url="https://example.com"))
            session.add(
                KnowledgeItemRow(
                    id=item_id,
                    meeting_id=meeting_id,
                    topic_id=topic.id,
                    type="ACTION",
                    description="Ship the release",
                    theme=topic.name,
                    status="Open",
                    confidence="HIGH",
                    owner="Ada",
                    stakeholders=["Ada"],
                    due_date=None,
                    due_date_source_text=None,
                    rationale=None,
                    resolution=None,
                    evidence_speaker="Ada",
                    evidence_timestamp="00:01:00",
                    evidence_quote="We'll ship it",
                    evidence_context=None,
                    related_ids=[],
                    embedding=None,
                )
            )
            session.commit()

        baseline = data.recalculate_priority_for_topic(topic.id)
        assert baseline is not None and baseline.priority is not None
        assert baseline.priority.calculated_priority != "CRITICAL"

        with db.get_session() as session:
            row = session.get(KnowledgeItemRow, item_id)
            row.status = "Blocked"
            row.due_date = "2020-01-01"  # overdue
            session.commit()

        escalated = data.recalculate_priority_for_topic(topic.id)
        assert escalated is not None and escalated.priority is not None
        assert escalated.priority.calculated_priority == "CRITICAL"
        assert escalated.priority.hard_escalations

        history = data.get_priority_history(topic.id)
        assert len(history) == 1
        assert history[0].new_priority == "CRITICAL"

        overridden = data.set_priority_override(topic.id, "MINOR", "manual review")
        assert overridden is not None and overridden.priority is not None
        assert overridden.priority.effective_priority == "MINOR"
        assert overridden.priority.calculated_priority == "CRITICAL"

        # recalculation must never silently remove a human override
        data.recalculate_priority_for_topic(topic.id)
        still_overridden = data.get_topic_by_id(topic.id)
        assert still_overridden is not None and still_overridden.priority is not None
        assert still_overridden.priority.manual_override is not None
        assert still_overridden.priority.effective_priority == "MINOR"
    finally:
        # deleted directly at the row level (not via data.delete_topic/assign_item_topic) so
        # cleanup can't itself leak data if one step fails - each step is independent and
        # best-effort. Deleting the meeting cascades its items regardless of topic_id, and
        # deleting the topic cascades its priority history (topic_priority_history has
        # ON DELETE CASCADE), so nothing here depends on prior steps having succeeded.
        with db.get_session() as session:
            meeting_row = session.get(MeetingRow, meeting_id)
            if meeting_row is not None:
                session.delete(meeting_row)
            try:
                session.commit()
            except Exception:
                session.rollback()
        with db.get_session() as session:
            topic_row = session.get(TopicRow, topic.id)
            if topic_row is not None:
                session.delete(topic_row)
            try:
                session.commit()
            except Exception:
                session.rollback()
