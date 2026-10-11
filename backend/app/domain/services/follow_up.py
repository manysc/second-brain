"""Picks what is worth raising at the next meeting: open questions, due-soon/overdue/undated actions, and
decisions something unresolved still depends on - grouped under the highest-priority topics, plus items pulled
in from other topics through related_ids. Items nothing has happened to for a while can be left out, and the
whole selection can be narrowed to some people, meetings or topics."""
from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from app.domain.entities.knowledge_item import KnowledgeItem
from app.domain.entities.topic import Topic
from app.domain.value_objects.dates import parse_iso_date
from app.domain.value_objects.priority import PRIORITY_RANK, TopicPriorityHistoryEntry

MAX_RELATED_PER_TOPIC = 5


@dataclass(frozen=True)
class RelatedFollowUp:
    item: KnowledgeItem
    topic_id: str
    topic_name: str
    reason: str


@dataclass(frozen=True)
class TopicFollowUp:
    topic: Topic
    follow_up_items: tuple[KnowledgeItem, ...]
    escalated_recently: bool
    escalation_drivers: tuple[str, ...]
    related_from_other_topics: tuple[RelatedFollowUp, ...]


@dataclass(frozen=True)
class FollowUpSelection:
    """`hidden_stale_count` is how many items the age cut-off left out, and `total_topics` how many topics had
    something to raise before `limit` cut the list - both inside the scope that was asked for."""

    topics: tuple[TopicFollowUp, ...]
    hidden_stale_count: int
    total_topics: int


def _name_key(name: str) -> str:
    return name.strip().casefold()


@dataclass(frozen=True)
class FollowUpScope:
    """Narrows a selection to some people, meetings or topics. An empty set does not restrict; within a set any
    match counts, and every non-empty set has to match. Build it with `of`, which normalizes what a person typed."""

    stakeholders: frozenset[str] = frozenset()
    meeting_ids: frozenset[str] = frozenset()
    topic_ids: frozenset[str] = frozenset()

    @classmethod
    def of(
        cls, stakeholders: Iterable[str] = (), meeting_ids: Iterable[str] = (), topic_ids: Iterable[str] = ()
    ) -> FollowUpScope:
        """Names match whole, ignoring case and surrounding spaces; blank values are dropped."""
        return cls(
            stakeholders=frozenset(_name_key(name) for name in stakeholders if name.strip()),
            meeting_ids=frozenset(value.strip() for value in meeting_ids if value.strip()),
            topic_ids=frozenset(value.strip() for value in topic_ids if value.strip()),
        )

    def covers_item(self, item: KnowledgeItem) -> bool:
        if self.meeting_ids and item.meeting_id not in self.meeting_ids:
            return False
        if self.stakeholders:
            names = {_name_key(name) for name in (item.owner, *item.stakeholders) if name}
            if not names & self.stakeholders:
                return False
        return True

    def covers_topic(self, topic_id: str) -> bool:
        return not self.topic_ids or topic_id in self.topic_ids


def last_activity(item: KnowledgeItem, meeting_date: date | None) -> date | None:
    """Items carry no date of their own, so this is the latest of: the meeting it came from, its newest note, a
    manual priority override and, for an action, its due date. Items added by hand all share one synthetic
    meeting, whose date says nothing about any of them, so it is ignored for those."""
    stamps = [None if item.is_manual else meeting_date]
    stamps.extend(parse_iso_date(note.created_at) for note in item.notes)
    if item.manual_override is not None:
        stamps.append(parse_iso_date(item.manual_override.overridden_at))
    if item.type == "ACTION":
        stamps.append(parse_iso_date(item.due_date))
    known = [stamp for stamp in stamps if stamp is not None]
    return max(known) if known else None


def is_stale(item: KnowledgeItem, meeting_date: date | None, reference_date: date, max_age_days: int) -> bool:
    """An item with no known date is never stale: there is nothing to judge its age by."""
    latest = last_activity(item, meeting_date)
    return latest is not None and latest < reference_date - timedelta(days=max_age_days)


def resolve_related_item_id(raw_id: str, item_by_id: Mapping[str, KnowledgeItem], suffix_to_id: Mapping[str, str]) -> str | None:
    """related_ids values may be a bare suffix (e.g. "D-004") or a full "meeting:id"."""
    if raw_id in item_by_id:
        return raw_id
    return suffix_to_id.get(raw_id)


def is_action_due(item: KnowledgeItem, reference_date: date, due_soon_days: int) -> bool:
    """A missing or unparseable due date is itself a follow-up signal (an ambiguous commitment)."""
    due = parse_iso_date(item.due_date)
    if due is None:
        return True
    return due <= reference_date + timedelta(days=due_soon_days)


def follow_up_sort_key(item: KnowledgeItem) -> tuple[int, date, str]:
    """Questions first, then actions (overdue/undated first via ascending due date), then decisions."""
    type_rank = {"QUESTION": 0, "ACTION": 1, "DECISION": 2}.get(item.type, 3)
    return (type_rank, parse_iso_date(item.due_date) or date.min, item.id)


