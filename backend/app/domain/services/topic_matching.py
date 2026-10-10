"""Files newly ingested items under an *existing* topic. Ingestion never creates a topic: when nothing
matches, the item lands in "Uncategorized" with the extractor's theme kept as a proposal for a human to
accept, rename or redirect on the review page.

Match order: (1) exact topic name == theme, (2) the topic most of the item's related items already sit in,
(3) the topic whose centroid is semantically closest (>= ITEM_TOPIC_MATCH_SIMILARITY)."""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

import numpy as np

from app.domain.policies import ITEM_TOPIC_MATCH_SIMILARITY, UNCATEGORIZED_TOPIC
from app.domain.services.similarity import closest_topic
from app.domain.value_objects.extraction import ExtractedItem

Vector = Sequence[float] | np.ndarray


@dataclass(frozen=True)
class TopicSnapshot:
    """What matching needs to know about a topic: its name and the embeddings of the items already in it."""

    topic_id: str
    name: str
    item_embeddings: Sequence[Vector | None] = ()


# (topic id, proposed topic name). The proposal is set only when the item is unmatched.
Assignment = tuple[str, str | None]


class TopicMatcher:
    """Holds the topics in memory for one ingestion run and learns from each item it files.

    `related_topic_ids` answers, for a list of item ids, the topic ids (non-null) of those already stored;
    `ensure_uncategorized` returns the id of the Uncategorized topic, creating it if needed."""

    def __init__(
        self,
        topics: Iterable[TopicSnapshot],
        *,
        related_topic_ids: Callable[[Sequence[str]], Sequence[str]],
        ensure_uncategorized: Callable[[], str],
    ) -> None:
        self._related_topic_ids = related_topic_ids
        self._ensure_uncategorized = ensure_uncategorized
        self._uncategorized_id: str | None = None
        self._ids_by_name: dict[str, str] = {}
        self._names_by_id: dict[str, str] = {}
        self._sums: dict[str, np.ndarray] = {}
        self._counts: dict[str, int] = {}
        for topic in topics:
            self._ids_by_name[topic.name.casefold()] = topic.topic_id
            self._names_by_id[topic.topic_id] = topic.name
            if topic.name == UNCATEGORIZED_TOPIC:
                self._uncategorized_id = topic.topic_id
                continue
            vectors = [np.array(embedding) for embedding in topic.item_embeddings if embedding is not None]
            if vectors:
                self._sums[topic.topic_id] = np.sum(vectors, axis=0)
                self._counts[topic.topic_id] = len(vectors)

    def _uncategorized(self) -> str:
        if self._uncategorized_id is None:
            self._uncategorized_id = self._ensure_uncategorized()
            self._ids_by_name[UNCATEGORIZED_TOPIC.casefold()] = self._uncategorized_id
            self._names_by_id[self._uncategorized_id] = UNCATEGORIZED_TOPIC
        return self._uncategorized_id

    def _by_related_items(self, item: ExtractedItem, batch_topic_ids: Iterable[str] = ()) -> str | None:
        """Majority topic among the item's related items already stored plus `batch_topic_ids`
        (topics of related items from the same extract, which aren't stored yet)."""
        full_ids = item.full_related_ids()
        topic_ids = list(batch_topic_ids)
        if full_ids:
            topic_ids += [
                topic_id for topic_id in self._related_topic_ids(full_ids) if topic_id != self._uncategorized_id
            ]
        return Counter(topic_ids).most_common(1)[0][0] if topic_ids else None

    def resolve(self, item: ExtractedItem, vector: Vector, batch_topic_ids: Iterable[str] = ()) -> Assignment:
        theme = (item.theme or "").strip()
        if not theme or theme.casefold() == UNCATEGORIZED_TOPIC.casefold():
            return self._uncategorized(), None
        matched = self._ids_by_name.get(theme.casefold()) or self._by_related_items(item, batch_topic_ids)
        if matched is None:
            centroids = {topic_id: total / self._counts[topic_id] for topic_id, total in self._sums.items()}
            matched, _ = closest_topic(np.array(vector), centroids, ITEM_TOPIC_MATCH_SIMILARITY)
        if matched is not None:
            return matched, None
        return self._uncategorized(), theme

    def resolve_batch(self, entries: Sequence[tuple[ExtractedItem, Vector]]) -> dict[str, Assignment]:
        """Resolves every new item of an extract at once, so related items are found regardless of
        order or link direction (B -> A, A -> B, or chains): links are treated as undirected, and
        items left in "Uncategorized" adopt a related item's topic until nothing changes."""
        known_ids = {item.id for item, _ in entries}
        neighbours: dict[str, set[str]] = defaultdict(set)
        for item, _ in entries:
            for other_id in item.full_related_ids():
                if other_id in known_ids and other_id != item.id:
                    neighbours[item.id].add(other_id)
                    neighbours[other_id].add(item.id)

        resolved: dict[str, Assignment] = {}
        matched: dict[str, str] = {}  # item id -> existing (non-Uncategorized) topic it was filed under

        def note(item_id: str, topic_id: str, proposal: str | None) -> None:
            resolved[item_id] = (topic_id, proposal)
            if topic_id != self._uncategorized_id:
                matched[item_id] = topic_id

        for item, vector in entries:
            batch_topic_ids = [matched[other] for other in neighbours[item.id] if other in matched]
            note(item.id, *self.resolve(item, vector, batch_topic_ids))

        changed = True
        while changed:
            changed = False
            for item, _ in entries:
                if item.id in matched:
                    continue
                votes = Counter(matched[other] for other in neighbours[item.id] if other in matched)
                if votes:
                    note(item.id, votes.most_common(1)[0][0], None)
                    changed = True

        # fold vectors in only once each item's final topic is known
        for item, vector in entries:
            self.record(resolved[item.id][0], vector)
        return resolved

    def name_of(self, topic_id: str) -> str:
        return self._names_by_id[topic_id]

    def record(self, topic_id: str, vector: Vector) -> None:
        """Folds a newly filed item into its topic's centroid so later items in the run can match it."""
        if topic_id == self._uncategorized_id:
            return
        self._sums[topic_id] = self._sums.get(topic_id, 0) + np.array(vector)
        self._counts[topic_id] = self._counts.get(topic_id, 0) + 1
