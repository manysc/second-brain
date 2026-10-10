"""The item-to-item graph. Nodes are all knowledge items; edges come from three sources layered by
confidence - evidence-grounded `related_ids` (certain), shared topic membership (structural), and embedding
cosine similarity above a threshold (a possible-relationship discovery layer, never an assertion). Each pair
gets at most one edge, preferring the most-confident kind available for that pair."""
from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

from app.domain.entities.knowledge_item import KnowledgeItem
from app.domain.entities.topic import Topic
from app.domain.services.similarity import cosine_similarity

EdgeKind = Literal["related", "topic", "semantic"]


@dataclass(frozen=True)
class ItemEdge:
    source: str
    target: str
    kind: EdgeKind
    # 1.0 for related/topic edges; cosine similarity (0-1) for semantic edges
    weight: float = 1.0


def related_item_target(raw_id: str, item_by_id: Mapping[str, KnowledgeItem], id_by_local_key: Mapping[str, str]) -> str | None:
    """related_ids values may be a full item id or just its local key (e.g. "D-004")."""
    if raw_id in item_by_id:
        return raw_id
    return id_by_local_key.get(raw_id)


def build_item_edges(
    items: Sequence[KnowledgeItem], topics_by_id: Mapping[str, Topic], min_semantic_similarity: float
) -> list[ItemEdge]:
    edges: list[ItemEdge] = []
    seen_pairs: set[frozenset[str]] = set()

    def add_edge(a: str, b: str, kind: EdgeKind, weight: float = 1.0) -> None:
        pair = frozenset((a, b))
        if a == b or pair in seen_pairs:
            return
        seen_pairs.add(pair)
        edges.append(ItemEdge(source=a, target=b, kind=kind, weight=weight))

    item_by_id = {item.id: item for item in items}
    id_by_local_key: dict[str, str] = {}
    for item in items:
        id_by_local_key.setdefault(item.local_key, item.id)

    for item in items:
        for raw_id in item.related_ids:
            target = related_item_target(raw_id, item_by_id, id_by_local_key)
            if target is not None:
                add_edge(item.id, target, "related")

    topic_groups: dict[str, list[str]] = {}
    for item in items:
        topic = topics_by_id.get(item.topic_id) if item.topic_id is not None else None
        if topic is None or topic.is_uncategorized:
            continue
        topic_groups.setdefault(topic.id, []).append(item.id)
    for group_ids in topic_groups.values():
        for a, b in itertools.combinations(sorted(group_ids), 2):
            add_edge(a, b, "topic")

    vectors = {item.id: np.array(item.embedding) for item in items if item.embedding is not None}
    vector_ids = list(vectors.keys())
    for i in range(len(vector_ids)):
        for j in range(i + 1, len(vector_ids)):
            a, b = vector_ids[i], vector_ids[j]
            similarity = cosine_similarity(vectors[a], vectors[b])
            if similarity >= min_semantic_similarity:
                add_edge(a, b, "semantic", weight=similarity)

    return edges


def related_items(item: KnowledgeItem, all_items: Sequence[KnowledgeItem]) -> list[KnowledgeItem]:
    """The items an item's evidence-grounded related_ids point at (matched by full id or local key)."""
    ids = set(item.related_ids)
    return [candidate for candidate in all_items if candidate.local_key in ids or candidate.id in ids]
