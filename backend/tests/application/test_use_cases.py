"""Use-case tests over in-memory fakes: the orchestration rules of the application layer, with no database,
object storage or model involved."""
from __future__ import annotations

import pytest

from app.application.dtos import NewItem
from app.application.exceptions import ExtractSourceUnavailable, IngestionAlreadyRunning
from app.domain.entities.knowledge_item import ItemEdit
from app.domain.entities.meeting import Meeting
from app.domain.entities.note import Note
from app.domain.exceptions import (
    ImageTooLarge,
    InvalidTopicMerge,
    InvalidTopicName,
    ItemNotDeletable,
    ItemNotEditable,
    ItemNotFound,
    ItemsNotFound,
    MeetingNotFound,
    NoMeetingsAvailable,
    ProposalTargetTopicNotFound,
    ReviewCandidateAlreadyDecided,
    ReviewCandidateNotFound,
    TopicHasItems,
    TopicNameConflict,
    TopicNotFound,
    TopicProposalNotFound,
    UnsupportedImageType,
)
from app.domain.value_objects.evidence import Evidence
from app.domain.value_objects.extraction import (
    ExtractedMeeting,
    ExtractedReviewCandidate,
)
from tests.application.fakes import World
from tests.domain import factories as make

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
BILLING, HIRING, OTHER = [1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]


@pytest.fixture
def world() -> World:
    return World(
        {
            "Export invoices as parquet": BILLING,
            "Invoice export job": [0.98, 0.05, 0.0, 0.0],
            "Open a backend role": HIRING,
            "Plan the offsite": OTHER,
        }
    )


def seed_topics(world: World):
    billing, hiring = make.topic("billing", "Billing"), make.topic("hiring", "Hiring")
    world.db.seed(
        Meeting(id="m1", title="Sync", date="2026-06-01", source_url="sync.json"),
        billing,
        hiring,
        make.item("m1:A-1", description="Export invoices as parquet", topic_id="billing", theme="Billing", embedding=BILLING),
        make.item("m1:A-2", description="Open a backend role", topic_id="hiring", theme="Hiring", embedding=HIRING, type="QUESTION"),
    )
    return billing, hiring


# -- topics ----------------------------------------------------------------------------------------------


def test_create_topic_rejects_a_taken_name(world):
    created = world.app.create_topic("Billing")
    assert (created.name, created.items, created.priority) == ("Billing", (), None)
    with pytest.raises(TopicNameConflict):
        world.app.create_topic("Billing")
    assert len(world.db.state.topics) == 1


def test_rename_updates_the_items_theme_and_rejects_another_topics_name(world):
    seed_topics(world)
    renamed = world.app.rename_topic("billing", "Finance")
    assert renamed.name == "Finance" and [item.theme for item in renamed.items] == ["Finance"]
    assert world.db.item("m1:A-1").theme == "Finance"
    with pytest.raises(TopicNameConflict):
        world.app.rename_topic("billing", "Hiring")
    world.app.rename_topic("billing", "Finance")  # its own name is not a conflict
    with pytest.raises(TopicNotFound):
        world.app.rename_topic("nope", "x")


def test_delete_topic_requires_it_to_be_empty_and_cleans_up_its_images(world):
    seed_topics(world)
    with pytest.raises(TopicHasItems) as excinfo:
        world.app.delete_topic("billing")
    assert excinfo.value.item_count == 1

    empty = world.app.create_topic("Empty")
    world.app.add_topic_image(empty.id, "a.png", PNG)
    assert len(world.images.objects) == 1
    world.app.delete_topic(empty.id)
    assert world.db.topic_named("Empty") is None and world.images.objects == {}
    with pytest.raises(TopicNotFound):
        world.app.delete_topic(empty.id)


def test_a_failing_image_store_does_not_fail_the_topic_delete(world):
    empty = world.app.create_topic("Empty")
    world.app.add_topic_image(empty.id, "a.png", PNG)
    world.images.fail_delete = True
    world.app.delete_topic(empty.id)
    assert world.db.topic_named("Empty") is None


