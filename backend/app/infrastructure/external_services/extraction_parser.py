"""Anti-corruption layer for meeting extracts: understands the extraction tool's JSON (single meetings,
multi-meeting bundles, flattened registers) and hands the domain clean ExtractedMeeting values.

File naming carries identity: the S3 key is the source of truth for the meeting id, and
"<meeting-key>--<variant>.json" lets several LLM extracts of the same meeting share one meeting id."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from app.domain.value_objects.confidence import Confidence
from app.domain.value_objects.evidence import Evidence
from app.domain.value_objects.extraction import (
    ExtractedItem,
    ExtractedMeeting,
    ExtractedReviewCandidate,
)
from app.domain.value_objects.item_type import ItemType

# --- Raw extraction file shape ---------------------------------------------------------------------------


class RawEvidence(BaseModel):
    speaker: str | None = None
    timestamp: str | None = None
    quote: str = ""
    context: str | None = None


class RawCandidate(BaseModel):
    candidate_id: str
    type: str
    description: str
    theme: str | None = None
    status: str = "Open"
    owner: str | None = None
    proposed_by: str | None = None
    decision_owner: str | None = None
    due_date: str | None = None
    due_date_source_text: str | None = None
    priority: str | None = None
    confidence: str = "Medium"
    rationale: str | None = None
    resolution: str | None = None
    evidence: RawEvidence
    related_candidate_ids: list[str] = Field(default_factory=list)


class RawMeetingInfo(BaseModel):
    meeting_id: str
    title: str
    date: str
    source_url: str | None = None


class RawReviewCandidate(BaseModel):
    candidate_type: str
    description: str
    reason_for_review: str
    confidence: str
    evidence: RawEvidence


class RawExtraction(BaseModel):
    # not read anywhere downstream, and not always repeated on each entry of a multi-meeting
    # bundle file - kept only for forward compatibility, never required
    schema_version: str | None = None
    meeting: RawMeetingInfo
    ideas: list[RawCandidate]
    decisions: list[RawCandidate]
    actions: list[RawCandidate]
    questions: list[RawCandidate]
    review_candidates: list[RawReviewCandidate]


# --- normalization ---------------------------------------------------------------------------------------


def _normalize_confidence(value: str) -> Confidence:
    normalized = value.upper()
    return normalized if normalized in ("HIGH", "LOW") else "MEDIUM"  # type: ignore[return-value]


def _normalize_evidence(raw: RawEvidence) -> Evidence:
    return Evidence(speaker=raw.speaker, timestamp=raw.timestamp, quote=raw.quote, context=raw.context)


def _normalize_meeting_date(value: str, meeting_id: str) -> str:
    """Meeting dates must already be strict ISO 'YYYY-MM-DD'; fail loudly instead of guessing at
    ambiguous formats (same policy as due_date parsing)."""
    candidate = value.strip()
    try:
        date.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(
            f"meeting '{meeting_id}' has a non-ISO date {value!r}; expected 'YYYY-MM-DD'"
        ) from exc
    return candidate


def _item_id_prefix(meeting_id: str, variant: str) -> str:
    # variant namespaces ids so two LLM extracts of the same meeting never collide on candidate_id
    return f"{meeting_id}:{variant}" if variant else meeting_id


def _normalize_item(candidate: RawCandidate, item_type: ItemType, meeting_id: str, variant: str) -> ExtractedItem:
    owner = candidate.owner or candidate.proposed_by or candidate.decision_owner
    speaker = candidate.evidence.speaker
    stakeholders = list(dict.fromkeys(value for value in (owner, speaker) if value))
    return ExtractedItem(
        id=f"{_item_id_prefix(meeting_id, variant)}:{candidate.candidate_id}",
        type=item_type,
        description=candidate.description,
        theme=candidate.theme,
        status=candidate.status,
        confidence=_normalize_confidence(candidate.confidence),
        owner=owner,
        stakeholders=stakeholders,
        due_date=candidate.due_date,
        due_date_source_text=candidate.due_date_source_text,
        rationale=candidate.rationale,
        resolution=candidate.resolution,
        evidence=_normalize_evidence(candidate.evidence),
        related_ids=candidate.related_candidate_ids,
        meeting_id=meeting_id,
    )


def repair_json(text: str) -> dict:
    original = text.strip()
    # the source file is sometimes missing its enclosing braces
    repaired = original if original.startswith("{") else f"{{{original}}}"
    return json.loads(repaired)


def derive_meeting_identity(key: str) -> tuple[str, str]:
    """(meeting id, variant) from the S3 key.

    The extraction JSON's own meeting_id is sometimes blank or duplicated across files; the S3 key is always
    unique, so it's the source of truth for id-namespacing. "<meeting-key>--<variant>.json" lets two different
    LLM extracts of the same meeting (e.g. "standup--gpt4.json" / "standup--claude.json") share one canonical
    meeting id. Split before sanitizing so sanitization can't accidentally manufacture a "--"."""
    stem = Path(key).stem
    meeting_part, sep, variant_part = stem.partition("--")
    meeting_id = re.sub(r"[^A-Za-z0-9_-]", "-", meeting_part)
    variant = re.sub(r"[^A-Za-z0-9_-]", "-", variant_part) if sep else ""
    return meeting_id, variant


