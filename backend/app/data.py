"""Ports src/lib/data.ts: load, validate and normalize the meeting extraction file."""
from __future__ import annotations

import json
from pathlib import Path

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

DATA_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "meeting-extract.json"


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


def load_meeting() -> Meeting:
    original = DATA_FILE.read_text(encoding="utf8").strip()
    # the source file is sometimes missing its enclosing braces
    repaired = original if original.startswith("{") else f"{{{original}}}"
    parsed = RawExtraction.model_validate(json.loads(repaired))
    meeting_id = parsed.meeting.meeting_id

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


def related_items(item: KnowledgeItem, meeting: Meeting) -> list[KnowledgeItem]:
    ids = set(item.related_ids)
    return [
        candidate
        for candidate in meeting.items
        if candidate.id.split(":", 1)[1] in ids or candidate.id in ids
    ]
