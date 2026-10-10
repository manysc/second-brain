"""Topic priority use cases: recalculation on demand, the manual override and the history of changes."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.application.dtos import TopicDTO
from app.application.interfaces.repositories import UnitOfWork, UnitOfWorkFactory
from app.application.interfaces.services import Clock
from app.application.services import assembler
from app.application.services.priority_recalculation import PriorityRecalculator
from app.domain.exceptions import TopicNotFound
from app.domain.value_objects.priority import TopicPriorityHistoryEntry


def recent_escalations(uow: UnitOfWork, clock: Clock, days: int) -> list[TopicPriorityHistoryEntry]:
    """Priority increases recorded in the last `days` days, newest first."""
    cutoff = (clock.now() - timedelta(days=days)).isoformat()
    return [entry for entry in uow.priority_history.list_since(cutoff) if entry.is_escalation]


@dataclass(frozen=True)
class RecalculateTopicPriority:
    uow: UnitOfWorkFactory
    recalculator: PriorityRecalculator

    def __call__(self, topic_id: str, trigger: str = "manual") -> TopicDTO:
        if not self.recalculator.recalculate_topic(topic_id, trigger):
            raise TopicNotFound(topic_id)
        with self.uow() as uow:
            topic = uow.topics.get(topic_id)
            if topic is None:
                raise TopicNotFound(topic_id)
            return assembler.load_topic_dto(uow, topic)


@dataclass(frozen=True)
class RecalculateAllPriorities:
    recalculator: PriorityRecalculator

    def __call__(self, trigger: str = "recalculate_all") -> int:
        """Returns how many topics were recalculated."""
        return self.recalculator.recalculate_all(trigger)


@dataclass(frozen=True)
class SetTopicPriorityOverride:
    uow: UnitOfWorkFactory
    clock: Clock

    def __call__(self, topic_id: str, priority: str | None, reason: str | None) -> TopicDTO:
        with self.uow() as uow:
            topic = uow.topics.get(topic_id)
            if topic is None:
                raise TopicNotFound(topic_id)
            topic.override_priority(priority, reason, self.clock.now().isoformat())  # type: ignore[arg-type]
            uow.topics.save(topic)
            uow.commit()
            return assembler.load_topic_dto(uow, topic)


@dataclass(frozen=True)
class GetPriorityHistory:
    uow: UnitOfWorkFactory

    def __call__(self, topic_id: str, *, require_topic: bool = True) -> list[TopicPriorityHistoryEntry]:
        """A topic's priority changes, newest first. With `require_topic=False` an unknown topic simply has
        no history."""
        with self.uow() as uow:
            if require_topic and uow.topics.get(topic_id) is None:
                raise TopicNotFound(topic_id)
            return uow.priority_history.list_for_topic(topic_id)


@dataclass(frozen=True)
class GetRecentEscalations:
    uow: UnitOfWorkFactory
    clock: Clock

    def __call__(self, days: int = 14) -> list[TopicPriorityHistoryEntry]:
        with self.uow() as uow:
            return recent_escalations(uow, self.clock, days)
