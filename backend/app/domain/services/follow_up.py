"""Picks what is worth raising at the next meeting: open questions, due-soon/overdue/undated actions, and
decisions something unresolved still depends on - grouped under the highest-priority topics, plus items pulled
in from other topics through related_ids."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
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
) -> list[TopicFollowUp]:
    """`recent_escalations` must be newest first. Topics are ranked by effective priority, then score."""
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

    follow_up_ids: set[str] = set()
    for item in item_by_id.values():
        if item.type == "QUESTION":
            if not item.is_resolved:
                follow_up_ids.add(item.id)
        elif item.type == "ACTION":
            if not item.is_resolved and is_action_due(item, reference_date, due_soon_days):
                follow_up_ids.add(item.id)
        elif item.type == "DECISION":
            dependents = referenced_by.get(item.id, [])
            if any(not item_by_id[dep_id].is_resolved for dep_id in dependents if dep_id in item_by_id):
                follow_up_ids.add(item.id)

    escalations_by_topic: dict[str, list[TopicPriorityHistoryEntry]] = {}
    for entry in recent_escalations:
        escalations_by_topic.setdefault(entry.topic_id, []).append(entry)

    ranked: list[tuple[Topic, list[KnowledgeItem]]] = []
    for topic in topics:
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
    return selected
