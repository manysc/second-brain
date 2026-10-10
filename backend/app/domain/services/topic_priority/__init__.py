"""Deterministic, explainable topic priority (CRITICAL/MAJOR/MINOR). See scorer.py for the design notes."""
from app.domain.services.topic_priority.config import (
    PRIORITY_CONFIG,
    TOPIC_PRIORITY_ALGORITHM_VERSION,
)
from app.domain.services.topic_priority.facts import (
    ItemFact,
    PreviousPriorityState,
    TopicPriorityFacts,
    dependency_reach,
    item_fact,
    meeting_ages_days,
)
from app.domain.services.topic_priority.scorer import TopicPriorityScorer
from app.domain.services.topic_priority.semantic import (
    HYPOTHESES,
    build_semantic_context,
)

__all__ = [
    "HYPOTHESES",
    "PRIORITY_CONFIG",
    "TOPIC_PRIORITY_ALGORITHM_VERSION",
    "ItemFact",
    "PreviousPriorityState",
    "TopicPriorityFacts",
    "TopicPriorityScorer",
    "build_semantic_context",
    "dependency_reach",
    "item_fact",
    "meeting_ages_days",
]
