"""Unit tests for domain services: similarity, topic ranking and priority facts/scoring. Pure, no database."""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from app.domain.services import similarity
from app.domain.services.topic_priority import (
    PRIORITY_CONFIG,
    TopicPriorityFacts,
    TopicPriorityScorer,
    build_semantic_context,
    dependency_reach,
    item_fact,
    meeting_ages_days,
)
from app.domain.services.topic_ranking import (
    RankedTopic,
    TopicProfile,
    TopicRanker,
    confident_topic_id,
)
from app.domain.value_objects.priority import (
    SemanticContribution,
    TopicPriorityInfo,
    TopicPrioritySignal,
)
from app.infrastructure.external_services.tfidf_description_index import (
    build_tfidf_description_index,
)

REF = date(2026, 6, 15)


def test_cosine_similarity():
    assert similarity.cosine_similarity(np.array([1.0, 0.0]), np.array([2.0, 0.0])) == pytest.approx(1.0)
    assert similarity.cosine_similarity(np.array([1.0, 0.0]), np.array([0.0, 3.0])) == pytest.approx(0.0)


def test_centroids_skip_missing_vectors_and_empty_topics():
    centroids = similarity.topic_centroids({"a": [[1.0, 0.0], None, [0.0, 1.0]], "b": [None], "c": []})
    assert set(centroids) == {"a"}
    assert centroids["a"].tolist() == [0.5, 0.5]
    assert similarity.centroid([]) is None


def test_closest_topic_requires_the_minimum_similarity():
    centroids = {"x": np.array([1.0, 0.0]), "y": np.array([0.0, 1.0])}
    assert similarity.closest_topic(np.array([0.9, 0.1]), centroids, 0.6)[0] == "x"
    topic_id, best = similarity.closest_topic(np.array([1.0, 1.0]), centroids, 0.9)
    assert topic_id is None and best == pytest.approx(0.7071, abs=1e-3)
    assert similarity.closest_topic(np.array([1.0, 0.0]), {}, 0.1) == (None, -1.0)


def _profiles() -> list[TopicProfile]:
    return [
        TopicProfile("billing", "Billing exports", (), [[1.0, 0.0, 0.0], [0.9, 0.1, 0.0]], ["parquet export job", "invoice csv"]),
        TopicProfile("hiring", "Hiring plan", (), [[0.0, 1.0, 0.0]], ["open backend role"]),
        TopicProfile("empty", "No items yet", (), [], []),
    ]


def test_ranker_works_without_a_description_index_and_skips_topics_without_embeddings():
    ranker = TopicRanker(_profiles())
    ranked = ranker.rank([1.0, 0.05, 0.0], "export billing data")
    assert [r.topic_id for r in ranked] == ["billing", "hiring"]
    assert ranked[0].score > ranked[1].score and 0.99 < ranked[0].centroid_similarity <= 1.0
    assert TopicRanker([]).rank([1.0, 0.0, 0.0], "x") == []
    assert ranker.rank_many([], []) == []


def test_description_index_only_joins_the_score_when_embeddings_are_unsure():
    plain = TopicRanker(_profiles())
    lexical = TopicRanker(_profiles(), build_tfidf_description_index)
    sure = [1.0, 0.0, 0.0]
    assert lexical.rank(sure, "open backend role")[0].score == pytest.approx(plain.rank(sure, "open backend role")[0].score)
    unsure = [0.3, 0.3, 0.9]  # no centroid reaches the gate, so the text decides
    assert lexical.rank(unsure, "open backend role")[0].topic_id == "hiring"
    assert lexical.rank(unsure, "open backend role")[0].score != pytest.approx(plain.rank(unsure, "open backend role")[0].score)


def test_tfidf_index_is_absent_without_a_vocabulary():
    assert build_tfidf_description_index([[], []]) is None
    assert build_tfidf_description_index([["the and of"], ["   "]]) is None
    index = build_tfidf_description_index([["parquet export"], []])
    assert index is not None and index.similarities(["parquet"]).shape == (1, 2)


