"""Unit tests for domain services that work on entities: follow-ups, the item graph, topic matching and ranking."""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from app.domain.entities.note import Note
from app.domain.services import similarity
from app.domain.services.follow_up import (
    FollowUpScope,
    is_stale,
    last_activity,
    select_follow_ups,
)
from app.domain.services.item_graph import build_item_edges, related_items
from app.domain.services.search_ranking import rank_search_hits
from app.domain.services.topic_matching import TopicMatcher, TopicSnapshot
from app.domain.value_objects.priority import (
    ManualPriorityOverride,
    TopicPriorityHistoryEntry,
)
from tests.domain import factories as make

REF = date(2026, 6, 15)


def _select(topics, items, escalations=(), limit=5, due_soon_days=7, **options):
    by_topic: dict[str, list] = {}
    for current in items:
        by_topic.setdefault(current.topic_id, []).append(current)
    return select_follow_ups(
        topics, by_topic, list(escalations), reference_date=REF, limit=limit, due_soon_days=due_soon_days, **options
    )


def _follow_ups(topics, items, escalations=(), limit=5, due_soon_days=7):
    return list(_select(topics, items, escalations, limit, due_soon_days).topics)


def _ids(selection):
    return [current.id for followed in selection.topics for current in followed.follow_up_items]


# -- follow-up -------------------------------------------------------------------------------------------


def test_follow_up_selects_open_questions_due_actions_and_decisions_with_open_dependents():
    items = [
        make.item("m:Q-1", type="QUESTION"),
        make.item("m:Q-2", type="QUESTION", status="Answered"),
        make.item("m:A-1", type="ACTION", due_date="2026-06-20"),  # within 7 days
        make.item("m:A-2", type="ACTION", due_date="2026-08-01"),  # far away
        make.item("m:A-3", type="ACTION", due_date=None),  # undated is a signal
        make.item("m:A-4", type="ACTION", due_date="soon"),  # unparseable is treated like undated
        make.item("m:A-5", type="ACTION", due_date="2026-06-01", status="Done"),
        make.item("m:D-1", type="DECISION"),
        make.item("m:D-2", type="DECISION"),
        make.item("m:I-1", type="IDEA", related_ids=("D-1",)),  # an open item depends on D-1
    ]
    [selected] = _follow_ups([make.topic()], items)
    assert [current.id for current in selected.follow_up_items] == ["m:Q-1", "m:A-3", "m:A-4", "m:A-1", "m:D-1"]
    assert not selected.escalated_recently and selected.escalation_drivers == ()


def test_follow_up_ranks_topics_by_effective_priority_then_score_and_respects_the_limit():
    critical = make.topic("t1", "Critical", calculation=make.calculation("CRITICAL", 80))
    major_high = make.topic("t2", "Major high", calculation=make.calculation("MAJOR", 60))
    major_low = make.topic("t3", "Major low", calculation=make.calculation("MAJOR", 50))
    overridden = make.topic("t4", "Overridden", calculation=make.calculation("MINOR", 99))
    overridden.override_priority("CRITICAL", None, "now")
    unscored = make.topic("t5", "Unscored")
    quiet = make.topic("t6", "Nothing to raise", calculation=make.calculation("CRITICAL", 100))
    topics = [unscored, major_low, critical, quiet, major_high, overridden]
    items = [make.item(f"m:Q-{t.id}", type="QUESTION", topic_id=t.id) for t in topics if t is not quiet]
    assert [f.topic.id for f in _follow_ups(topics, items)] == ["t4", "t1", "t2", "t3", "t5"]
    assert [f.topic.id for f in _follow_ups(topics, items, limit=2)] == ["t4", "t1"]