def test_merge_moves_items_notes_and_images_then_recalculates_the_target(world):
    seed_topics(world)
    world.app.add_topic_note("billing", "from billing")
    world.app.add_topic_image("billing", "a.png", PNG)
    merged = world.app.merge_topics("billing", "hiring")
    assert world.db.state.topics.keys() == {"hiring"}
    assert sorted(item.id for item in merged.items) == ["m1:A-1", "m1:A-2"]
    assert [note.body for note in merged.notes] == ["from billing"] and len(merged.images) == 1
    assert world.db.item("m1:A-1").theme == "Hiring"
    assert merged.priority is not None  # recalculated after the merge

    with pytest.raises(InvalidTopicMerge):
        world.app.merge_topics("hiring", "hiring")
    with pytest.raises(InvalidTopicMerge):
        world.app.merge_topics("ghost", "ghost")  # rejected before anything is looked up
    with pytest.raises(TopicNotFound):
        world.app.merge_topics("ghost", "hiring")


def test_topic_tags_notes_and_status(world):
    seed_topics(world)
    assert world.app.add_topic_tag("billing", " Q3  Launch ").tags == ("q3 launch",)
    assert world.app.remove_topic_tag("billing", "Q3 LAUNCH").tags == ()
    with_note = world.app.add_topic_note("billing", "hello")
    note_id = with_note.notes[0].id
    assert with_note.notes[0].created_at == world.clock.now().isoformat()
    assert world.app.edit_topic_note("billing", note_id, "edited").notes[0].body == "edited"
    assert world.app.delete_topic_note("billing", note_id).notes == ()
    assert world.app.set_topic_status("billing", "Closed").status == "Closed"
    for use_case, args in [
        (world.app.add_topic_tag, ("nope", "x")),
        (world.app.add_topic_note, ("nope", "x")),
        (world.app.set_topic_status, ("nope", "Open")),
        (world.app.get_topic, ("nope",)),
    ]:
        with pytest.raises(TopicNotFound):
            use_case(*args)


def test_related_topics_and_merge_suggestions_skip_uncategorized(world):
    seed_topics(world)
    world.db.seed(
        make.topic("finance", "Finance"),
        make.item("m1:A-3", description="Invoice export job", topic_id="finance", embedding=[0.98, 0.05, 0.0, 0.0]),
        make.topic("unc", "Uncategorized"),
        make.item("m1:A-4", topic_id="unc", embedding=BILLING),
    )
    related = world.app.get_related_topics("billing")
    assert [(r.id, r.item_count) for r in related] == [("finance", 1)] and related[0].similarity > 0.99
    suggestions = world.app.suggest_topic_merges()
    assert [(s.topic_a.id, s.topic_b.id) for s in suggestions] == [("billing", "finance")]
    assert world.app.suggest_topic_merges(max_related_items=1) == []  # only topics with fewer items qualify
    with pytest.raises(TopicNotFound):
        world.app.get_related_topics("nope")


# -- items -----------------------------------------------------------------------------------------------


def test_adding_an_item_by_hand_creates_the_manual_meeting_once_and_recalculates_the_topic(world):
    seed_topics(world)
    created = world.app.create_item("billing", NewItem(type="ACTION", description="Call the vendor", owner="Ana"))
    assert created.id == "manual:id-1" and created.meeting_id == "manual"
    assert (created.status, created.confidence, created.stakeholders, created.topic_name) == ("Open", "HIGH", ("Ana",), "Billing")
    assert world.db.state.meetings["manual"].date == "2026-06-15"
    assert world.db.topic("billing").calculation is not None  # recalculated after the commit
    assert created.effective_priority is None  # the returned item predates that recalculation

    world.app.create_item("billing", NewItem(type="IDEA", description="Another"))
    assert len([m for m in world.db.state.meetings if m == "manual"]) == 1
    with pytest.raises(TopicNotFound):
        world.app.create_item("nope", NewItem(type="IDEA", description="x"))


