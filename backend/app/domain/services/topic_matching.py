"""Files newly ingested items under an *existing* topic. Ingestion never creates a topic: when nothing
matches, the item lands in "Uncategorized" with the extractor's theme kept as a proposal for a human to
accept, rename or redirect on the review page.

Match order: (1) exact topic name == theme, (2) the topic most of the item's related items already sit in,
(3) the hybrid ranker's top topic when it is at least a MEDIUM-confidence match (topic_ranking.py).
Steps 2 and 3 also run without a theme: the extractor sets one only on ideas, so decisions, actions and
questions would otherwise never be matched. Only a named or linked topic spreads along an extract's links; a
ranker match does not (re-ingesting October's items, guesses passed on that way matched a human 28% of the time)."""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

import numpy as np

from app.domain.policies import UNCATEGORIZED_TOPIC
from app.domain.services.topic_ranking import TopicRanker, confident_topic_id
from app.domain.value_objects.extraction import ExtractedItem

Vector = Sequence[float] | np.ndarray


@dataclass(frozen=True)
class TopicSnapshot:
    """What name matching needs to know about a topic; the ranker holds what its items mean."""

    topic_id: str
    name: str


# (topic id, proposed topic name). The proposal is set only when the item is unmatched.
Assignment = tuple[str, str | None]


class TopicMatcher:
    """Holds the topics in memory while one extract is filed.

    `ranker` ranks the existing topics (built from their items, never from Uncategorized's);
    `related_topic_ids` answers, for a list of item ids, the topic ids (non-null) of those already stored;
    `ensure_uncategorized` returns the id of the Uncategorized topic, creating it if needed."""

    def __init__(
        self,
        topics: Iterable[TopicSnapshot],
        *,
        ranker: TopicRanker,
        related_topic_ids: Callable[[Sequence[str]], Sequence[str]],
        ensure_uncategorized: Callable[[], str],
    ) -> None:
        self._ranker = ranker
        self._related_topic_ids = related_topic_ids
        self._ensure_uncategorized = ensure_uncategorized
        self._uncategorized_id: str | None = None
        self._ids_by_name: dict[str, str] = {}
        self._names_by_id: dict[str, str] = {}
        for topic in topics:
            self._ids_by_name[topic.name.casefold()] = topic.topic_id
            self._names_by_id[topic.topic_id] = topic.name
            if topic.name == UNCATEGORIZED_TOPIC:
                self._uncategorized_id = topic.topic_id

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
        return self._resolve(item, vector, batch_topic_ids)[0]

    def _resolve(self, item: ExtractedItem, vector: Vector, batch_topic_ids: Iterable[str]) -> tuple[Assignment, bool]:
        """The assignment, and whether its topic may spread to the item's linked items: a named or linked topic
        may, a ranker match may not (links between items of one extract are too loose to pass a guess on)."""
        theme = (item.theme or "").strip()
        if theme.casefold() == UNCATEGORIZED_TOPIC.casefold():
            theme = ""
        named_or_linked = (self._ids_by_name.get(theme.casefold()) if theme else None) or self._by_related_items(
            item, batch_topic_ids
        )
        if named_or_linked is not None:
            return (named_or_linked, None), True
        ranked = confident_topic_id(self._ranker.rank(vector, item.description, top_n=1))
        if ranked is not None:
            return (ranked, None), False
        return (self._uncategorized(), theme or None), False

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
        spreading: dict[str, str] = {}  # item id -> named or linked topic it passes on to its linked items

        def note(item_id: str, assignment: Assignment, spreads: bool) -> None:
            resolved[item_id] = assignment
            if spreads:
                spreading[item_id] = assignment[0]

        for item, vector in entries:
            batch_topic_ids = [spreading[other] for other in neighbours[item.id] if other in spreading]
            note(item.id, *self._resolve(item, vector, batch_topic_ids))

        changed = True
        while changed:
            changed = False
            for item, _ in entries:
                if resolved[item.id][0] != self._uncategorized_id:
                    continue
                votes = Counter(spreading[other] for other in neighbours[item.id] if other in spreading)
                if votes:
                    note(item.id, (votes.most_common(1)[0][0], None), True)
                    changed = True
        return resolved

    def name_of(self, topic_id: str) -> str:
        return self._names_by_id[topic_id]
