"""Unit tests for the entities: each business rule they guard, with the old app.data behavior as the spec."""
from __future__ import annotations

import pytest

from app.domain.entities.knowledge_item import ItemEdit, KnowledgeItem
from app.domain.entities.meeting import Meeting
from app.domain.entities.note import Note
from app.domain.entities.review_candidate import ReviewCandidate
from app.domain.entities.topic_image import TopicImage
from app.domain.exceptions import (
    InvalidTopicMerge,
    ItemNotDeletable,
    ItemNotEditable,
    ReviewCandidateAlreadyDecided,
    TooManyTags,
    TopicHasItems,
)
from app.domain.value_objects.evidence import Evidence
from app.domain.value_objects.extraction import (
    ExtractedMeeting,
    ExtractedReviewCandidate,
)
from app.domain.value_objects.tag import MAX_TAGS
from tests.domain import factories as make

NOW = "2026-06-15T10:00:00+00:00"


# -- entities have no public setters ---------------------------------------------------------------------


@pytest.mark.parametrize("entity", [make.item(), make.topic(), make.candidate(), Meeting(id="m", title="t", date="2026-01-01", source_url="")])
def test_state_cannot_be_assigned_from_outside(entity):
    for name in ("id", "status" if hasattr(entity, "status") else "title"):
        with pytest.raises(AttributeError, match="read-only"):
            setattr(entity, name, "x")


# -- KnowledgeItem ---------------------------------------------------------------------------------------


def test_manual_item_hangs_off_the_manual_meeting_with_high_confidence():
    created = KnowledgeItem.manual(
        unique_id="u1", topic=make.topic(), type="ACTION", description="Call vendor", owner="Ana", due_date="2026-07-01",
        rationale=None, embedding=[0.1],
    )
    assert (created.id, created.meeting_id, created.is_manual) == ("manual:u1", "manual", True)
    assert (created.topic_id, created.theme, created.status, created.confidence) == ("t1", "Launch", "Open", "HIGH")
    assert created.stakeholders == ("Ana",) and created.evidence == Evidence(quote="Added manually")
    ownerless = KnowledgeItem.manual(
        unique_id="u2", topic=make.topic(), type="IDEA", description="x", owner=None, due_date=None, rationale=None, embedding=[0.1]
    )
    assert ownerless.stakeholders == ()


def test_accepted_candidate_becomes_a_high_confidence_item_owned_by_the_speaker():
    promoted = KnowledgeItem.from_review_candidate(make.candidate(), topic_id="t9", topic_name="Infra", embedding=[0.2])
    assert promoted.id == "m1:accepted-review-1" and promoted.meeting_id == "m1"
    assert (promoted.type, promoted.status, promoted.confidence) == ("DECISION", "Open", "HIGH")
    assert (promoted.owner, promoted.stakeholders, promoted.rationale) == ("Ben", ("Ben",), "Explicit agreement")
    assert (promoted.topic_id, promoted.theme) == ("t9", "Infra")
    odd = KnowledgeItem.from_review_candidate(
        make.candidate(type="risk", evidence=Evidence(quote="q")), topic_id="t", topic_name="T", embedding=[0.2]
    )
    assert (odd.type, odd.owner, odd.stakeholders) == ("IDEA", None, ())


def test_status_collapses_to_open_closed_for_reading():
    assert make.item(status="Answered").open_closed == "Closed" and make.item(status="Answered").is_resolved
    current = make.item()
    current.set_status("Closed")
    assert current.status == "Closed" and current.open_closed == "Closed"


def test_item_priority_override_wins_over_the_topic_and_clearing_removes_reason_and_time():
    current = make.item()
    major_topic = make.topic(calculation=make.calculation("MAJOR"))
    assert current.effective_priority(major_topic) == "MAJOR"
    assert current.effective_priority(None) is None
    current.override_priority("CRITICAL", "exec ask", NOW)
    assert current.effective_priority(major_topic) == "CRITICAL"
    assert (current.manual_override.reason, current.manual_override.overridden_at) == ("exec ask", NOW)
    current.override_priority(None, "ignored", NOW)
    assert current.manual_override is None and current.effective_priority(major_topic) == "MAJOR"


def test_item_inherits_the_topic_override_before_its_calculated_priority():
    overridden_topic = make.topic(calculation=make.calculation("MINOR"))
    overridden_topic.override_priority("CRITICAL", None, NOW)
    assert make.item().effective_priority(overridden_topic) == "CRITICAL"
    assert make.item().effective_priority(make.topic()) is None


def test_item_tags_are_normalized_deduplicated_and_capped():
    current = make.item()
    current.add_tag(" Q3  Launch ")
    current.add_tag("q3 launch")
    assert current.tags == ("q3 launch",)
    current.remove_tag("Q3 LAUNCH")
    assert current.tags == ()
    full = make.item(tags=[f"t{i}" for i in range(MAX_TAGS)])
    with pytest.raises(TooManyTags):
        full.add_tag("extra")


