"""Ingestion must never create topics on its own: an unmatched theme becomes a proposal that a human
accepts (optionally renamed or redirected to an existing topic) or rejects. Mirrors test_topics.py's
db_ready pattern (auto-skips if Postgres isn't reachable).
"""
from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from sqlalchemy import select

from app.domain.exceptions import TopicNotFound
from app.domain.value_objects.evidence import Evidence
from app.domain.value_objects.extraction import ExtractedItem, ExtractedMeeting
from app.infrastructure.persistence import database as db
from app.infrastructure.persistence.orm_models import KnowledgeItemRow, MeetingRow, TopicRow
from tests.support import brain, merge_extract


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _meeting(meeting_id: str, theme: str, description: str = "Quokka migration rollout schedule") -> ExtractedMeeting:
    item = ExtractedItem(
        id=f"{meeting_id}:idea-1",
        type="IDEA",
        description=description,
        theme=theme,
        status="Open",
        confidence="HIGH",
        evidence=Evidence(speaker="Ada", timestamp="00:01:00", quote=description, context=None),
        meeting_id=meeting_id,
    )
    return ExtractedMeeting(
        id=meeting_id, title="Proposal test meeting", date="2026-09-01", source_url="https://example.com", items=[item]
    )


def _multi_item_meeting(meeting_id: str, specs: list[tuple[str, str, list[str], str]]) -> ExtractedMeeting:
    """specs: (candidate id, theme, related candidate ids, description), in extract order."""
    items = [
        ExtractedItem(
            id=f"{meeting_id}:{cid}", type="IDEA", description=description, theme=theme, status="Open",
            confidence="HIGH", related_ids=related,
            evidence=Evidence(speaker="Ada", timestamp="00:01:00", quote=description, context=None),
            meeting_id=meeting_id,
        )
        for cid, theme, related, description in specs
    ]
    return replace(_meeting(meeting_id, "unused"), items=tuple(items))


def _ingest(meeting: ExtractedMeeting) -> None:
    with db.get_session() as session:
        merge_extract(session, meeting)
        session.commit()


def _item(item_id: str) -> KnowledgeItemRow:
    with db.get_session() as session:
        return session.get(KnowledgeItemRow, item_id)


def _topic_named(name: str) -> TopicRow | None:
    with db.get_session() as session:
        return session.execute(select(TopicRow).where(TopicRow.name == name)).scalar_one_or_none()


def _cleanup(meeting_id: str, topic_names: list[str]) -> None:
    with db.get_session() as session:
        for row in session.execute(select(KnowledgeItemRow).where(KnowledgeItemRow.meeting_id == meeting_id)).scalars():
            session.delete(row)
        session.flush()
        meeting = session.get(MeetingRow, meeting_id)
        if meeting is not None:
            session.delete(meeting)
        for name in topic_names:
            topic = session.execute(select(TopicRow).where(TopicRow.name == name)).scalar_one_or_none()
            if topic is not None:
                session.delete(topic)
        session.commit()


def test_ingestion_does_not_create_topic_for_new_theme(db_ready):
    meeting_id, theme = _unique("proposal-meeting"), _unique("novel-theme")
    try:
        _ingest(_meeting(meeting_id, theme))
        assert _topic_named(theme) is None
        item = _item(f"{meeting_id}:idea-1")
        assert item.topic_id is not None
        assert item.suggested_topic == theme or item.suggested_topic is None  # None only if matched an existing topic
        proposals = {p.name: p for p in brain.list_topic_proposals()}
        assert (theme in proposals) == (item.suggested_topic == theme)
    finally:
        _cleanup(meeting_id, [])


def test_ingestion_files_item_under_existing_topic_with_matching_name(db_ready):
    meeting_id = _unique("proposal-meeting")
    topic = brain.create_topic(_unique("existing-topic"))
    try:
        _ingest(_meeting(meeting_id, topic.name.upper()))
        item = _item(f"{meeting_id}:idea-1")
        assert item.topic_id == topic.id
        assert item.suggested_topic is None
    finally:
        _cleanup(meeting_id, [topic.name])


def test_accept_proposal_creates_topic_only_on_acceptance_and_allows_rename(db_ready):
    meeting_id, theme, renamed = _unique("proposal-meeting"), _unique("novel-theme"), _unique("renamed-topic")
    try:
        _ingest(_meeting(meeting_id, theme))
        item_id = f"{meeting_id}:idea-1"
        if _item(item_id).suggested_topic is None:
            pytest.skip("item matched an existing topic semantically in this database")
        brain.accept_topic_proposal(theme, topic_name=renamed)
        created = _topic_named(renamed)
        assert created is not None
        assert _topic_named(theme) is None
        item = _item(item_id)
        assert (item.topic_id, item.theme, item.suggested_topic) == (created.id, renamed, None)
    finally:
        _cleanup(meeting_id, [renamed, theme])


