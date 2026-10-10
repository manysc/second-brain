"""Tests for the hybrid topic ranker (backend/app/topic_suggestions.py). Pure - no database."""
from __future__ import annotations

import pytest

from app.domain.services.topic_ranking import (
    DESCRIPTION_MATCH_GATE,
    HIGH_CONFIDENCE_SCORE,
    MEDIUM_CONFIDENCE_SCORE,
    TopicProfile,
    confidence_band,
)
from app.domain.services.topic_ranking import TopicRanker as DomainTopicRanker
from app.infrastructure.external_services.tfidf_description_index import build_tfidf_description_index


def TopicRanker(profiles):  # noqa: N802  (reads like the class it wraps)
    """The ranker as production wires it: with the TF-IDF description index for the lexical signal."""
    return DomainTopicRanker(profiles, build_tfidf_description_index)


Q = [1.0, 0.0, 0.0, 0.0]


def _profile(topic_id: str, embeddings: list[list[float]], name: str | None = None, descriptions=None, tags=()):
    return TopicProfile(
        topic_id=topic_id,
        name=name or topic_id,
        tags=tags,
        item_embeddings=embeddings,
        item_descriptions=descriptions if descriptions is not None else ["placeholder"] * len(embeddings),
    )


def test_nearest_neighbour_vote_beats_a_centroid_dragged_off_by_unrelated_items():
    # A has three near-duplicates of the query, but five unrelated items drag its centroid away;
    # B's single item has the closer centroid
    near = [[1.0, 0.1, 0.0, 0.0], [1.0, 0.0, 0.1, 0.0], [1.0, 0.1, 0.1, 0.0]]
    far = [[0.0, 1.0, 0.0, 0.0]] * 5
    ranker = TopicRanker([_profile("a", near + far), _profile("b", [[0.7, 0.7, 0.0, 0.0]])])

    ranked = ranker.rank(Q, "unrelated text")

    assert [r.topic_id for r in ranked] == ["a", "b"]
    assert ranked[0].centroid_similarity < ranked[1].centroid_similarity


def test_topic_name_token_in_the_text_breaks_an_embedding_tie():
    ranker = TopicRanker([_profile("bulga", [Q], name="Bulga Deployment"), _profile("kpas", [Q], name="KPAS")])

    assert ranker.rank(Q, "Add Aha links on the KPAS status page")[0].topic_id == "kpas"
    assert ranker.rank(Q, "Finalize the Bulga on-site testing plan")[0].topic_id == "bulga"


def test_topic_tags_count_as_name_tokens():
    ranker = TopicRanker([_profile("a", [Q], name="Alpha"), _profile("b", [Q], name="Beta", tags=["helm"])])

    assert ranker.rank(Q, "Create the helm chart artifact")[0].topic_id == "b"


def test_name_tokens_shared_by_many_topics_are_ignored():
    names = ["Alpha Strategy", "Beta Strategy", "Gamma Strategy", "Delta"]
    ranker = TopicRanker([_profile(n, [Q], name=n) for n in names])

    ranked = ranker.rank(Q, "strategy for next quarter", top_n=4)

    # "strategy" names three topics, so it identifies none: Delta scores the same as the others
    assert len({round(r.score, 9) for r in ranked}) == 1


def test_item_descriptions_only_count_when_no_centroid_is_close():
    helm = _profile("helm", [Q], name="Alpha", descriptions=["Helm chart artifact for the deployment"])
    visa = _profile("visa", [Q], name="Beta", descriptions=["Visa status and travel backup"])
    ranker = TopicRanker([helm, visa])
    text = "Create the helm chart artifact"

    close = ranker.rank(Q, text)
    assert close[0].centroid_similarity >= DESCRIPTION_MATCH_GATE
    assert close[0].score == pytest.approx(close[1].score)

    distant_vector = [0.5, 0.866, 0.0, 0.0]  # cosine 0.5 to both topics
    distant = ranker.rank(distant_vector, text)
    assert distant[0].centroid_similarity < DESCRIPTION_MATCH_GATE
    assert distant[0].topic_id == "helm"
    assert distant[0].score > distant[1].score


def test_candidates_are_best_first_and_capped():
    profiles = [_profile(f"t{i}", [[1.0, i * 0.5, 0.0, 0.0]]) for i in range(5)]
    ranker = TopicRanker(profiles)

    ranked = ranker.rank(Q, "text")
    assert [r.topic_id for r in ranked] == ["t0", "t1", "t2"]
    assert ranked[0].score > ranked[1].score > ranked[2].score
    assert len(ranker.rank(Q, "text", top_n=1)) == 1


def test_rank_many_matches_rank():
    ranker = TopicRanker([_profile("a", [Q]), _profile("b", [[0.0, 1.0, 0.0, 0.0]])])
    vectors = [Q, [0.0, 1.0, 0.0, 0.0]]

    assert ranker.rank_many(vectors, ["x", "y"]) == [ranker.rank(vectors[0], "x"), ranker.rank(vectors[1], "y")]


def test_topics_without_embedded_items_are_skipped_and_empty_input_is_safe():
    assert TopicRanker([]).rank(Q, "text") == []
    assert TopicRanker([_profile("empty", [])]).rank(Q, "text") == []

    ranker = TopicRanker([_profile("empty", []), _profile("single", [Q])])
    assert [r.topic_id for r in ranker.rank(Q, "text")] == ["single"]
    assert ranker.rank_many([], []) == []


def test_stop_word_only_descriptions_do_not_break_the_ranker():
    ranker = TopicRanker([_profile("a", [Q], descriptions=["the and", ""])])

    assert ranker.rank([0.5, 0.866, 0.0, 0.0], "the")[0].topic_id == "a"


@pytest.mark.parametrize(
    ("score", "band"),
    [
        (HIGH_CONFIDENCE_SCORE, "HIGH"),
        (0.95, "HIGH"),
        (HIGH_CONFIDENCE_SCORE - 1e-6, "MEDIUM"),
        (MEDIUM_CONFIDENCE_SCORE, "MEDIUM"),
        (MEDIUM_CONFIDENCE_SCORE - 1e-6, "LOW"),
        (0.0, "LOW"),
    ],
)
def test_confidence_band_boundaries(score, band):
    assert confidence_band(score) == band