def test_editing_re_embeds_only_when_the_description_changes(world):
    seed_topics(world)
    world.app.update_item("m1:A-1", ItemEdit(fields=frozenset({"owner"}), owner="Cy"))
    assert world.embedder.calls == []
    world.app.update_item("m1:A-1", ItemEdit(fields=frozenset({"description"}), description="Plan the offsite"))
    assert world.embedder.embedded == ["Plan the offsite"]
    assert list(world.db.item("m1:A-1").embedding) == OTHER
    with pytest.raises(ItemNotEditable):
        world.app.update_item("m1:A-1", ItemEdit(fields=frozenset({"type"}), type="IDEA"))
    with pytest.raises(ItemNotFound):
        world.app.update_item("nope", ItemEdit(fields=frozenset({"owner"}), owner="x"))


def test_only_manual_items_can_be_deleted(world):
    seed_topics(world)
    with pytest.raises(ItemNotDeletable):
        world.app.delete_item("m1:A-1")
    manual = world.app.create_item("billing", NewItem(type="IDEA", description="temp"))
    world.app.delete_item(manual.id)
    assert manual.id not in world.db.state.items
    with pytest.raises(ItemNotFound):
        world.app.delete_item(manual.id)


def test_status_override_tags_and_notes_on_items(world):
    seed_topics(world)
    assert world.app.set_item_status("m1:A-1", "Closed").status == "Closed"
    overridden = world.app.set_item_priority_override("m1:A-1", "CRITICAL", "exec ask")
    assert overridden.effective_priority == "CRITICAL"
    assert overridden.manual_override.overridden_at == world.clock.now().isoformat()
    cleared = world.app.set_item_priority_override("m1:A-1", None, "ignored")
    assert cleared.manual_override is None and cleared.effective_priority is None
    assert world.app.add_item_tag("m1:A-1", "Infra").tags == ("infra",)
    assert world.app.remove_item_tag("m1:A-1", "INFRA").tags == ()
    noted = world.app.add_item_note("m1:A-1", "first")
    assert world.app.edit_item_note("m1:A-1", noted.notes[0].id, "edited").notes[0].body == "edited"
    assert world.app.delete_item_note("m1:A-1", noted.notes[0].id).notes == ()
    with pytest.raises(ItemNotFound):
        world.app.set_item_status("nope", "Open")


def test_moving_an_item_recalculates_both_topics_and_hides_uncategorized(world):
    seed_topics(world)
    moved = world.app.assign_item_topic("m1:A-1", "hiring")
    assert (moved.topic_id, moved.topic_name, moved.theme) == ("hiring", "Hiring", "Hiring")
    assert world.db.topic("billing").calculation is not None and world.db.topic("hiring").calculation is not None
    unassigned = world.app.assign_item_topic("m1:A-1", None)
    assert (unassigned.topic_id, unassigned.theme) == (None, None)
    world.db.seed(make.topic("unc", "Uncategorized"))
    parked = world.app.assign_item_topic("m1:A-1", "unc")
    assert (parked.topic_id, parked.topic_name, parked.theme) == (None, None, "Uncategorized")
    with pytest.raises(ItemNotFound):
        world.app.assign_item_topic("nope", "hiring")
    with pytest.raises(TopicNotFound):
        world.app.assign_item_topic("m1:A-1", "nope")


def test_bulk_move_is_all_or_nothing(world):
    seed_topics(world)
    with pytest.raises(ItemsNotFound) as excinfo:
        world.app.assign_items_topic(["m1:A-1", "ghost"], "hiring")
    assert str(excinfo.value) == "items not found: ['ghost']"
    assert world.db.item("m1:A-1").topic_id == "billing"
    with pytest.raises(TopicNotFound):
        world.app.assign_items_topic(["m1:A-1"], "nope")
    moved = world.app.assign_items_topic(["m1:A-1", "m1:A-2"], "hiring")
    assert {item.topic_id for item in moved} == {"hiring"}


def test_listing_items_filters_by_type_status_and_priority(world):
    seed_topics(world)
    world.app.set_item_status("m1:A-1", "Done")
    world.app.set_item_priority_override("m1:A-2", "MAJOR", None)
    assert {item.id for item in world.app.list_items()} == {"m1:A-1", "m1:A-2"}
    assert [item.id for item in world.app.list_items(item_type="QUESTION")] == ["m1:A-2"]
    assert [item.id for item in world.app.list_items(status="Closed")] == ["m1:A-1"]
    assert [item.id for item in world.app.list_items(priority="MAJOR")] == ["m1:A-2"]