def test_accept_proposal_can_be_redirected_to_existing_topic(db_ready):
    meeting_id, theme = _unique("proposal-meeting"), _unique("novel-theme")
    target = brain.create_topic(_unique("target-topic"))
    try:
        _ingest(_meeting(meeting_id, theme))
        item_id = f"{meeting_id}:idea-1"
        if _item(item_id).suggested_topic is None:
            pytest.skip("item matched an existing topic semantically in this database")
        brain.accept_topic_proposal(theme, existing_topic_id=target.id)
        assert _topic_named(theme) is None
        assert _item(item_id).topic_id == target.id
    finally:
        _cleanup(meeting_id, [target.name, theme])


def test_reject_proposal_keeps_item_out_of_a_new_topic_and_survives_reingest(db_ready):
    meeting_id, theme = _unique("proposal-meeting"), _unique("novel-theme")
    try:
        meeting = _meeting(meeting_id, theme)
        _ingest(meeting)
        item_id = f"{meeting_id}:idea-1"
        if _item(item_id).suggested_topic is None:
            pytest.skip("item matched an existing topic semantically in this database")
        assert brain.reject_topic_proposal(theme) >= 1
        _ingest(meeting)  # re-ingest must not resurrect the proposal
        assert _item(item_id).suggested_topic is None
        assert _topic_named(theme) is None
    finally:
        _cleanup(meeting_id, [])


# distinct descriptions so the in-meeting near-duplicate check never merges these items
_DESCRIPTIONS = ["Quokka migration rollout schedule", "Budget approval for the office plants", "Hiring plan for the Lisbon team"]


def _ingest_related(specs_for, existing_topic):
    meeting_id, theme = _unique("proposal-meeting"), _unique("novel-theme")
    meeting = _multi_item_meeting(meeting_id, specs_for(theme, existing_topic.name))
    _ingest(meeting)
    return meeting_id, theme


def test_related_item_later_in_extract_is_found(db_ready):
    topic = brain.create_topic(_unique("existing-topic"))
    meeting_id = None
    try:
        # B (novel theme) comes first and links forward to A, which matches the existing topic by name
        meeting_id, _ = _ingest_related(
            lambda theme, name: [
                ("b", theme, ["a"], _DESCRIPTIONS[0]),
                ("a", name, [], _DESCRIPTIONS[1]),
            ],
            topic,
        )
        b = _item(f"{meeting_id}:b")
        assert (b.topic_id, b.suggested_topic) == (topic.id, None)
    finally:
        _cleanup(meeting_id, [topic.name]) if meeting_id else brain.delete_topic(topic.id)


def test_related_link_is_followed_in_reverse_direction(db_ready):
    topic = brain.create_topic(_unique("existing-topic"))
    meeting_id = None
    try:
        # A links to B; B (novel theme) declares no link back
        meeting_id, _ = _ingest_related(
            lambda theme, name: [
                ("b", theme, [], _DESCRIPTIONS[0]),
                ("a", name, ["b"], _DESCRIPTIONS[1]),
            ],
            topic,
        )
        b = _item(f"{meeting_id}:b")
        assert (b.topic_id, b.suggested_topic) == (topic.id, None)
    finally:
        _cleanup(meeting_id, [topic.name]) if meeting_id else brain.delete_topic(topic.id)


def test_related_chain_resolves_regardless_of_order(db_ready):
    topic = brain.create_topic(_unique("existing-topic"))
    meeting_id = None
    try:
        meeting_id, _ = _ingest_related(
            lambda theme, name: [
                ("c", theme + "-c", ["b"], _DESCRIPTIONS[0]),
                ("b", theme + "-b", ["a"], _DESCRIPTIONS[1]),
                ("a", name, [], _DESCRIPTIONS[2]),
            ],
            topic,
        )
        for cid in ("a", "b", "c"):
            item = _item(f"{meeting_id}:{cid}")
            assert (item.topic_id, item.suggested_topic) == (topic.id, None), cid
    finally:
        _cleanup(meeting_id, [topic.name]) if meeting_id else brain.delete_topic(topic.id)


def test_items_related_only_to_each_other_stay_proposals(db_ready):
    meeting_id, theme = _unique("proposal-meeting"), _unique("novel-theme")
    try:
        _ingest(
            _multi_item_meeting(
                meeting_id,
                [("a", theme + "-a", ["b"], _DESCRIPTIONS[0]), ("b", theme + "-b", [], _DESCRIPTIONS[1])],
            )
        )
        for cid, suffix in (("a", "-a"), ("b", "-b")):
            item = _item(f"{meeting_id}:{cid}")
            if item.suggested_topic is None:
                pytest.skip("item matched an existing topic semantically in this database")
            assert item.suggested_topic == theme + suffix
        assert _topic_named(theme + "-a") is None and _topic_named(theme + "-b") is None
    finally:
        _cleanup(meeting_id, [])


