"""Topic priority: the level vocabulary and the immutable records a calculation produces."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal

TopicPriorityLevel = Literal["CRITICAL", "MAJOR", "MINOR"]
PriorityConfidence = Literal["HIGH", "MEDIUM", "LOW"]

# higher = more urgent; used to detect an escalation and to rank topics
PRIORITY_RANK: dict[str, int] = {"MINOR": 0, "MAJOR": 1, "CRITICAL": 2}


def is_escalation(previous: str | None, new: str) -> bool:
    """A priority change counts as an escalation only when a previous level existed and the rank went up."""
    return previous is not None and PRIORITY_RANK.get(new, 0) > PRIORITY_RANK.get(previous, 0)


@dataclass(frozen=True)
class ManualPriorityOverride:
    """A human decision that wins over the calculated priority and is never touched by recalculation."""

    priority: TopicPriorityLevel
    reason: str | None = None
    overridden_at: str = ""


def _number(value: float) -> float:
    return float(value)


@dataclass(frozen=True)
class TopicPrioritySignal:
    """One explainable contribution to a topic's score."""

    type: str
    normalized_score: float
    weighted_score: float
    max_score: float
    explanation: str
    raw_value: float | str | bool | None = None
    source_knowledge_item_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # numbers are always floats (counts included), so a stored/serialized signal has one shape
        object.__setattr__(self, "normalized_score", _number(self.normalized_score))
        object.__setattr__(self, "weighted_score", _number(self.weighted_score))
        object.__setattr__(self, "max_score", _number(self.max_score))
        if isinstance(self.raw_value, int) and not isinstance(self.raw_value, bool):
            object.__setattr__(self, "raw_value", float(self.raw_value))
        object.__setattr__(self, "source_knowledge_item_ids", tuple(self.source_knowledge_item_ids))


@dataclass(frozen=True)
class HardEscalation:
    """A rule that forces CRITICAL regardless of the accumulated score."""

    rule_id: str
    reason: str
    source_knowledge_item_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_knowledge_item_ids", tuple(self.source_knowledge_item_ids))


@dataclass(frozen=True)
class SemanticContribution:
    """The optional, bounded adjustment a semantic classifier made to the deterministic score."""

    provider: str
    model: str
    scores: Mapping[str, float]
    contribution: float
    disagreement: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "contribution", _number(self.contribution))


@dataclass(frozen=True)
class TopicPriorityInfo:
    """A topic's calculated priority with its explanation, plus the manual override when one is set."""

    calculated_priority: TopicPriorityLevel
    calculated_score: float
    effective_priority: TopicPriorityLevel
    confidence: PriorityConfidence
    explanation: str
    calculated_at: str
    algorithm_version: str
    signals: tuple[TopicPrioritySignal, ...] = ()
    hard_escalations: tuple[HardEscalation, ...] = ()
    semantic_contribution: SemanticContribution | None = None
    manual_override: ManualPriorityOverride | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "calculated_score", _number(self.calculated_score))
        object.__setattr__(self, "signals", tuple(self.signals))
        object.__setattr__(self, "hard_escalations", tuple(self.hard_escalations))

    def with_override(self, override: ManualPriorityOverride | None) -> TopicPriorityInfo:
        """The same calculation seen through a manual override: the override, when set, is the effective priority."""
        return replace(
            self,
            manual_override=override,
            effective_priority=override.priority if override is not None else self.calculated_priority,
        )

    def top_drivers(self, limit: int = 3) -> list[TopicPrioritySignal]:
        """The signals that contributed most, strongest first."""
        positive = (signal for signal in self.signals if signal.weighted_score > 0)
        return sorted(positive, key=lambda signal: signal.weighted_score, reverse=True)[:limit]

    def source_item_ids(self) -> list[str]:
        return sorted({item_id for signal in self.signals for item_id in signal.source_knowledge_item_ids})


@dataclass(frozen=True)
class TopicPriorityHistoryEntry:
    """Recorded each time a topic's calculated priority category changes."""

    id: str
    topic_id: str
    new_priority: TopicPriorityLevel
    new_score: float
    changed_at: str
    algorithm_version: str
    trigger: str
    previous_priority: TopicPriorityLevel | None = None
    previous_score: float | None = None
    primary_drivers: tuple[str, ...] = ()
    source_knowledge_item_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "primary_drivers", tuple(self.primary_drivers))
        object.__setattr__(self, "source_knowledge_item_ids", tuple(self.source_knowledge_item_ids))

    @property
    def is_escalation(self) -> bool:
        return is_escalation(self.previous_priority, self.new_priority)