def _normalize_extraction(parsed: RawExtraction, meeting_id: str, variant: str, key: str) -> ExtractedMeeting:
    items = [
        *(_normalize_item(c, "IDEA", meeting_id, variant) for c in parsed.ideas),
        *(_normalize_item(c, "DECISION", meeting_id, variant) for c in parsed.decisions),
        *(_normalize_item(c, "ACTION", meeting_id, variant) for c in parsed.actions),
        *(_normalize_item(c, "QUESTION", meeting_id, variant) for c in parsed.questions),
    ]
    review_candidates = [
        ExtractedReviewCandidate(
            id=f"{_item_id_prefix(meeting_id, variant)}:review-{index + 1}",
            type=candidate.candidate_type,
            description=candidate.description,
            reason=candidate.reason_for_review,
            confidence=_normalize_confidence(candidate.confidence),
            evidence=_normalize_evidence(candidate.evidence),
        )
        for index, candidate in enumerate(parsed.review_candidates)
    ]
    return ExtractedMeeting(
        id=meeting_id,
        title=parsed.meeting.title,
        date=_normalize_meeting_date(parsed.meeting.date, meeting_id),
        source_url=parsed.meeting.source_url or Path(key).name,
        items=items,
        review_candidates=review_candidates,
    )


# --- files that hold more than one meeting ---------------------------------------------------------------

_SOURCE_MEETING_PATTERN = re.compile(r"source meeting (MTG-\d{8}-\d{3}) \((\d{4}-\d{2}-\d{2}),")
_MEETING_COUNT_SUFFIX = re.compile(r"\s*\(\d+\s+meetings?\)\s*$", re.IGNORECASE)


def _embedded_source_meeting(candidate: RawCandidate) -> tuple[str, str] | None:
    match = _SOURCE_MEETING_PATTERN.search(candidate.evidence.context or "")
    return (match.group(1), match.group(2)) if match else None


def _strip_meeting_count_suffix(title: str) -> str:
    # a flattened register's own title (e.g. "DC-MS 1:1 Meeting Register (12 meetings)") describes
    # the whole file, not any individual meeting split out of it - drop the aggregate count
    return _MEETING_COUNT_SUFFIX.sub("", title).strip()