def test_item_notes_append_edit_and_remove_ignoring_unknown_ids():
    current = make.item()
    current.add_note(Note("n1", "first", NOW))
    current.add_note(Note("n2", "second", NOW))
    current.edit_note("n1", "edited")
    current.edit_note("missing", "nope")
    assert [note.body for note in current.notes] == ["edited", "second"]
    current.remove_note("n1")
    current.remove_note("missing")
    assert [note.id for note in current.notes] == ["n2"]


def test_filing_keeps_the_theme_equal_to_the_topic_name():
    current = make.item(suggested_topic="Infra")
    current.file_under(make.topic("t2", "Infra"))
    assert (current.topic_id, current.theme, current.suggested_topic) == ("t2", "Infra", "Infra")
    current.file_under(None)
    assert (current.topic_id, current.theme) == (None, None)
    current.accept_proposal(make.topic("t3", "Infrastructure"))
    assert (current.topic_id, current.theme, current.suggested_topic) == ("t3", "Infrastructure", None)
    pending = make.item(suggested_topic="Hiring")
    pending.dismiss_proposal()
    assert pending.suggested_topic is None and pending.topic_id == "t1"


def test_edit_touches_only_named_fields_and_reports_a_changed_description():
    current = make.item(due_date="2026-07-01", due_date_source_text="next month", rationale="because")
    assert current.edit(ItemEdit(fields=frozenset({"owner"}), owner="Cy")) is False
    assert (current.owner, current.stakeholders, current.due_date, current.rationale) == ("Cy", ("Cy",), "2026-07-01", "because")
    assert current.edit(ItemEdit(fields=frozenset({"description"}), description="Ship the beta")) is False
    assert current.edit(ItemEdit(fields=frozenset({"description", "due_date", "rationale", "owner"}), description="Ship GA")) is True
    assert (current.description, current.due_date, current.due_date_source_text, current.rationale) == ("Ship GA", None, None, None)
    assert (current.owner, current.stakeholders) == (None, ())


def test_only_manual_items_can_change_type_or_be_deleted():
    extracted_item = make.item()
    with pytest.raises(ItemNotEditable, match="cannot be changed"):
        extracted_item.edit(ItemEdit(fields=frozenset({"type"}), type="IDEA"))
    assert extracted_item.edit(ItemEdit(fields=frozenset({"type"}), type="ACTION")) is False  # same type is allowed
    with pytest.raises(ItemNotDeletable) as excinfo:
        extracted_item.ensure_deletable()
    assert excinfo.value.item_id == "m1:A-1" and str(excinfo.value) == "Only manually added items can be deleted"

    manual = make.item("manual:1")
    manual.edit(ItemEdit(fields=frozenset({"type"}), type="QUESTION"))
    assert manual.type == "QUESTION"
    manual.ensure_deletable()


def test_reinforce_raises_confidence_once():
    current = make.item(confidence="LOW")
    assert current.reinforce() is True and current.confidence == "HIGH"
    assert current.reinforce() is False


def test_reingest_ignores_human_owned_status_and_a_reinforced_confidence():
    stored = make.item(status="Closed")
    assert not stored.differs_from_extraction(make.extracted(status="Open"))
    assert stored.differs_from_extraction(make.extracted(confidence="LOW"))
    reinforced = make.item(confidence="HIGH")
    assert not reinforced.differs_from_extraction(make.extracted(confidence="MEDIUM"))
    assert reinforced.differs_from_extraction(make.extracted(owner="Cy"))
    assert stored.differs_from_extraction(make.extracted(evidence=Evidence(quote="other")))
    assert stored.differs_from_extraction(make.extracted(related_ids=("B-2",)))


def test_apply_extraction_refreshes_extractor_fields_and_keeps_human_decisions():
    stored = make.item(status="Closed", topic_id="t7", theme="Chosen", suggested_topic=None, tags=("keep",), embedding=[0.1])
    stored.override_priority("MAJOR", None, NOW)
    stored.apply_extraction(
        make.extracted(description="Ship GA", status="Open", theme="Other", owner="Cy", stakeholders=("Cy",), related_ids=("B-2",)),
        embedding=[0.9],
    )
    assert (stored.description, stored.owner, stored.stakeholders, stored.related_ids) == ("Ship GA", "Cy", ("Cy",), ("B-2",))
    assert stored.embedding == [0.9]
    assert (stored.status, stored.topic_id, stored.theme, stored.tags) == ("Closed", "t7", "Chosen", ("keep",))
    assert stored.manual_override.priority == "MAJOR"
    stored.apply_extraction(make.extracted(description="Ship GA"))
    assert stored.embedding == [0.9]  # no new embedding supplied: the stored one stays


def test_new_ingested_item_takes_the_matched_topic_and_keeps_the_proposal():
    created = KnowledgeItem.from_extraction(
        make.extracted(theme="Billing", status="In progress"), topic_id="unc", topic_name="Uncategorized",
        suggested_topic="Billing", embedding=[0.3],
    )
    assert (created.topic_id, created.theme, created.suggested_topic, created.status) == ("unc", "Uncategorized", "Billing", "In progress")
    assert created.local_key == "A-1"


