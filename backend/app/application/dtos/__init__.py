"""Flat, immutable structures that cross the application boundary. Entities never leave the application
layer; immutable domain value objects (Evidence, the priority records) may travel inside a DTO unchanged."""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.value_objects.evidence import Evidence
from app.domain.value_objects.priority import ManualPriorityOverride, TopicPriorityInfo


@dataclass(frozen=True)
class NoteDTO:
    id: str
    body: str
    created_at: str


@dataclass(frozen=True)
class TopicImageDTO:
    """Deliberately without the storage key: clients fetch the bytes through the API."""

    id: str
    filename: str
    content_type: str
    size: int
    created_at: str


@dataclass(frozen=True)
class KnowledgeItemDTO:
    id: str
    type: str
    description: str
    theme: str | None
    # the topic the item is filed under (None when uncategorized), so a client can link to it
    topic_id: str | None
    topic_name: str | None
    # always Open/Closed: the extractor's free-text status is collapsed for reading
    status: str
    confidence: str
    owner: str | None
    stakeholders: tuple[str, ...]
    due_date: str | None
    due_date_source_text: str | None
    rationale: str | None
    resolution: str | None
    evidence: Evidence
    related_ids: tuple[str, ...]
    meeting_id: str
    # the item's own override, else inherited from its topic
    effective_priority: str | None
    manual_override: ManualPriorityOverride | None
    notes: tuple[NoteDTO, ...]
    tags: tuple[str, ...]


@dataclass(frozen=True)
class ReviewCandidateDTO:
    id: str
    type: str
    description: str
    reason: str
    confidence: str
    evidence: Evidence
    status: str
    # existing topic an accepted candidate would be filed under (a confident match), to pre-select a picker
    suggested_topic_id: str | None = None


@dataclass(frozen=True)
class TopicDTO:
    id: str
    name: str
    status: str
    items: tuple[KnowledgeItemDTO, ...]
    stakeholders: tuple[str, ...]
    priority: TopicPriorityInfo | None = None
    notes: tuple[NoteDTO, ...] = ()
    tags: tuple[str, ...] = ()
    images: tuple[TopicImageDTO, ...] = ()


@dataclass(frozen=True)
class MeetingDTO:
    id: str
    title: str
    date: str
    source_url: str
    items: tuple[KnowledgeItemDTO, ...]
    review_candidates: tuple[ReviewCandidateDTO, ...]
    # the meeting's own items grouped by theme; ids are "<meeting id>:<theme>", not persisted topic ids
    topics: tuple[TopicDTO, ...]


@dataclass(frozen=True)
class ItemDetailDTO:
    item: KnowledgeItemDTO
    related: tuple[KnowledgeItemDTO, ...]
    # nearest neighbours by embedding, distinct from `related` (which is evidence-grounded only)
    similar: tuple[KnowledgeItemDTO, ...] = ()


@dataclass(frozen=True)
class SearchResultDTO:
    items: tuple[KnowledgeItemDTO, ...]
    # topics owning at least one matched item, each carrying its full item list (not just the match)
    topics: tuple[TopicDTO, ...]


@dataclass(frozen=True)
class GraphNodeDTO:
    id: str
    type: str
    description: str
    confidence: str
    owner: str | None
    topic_id: str | None
    topic_name: str | None
    meeting_id: str
    # effective (override-aware) priority of the node, if calculated
    priority: str | None


@dataclass(frozen=True)
class GraphEdgeDTO:
    source: str
    target: str
    kind: str
    weight: float = 1.0


@dataclass(frozen=True)
class GraphTopicDTO:
    id: str
    name: str
    item_count: int


@dataclass(frozen=True)
class TopicLinkDTO:
    """Directed: `target` is one of the topics most related to `source`."""

    source: str
    target: str
    similarity: float


@dataclass(frozen=True)
class GraphDTO:
    nodes: tuple[GraphNodeDTO, ...]
    edges: tuple[GraphEdgeDTO, ...]
    topics: tuple[GraphTopicDTO, ...] = ()
    topic_links: tuple[TopicLinkDTO, ...] = ()


@dataclass(frozen=True)
class RelatedTopicDTO:
    id: str
    name: str
    status: str
    similarity: float
    item_count: int


@dataclass(frozen=True)
class TopicMergeSuggestionDTO:
    topic_a: TopicDTO
    topic_b: TopicDTO
    similarity: float


@dataclass(frozen=True)
class TopicCandidateDTO:
    """A lightweight reference to an existing topic ranked for an item."""

    topic_id: str
    topic_name: str
    item_count: int
    score: float
    centroid_similarity: float


@dataclass(frozen=True)
class ItemTopicSuggestionDTO:
    item: KnowledgeItemDTO
    # best first
    candidates: tuple[TopicCandidateDTO, ...]
    score: float
    confidence: str


@dataclass(frozen=True)
class TopicProposalDTO:
    """A new topic name the extractor proposed for a group of items; nothing is created until a human accepts it."""

    name: str
    items: tuple[KnowledgeItemDTO, ...]
    suggested_existing_topic_id: str | None = None


@dataclass(frozen=True)
class FollowUpRelatedItemDTO:
    item: KnowledgeItemDTO
    topic_id: str
    topic_name: str
    reason: str


@dataclass(frozen=True)
class FollowUpTopicDTO:
    topic: TopicDTO
    follow_up_items: tuple[KnowledgeItemDTO, ...]
    escalated_recently: bool
    escalation_drivers: tuple[str, ...] = ()
    related_from_other_topics: tuple[FollowUpRelatedItemDTO, ...] = ()


@dataclass(frozen=True)
class FollowUpDTO:
    topics: tuple[FollowUpTopicDTO, ...]
    generated_at: str


@dataclass(frozen=True)
class TopicImageContentDTO:
    body: bytes
    content_type: str


@dataclass(frozen=True)
class IngestSummary:
    """What one ingestion run did. new/updated/unchanged count distinct meeting ids, so two LLM
    extracts of the same meeting count once; `processed` counts every parsed (sub-)meeting."""

    processed: int
    new: int
    updated: int
    unchanged: int

    @property
    def changed(self) -> bool:
        return bool(self.new or self.updated)


@dataclass(frozen=True)
class NewItem:
    """What a person supplies when adding an item by hand."""

    type: str
    description: str
    owner: str | None = None
    due_date: str | None = None
    rationale: str | None = None