def test_confident_topic_id_ignores_low_confidence_matches():
    assert confident_topic_id([RankedTopic("t", 0.55, 0.5)]) == "t"
    assert confident_topic_id([RankedTopic("t", 0.2, 0.2)]) is None
    assert confident_topic_id([]) is None


def _fact(item_id="i1", **overrides):
    values = dict(
        item_id=item_id, item_type="ACTION", status_text="Open", confidence="HIGH", due_date=None,
        due_date_source_text=None, stakeholders=["Ana"], description="Ship", rationale=None, resolution=None,
        evidence_quote="we ship",
    )
    values.update(overrides)
    return item_fact(**values)


def test_item_fact_marks_unparseable_due_dates_with_source_text_as_ambiguous():
    assert _fact(due_date="2026-06-20").due_date == date(2026, 6, 20)
    ambiguous = _fact(due_date="next sprint", due_date_source_text="next sprint")
    assert ambiguous.due_date is None and ambiguous.has_ambiguous_due_date
    assert not _fact(due_date=None, due_date_source_text=None).has_ambiguous_due_date
    fact = _fact(status_text=None, stakeholders=None, rationale="because", resolution="done")
    assert (fact.status_text, fact.stakeholder_count, fact.heuristic_text) == ("", 0, "Ship because done we ship")


def test_meeting_ages_ignore_meetings_without_a_real_date():
    assert meeting_ages_days(["2026-06-10", "unknown", None, "2026-05-16"], REF) == [5, 30]


def test_dependency_reach_counts_other_topics_linked_in_either_direction():
    topic_by_item = {"a1": "A", "a2": "A", "b1": "B", "c1": "C", "d1": "D", "u1": None}
    related = {"a1": ["b1", "a2", "missing"], "c1": ["a2"], "d1": ["b1"], "u1": ["a1"]}
    assert dependency_reach("A", ["a1", "a2"], topic_by_item, related) == 2  # B (outgoing) and C (incoming)
    assert dependency_reach("D", ["d1"], topic_by_item, related) == 1
    assert dependency_reach("B", ["b1"], topic_by_item, {}) == 0


def test_scorer_returns_domain_records_and_accepts_an_injected_clock():
    facts = TopicPriorityFacts(
        topic_id="t",
        items=[_fact("i1", due_date="2026-06-16"), _fact("i2", item_type="DECISION")],
        distinct_meeting_ages_days=[3, 20],
        decision_count=1,
        stakeholder_total=2,
        external_dependency_reach=1,
        reference_date=REF,
    )
    info = TopicPriorityScorer().score(facts, calculated_at="2026-06-15T00:00:00+00:00")
    assert isinstance(info, TopicPriorityInfo) and isinstance(info.signals[0], TopicPrioritySignal)
    assert info.calculated_at == "2026-06-15T00:00:00+00:00"
    assert info.effective_priority == info.calculated_priority and info.manual_override is None
    assert all(isinstance(signal.weighted_score, float) for signal in info.signals)
    assert info.explanation.startswith(f"{info.calculated_priority} ({info.calculated_score}/100): ")


def test_scorer_bounds_the_semantic_adjustment():
    facts = TopicPriorityFacts(topic_id="t", items=[_fact()], reference_date=REF)
    scorer = TopicPriorityScorer()
    plain = scorer.score(facts)
    semantic = SemanticContribution(
        provider="test", model="m", scores={"critical": 0.98, "major": 0.01, "minor": 0.01}, contribution=0.0, disagreement=False
    )
    adjusted = scorer.score(facts, semantic=semantic)
    assert adjusted.semantic_contribution.contribution == PRIORITY_CONFIG["semantic_max_adjustment"]
    assert adjusted.calculated_score == pytest.approx(plain.calculated_score + PRIORITY_CONFIG["semantic_max_adjustment"])
    assert adjusted.semantic_contribution.disagreement is True


def test_semantic_context_is_grounded_in_the_facts_only():
    facts = TopicPriorityFacts(topic_id="t", items=[_fact(due_date="2026-06-20"), _fact("i2", status_text="")], reference_date=REF)
    assert build_semantic_context("Launch", facts) == (
        "Topic: Launch\n- [ACTION] status=Open due=2026-06-20\n- [ACTION] status=unknown due=none"
    )