def test_follow_up_pulls_related_items_from_other_topics_and_reports_escalations():
    here, there = make.topic("t1", "Here"), make.topic("t2", "There")
    items = [
        make.item("m:Q-1", type="QUESTION", topic_id="t1", related_ids=("Q-9",)),
        make.item("m:Q-9", type="QUESTION", topic_id="t2"),
        make.item("m:Q-8", type="QUESTION", topic_id="t2", related_ids=("m:Q-1",)),
        make.item("m:I-7", type="IDEA", topic_id="t2", related_ids=("Q-1",)),  # not itself a follow-up
    ]
    escalation = TopicPriorityHistoryEntry(
        id="h", topic_id="t1", previous_priority="MINOR", new_priority="MAJOR", new_score=50, changed_at="now",
        algorithm_version="1.0", trigger="manual", primary_drivers=["two decisions"],
    )
    selected = {f.topic.id: f for f in _follow_ups([here, there], items, [escalation])}
    related = selected["t1"].related_from_other_topics
    assert [(r.item.id, r.topic_id, r.topic_name, r.reason) for r in related] == [
        ("m:Q-9", "t2", "There", "Related to m:Q-1 in this topic"),
        ("m:Q-8", "t2", "There", "References m:Q-1 in this topic"),
    ]
    assert selected["t1"].escalated_recently and selected["t1"].escalation_drivers == ("two decisions",)
    assert not selected["t2"].escalated_recently


# meeting id -> date: "old" is 45 days before REF, "new" 5. The manual meeting's date must never count.
DATES = {"old": date(2026, 5, 1), "new": date(2026, 6, 10), "manual": date(2026, 1, 1)}


def test_follow_up_leaves_out_items_with_no_activity_inside_the_age_window():
    items = [
        make.item("new:Q-1", type="QUESTION"),
        make.item("old:Q-1", type="QUESTION"),  # nothing since the old meeting
        make.item("old:Q-2", type="QUESTION", notes=(Note(id="n", body="still open", created_at="2026-06-12T09:00:00+00:00"),)),
        make.item("old:Q-3", type="QUESTION", manual_override=ManualPriorityOverride("MAJOR", None, "2026-06-01T00:00:00+00:00")),
        make.item("old:A-1", type="ACTION", due_date="2026-06-18"),  # old meeting, but due this week
        make.item("old:A-2", type="ACTION", due_date="2026-05-10"),  # overdue for longer than the window
        make.item("old:A-3", type="ACTION"),  # undated, so only the old meeting dates it
        make.item("manual:A-1", type="ACTION"),  # added by hand: no date of its own
        make.item("gone:Q-1", type="QUESTION"),  # its meeting has no known date
    ]
    selection = _select([make.topic()], items, meeting_dates=DATES, max_age_days=30)
    assert _ids(selection) == ["gone:Q-1", "new:Q-1", "old:Q-2", "old:Q-3", "manual:A-1", "old:A-1"]
    assert selection.hidden_stale_count == 3

    without_cut_off = _select([make.topic()], items, meeting_dates=DATES)
    assert len(_ids(without_cut_off)) == len(items) and without_cut_off.hidden_stale_count == 0


def test_an_item_is_stale_only_past_the_window_and_never_without_a_date():
    question = make.item("m:Q-1", type="QUESTION")
    assert last_activity(question, date(2026, 5, 16)) == date(2026, 5, 16)
    assert not is_stale(question, date(2026, 5, 16), REF, 30)  # exactly 30 days old
    assert is_stale(question, date(2026, 5, 15), REF, 30)
    assert last_activity(question, None) is None and not is_stale(question, None, REF, 30)
    # a due date dates an action, not a question
    assert last_activity(make.item("m:Q-2", type="QUESTION", due_date="2026-06-14"), date(2026, 5, 1)) == date(2026, 5, 1)
    assert last_activity(make.item("m:A-1", type="ACTION", due_date="2026-06-14"), date(2026, 5, 1)) == date(2026, 6, 14)


def test_follow_up_drops_a_decision_whose_only_open_dependent_is_stale():
    items = [
        make.item("old:D-1", type="DECISION"),
        make.item("old:D-2", type="DECISION"),
        make.item("old:I-1", type="IDEA", related_ids=("old:D-1",)),  # stale, so D-1 has nothing live behind it
        make.item("new:I-2", type="IDEA", related_ids=("old:D-2",)),  # live, so the old D-2 stays
    ]
    selection = _select([make.topic()], items, meeting_dates=DATES, max_age_days=30)
    assert _ids(selection) == ["old:D-2"] and selection.hidden_stale_count == 1