def test_item_detail_separates_evidence_links_from_semantic_neighbours(world):
    seed_topics(world)
    world.db.seed(
        make.item("m1:A-3", description="Invoice export job", related_ids=("A-2",), topic_id="billing", embedding=[0.98, 0.05, 0.0, 0.0]),
    )
    detail = world.app.get_item_detail("m1:A-3")
    assert [item.id for item in detail.related] == ["m1:A-2"]
    assert [item.id for item in detail.similar] == ["m1:A-1"]  # the related item is never repeated as "similar"
    with pytest.raises(ItemNotFound):
        world.app.get_item_detail("nope")


# -- priority --------------------------------------------------------------------------------------------


def test_a_manual_override_survives_recalculation_and_history_tracks_category_changes(world):
    seed_topics(world)
    world.app.set_topic_priority_override("billing", "CRITICAL", "exec ask")
    recalculated = world.app.recalculate_topic_priority("billing")
    assert recalculated.priority.effective_priority == "CRITICAL"
    assert recalculated.priority.calculated_priority == "MINOR"
    assert recalculated.priority.manual_override.reason == "exec ask"
    assert world.app.get_priority_history("billing") == []  # first calculation is not a change

    world.clock.advance(days=1)
    for index in range(6):  # enough decisions and deadlines to leave MINOR
        world.db.seed(
            make.item(f"m1:D-{index}", type="DECISION", topic_id="billing", stakeholders=(f"p{index}",), embedding=BILLING),
            make.item(f"m1:X-{index}", type="ACTION", topic_id="billing", due_date="2026-06-10", status="Blocked", embedding=BILLING),
        )
    world.app.recalculate_topic_priority("billing", trigger="item_added")
    [entry] = world.app.get_priority_history("billing")
    assert (entry.previous_priority, entry.new_priority, entry.trigger) == ("MINOR", "CRITICAL", "item_added")
    assert world.app.get_recent_escalations(days=1) == [entry]
    world.clock.advance(days=30)
    assert world.app.get_recent_escalations(days=14) == []

    with pytest.raises(TopicNotFound):
        world.app.recalculate_topic_priority("nope")
    with pytest.raises(TopicNotFound):
        world.app.get_priority_history("nope")
    assert world.app.get_priority_history("nope", require_topic=False) == []
    assert world.app.recalculate_all_priorities() == 2


# -- review ----------------------------------------------------------------------------------------------


def review_candidate(candidate_id: str, description: str, **overrides):
    return make.candidate(candidate_id, description=description, **overrides)


def test_accepting_files_the_new_item_where_the_reviewer_chose(world):
    seed_topics(world)
    world.db.seed(review_candidate("m1:review-1", "Plan the offsite"))
    decided = world.app.decide_review_candidate("m1:review-1", "ACCEPTED", "hiring")
    assert decided.status == "ACCEPTED"
    promoted = world.db.item("m1:accepted-review-1")
    assert (promoted.topic_id, promoted.theme, promoted.confidence, promoted.type) == ("hiring", "Hiring", "HIGH", "DECISION")
    with pytest.raises(ReviewCandidateAlreadyDecided):
        world.app.decide_review_candidate("m1:review-1", "REJECTED")
    with pytest.raises(ReviewCandidateNotFound):
        world.app.decide_review_candidate("nope", "REJECTED")