def _add_review_candidate(meeting_id: str, description: str) -> str:
    from app.infrastructure.persistence.orm_models import ReviewCandidateRow

    candidate_id = f"{meeting_id}:review-1"
    with db.get_session() as session:
        session.add(MeetingRow(id=meeting_id, title="Review test meeting", date="2026-09-01", source_url="https://example.com"))
        session.flush()
        session.add(
            ReviewCandidateRow(
                id=candidate_id, meeting_id=meeting_id, type="IDEA", description=description, reason="unsure",
                confidence="LOW", evidence_speaker="Ada", evidence_timestamp="00:01:00", evidence_quote=description,
                evidence_context=None, status="PENDING",
            )
        )
        session.commit()
    return candidate_id


def _delete_candidate_meeting(meeting_id: str) -> None:
    from app.infrastructure.persistence.orm_models import ReviewCandidateRow

    with db.get_session() as session:
        for row in session.execute(select(ReviewCandidateRow).where(ReviewCandidateRow.meeting_id == meeting_id)).scalars():
            session.delete(row)
        session.flush()
    _cleanup(meeting_id, [])


def test_accept_review_candidate_into_chosen_topic(db_ready):
    meeting_id = _unique("review-meeting")
    topic = brain.create_topic(_unique("chosen-topic"))
    try:
        candidate_id = _add_review_candidate(meeting_id, _DESCRIPTIONS[2])
        brain.decide_review_candidate(candidate_id, "ACCEPTED", topic_id=topic.id)
        with db.get_session() as session:
            item = session.execute(select(KnowledgeItemRow).where(KnowledgeItemRow.meeting_id == meeting_id)).scalar_one()
        assert (item.topic_id, item.theme) == (topic.id, topic.name)
    finally:
        _delete_candidate_meeting(meeting_id)
        with db.get_session() as session:
            session.delete(session.get(TopicRow, topic.id))
            session.commit()


def test_pending_review_candidates_drops_decided_ones(db_ready):
    meeting_id = _unique("review-meeting")
    try:
        candidate_id = _add_review_candidate(meeting_id, _DESCRIPTIONS[2])
        pending = {c.id: c for c in brain.list_pending_review()}
        assert pending[candidate_id].status == "PENDING"
        assert all(c.status == "PENDING" for c in pending.values())
        brain.decide_review_candidate(candidate_id, "REJECTED")
        assert candidate_id not in {c.id for c in brain.list_pending_review()}
    finally:
        _delete_candidate_meeting(meeting_id)


def test_accept_review_candidate_with_blank_topic_uses_uncategorized_and_bad_topic_is_rejected(db_ready):
    meeting_id = _unique("review-meeting")
    try:
        candidate_id = _add_review_candidate(meeting_id, _DESCRIPTIONS[2])
        with pytest.raises(TopicNotFound):
            brain.decide_review_candidate(candidate_id, "ACCEPTED", topic_id="no-such-topic")
        brain.decide_review_candidate(candidate_id, "ACCEPTED", topic_id="")
        with db.get_session() as session:
            item = session.execute(select(KnowledgeItemRow).where(KnowledgeItemRow.meeting_id == meeting_id)).scalar_one()
            assert session.get(TopicRow, item.topic_id).name == "Uncategorized"
    finally:
        _delete_candidate_meeting(meeting_id)


def test_topic_ranker_is_reused_until_its_inputs_change(db_ready):
    from app.application.services.topic_ranker_cache import TopicRankerCache
    from app.infrastructure.external_services.tfidf_description_index import build_tfidf_description_index
    from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

    builds = []

    def counting_index(descriptions):
        builds.append(1)
        return build_tfidf_description_index(descriptions)

    cache = TopicRankerCache(counting_index)
    topic = brain.create_topic(_unique("ranker-cache-topic"))
    try:
        with SqlAlchemyUnitOfWork() as uow:
            first = cache.get(uow)
            assert cache.get(uow) is first
        assert len(builds) == 1

        brain.add_topic_tag(topic.id, "cache-buster")
        with SqlAlchemyUnitOfWork() as uow:
            assert cache.get(uow) is not first
        assert len(builds) == 2
    finally:
        with db.get_session() as session:
            session.delete(session.get(TopicRow, topic.id))
            session.commit()


def test_candidates_get_a_suggested_topic_only_for_close_matches(db_ready):
    meeting_id, close_meeting, far_meeting = _unique("review-meeting"), _unique("review-close"), _unique("review-far")
    topic = brain.create_topic(_unique("hint-topic"))
    try:
        _ingest(_meeting(meeting_id, topic.name))  # gives the topic an embedded item
        close_id = _add_review_candidate(close_meeting, "Quokka migration rollout schedule")
        far_id = _add_review_candidate(far_meeting, "zzz qqq xxx 12345")

        pending = {candidate.id: candidate for candidate in brain.list_pending_review()}
        close, far = pending[close_id], pending[far_id]
        assert close.suggested_topic_id is not None  # ours, unless another topic is closer still
        assert far.suggested_topic_id is None or far.suggested_topic_id != topic.id
    finally:
        _delete_candidate_meeting(close_meeting)
        _delete_candidate_meeting(far_meeting)
        _cleanup(meeting_id, [topic.name])