def test_follow_up_scope_narrows_by_person_meeting_and_topic():
    here, there = make.topic("t1", "Here"), make.topic("t2", "There")
    items = [
        make.item("m1:Q-1", type="QUESTION", topic_id="t1", owner="Ana", stakeholders=("Ana",)),
        make.item("m1:Q-2", type="QUESTION", topic_id="t1", owner="Ben", stakeholders=("Ben", "Cy")),
        make.item("m2:Q-3", type="QUESTION", topic_id="t2", owner=None, stakeholders=("Ana",)),
        make.item("m2:Q-4", type="QUESTION", topic_id="t2", owner="Dee", stakeholders=()),
    ]

    def picked(**scope):
        return _ids(_select([here, there], items, scope=FollowUpScope.of(**scope)))

    assert picked(stakeholders=[" ANA "]) == ["m1:Q-1", "m2:Q-3"]  # owner or stakeholder, any case
    assert picked(stakeholders=["ana", "dee"]) == ["m1:Q-1", "m2:Q-3", "m2:Q-4"]  # any of the names
    assert picked(stakeholders=["An"]) == []  # whole names only
    assert picked(meeting_ids=["m2"]) == ["m2:Q-3", "m2:Q-4"]
    assert picked(topic_ids=["t1"]) == ["m1:Q-1", "m1:Q-2"]
    assert picked(stakeholders=["Ana"], meeting_ids=["m1", "m2"], topic_ids=["t2"]) == ["m2:Q-3"]  # all filters together
    assert picked(topic_ids=["no-such-topic"]) == [] and picked(meeting_ids=["no-such-meeting"]) == []
    assert len(picked(stakeholders=["  "], meeting_ids=[""])) == 4  # blank values do not restrict


def test_follow_up_scope_matches_a_name_inside_its_variants():
    items = [
        make.item("m1:Q-1", type="QUESTION", owner="Akshay", stakeholders=("Akshay",)),
        make.item("m1:Q-2", type="QUESTION", owner=None, stakeholders=("Akshay / QA (reported)",)),
        make.item("m1:Q-3", type="QUESTION", owner="Akshay and Nando", stakeholders=()),
        make.item("m1:Q-4", type="QUESTION", owner="Akshay Chowdu", stakeholders=("Akshay Chowdu",)),
        make.item("m1:Q-5", type="QUESTION", owner="Anand", stakeholders=("Akshaya",)),
    ]

    def picked(*names):
        return _ids(_select([make.topic()], items, scope=FollowUpScope.of(stakeholders=names)))

    assert picked("akshay") == ["m1:Q-1", "m1:Q-2", "m1:Q-3", "m1:Q-4"]  # whole words, not "Akshaya"
    assert picked("Akshay Chowdu") == ["m1:Q-4"]  # every word, in order
    assert picked("Nando") == ["m1:Q-3"] and picked("qa") == ["m1:Q-2"]
    assert picked("Ana") == [] and picked("Chowdu Akshay") == []
    assert picked("Akshay / QA (reported)") == ["m1:Q-2"]  # a full raw value still matches itself


def test_follow_up_topic_scope_still_lists_related_items_from_other_topics():
    here, there = make.topic("t1", "Here"), make.topic("t2", "There")
    items = [
        make.item("m1:Q-1", type="QUESTION", topic_id="t1", related_ids=("Q-9", "Q-8")),
        make.item("m1:Q-9", type="QUESTION", topic_id="t2"),
        make.item("m2:Q-8", type="QUESTION", topic_id="t2"),
    ]
    one_topic = _select([here, there], items, scope=FollowUpScope.of(topic_ids=["t1"]))
    assert [followed.topic.id for followed in one_topic.topics] == ["t1"] and one_topic.total_topics == 1
    assert [related.item.id for related in one_topic.topics[0].related_from_other_topics] == ["m1:Q-9", "m2:Q-8"]
    # the other filters still apply to them
    one_meeting = _select([here, there], items, scope=FollowUpScope.of(topic_ids=["t1"], meeting_ids=["m1"]))
    assert [related.item.id for related in one_meeting.topics[0].related_from_other_topics] == ["m1:Q-9"]


