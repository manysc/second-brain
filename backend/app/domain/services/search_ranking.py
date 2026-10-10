from __future__ import annotations

from collections.abc import Sequence

from app.domain.entities.knowledge_item import KnowledgeItem
from app.domain.value_objects.confidence import CONFIDENCE_RANK


def rank_search_hits(hits: Sequence[tuple[KnowledgeItem, float]]) -> list[KnowledgeItem]:
    """Orders the nearest items by confidence (HIGH first), using semantic distance as the tiebreak."""
    ranked = sorted(hits, key=lambda hit: (CONFIDENCE_RANK.get(hit[0].confidence, 99), hit[1]))
    return [item for item, _ in ranked]