def select_follow_ups(
    topics: Sequence[Topic],
    items_by_topic: Mapping[str, Sequence[KnowledgeItem]],
    recent_escalations: Sequence[TopicPriorityHistoryEntry],
    *,
    reference_date: date,
    limit: int,
    due_soon_days: int,
    meeting_dates: Mapping[str, date] | None = None,
    max_age_days: int | None = None,
    scope: FollowUpScope | None = None,
) -> FollowUpSelection:
    """`recent_escalations` must be newest first. Topics are ranked by effective priority, then score.

    With `max_age_days`, items that are stale against `meeting_dates` (meeting id -> date) are left out and
    counted. `scope` keeps only the items it covers and ranks only the topics it covers; items listed as related
    from other topics may still come from outside those topics."""
    meeting_dates = meeting_dates or {}
    scope = scope or FollowUpScope()
    item_by_id: dict[str, KnowledgeItem] = {}
    topic_id_by_item_id: dict[str, str] = {}
    topic_name_by_id: dict[str, str] = {}
    for topic in topics:
        topic_name_by_id[topic.id] = topic.name
        for item in items_by_topic.get(topic.id, ()):
            item_by_id[item.id] = item
            topic_id_by_item_id[item.id] = topic.id
    suffix_to_id: dict[str, str] = {}
    for item_id in item_by_id:
        suffix_to_id.setdefault(item_id.split(":", 1)[-1], item_id)

    # reverse related_ids map: item id -> ids of items that list it in their own related_ids
    referenced_by: dict[str, list[str]] = {}
    for item in item_by_id.values():
        for raw_id in item.related_ids:
            target_id = resolve_related_item_id(raw_id, item_by_id, suffix_to_id)
            if target_id is not None:
                referenced_by.setdefault(target_id, []).append(item.id)

    def qualifying(ignored: Collection[str]) -> set[str]:
        """Ignored items are not raised themselves and do not keep a decision in. A decision's own age is never
        the question: something live depending on it is what makes it worth raising."""
        ids: set[str] = set()
        for item in item_by_id.values():
            if item.type == "QUESTION":
                if not item.is_resolved and item.id not in ignored:
                    ids.add(item.id)
            elif item.type == "ACTION":
                if not item.is_resolved and item.id not in ignored and is_action_due(item, reference_date, due_soon_days):
                    ids.add(item.id)
            elif item.type == "DECISION":
                dependents = referenced_by.get(item.id, [])
                if any(dep_id not in ignored and not item_by_id[dep_id].is_resolved for dep_id in dependents):
                    ids.add(item.id)
        return ids

    stale_ids: set[str] = set()
    if max_age_days is not None:
        stale_ids = {
            item.id
            for item in item_by_id.values()
            if is_stale(item, meeting_dates.get(item.meeting_id), reference_date, max_age_days)
        }
    in_scope_ids = {item.id for item in item_by_id.values() if scope.covers_item(item)}
    fresh_ids = qualifying(stale_ids)
    follow_up_ids = fresh_ids & in_scope_ids
    hidden_stale_count = 0
    if stale_ids:
        hidden_stale_count = sum(
            1
            for item_id in (qualifying(()) - fresh_ids) & in_scope_ids
            if scope.covers_topic(topic_id_by_item_id[item_id])
        )

    escalations_by_topic: dict[str, list[TopicPriorityHistoryEntry]] = {}
    for entry in recent_escalations:
        escalations_by_topic.setdefault(entry.topic_id, []).append(entry)

    ranked: list[tuple[Topic, list[KnowledgeItem]]] = []
    for topic in topics:
        if not scope.covers_topic(topic.id):
            continue
        follow_up_items = sorted(
            (item for item in items_by_topic.get(topic.id, ()) if item.id in follow_up_ids), key=follow_up_sort_key
        )
        if follow_up_items:
            ranked.append((topic, follow_up_items))

    def rank_key(pair: tuple[Topic, list[KnowledgeItem]]) -> tuple[int, float]:
        priority = pair[0].priority
        if priority is None:
            return (-1, 0.0)
        return (PRIORITY_RANK.get(priority.effective_priority, -1), priority.calculated_score)

    ranked.sort(key=rank_key, reverse=True)

    selected: list[TopicFollowUp] = []
    for topic, follow_up_items in ranked[:limit]:
        topic_items = items_by_topic.get(topic.id, ())
        topic_item_ids = {item.id for item in topic_items}
        candidates: list[tuple[str, str]] = []
        for item in topic_items:
            for raw_id in item.related_ids:
                target_id = resolve_related_item_id(raw_id, item_by_id, suffix_to_id)
                if target_id is not None:
                    candidates.append((target_id, f"Related to {item.id} in this topic"))
            for referencing_id in referenced_by.get(item.id, []):
                candidates.append((referencing_id, f"References {item.id} in this topic"))

        related: list[RelatedFollowUp] = []
        seen_related_ids: set[str] = set()
        for other_id, reason in candidates:
            if other_id in topic_item_ids or other_id in seen_related_ids or other_id not in follow_up_ids:
                continue
            other_topic_id = topic_id_by_item_id.get(other_id)
            if other_topic_id is None or other_topic_id == topic.id:
                continue
            seen_related_ids.add(other_id)
            related.append(
                RelatedFollowUp(
                    item=item_by_id[other_id],
                    topic_id=other_topic_id,
                    topic_name=topic_name_by_id.get(other_topic_id, ""),
                    reason=reason,
                )
            )
            if len(related) >= MAX_RELATED_PER_TOPIC:
                break

        topic_escalations = escalations_by_topic.get(topic.id, [])
        selected.append(
            TopicFollowUp(
                topic=topic,
                follow_up_items=tuple(follow_up_items),
                escalated_recently=bool(topic_escalations),
                escalation_drivers=topic_escalations[0].primary_drivers if topic_escalations else (),
                related_from_other_topics=tuple(related),
            )
        )
    return FollowUpSelection(topics=tuple(selected), hidden_stale_count=hidden_stale_count, total_topics=len(ranked))