def test_accepting_without_a_topic_auto_matches_or_falls_back_to_uncategorized(world):
    seed_topics(world)
    world.db.seed(
        review_candidate("m1:review-1", "Billing dashboard idea"),  # near Billing, but not a duplicate of its item
        review_candidate("m1:review-2", "Plan the offsite"),  # close to nothing
        review_candidate("m1:review-3", "Something else entirely"),
    )
    world.embedder.vectors["Something else entirely"] = [0.0, 0.0, 0.0, 1.0]
    world.embedder.vectors["Billing dashboard idea"] = [0.7, 0.0, 0.0, 0.7]  # similarity 0.71: a match, distance 0.29
    world.app.decide_review_candidate("m1:review-1", "ACCEPTED", None)
    assert world.db.item("m1:accepted-review-1").topic_id == "billing"
    world.app.decide_review_candidate("m1:review-2", "ACCEPTED", None)
    uncategorized = world.db.topic_named("Uncategorized")
    assert uncategorized is not None and world.db.item("m1:accepted-review-2").topic_id == uncategorized.id
    world.app.decide_review_candidate("m1:review-3", "ACCEPTED", "")  # "" = the reviewer chose Uncategorized
    assert world.db.item("m1:accepted-review-3").topic_id == uncategorized.id
    assert len([t for t in world.db.state.topics.values() if t.name == "Uncategorized"]) == 1


def test_accepting_a_near_duplicate_reinforces_the_existing_item_instead(world):
    seed_topics(world)
    world.db.seed(review_candidate("m1:review-1", "Export invoices as parquet"))
    assert world.db.item("m1:A-1").confidence == "MEDIUM"
    world.app.decide_review_candidate("m1:review-1", "ACCEPTED", "hiring")
    assert "m1:accepted-review-1" not in world.db.state.items
    assert world.db.item("m1:A-1").confidence == "HIGH" and world.db.item("m1:A-1").topic_id == "billing"


def test_a_missing_topic_aborts_the_decision_and_rejecting_creates_nothing(world):
    seed_topics(world)
    world.db.seed(review_candidate("m1:review-1", "Plan the offsite"))
    with pytest.raises(TopicNotFound):
        world.app.decide_review_candidate("m1:review-1", "ACCEPTED", "nope")
    assert world.db.state.candidates["m1:review-1"].is_pending
    world.app.decide_review_candidate("m1:review-1", "REJECTED", "hiring")
    assert world.db.state.candidates["m1:review-1"].status == "REJECTED"
    assert "m1:accepted-review-1" not in world.db.state.items


def test_pending_review_lists_newest_meeting_first_with_a_confident_topic_hint(world):
    seed_topics(world)
    world.db.seed(
        Meeting(id="m2", title="Later", date="2026-06-09", source_url="later.json"),
        review_candidate("m1:review-1", "Invoice export job"),
        review_candidate("m2:review-1", "Plan the offsite"),
        review_candidate("m1:review-2", "Open a backend role", status="REJECTED"),
    )
    pending = world.app.list_pending_review()
    assert [(c.id, c.suggested_topic_id) for c in pending] == [("m2:review-1", None), ("m1:review-1", "billing")]


def test_topic_proposals_are_grouped_and_only_create_a_topic_when_accepted(world):
    seed_topics(world)
    world.db.seed(
        make.topic("unc", "Uncategorized"),
        make.item("m1:P-1", topic_id="unc", theme="Uncategorized", suggested_topic="Offsite", description="Plan the offsite", embedding=OTHER),
        make.item("m1:P-2", topic_id="unc", theme="Uncategorized", suggested_topic="Offsite", description="Plan the offsite", embedding=OTHER),
        make.item("m1:P-3", topic_id="unc", theme="Uncategorized", suggested_topic="Invoices", description="Invoice export job", embedding=[0.98, 0.05, 0.0, 0.0]),
    )
    proposals = world.app.list_topic_proposals()
    assert [(p.name, len(p.items), p.suggested_existing_topic_id) for p in proposals] == [("Offsite", 2, None), ("Invoices", 1, "billing")]
    assert world.db.topic_named("Offsite") is None  # listing never creates anything

    filed = world.app.accept_topic_proposal("Offsite", " Team offsite ")
    created = world.db.topic_named("Team offsite")
    assert created is not None and {item.topic_id for item in filed} == {created.id}
    assert world.db.item("m1:P-1").suggested_topic is None and world.db.item("m1:P-1").theme == "Team offsite"

    world.app.accept_topic_proposal("Invoices", existing_topic_id="billing")
    assert world.db.item("m1:P-3").topic_id == "billing" and world.db.topic_named("Invoices") is None
    assert world.app.list_topic_proposals() == []