def test_follow_up_counts_hidden_items_and_topics_inside_the_scope():
    topics = [make.topic("t1", "One"), make.topic("t2", "Two"), make.topic("t3", "Three")]
    items = [
        make.item("new:Q-1", type="QUESTION", topic_id="t1"),
        make.item("old:Q-2", type="QUESTION", topic_id="t1"),
        make.item("new:Q-3", type="QUESTION", topic_id="t2", owner="Dee", stakeholders=("Dee",)),
        make.item("old:Q-4", type="QUESTION", topic_id="t2", owner="Dee", stakeholders=("Dee",)),
        make.item("old:Q-5", type="QUESTION", topic_id="t3"),
    ]

    def counts(limit=5, **scope):
        selection = _select(topics, items, limit=limit, meeting_dates=DATES, max_age_days=30, scope=FollowUpScope.of(**scope))
        return len(selection.topics), selection.total_topics, selection.hidden_stale_count

    assert counts(limit=1) == (1, 2, 3)  # t3 has only a stale item; the limit does not change the totals
    assert counts(topic_ids=["t1"]) == (1, 1, 1)
    assert counts(stakeholders=["Dee"]) == (1, 1, 1)
    assert counts(meeting_ids=["old"]) == (0, 0, 3)


# -- item graph ------------------------------------------------------------------------------------------


def test_graph_prefers_related_over_topic_over_semantic_edges_one_per_pair():
    topics = {"t1": make.topic("t1", "Launch"), "unc": make.topic("unc", "Uncategorized")}
    items = [
        make.item("m:A-1", topic_id="t1", related_ids=("A-2", "missing"), embedding=[1.0, 0.0]),
        make.item("m:A-2", topic_id="t1", embedding=[1.0, 0.01]),
        make.item("m:A-3", topic_id="t1", embedding=[0.0, 1.0]),
        make.item("m:A-4", topic_id="unc", embedding=[1.0, 0.02]),
        make.item("m:A-5", topic_id="unc", embedding=None),
        make.item("m:A-6", topic_id=None, embedding=[0.0, 1.0]),
    ]
    edges = build_item_edges(items, topics, 0.9)
    assert [(e.source, e.target, e.kind) for e in edges] == [
        ("m:A-1", "m:A-2", "related"),
        ("m:A-1", "m:A-3", "topic"),
        ("m:A-2", "m:A-3", "topic"),
        ("m:A-1", "m:A-4", "semantic"),
        ("m:A-2", "m:A-4", "semantic"),
        ("m:A-3", "m:A-6", "semantic"),
    ]
    assert edges[0].weight == 1.0 and 0.99 < edges[3].weight <= 1.0


def test_related_items_match_by_local_key_or_full_id():
    source = make.item("m:A-1", related_ids=("A-2", "other:Z-9"))
    others = [make.item("m:A-2"), make.item("other:Z-9"), make.item("m:A-3")]
    assert [current.id for current in related_items(source, [source, *others])] == ["m:A-2", "other:Z-9"]


def test_search_hits_rank_by_confidence_then_distance():
    hits = [
        (make.item("m:1", confidence="LOW"), 0.1),
        (make.item("m:2", confidence="HIGH"), 0.5),
        (make.item("m:3", confidence="HIGH"), 0.2),
        (make.item("m:4", confidence="MEDIUM"), 0.05),
    ]
    assert [current.id for current in rank_search_hits(hits)] == ["m:3", "m:2", "m:4", "m:1"]


def test_most_similar_and_similar_pairs():
    centroids = {"a": np.array([1.0, 0.0]), "b": np.array([0.9, 0.1]), "c": np.array([0.0, 1.0]), "d": None}
    ranked = similarity.most_similar(centroids["a"], {k: v for k, v in centroids.items() if k != "a"}, 0.5, 5)
    assert [topic_id for topic_id, _ in ranked] == ["b"]
    assert similarity.most_similar(None, centroids, 0.0, 5) == []
    pairs = similarity.similar_pairs({k: v for k, v in centroids.items() if v is not None}, 0.5, 10)
    assert [(a, b) for a, b, _ in pairs] == [("a", "b")] and pairs[0][2] == pytest.approx(0.9939, abs=1e-3)


