"""Automatic topic priority: gathers the facts, runs the pure scorer and stores the result. It writes only the
calculated side of a topic's priority, so a manual override always survives recalculation."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from app.application.interfaces.repositories import UnitOfWork, UnitOfWorkFactory
from app.application.interfaces.semantic_classifier import SemanticClassifier
from app.application.interfaces.services import Clock, IdGenerator
from app.domain.entities.knowledge_item import KnowledgeItem
from app.domain.entities.topic import Topic
from app.domain.services.topic_priority import (
    TopicPriorityFacts,
    TopicPriorityScorer,
    build_semantic_context,
    dependency_reach,
    item_fact,
    meeting_ages_days,
)

LinkIndex = tuple[Mapping[str, str | None], Mapping[str, Sequence[str]]]


def gather_facts(
    uow: UnitOfWork, topic: Topic, items: Sequence[KnowledgeItem], reference_date: date, links: LinkIndex
) -> TopicPriorityFacts:
    meeting_ids = list({item.meeting_id for item in items})
    meeting_dates = uow.meetings.dates_by_id(meeting_ids) if meeting_ids else {}
    topic_by_item_id, related_ids_by_item_id = links
    return TopicPriorityFacts(
        topic_id=topic.id,
        items=[
            item_fact(
                item_id=item.id,
                item_type=item.type,
                status_text=item.status,
                confidence=item.confidence,
                due_date=item.due_date,
                due_date_source_text=item.due_date_source_text,
                stakeholders=item.stakeholders,
                description=item.description,
                rationale=item.rationale,
                resolution=item.resolution,
                evidence_quote=item.evidence.quote,
            )
            for item in items
        ],
        distinct_meeting_ages_days=meeting_ages_days(
            (meeting_dates.get(meeting_id) for meeting_id in meeting_ids), reference_date
        ),
        decision_count=sum(1 for item in items if item.type == "DECISION"),
        stakeholder_total=len({name for item in items for name in item.stakeholders}),
        external_dependency_reach=dependency_reach(
            topic.id, [item.id for item in items], topic_by_item_id, related_ids_by_item_id
        ),
        reference_date=reference_date,
    )


@dataclass(frozen=True)
class PriorityRecalculator:
    uow: UnitOfWorkFactory
    classifier: SemanticClassifier
    clock: Clock
    ids: IdGenerator
    scorer: TopicPriorityScorer = field(default_factory=TopicPriorityScorer)

    def recalculate_in(
        self, uow: UnitOfWork, topic: Topic, items: Sequence[KnowledgeItem], trigger: str, links: LinkIndex
    ) -> None:
        """Recalculates one topic inside the caller's unit of work (the caller commits)."""
        now = self.clock.now()
        facts = gather_facts(uow, topic, items, now.date(), links)
        semantic = self.classifier.classify(build_semantic_context(topic.name, facts))
        result = self.scorer.score(facts, topic.previous_priority_state, semantic, calculated_at=now.isoformat())
        entry = topic.record_priority(result, trigger=trigger, history_id=self.ids.new_id())
        uow.topics.save(topic)
        if entry is not None:
            uow.priority_history.add(entry)

    def recalculate_topic(self, topic_id: str, trigger: str) -> bool:
        """Returns False when the topic does not exist."""
        with self.uow() as uow:
            topic = uow.topics.get(topic_id)
            if topic is None:
                return False
            self.recalculate_in(uow, topic, uow.items.list_by_topic(topic_id), trigger, uow.items.link_index())
            uow.commit()
            return True

    def recalculate_topics(self, topic_ids: Iterable[str | None], trigger: str) -> None:
        """Recomputes only the given (affected) topics - not every topic in the system."""
        for topic_id in set(topic_ids):
            if topic_id:
                self.recalculate_topic(topic_id, trigger)

    def recalculate_all(self, trigger: str) -> int:
        with self.uow() as uow:
            topics = uow.topics.list_all()
            items_by_topic: dict[str, list[KnowledgeItem]] = {topic.id: [] for topic in topics}
            for item in uow.items.list_all():
                if item.topic_id in items_by_topic:
                    items_by_topic[item.topic_id].append(item)
            links = uow.items.link_index()
            for topic in topics:
                self.recalculate_in(uow, topic, items_by_topic[topic.id], trigger, links)
            uow.commit()
            return len(topics)