def test_proposal_decisions_validate_their_target(world):
    seed_topics(world)
    world.db.seed(make.topic("unc", "Uncategorized"), make.item("m1:P-1", topic_id="unc", suggested_topic="Offsite", embedding=OTHER))
    with pytest.raises(TopicProposalNotFound):
        world.app.accept_topic_proposal("Nope")
    with pytest.raises(ProposalTargetTopicNotFound):
        world.app.accept_topic_proposal("Offsite", existing_topic_id="ghost")
    with pytest.raises(InvalidTopicName):
        world.app.accept_topic_proposal("Offsite", "   ")
    world.app.accept_topic_proposal("Offsite", "Hiring")  # an existing name reuses that topic
    assert world.db.item("m1:P-1").topic_id == "hiring"

    world.db.seed(make.item("m1:P-2", topic_id="unc", suggested_topic="Later", embedding=OTHER))
    assert world.app.reject_topic_proposal("Later") == 1
    assert world.db.item("m1:P-2").suggested_topic is None and world.db.item("m1:P-2").topic_id == "unc"
    with pytest.raises(TopicProposalNotFound):
        world.app.reject_topic_proposal("Later")


# -- images ----------------------------------------------------------------------------------------------


def test_images_are_validated_before_the_topic_is_looked_up_and_served_by_id(world):
    seed_topics(world)
    with pytest.raises(UnsupportedImageType):
        world.app.add_topic_image("nope", "x.png", b"hello")
    with pytest.raises(ImageTooLarge):
        world.app.add_topic_image("nope", "x.png", b"x" * (5 * 1024 * 1024 + 1))
    with pytest.raises(TopicNotFound):
        world.app.add_topic_image("nope", "x.png", PNG)
    assert world.images.objects == {}

    topic = world.app.add_topic_image("billing", "C:\\shots\\a.png", PNG)
    [image] = topic.images
    assert (image.filename, image.content_type, image.size) == ("a.png", "image/png", len(PNG))
    content = world.app.get_topic_image("billing", image.id)
    assert (content.body, content.content_type) == (PNG, "image/png")
    assert world.app.get_topic_image("hiring", image.id) is None  # another topic's image id
    assert world.app.get_topic_image("nope", image.id) is None

    assert world.app.delete_topic_image("billing", "unknown").images == topic.images  # a missing image is a no-op
    assert world.app.delete_topic_image("billing", image.id).images == () and world.images.objects == {}


# -- whole-knowledge-base views --------------------------------------------------------------------------


def test_meetings_are_listed_newest_first_with_per_meeting_theme_groups(world):
    seed_topics(world)
    world.db.seed(Meeting(id="m0", title="Older", date="2026-01-01", source_url="old.json"), review_candidate("m1:review-1", "x"))
    meetings = world.app.list_meetings()
    assert [m.id for m in meetings] == ["m1", "m0"]
    assert [(t.id, len(t.items)) for t in meetings[0].topics] == [("m1:Billing", 1), ("m1:Hiring", 1)]
    assert [c.id for c in meetings[0].review_candidates] == ["m1:review-1"]
    assert world.app.get_most_recent_meeting().id == "m1" and world.app.get_meeting("m0").title == "Older"
    with pytest.raises(MeetingNotFound):
        world.app.get_meeting("nope")
    with pytest.raises(NoMeetingsAvailable):
        World().app.get_most_recent_meeting()


def test_search_ranks_high_confidence_first_and_returns_the_owning_topics_in_full(world):
    seed_topics(world)
    world.db.seed(
        make.item("m1:A-3", description="Invoice export job", topic_id="billing", confidence="HIGH", embedding=[0.9, 0.3, 0.0, 0.0]),
    )
    world.embedder.vectors["invoices"] = BILLING
    result = world.app.search("invoices", limit=2)
    assert [item.id for item in result.items] == ["m1:A-3", "m1:A-1"]  # HIGH beats the nearer MEDIUM item
    assert [(topic.id, len(topic.items)) for topic in result.topics] == [("billing", 2)]