# -- Topic -----------------------------------------------------------------------------------------------


def test_topic_priority_is_none_until_calculated_and_override_is_independent():
    current = make.topic()
    assert current.priority is None and current.effective_priority is None and current.previous_priority_state is None
    current.override_priority("CRITICAL", "why", NOW)
    assert current.effective_priority == "CRITICAL" and current.priority is None

    assert current.record_priority(make.calculation("MAJOR", 50), trigger="manual", history_id="h1") is None  # first calc
    assert current.priority.calculated_priority == "MAJOR" and current.priority.effective_priority == "CRITICAL"
    assert current.manual_override.reason == "why"  # recalculation never touches the override
    state = current.previous_priority_state
    assert (state.priority, state.score) == ("MAJOR", 50.0)

    current.override_priority(None, None, NOW)
    assert current.priority.effective_priority == "MAJOR" and current.priority.manual_override is None


def test_history_is_recorded_only_when_the_category_changes():
    current = make.topic(calculation=make.calculation("MINOR", 20))
    assert current.record_priority(make.calculation("MINOR", 30), trigger="item_edited", history_id="h1") is None
    entry = current.record_priority(make.calculation("CRITICAL", 80), trigger="item_added", history_id="h2")
    assert entry is not None and entry.is_escalation
    assert (entry.id, entry.topic_id, entry.previous_priority, entry.new_priority) == ("h2", "t1", "MINOR", "CRITICAL")
    assert (entry.previous_score, entry.new_score, entry.trigger) == (30.0, 80.0, "item_added")
    assert entry.primary_drivers == ("nine", "five") and entry.source_knowledge_item_ids == ("i1", "i2")
    assert entry.changed_at == "2026-06-15T00:00:00+00:00"


def test_topic_can_only_be_deleted_empty_and_never_merged_into_itself():
    current = make.topic()
    current.ensure_deletable(0)
    with pytest.raises(TopicHasItems) as excinfo:
        current.ensure_deletable(3)
    assert excinfo.value.item_count == 3
    with pytest.raises(InvalidTopicMerge, match="cannot merge a topic into itself"):
        current.ensure_can_merge_into(make.topic())
    current.ensure_can_merge_into(make.topic("t2", "Other"))


def test_topic_notes_tags_images_and_rename():
    current = make.topic()
    current.rename("Launch 2")
    current.set_status("Closed")
    current.add_tag("Infra")
    current.add_note(Note("n1", "hello", NOW))
    current.edit_note("n1", "edited")
    image = TopicImage(id="i1", key="topics/t1/i1.png", filename="a.png", content_type="image/png", size=3, created_at=NOW)
    current.attach_image(image)
    assert (current.name, current.status, current.tags, current.notes[0].body) == ("Launch 2", "Closed", ("infra",), "edited")
    assert current.find_image("i1") is image and current.find_image("nope") is None
    assert current.detach_image("nope") is None and current.detach_image("i1") is image
    assert current.images == ()
    current.remove_note("n1")
    assert current.notes == () and not current.is_uncategorized
    assert make.topic(name="Uncategorized").is_uncategorized


# -- ReviewCandidate / Meeting ---------------------------------------------------------------------------


def test_a_review_decision_is_final():
    pending = make.candidate()
    assert pending.is_pending and pending.local_key == "review-1"
    pending.decide("ACCEPTED")
    assert pending.status == "ACCEPTED"
    with pytest.raises(ReviewCandidateAlreadyDecided):
        pending.decide("REJECTED")


def test_reingest_never_reopens_a_decided_candidate():
    decided = make.candidate(status="REJECTED")
    update = ExtractedReviewCandidate(
        id="m1:review-1", type="decision", description="Adopt pgvector 0.8", reason="Explicit agreement",
        confidence="MEDIUM", evidence=Evidence(speaker="Ben", quote="we agree"),
    )
    assert decided.differs_from_extraction(update)
    decided.apply_extraction(update)
    assert decided.description == "Adopt pgvector 0.8" and decided.status == "REJECTED"
    assert not decided.differs_from_extraction(update)
    assert ReviewCandidate.from_extraction(update, "m1").status == "PENDING"


def test_meeting_follows_its_extract_and_the_manual_meeting_is_synthetic():
    extract = ExtractedMeeting(id="m1", title="Sync", date="2026-06-01", source_url="sync.json")
    meeting = Meeting.from_extraction(extract)
    assert not meeting.differs_from_extraction(extract)
    renamed = ExtractedMeeting(id="m1", title="Weekly sync", date="2026-06-01", source_url="sync.json")
    assert meeting.differs_from_extraction(renamed)
    meeting.apply_extraction(renamed)
    assert meeting.title == "Weekly sync"
    manual = Meeting.manual("2026-06-15")
    assert (manual.id, manual.title, manual.date, manual.source_url) == ("manual", "Manual entries", "2026-06-15", "")
