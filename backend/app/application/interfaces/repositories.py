"""Persistence ports. Implementations map between stored rows and domain entities, so nothing above this line
ever sees a database type. All methods of one unit of work share a single transaction: a query sees what earlier
calls in the same unit of work added or changed."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from app.domain.entities.knowledge_item import Embedding, KnowledgeItem
from app.domain.entities.meeting import Meeting
from app.domain.entities.review_candidate import ReviewCandidate
from app.domain.entities.topic import Topic
from app.domain.services.topic_ranking import TopicProfile
from app.domain.value_objects.priority import TopicPriorityHistoryEntry


class MeetingRepository(Protocol):
    def get(self, meeting_id: str) -> Meeting | None: ...

    def list_all(self) -> list[Meeting]: ...

    def dates_by_id(self, meeting_ids: Sequence[str]) -> dict[str, str]: ...

    def add(self, meeting: Meeting) -> None: ...

    def save(self, meeting: Meeting) -> None: ...


class KnowledgeItemRepository(Protocol):
    def get(self, item_id: str) -> KnowledgeItem | None: ...

    def list_all(self) -> list[KnowledgeItem]: ...

    def list_by_ids(self, item_ids: Sequence[str], *, with_embeddings: bool = True) -> list[KnowledgeItem]:
        """`with_embeddings=False` skips loading the vectors (they are large); saving such an item leaves its
        stored embedding untouched unless the item was re-embedded."""
        ...

    def list_by_topic(self, topic_id: str) -> list[KnowledgeItem]: ...

    def list_by_topics(self, topic_ids: Sequence[str]) -> list[KnowledgeItem]: ...

    def list_with_proposal(self, suggested_topic: str | None = None) -> list[KnowledgeItem]:
        """Items still waiting for a decision on a proposed topic name: every such item ordered by id, or only
        the ones proposed under `suggested_topic`."""
        ...

    def count_by_topic(self, topic_id: str) -> int: ...

    def topic_ids_of(self, item_ids: Sequence[str]) -> list[str]:
        """The topic id of each of these items that has one."""
        ...

    def link_index(self) -> tuple[dict[str, str | None], dict[str, tuple[str, ...]]]:
        """For every item: its topic id, and its related_ids. Cheap (no item bodies or vectors)."""
        ...

    def find_duplicate(
        self, embedding: Embedding, *, max_distance: float, meeting_id: str | None = None
    ) -> KnowledgeItem | None:
        """The nearest embedded item (within one meeting when given) if its cosine distance is below
        `max_distance`. It is returned without its vector loaded."""
        ...

    def nearest(
        self, embedding: Embedding, limit: int, *, exclude_ids: Sequence[str] = ()
    ) -> list[tuple[KnowledgeItem, float]]:
        """The `limit` items closest to `embedding` by cosine distance, nearest first, with their distances."""
        ...

    def add(self, item: KnowledgeItem) -> None: ...

    def save(self, item: KnowledgeItem) -> None: ...

    def delete(self, item: KnowledgeItem) -> None: ...


class TopicRepository(Protocol):
    def get(self, topic_id: str) -> Topic | None: ...

    def get_by_name(self, name: str) -> Topic | None: ...

    def list_all(self) -> list[Topic]: ...

    def list_by_ids(self, topic_ids: Sequence[str]) -> list[Topic]: ...

    def add(self, topic: Topic) -> None:
        """Raises TopicNameConflict when the name is already taken."""
        ...

    def save(self, topic: Topic) -> None:
        """Raises TopicNameConflict when a rename collides with another topic."""
        ...

    def delete(self, topic: Topic) -> None: ...

    def merge(self, source: Topic, target: Topic) -> None:
        """Moves the source topic's items, notes and images to the target, then deletes the source."""
        ...

    def ranking_version(self) -> str:
        """An opaque token that changes whenever anything ranking_profiles() reads changes - including writes
        made by another process."""
        ...

    def ranking_profiles(self) -> list[TopicProfile]:
        """Every topic except Uncategorized, with the embeddings and descriptions of its items."""
        ...


class ReviewCandidateRepository(Protocol):
    def get(self, candidate_id: str) -> ReviewCandidate | None: ...

    def list_all(self) -> list[ReviewCandidate]: ...

    def list_pending(self) -> list[ReviewCandidate]:
        """Candidates awaiting a decision, newest meeting first."""
        ...

    def list_by_ids(self, candidate_ids: Sequence[str]) -> list[ReviewCandidate]: ...

    def add(self, candidate: ReviewCandidate) -> None: ...

    def save(self, candidate: ReviewCandidate) -> None: ...


class PriorityHistoryRepository(Protocol):
    def add(self, entry: TopicPriorityHistoryEntry) -> None: ...

    def list_for_topic(self, topic_id: str) -> list[TopicPriorityHistoryEntry]:
        """Newest first."""
        ...

    def list_since(self, cutoff_iso: str) -> list[TopicPriorityHistoryEntry]:
        """Entries changed at or after `cutoff_iso`, newest first."""
        ...


class UnitOfWork(Protocol):
    """One business transaction. Nothing is persisted until commit(); leaving the block without committing
    discards the changes."""

    meetings: MeetingRepository
    items: KnowledgeItemRepository
    topics: TopicRepository
    review_candidates: ReviewCandidateRepository
    priority_history: PriorityHistoryRepository

    def __enter__(self) -> UnitOfWork: ...

    def __exit__(self, *exc_info: object) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWork: ...


# convenience aliases for use-case signatures
TopicsById = Mapping[str, Topic]
