"""Ports scripts/verify-ingestion.mjs: sanity-checks the raw extraction file and load_meeting()."""
import json

from app.data import DATA_FILE, load_meeting

EXPECTED_COUNTS = {"ideas": 2, "decisions": 5, "actions": 10, "questions": 7, "review_candidates": 4}
EXPECTED_RELATIONS = [
    ("A-007", "I-002"),
    ("D-001", "A-002"),
    ("D-001", "Q-001"),
    ("D-004", "A-001"),
    ("D-004", "A-009"),
    ("D-004", "A-010"),
]


def _raw_data() -> dict:
    original = DATA_FILE.read_text(encoding="utf8").strip()
    repaired = original if original.startswith("{") else f"{{{original}}}"
    return json.loads(repaired)


def test_candidate_counts_match_expected():
    data = _raw_data()
    for key, count in EXPECTED_COUNTS.items():
        assert len(data[key]) == count, f"{key}: expected {count}, got {len(data[key])}"


def test_related_candidate_links_are_preserved():
    data = _raw_data()
    all_candidates = [*data["ideas"], *data["decisions"], *data["actions"], *data["questions"]]
    by_id = {candidate["candidate_id"]: candidate for candidate in all_candidates}
    for source_id, target_id in EXPECTED_RELATIONS:
        assert target_id in by_id[source_id]["related_candidate_ids"], f"{source_id} -> {target_id} missing"


def test_ambiguous_due_dates_are_not_fabricated():
    data = _raw_data()
    all_candidates = [*data["ideas"], *data["decisions"], *data["actions"], *data["questions"]]
    by_id = {candidate["candidate_id"]: candidate for candidate in all_candidates}
    assert by_id["A-009"]["due_date"] == "2026-08-25"
    assert by_id["A-010"]["due_date"] is None


def test_review_candidates_are_neither_promoted_nor_lost():
    data = _raw_data()
    assert len(data["review_candidates"]) == 4


def test_load_meeting_normalizes_the_same_counts():
    meeting = load_meeting()
    assert len(meeting.items) == sum(
        EXPECTED_COUNTS[key] for key in ("ideas", "decisions", "actions", "questions")
    )
    assert len(meeting.review_candidates) == EXPECTED_COUNTS["review_candidates"]