def test_graph_and_follow_up_views(world):
    seed_topics(world)
    graph = world.app.build_graph(min_semantic_similarity=0.5)
    assert {node.id for node in graph.nodes} == {"m1:A-1", "m1:A-2"} and graph.edges == ()
    assert [(topic.id, topic.item_count) for topic in graph.topics] == [("billing", 1), ("hiring", 1)]

    follow_up = world.app.get_follow_up()
    assert follow_up.generated_at == world.clock.now().isoformat()
    assert {topic.topic.id: [item.id for item in topic.follow_up_items] for topic in follow_up.topics} == {
        "billing": ["m1:A-1"],  # an undated open action
        "hiring": ["m1:A-2"],  # an open question
    }


# -- ingestion -------------------------------------------------------------------------------------------


def extract(meeting_id: str = "m9", *items, title: str = "Planning", candidates=()) -> ExtractedMeeting:
    return ExtractedMeeting(
        id=meeting_id, title=title, date="2026-06-10", source_url=f"{meeting_id}.json", items=items, review_candidates=candidates
    )


def extracted_candidate(candidate_id: str, description: str = "Maybe adopt pgvector") -> ExtractedReviewCandidate:
    return ExtractedReviewCandidate(
        id=candidate_id, type="decision", description=description, reason="unclear", confidence="LOW", evidence=Evidence(quote="q")
    )


def test_first_ingest_files_items_by_name_or_proposes_a_new_topic(world):
    seed_topics(world)
    world.source.extracts["m9.json"] = [
        extract(
            "m9",
            make.extracted("m9:A-1", theme="billing", description="Invoice export job"),
            make.extracted("m9:A-2", theme="Offsite", description="Plan the offsite"),
            make.extracted("m9:A-3", theme=None, description="Plan the offsite"),
            candidates=[extracted_candidate("m9:review-1")],
        )
    ]
    summary = world.app.ingest_extracts()
    assert (summary.processed, summary.new, summary.updated, summary.unchanged, summary.changed) == (1, 1, 0, 0, True)
    uncategorized = world.db.topic_named("Uncategorized")
    assert world.db.item("m9:A-1").topic_id == "billing" and world.db.item("m9:A-1").suggested_topic is None
    offsite = world.db.item("m9:A-2")
    assert (offsite.topic_id, offsite.theme, offsite.suggested_topic) == (uncategorized.id, "Uncategorized", "Offsite")
    assert "m9:A-3" not in world.db.state.items  # a near-duplicate of A-2 in the same meeting reinforces it instead
    assert world.db.item("m9:A-2").confidence == "HIGH"
    assert world.db.state.candidates["m9:review-1"].is_pending
    assert world.db.topic_named("Offsite") is None  # ingestion never creates a topic for a proposal
    assert world.db.topic("billing").calculation is not None  # everything is recalculated after a change


def test_reingesting_an_unchanged_extract_changes_and_embeds_nothing(world):
    seed_topics(world)
    world.source.extracts["m9.json"] = [extract("m9", make.extracted("m9:A-1", theme="Billing", description="Invoice export job"))]
    world.app.ingest_extracts()
    commits, world.embedder.calls = world.db.commits, []
    summary = world.app.ingest_extracts()
    assert (summary.new, summary.updated, summary.unchanged, summary.changed) == (0, 0, 1, False)
    assert world.embedder.embedded == []
    assert world.db.commits == commits + 1  # the ingest transaction itself; no recalculation ran