# -- topic matching (ingestion) --------------------------------------------------------------------------


def _matcher(topics, stored_topics=None, created=None):
    stored_topics = stored_topics or {}

    def related_topic_ids(item_ids):
        return [stored_topics[item_id] for item_id in item_ids if item_id in stored_topics]

    def ensure_uncategorized():
        (created if created is not None else []).append("created")
        return "unc-new"

    return TopicMatcher(topics, related_topic_ids=related_topic_ids, ensure_uncategorized=ensure_uncategorized)


BILLING = TopicSnapshot("billing", "Billing", [[1.0, 0.0, 0.0], [0.9, 0.1, 0.0], None])
HIRING = TopicSnapshot("hiring", "Hiring", [[0.0, 1.0, 0.0]])
UNCATEGORIZED = TopicSnapshot("unc", "Uncategorized", [[0.0, 0.0, 1.0]])
NEAR_BILLING, NEAR_HIRING, UNLIKE_ANYTHING = [1.0, 0.05, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]


def test_matching_prefers_name_then_related_items_then_the_closest_centroid():
    matcher = _matcher([BILLING, HIRING, UNCATEGORIZED], stored_topics={"m1:B-7": "hiring", "m1:B-8": "unc"})
    assert matcher.resolve(make.extracted(theme=" billing "), NEAR_HIRING) == ("billing", None)  # name beats vector
    assert matcher.resolve(make.extracted(theme="Offers", related_ids=("B-7", "B-8")), NEAR_BILLING) == ("hiring", None)
    assert matcher.resolve(make.extracted(theme="Invoices"), NEAR_BILLING) == ("billing", None)
    # Uncategorized's own items are never a matching signal, so a vector identical to them still matches nothing
    assert matcher.resolve(make.extracted(theme="Offsite"), UNLIKE_ANYTHING) == ("unc", "Offsite")
    assert matcher.name_of("billing") == "Billing"


def test_items_without_a_theme_go_to_uncategorized_without_a_proposal_creating_it_once():
    created: list[str] = []
    matcher = _matcher([BILLING], created=created)
    assert matcher.resolve(make.extracted(theme=None), NEAR_BILLING) == ("unc-new", None)
    assert matcher.resolve(make.extracted(theme="uncategorized"), NEAR_BILLING) == ("unc-new", None)
    assert matcher.resolve(make.extracted(theme="Unknown thing"), UNLIKE_ANYTHING) == ("unc-new", "Unknown thing")
    assert created == ["created"] and matcher.name_of("unc-new") == "Uncategorized"


def test_batch_resolution_propagates_topics_across_links_in_any_direction():
    matcher = _matcher([BILLING, HIRING, UNCATEGORIZED])
    entries = [
        (make.extracted("m1:A-1", theme="Mystery", related_ids=("A-2",)), UNLIKE_ANYTHING),  # only reachable via A-2
        (make.extracted("m1:A-2", theme="Mystery", related_ids=("A-3",)), UNLIKE_ANYTHING),  # only reachable via A-3
        (make.extracted("m1:A-3", theme="Hiring"), NEAR_HIRING),
        (make.extracted("m1:A-4", theme="Mystery"), UNLIKE_ANYTHING),  # unrelated: stays a proposal
    ]
    resolved = matcher.resolve_batch(entries)
    assert resolved == {
        "m1:A-1": ("hiring", None),
        "m1:A-2": ("hiring", None),
        "m1:A-3": ("hiring", None),
        "m1:A-4": ("unc", "Mystery"),
    }


def test_filed_items_shift_the_centroid_for_later_items_in_the_run():
    matcher = _matcher([TopicSnapshot("empty", "Empty topic", []), UNCATEGORIZED])
    assert matcher.resolve(make.extracted(theme="Other"), NEAR_HIRING) == ("unc", "Other")
    matcher.record("empty", NEAR_HIRING)
    matcher.record("unc", NEAR_BILLING)  # Uncategorized never becomes a matching signal
    assert matcher.resolve(make.extracted(theme="Other"), NEAR_HIRING) == ("empty", None)
    assert matcher.resolve(make.extracted(theme="Other"), NEAR_BILLING) == ("unc", "Other")
