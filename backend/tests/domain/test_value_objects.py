"""Unit tests for domain value objects: pure, no database."""
from __future__ import annotations

from datetime import date

import pytest

from app.domain.exceptions import ImageTooLarge, TooManyTags, UnsupportedImageType
from app.domain.value_objects.dates import parse_iso_date
from app.domain.value_objects.image_upload import (
    MAX_IMAGE_BYTES,
    ImageUpload,
    display_filename,
    sniff_image_type,
)
from app.domain.value_objects.item_type import normalize_item_type
from app.domain.value_objects.priority import (
    HardEscalation,
    ManualPriorityOverride,
    TopicPriorityHistoryEntry,
    TopicPriorityInfo,
    TopicPrioritySignal,
    is_escalation,
)
from app.domain.value_objects.status import (
    is_blocked_status,
    is_resolved_status,
    to_open_closed,
)
from app.domain.value_objects.tag import MAX_TAGS, normalize_tag, with_tag, without_tag

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8


def test_normalize_tag_trims_lowercases_and_collapses_whitespace():
    assert normalize_tag("  Q3   Launch ") == "q3 launch"


def test_with_tag_is_idempotent_and_normalizes():
    assert with_tag(["q3 launch"], "Q3  Launch") == ["q3 launch"]
    assert with_tag(None, "Infra") == ["infra"]
    assert with_tag(["a"], "b") == ["a", "b"]


def test_with_tag_enforces_the_limit_but_allows_re_adding_an_existing_tag():
    full = [f"t{i}" for i in range(MAX_TAGS)]
    with pytest.raises(TooManyTags) as excinfo:
        with_tag(full, "one too many")
    assert excinfo.value.args[0] == MAX_TAGS
    assert with_tag(full, "T0") == full


def test_without_tag_normalizes_and_ignores_unknown_tags():
    assert without_tag(["a", "b"], " A ") == ["b"]
    assert without_tag(["a"], "zzz") == ["a"]
    assert without_tag(None, "a") == []


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (PNG, ("image/png", "png")),
        (b"\xff\xd8\xff\xe0rest", ("image/jpeg", "jpg")),
        (b"GIF89a....", ("image/gif", "gif")),
        (b"GIF87a....", ("image/gif", "gif")),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", ("image/webp", "webp")),
        (b"<svg xmlns=...>", None),
        (b"", None),
    ],
)
def test_sniff_image_type_reads_magic_bytes(body, expected):
    assert sniff_image_type(body) == expected


def test_display_filename_strips_paths_and_unprintable_characters():
    assert display_filename("C:\\Users\\me\\shot.png") == "shot.png"
    assert display_filename("/tmp/a/b.jpg") == "b.jpg"
    assert display_filename("na\x00me\n.png") == "name.png"
    assert display_filename(None) == "image"
    assert display_filename("   ") == "image"
    assert len(display_filename("x" * 500)) == 200


def test_image_upload_validates_size_before_type():
    upload = ImageUpload.validate("../evil/shot.png", PNG)
    assert (upload.filename, upload.content_type, upload.extension, upload.size) == ("shot.png", "image/png", "png", len(PNG))
    with pytest.raises(UnsupportedImageType):
        ImageUpload.validate("notes.png", b"hello")
    with pytest.raises(ImageTooLarge) as excinfo:
        ImageUpload.validate("big.png", b"x" * (MAX_IMAGE_BYTES + 1))
    assert excinfo.value.args[0] == MAX_IMAGE_BYTES


def test_status_keywords_collapse_free_text_to_open_closed():
    assert is_resolved_status("Answered in follow-up") and is_resolved_status("DONE")
    assert not is_resolved_status("Open") and not is_resolved_status("")
    assert to_open_closed("Resolved") == "Closed" and to_open_closed("In progress") == "Open"
    assert is_blocked_status("Blocked by vendor") and not is_blocked_status("Open")