def test_reingest_refreshes_the_extract_but_never_overwrites_human_decisions(world):
    seed_topics(world)
    world.source.extracts["m9.json"] = [
        extract(
            "m9",
            make.extracted("m9:A-1", theme="Offsite", description="Plan the offsite", status="Open"),
            candidates=[extracted_candidate("m9:review-1")],
        )
    ]
    world.app.ingest_extracts()
    # a person works on what was ingested
    world.app.set_item_status("m9:A-1", "Closed")
    world.app.assign_item_topic("m9:A-1", "hiring")
    world.app.add_item_tag("m9:A-1", "kept")
    world.app.add_item_note("m9:A-1", "my note")
    world.app.set_item_priority_override("m9:A-1", "MAJOR", None)
    world.app.reject_topic_proposal("Offsite")
    world.app.decide_review_candidate("m9:review-1", "REJECTED")

    world.embedder.vectors["Plan the Q3 offsite"] = OTHER
    world.source.extracts["m9.json"] = [
        extract(
            "m9",
            make.extracted("m9:A-1", theme="Offsite", description="Plan the Q3 offsite", status="Open", owner="Cy", stakeholders=("Cy",)),
            title="Planning (edited)",
            candidates=[extracted_candidate("m9:review-1", "Maybe adopt pgvector 0.8")],
        )
    ]
    world.embedder.calls = []
    summary = world.app.ingest_extracts()
    assert (summary.new, summary.updated, summary.unchanged) == (0, 1, 0)
    item = world.db.item("m9:A-1")
    assert (item.description, item.owner) == ("Plan the Q3 offsite", "Cy")  # extractor-owned: refreshed
    assert world.embedder.embedded == ["Plan the Q3 offsite"]  # and re-embedded, because the text changed
    assert (item.status, item.topic_id, item.theme, item.suggested_topic) == ("Closed", "hiring", "Hiring", None)
    assert item.tags == ("kept",) and [note.body for note in item.notes] == ["my note"]
    assert item.manual_override.priority == "MAJOR"
    candidate = world.db.state.candidates["m9:review-1"]
    assert (candidate.description, candidate.status) == ("Maybe adopt pgvector 0.8", "REJECTED")
    assert world.db.state.meetings["m9"].title == "Planning (edited)"


def test_two_extracts_of_one_meeting_merge_and_count_once(world):
    seed_topics(world)
    world.source.extracts["m9--claude.json"] = [extract("m9", make.extracted("m9:claude:A-1", theme="Billing", description="Invoice export job"))]
    world.source.extracts["m9--gpt.json"] = [
        extract(
            "m9",
            make.extracted("m9:gpt:A-7", theme="Billing", description="Export invoices as parquet"),  # same thing, reworded
            make.extracted("m9:gpt:A-8", theme="Hiring", description="Open a backend role"),
        )
    ]
    world.embedder.vectors["Export invoices as parquet"] = [0.97, 0.06, 0.0, 0.0]
    summary = world.app.ingest_extracts()
    assert (summary.processed, summary.new) == (2, 1)
    assert "m9:gpt:A-7" not in world.db.state.items and world.db.item("m9:claude:A-1").confidence == "HIGH"
    assert world.db.item("m9:gpt:A-8").topic_id == "hiring"


def test_related_items_of_one_extract_are_filed_together(world):
    seed_topics(world)
    world.source.extracts["m9.json"] = [
        extract(
            "m9",
            make.extracted("m9:A-1", theme="Mystery", description="Plan the offsite", related_ids=("A-2",)),
            make.extracted("m9:A-2", theme="Hiring", description="Open a backend role"),
        )
    ]
    world.embedder.vectors["Open a backend role"] = HIRING
    world.app.ingest_extracts()
    assert world.db.item("m9:A-1").topic_id == "hiring" and world.db.item("m9:A-1").suggested_topic is None


def test_ingestion_runs_never_overlap_and_a_failed_run_commits_nothing(world):
    seed_topics(world)
    world.source.extracts["m9.json"] = [extract("m9", make.extracted("m9:A-1", theme="Billing"))]
    assert world.app.ingest_extracts.running is False
    with world.app.ingest_extracts._lock, pytest.raises(IngestionAlreadyRunning):
        world.app.ingest_extracts()
    world.source.unreachable = True
    with pytest.raises(ExtractSourceUnavailable):
        world.app.ingest_extracts()
    assert "m9" not in world.db.state.meetings and world.app.ingest_extracts.running is False
    world.source.unreachable = False
    assert world.app.ingest_extracts().new == 1


def test_notes_and_ids_come_from_the_injected_clock_and_id_generator(world):
    seed_topics(world)
    noted = world.app.add_item_note("m1:A-1", "hello")
    assert noted.notes == (type(noted.notes[0])(id="short1", body="hello", created_at="2026-06-15T10:00:00+00:00"),)
    assert world.db.item("m1:A-1").notes == (Note("short1", "hello", "2026-06-15T10:00:00+00:00"),)
