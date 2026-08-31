"""Ports src/lib/data.ts: load, validate and normalize meeting extraction files from object storage."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from app import s3_store
from app.models import (
    Confidence,
    Evidence,
    ItemType,
    KnowledgeItem,
    Meeting,
    RawCandidate,
    RawEvidence,
    RawExtraction,
    ReviewCandidate,
    Topic,
)


def _normalize_confidence(value: str) -> Confidence:
    normalized = value.upper()
    return normalized if normalized in ("HIGH", "LOW") else "MEDIUM"


def _normalize_evidence(raw: RawEvidence) -> Evidence:
    return Evidence(speaker=raw.speaker, timestamp=raw.timestamp, quote=raw.quote, context=raw.context)


def _normalize_item(candidate: RawCandidate, item_type: ItemType, meeting_id: str) -> KnowledgeItem:
    owner = candidate.owner or candidate.proposed_by or candidate.decision_owner
    speaker = candidate.evidence.speaker
    stakeholders = list(dict.fromkeys(value for value in (owner, speaker) if value))
    return KnowledgeItem(
        id=f"{meeting_id}:{candidate.candidate_id}",
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


def _repair_json(text: str) -> dict:
    original = text.strip()
    # the source file is sometimes missing its enclosing braces
    repaired = original if original.startswith("{") else f"{{{original}}}"
    return json.loads(repaired)


def _derive_meeting_id(key: str) -> str:
    # the extraction JSON's own meeting_id is sometimes blank or duplicated across files;
    # the S3 key is always unique, so it's the source of truth for id-namespacing
    stem = Path(key).stem
    return re.sub(r"[^A-Za-z0-9_-]", "-", stem)


def _normalize_extraction(parsed: RawExtraction, meeting_id: str) -> Meeting:
    items = [
        *(_normalize_item(c, "IDEA", meeting_id) for c in parsed.ideas),
        *(_normalize_item(c, "DECISION", meeting_id) for c in parsed.decisions),
        *(_normalize_item(c, "ACTION", meeting_id) for c in parsed.actions),
        *(_normalize_item(c, "QUESTION", meeting_id) for c in parsed.questions),
    ]

    review_candidates = [
        ReviewCandidate(
            id=f"{meeting_id}:review-{index + 1}",
            type=candidate.candidate_type,
            description=candidate.description,
            reason=candidate.reason_for_review,
            confidence=_normalize_confidence(candidate.confidence),
            evidence=_normalize_evidence(candidate.evidence),
            status="PENDING",
        )
        for index, candidate in enumerate(parsed.review_candidates)
    ]

    topic_map: dict[str, list[KnowledgeItem]] = {}
    for item in items:
        topic_map.setdefault(item.theme or "Uncategorized", []).append(item)

    topics = [
        Topic(
            id=f"{meeting_id}:{name}",
            name=name,
            items=topic_items,
            stakeholders=list(dict.fromkeys(s for item in topic_items for s in item.stakeholders)),
        )
        for name, topic_items in topic_map.items()
    ]

    return Meeting(
        id=meeting_id,
        title=parsed.meeting.title,
        date=parsed.meeting.date,
        source_url=parsed.meeting.source_url,
        items=items,
        review_candidates=review_candidates,
        topics=topics,
    )


@lru_cache(maxsize=1)
def _load_all_meetings_cached() -> tuple[Meeting, ...]:
    meetings = []
    for key in s3_store.list_extract_keys():
        parsed = RawExtraction.model_validate(_repair_json(s3_store.fetch_object_text(key)))
        meetings.append(_normalize_extraction(parsed, _derive_meeting_id(key)))
    return tuple(sorted(meetings, key=lambda meeting: meeting.date, reverse=True))


def clear_cache() -> None:
    _load_all_meetings_cached.cache_clear()


def load_meetings() -> list[Meeting]:
    return list(_load_all_meetings_cached())


def get_meeting(meeting_id: str) -> Meeting | None:
    return next((meeting for meeting in load_meetings() if meeting.id == meeting_id), None)


def most_recent_meeting() -> Meeting | None:
    meetings = load_meetings()
    return meetings[0] if meetings else None


def all_items(meetings: list[Meeting]) -> list[KnowledgeItem]:
    return [item for meeting in meetings for item in meeting.items]


def all_review_candidates(meetings: list[Meeting]) -> list[ReviewCandidate]:
    return [candidate for meeting in meetings for candidate in meeting.review_candidates]


def all_topics(meetings: list[Meeting]) -> list[Topic]:
    topic_map: dict[str, list[KnowledgeItem]] = {}
    for meeting in meetings:
        for topic in meeting.topics:
            topic_map.setdefault(topic.name, []).extend(topic.items)

    return [
        Topic(
            id=f"topic:{name}",
            name=name,
            items=items,
            stakeholders=list(dict.fromkeys(s for item in items for s in item.stakeholders)),
        )
        for name, items in topic_map.items()
    ]


def related_items(item: KnowledgeItem, meetings: list[Meeting]) -> list[KnowledgeItem]:
    ids = set(item.related_ids)
    return [
        candidate
        for candidate in all_items(meetings)
        if candidate.id.split(":", 1)[1] in ids or candidate.id in ids
    ]