def test_parse_iso_date_accepts_only_a_strict_iso_prefix():
    assert parse_iso_date("2026-03-04") == date(2026, 3, 4)
    assert parse_iso_date(" 2026-03-04T10:00:00Z") == date(2026, 3, 4)
    assert parse_iso_date("next Tuesday") is None
    assert parse_iso_date("") is None and parse_iso_date(None) is None


def test_normalize_item_type_files_unknown_kinds_as_ideas():
    assert normalize_item_type("decision") == "DECISION"
    assert normalize_item_type("RISK") == "IDEA"


def test_is_escalation_requires_a_previous_level_and_a_higher_rank():
    assert is_escalation("MINOR", "MAJOR") and is_escalation("MAJOR", "CRITICAL")
    assert not is_escalation(None, "CRITICAL")
    assert not is_escalation("CRITICAL", "MAJOR") and not is_escalation("MAJOR", "MAJOR")


def test_priority_records_store_numbers_as_floats_and_ids_as_tuples():
    signal = TopicPrioritySignal(
        type="impact_decisions", raw_value=3, normalized_score=1, weighted_score=14, max_score=14, explanation="x",
        source_knowledge_item_ids=["a", "b"],
    )
    assert (signal.raw_value, signal.normalized_score, signal.max_score) == (3.0, 1.0, 14.0)
    assert isinstance(signal.raw_value, float) and signal.source_knowledge_item_ids == ("a", "b")
    assert TopicPrioritySignal(type="t", raw_value=True, normalized_score=0, weighted_score=0, max_score=0, explanation="").raw_value is True
    assert TopicPrioritySignal(type="t", raw_value="2026-01-02", normalized_score=0, weighted_score=0, max_score=0, explanation="").raw_value == "2026-01-02"
    assert HardEscalation(rule_id="r", reason="because", source_knowledge_item_ids=["a"]).source_knowledge_item_ids == ("a",)


def _info(**overrides) -> TopicPriorityInfo:
    signals = [
        TopicPrioritySignal(type="a", normalized_score=1, weighted_score=5, max_score=5, explanation="five", source_knowledge_item_ids=["i2"]),
        TopicPrioritySignal(type="b", normalized_score=0, weighted_score=0, max_score=5, explanation="zero", source_knowledge_item_ids=["i1"]),
        TopicPrioritySignal(type="c", normalized_score=1, weighted_score=9, max_score=9, explanation="nine", source_knowledge_item_ids=["i1"]),
    ]
    values = dict(
        calculated_priority="MAJOR", calculated_score=50, effective_priority="MAJOR", confidence="MEDIUM",
        explanation="e", calculated_at="2026-01-01T00:00:00+00:00", algorithm_version="1.0", signals=signals,
    )
    values.update(overrides)
    return TopicPriorityInfo(**values)


def test_priority_info_override_changes_only_the_effective_priority():
    info = _info()
    overridden = info.with_override(ManualPriorityOverride(priority="CRITICAL", reason="exec ask", overridden_at="now"))
    assert (overridden.calculated_priority, overridden.effective_priority) == ("MAJOR", "CRITICAL")
    assert overridden.manual_override.reason == "exec ask"
    cleared = overridden.with_override(None)
    assert cleared.effective_priority == "MAJOR" and cleared.manual_override is None
    assert info.effective_priority == "MAJOR"  # immutable: the original is untouched


def test_priority_info_reports_top_drivers_and_source_items():
    info = _info()
    assert [signal.explanation for signal in info.top_drivers()] == ["nine", "five"]
    assert [signal.explanation for signal in info.top_drivers(limit=1)] == ["nine"]
    assert info.source_item_ids() == ["i1", "i2"]


def test_history_entry_knows_whether_it_was_an_escalation():
    base = dict(id="h", topic_id="t", new_score=80, changed_at="now", algorithm_version="1.0", trigger="manual")
    assert TopicPriorityHistoryEntry(previous_priority="MAJOR", new_priority="CRITICAL", **base).is_escalation
    assert not TopicPriorityHistoryEntry(previous_priority="CRITICAL", new_priority="MAJOR", **base).is_escalation
    assert not TopicPriorityHistoryEntry(previous_priority=None, new_priority="CRITICAL", **base).is_escalation
