"""Builders for domain entities used across the domain and application unit tests."""
from __future__ import annotations

from app.domain.entities.knowledge_item import KnowledgeItem
from app.domain.entities.review_candidate import ReviewCandidate
from app.domain.entities.topic import Topic
from app.domain.value_objects.evidence import Evidence
from app.domain.value_objects.extraction import ExtractedItem
from app.domain.value_objects.priority import TopicPriorityInfo, TopicPrioritySignal


def item(item_id: str = "m1:A-1", **overrides) -> KnowledgeItem:
    values = {
        "id": item_id,
        "meeting_id": item_id.split(":", 1)[0],
        "type": "ACTION",
        "description": "Ship the beta",
        "status": "Open",
        "confidence": "MEDIUM",
        "evidence": Evidence(speaker="Ana", timestamp="00:01", quote="we ship", context="planning"),
        "topic_id": "t1",
        "theme": "Launch",
        "owner": "Ana",
        "stakeholders": ("Ana", "Ben"),
    }
    values.update(overrides)
    return KnowledgeItem(**values)


def topic(topic_id: str = "t1", name: str = "Launch", **overrides) -> Topic:
    return Topic(id=topic_id, name=name, **overrides)


def candidate(candidate_id: str = "m1:review-1", **overrides) -> ReviewCandidate:
    values = {
        "id": candidate_id,
        "meeting_id": candidate_id.split(":", 1)[0],
        "type": "decision",
        "description": "Adopt pgvector",
        "reason": "Explicit agreement",
        "confidence": "MEDIUM",
        "evidence": Evidence(speaker="Ben", quote="we agree"),
    }
    values.update(overrides)
    return ReviewCandidate(**values)


def extracted(item_id: str = "m1:A-1", **overrides) -> ExtractedItem:
    values = {
        "id": item_id,
        "meeting_id": item_id.split(":", 1)[0],
        "type": "ACTION",
        "description": "Ship the beta",
        "status": "Open",
        "confidence": "MEDIUM",
        "evidence": Evidence(speaker="Ana", timestamp="00:01", quote="we ship", context="planning"),
        "theme": "Launch",
        "owner": "Ana",
        "stakeholders": ("Ana", "Ben"),
    }
    values.update(overrides)
    return ExtractedItem(**values)


def calculation(priority: str = "MAJOR", score: float = 50.0, **overrides) -> TopicPriorityInfo:
    values = {
        "calculated_priority": priority,
        "calculated_score": score,
        "effective_priority": priority,
        "confidence": "MEDIUM",
        "explanation": f"{priority} ({score}/100)",
        "calculated_at": "2026-06-15T00:00:00+00:00",
        "algorithm_version": "1.0",
        "signals": (
            TopicPrioritySignal(type="a", normalized_score=1, weighted_score=9, max_score=9, explanation="nine", source_knowledge_item_ids=["i2"]),
            TopicPrioritySignal(type="b", normalized_score=1, weighted_score=5, max_score=5, explanation="five", source_knowledge_item_ids=["i1"]),
        ),
    }
    values.update(overrides)
    return TopicPriorityInfo(**values)
