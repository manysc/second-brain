"""The plain facts the scorer works from. Gathering them (items, meeting dates, cross-topic links) is the
caller's job, so scoring stays pure and unit-testable."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from app.domain.value_objects.dates import parse_iso_date
from app.domain.value_objects.priority import TopicPriorityLevel


@dataclass
class ItemFact:
    id: str
    type: str
    status_text: str
    confidence: str
    due_date: date | None
    has_ambiguous_due_date: bool
    stakeholder_count: int
    heuristic_text: str


@dataclass
class TopicPriorityFacts:
    topic_id: str
    items: list[ItemFact] = field(default_factory=list)
    distinct_meeting_ages_days: list[int] = field(default_factory=list)
    decision_count: int = 0
    stakeholder_total: int = 0
    external_dependency_reach: int = 0
    reference_date: date = field(default_factory=lambda: datetime.now(timezone.utc).date())


@dataclass
class PreviousPriorityState:
    priority: TopicPriorityLevel
    score: float


def item_fact(
    *,
    item_id: str,
    item_type: str,
    status_text: str | None,
    confidence: str,
    due_date: str | None,
    due_date_source_text: str | None,
    stakeholders: Sequence[str] | None,
    description: str | None,
    rationale: str | None,
    resolution: str | None,
    evidence_quote: str | None,
) -> ItemFact:
    """An unparseable due date with source text is "ambiguous": never treated as overdue, never scored."""
    due = parse_iso_date(due_date)
    return ItemFact(
        id=item_id,
        type=item_type,
        status_text=status_text or "",
        confidence=confidence,
        due_date=due,
        has_ambiguous_due_date=due is None and bool(due_date_source_text),
        stakeholder_count=len(stakeholders or []),
        heuristic_text=" ".join(part for part in (description, rationale, resolution, evidence_quote) if part),
    )


def meeting_ages_days(meeting_dates: Iterable[str | None], reference_date: date) -> list[int]:
    """Age in days of each meeting with a real ISO date; meetings with unknown dates are left out."""
    ages: list[int] = []
    for raw in meeting_dates:
        parsed = parse_iso_date(raw)
        if parsed is not None:
            ages.append((reference_date - parsed).days)
    return ages


def dependency_reach(
    topic_id: str,
    item_ids: Sequence[str],
    topic_by_item_id: Mapping[str, str | None],
    related_ids_by_item_id: Mapping[str, Sequence[str]],
) -> int:
    """Distinct OTHER topics reached via the untyped related_ids link, in either direction.
    Called "dependency reach / connectivity" deliberately, not "importance". The two mappings cover
    every item in the knowledge base."""
    own_ids = set(item_ids)
    reached: set[str] = set()
    for item_id in item_ids:
        for related_id in related_ids_by_item_id.get(item_id, []):
            other_topic = topic_by_item_id.get(related_id)
            if other_topic and other_topic != topic_id:
                reached.add(other_topic)
    for other_id, other_topic in topic_by_item_id.items():
        if other_topic and other_topic != topic_id:
            if any(related_id in own_ids for related_id in related_ids_by_item_id.get(other_id, [])):
                reached.add(other_topic)
    return len(reached)