def _split_by_embedded_source_meeting(parsed: RawExtraction) -> list[RawExtraction] | None:
    """Some single-meeting-shaped files are actually a flattened export of several real meetings,
    recoverable only from a "source meeting MTG-... (date, ...)" annotation the extraction tool
    writes into each candidate's evidence.context (seen so far only in register exports that
    merge everything into one meeting instead of nesting per-meeting entries like
    `_find_bundle_entries` handles). Returns None when no candidate carries the annotation, i.e.
    this is a genuine single meeting."""
    field_lists = {
        "ideas": parsed.ideas,
        "decisions": parsed.decisions,
        "actions": parsed.actions,
        "questions": parsed.questions,
    }
    tagged = {
        field: [(candidate, _embedded_source_meeting(candidate)) for candidate in candidates]
        for field, candidates in field_lists.items()
    }
    if not any(source for pairs in tagged.values() for _, source in pairs):
        return None
    untagged = sum(1 for pairs in tagged.values() for _, source in pairs if source is None)
    if untagged:
        raise ValueError(
            f"{untagged} candidate(s) lack the 'source meeting' annotation needed to split this "
            "flattened register file by meeting"
        )

    groups: dict[tuple[str, str], dict[str, list[RawCandidate]]] = {}
    for field, pairs in tagged.items():
        for candidate, source in pairs:
            groups.setdefault(source, {name: [] for name in field_lists})[field].append(candidate)  # type: ignore[arg-type]

    return [
        RawExtraction(
            schema_version=parsed.schema_version,
            meeting=RawMeetingInfo(
                meeting_id=source_id,
                title=_strip_meeting_count_suffix(parsed.meeting.title),
                date=source_date,
                source_url=parsed.meeting.source_url,
            ),
            review_candidates=[],
            **bucket,
        )
        for (source_id, source_date), bucket in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0]))
    ]


def _find_bundle_entries(raw: dict) -> list[dict] | None:
    # the extraction tool isn't stable about what it calls a multi-meeting bundle's list of
    # per-meeting entries ("extractions", "meetings", ... seen so far), so find it structurally:
    # the one top-level list whose items are each shaped like a single-meeting extraction (they
    # carry a "meeting" key). This also correctly skips look-alike lists such as a "coverage"
    # summary array, whose entries are flat (meeting_id/date/counts) and lack a "meeting" key.
    for value in raw.values():
        if isinstance(value, list) and value and all(isinstance(item, dict) and "meeting" in item for item in value):
            return value
    return None


# --- entry points ----------------------------------------------------------------------------------------


def parse_single_extract(key: str, text: str) -> ExtractedMeeting:
    """Parses a file that holds exactly one meeting."""
    parsed = RawExtraction.model_validate(repair_json(text))
    meeting_id, variant = derive_meeting_identity(key)
    return _normalize_extraction(parsed, meeting_id, variant, key)


def parse_extract(key: str, text: str) -> list[ExtractedMeeting]:
    """Parses one extract file, which may be a single meeting, a "bundle" covering several meetings (whose
    per-meeting entries live under some top-level list, see `_find_bundle_entries`) or a flattened register.
    Each embedded meeting gets the id "<meeting-key>-<n>" so they never collide with each other or with the
    plain single-meeting id the same key would otherwise produce. Raises ValueError for anything else."""
    raw = repair_json(text)
    meeting_id, variant = derive_meeting_identity(key)
    try:
        parsed = RawExtraction.model_validate(raw)
    except ValidationError:
        pass
    else:
        split = _split_by_embedded_source_meeting(parsed)
        if split is None:
            return [_normalize_extraction(parsed, meeting_id, variant, key)]
        meetings = [
            _normalize_extraction(sub, f"{meeting_id}-{index + 1}", variant, key) for index, sub in enumerate(split)
        ]
        if parsed.review_candidates:
            review_only = parsed.model_copy(
                update={
                    "ideas": [],
                    "decisions": [],
                    "actions": [],
                    "questions": [],
                    "meeting": parsed.meeting.model_copy(
                        update={"title": _strip_meeting_count_suffix(parsed.meeting.title)}
                    ),
                }
            )
            meetings.append(_normalize_extraction(review_only, f"{meeting_id}-review", variant, key))
        return meetings

    bundle_entries = _find_bundle_entries(raw)
    if bundle_entries is None:
        raise ValueError(f"'{key}' is not a recognized single-meeting or bundle extraction file")
    return [
        _normalize_extraction(RawExtraction.model_validate(entry), f"{meeting_id}-{index + 1}", variant, key)
        for index, entry in enumerate(bundle_entries)
    ]
