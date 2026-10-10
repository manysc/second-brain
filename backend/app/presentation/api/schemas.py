"""The REST API's request and response schemas, serialized with camelCase keys (mirrored by hand in
src/Domain on the frontend). Responses are built from application DTOs with `Schema.model_validate(dto,
from_attributes=True)`; requests are turned into use-case arguments by the routers."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.application.dtos import NewItem
from app.domain.entities.knowledge_item import ItemEdit
from app.domain.value_objects.tag import (  # noqa: F401  (re-exported)
    MAX_TAG_LENGTH,
    MAX_TAGS,
    normalize_tag,
)

ItemType = Literal["IDEA", "DECISION", "ACTION", "QUESTION"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]
ReviewStatus = Literal["PENDING", "ACCEPTED", "REJECTED"]
TopicPriorityLevel = Literal["CRITICAL", "MAJOR", "MINOR"]
PriorityConfidence = Literal["HIGH", "MEDIUM", "LOW"]
OpenClosed = Literal["Open", "Closed"]


class CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class Evidence(CamelModel):
    speaker: str | None = None
    timestamp: str | None = None
    quote: str = ""
    context: str | None = None


class ManualPriorityOverride(CamelModel):
    priority: TopicPriorityLevel
    reason: str | None = None
    overridden_at: str = Field(alias="overriddenAt")


class Note(CamelModel):
    id: str
    body: str
    created_at: str = Field(alias="createdAt")


class NoteCreate(CamelModel):
    body: str = Field(min_length=1, max_length=10000)

    @field_validator("body")
    @classmethod
    def _strip_body(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Note cannot be empty")
        return v


class TopicImage(CamelModel):
    id: str
    filename: str
    content_type: str = Field(alias="contentType")
    size: int
    created_at: str = Field(alias="createdAt")




class TagCreate(CamelModel):
    tag: str = Field(min_length=1, max_length=MAX_TAG_LENGTH * 2)

    @field_validator("tag")
    @classmethod
    def _normalize_tag(cls, v: str) -> str:
        v = normalize_tag(v)
        if not v:
            raise ValueError("Tag cannot be empty")
        if len(v) > MAX_TAG_LENGTH:
            raise ValueError(f"Tag cannot be longer than {MAX_TAG_LENGTH} characters")
        return v


class ItemCreate(CamelModel):
    type: ItemType
    description: str = Field(min_length=1, max_length=2000)
    owner: str | None = Field(default=None, max_length=200)
    due_date: str | None = Field(default=None, alias="dueDate", max_length=50)
    rationale: str | None = Field(default=None, max_length=2000)

    @field_validator("description")
    @classmethod
    def _strip_description(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Description cannot be empty")
        return v

    @field_validator("owner", "due_date", "rationale")
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        v = v.strip() if v else None
        return v or None

    def to_new_item(self) -> NewItem:
        return NewItem(
            type=self.type,
            description=self.description,
            owner=self.owner,
            due_date=self.due_date,
            rationale=self.rationale,
        )


class ItemUpdate(CamelModel):
    """Partial edit: omitted fields are left alone; an explicit null/blank clears owner, due date or rationale."""

    type: ItemType | None = None
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    owner: str | None = Field(default=None, max_length=200)
    due_date: str | None = Field(default=None, alias="dueDate", max_length=50)
    rationale: str | None = Field(default=None, max_length=2000)

    @field_validator("description")
    @classmethod
    def _strip_description(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Description cannot be empty")
        return v

    @field_validator("owner", "due_date", "rationale")
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        v = v.strip() if v else None
        return v or None

    @model_validator(mode="after")
    def _check_fields(self) -> ItemUpdate:
        if not self.model_fields_set:
            raise ValueError("update must set at least one field")
        # type and description cannot be cleared, only replaced
        if "type" in self.model_fields_set and self.type is None:
            raise ValueError("type cannot be null")
        if "description" in self.model_fields_set and self.description is None:
            raise ValueError("description cannot be null")
        return self

    def to_item_edit(self) -> ItemEdit:
        """Only the fields the request actually set are part of the edit."""
        return ItemEdit(
            fields=frozenset(self.model_fields_set),
            type=self.type,
            description=self.description,
            owner=self.owner,
            due_date=self.due_date,
            rationale=self.rationale,
        )


class KnowledgeItem(CamelModel):
    id: str
    type: ItemType
    description: str
    theme: str | None = None
    # the topic the item is filed under (None when uncategorized), so the UI can link to it
    topic_id: str | None = Field(default=None, alias="topicId")
    topic_name: str | None = Field(default=None, alias="topicName")
    status: str
    confidence: Confidence
    owner: str | None = None
    stakeholders: list[str] = Field(default_factory=list)
    due_date: str | None = Field(default=None, alias="dueDate")
    due_date_source_text: str | None = Field(default=None, alias="dueDateSourceText")
    rationale: str | None = None
    resolution: str | None = None
    evidence: Evidence
    related_ids: list[str] = Field(default_factory=list, alias="relatedIds")
    meeting_id: str = Field(alias="meetingId")
    # Option A: items have no automatic scoring of their own - override wins, else inherited from topic
    effective_priority: TopicPriorityLevel | None = Field(default=None, alias="effectivePriority")
    manual_override: ManualPriorityOverride | None = Field(default=None, alias="manualOverride")
    notes: list[Note] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class ReviewCandidate(CamelModel):
    id: str
    type: str
    description: str
    reason: str
    confidence: Confidence
    evidence: Evidence
    status: ReviewStatus = "PENDING"
    # existing topic an accepted candidate would be filed under (semantic match); filled in by GET /api/review
    suggested_topic_id: str | None = Field(default=None, alias="suggestedTopicId")


class TopicPrioritySignal(CamelModel):
    type: str
    raw_value: float | str | bool | None = Field(default=None, alias="rawValue")
    normalized_score: float = Field(alias="normalizedScore")
    weighted_score: float = Field(alias="weightedScore")
    max_score: float = Field(alias="maxScore")
    explanation: str
    source_knowledge_item_ids: list[str] = Field(default_factory=list, alias="sourceKnowledgeItemIds")


class HardEscalation(CamelModel):
    rule_id: str = Field(alias="ruleId")
    reason: str
    source_knowledge_item_ids: list[str] = Field(default_factory=list, alias="sourceKnowledgeItemIds")


class SemanticContribution(CamelModel):
    provider: str
    model: str
    scores: dict[str, float]
    contribution: float
    disagreement: bool


class TopicPriorityInfo(CamelModel):
    calculated_priority: TopicPriorityLevel = Field(alias="calculatedPriority")
    calculated_score: float = Field(alias="calculatedScore")
    effective_priority: TopicPriorityLevel = Field(alias="effectivePriority")
    confidence: PriorityConfidence
    signals: list[TopicPrioritySignal] = Field(default_factory=list)
    hard_escalations: list[HardEscalation] = Field(default_factory=list, alias="hardEscalations")
    explanation: str
    calculated_at: str = Field(alias="calculatedAt")
    algorithm_version: str = Field(alias="algorithmVersion")
    semantic_contribution: SemanticContribution | None = Field(default=None, alias="semanticContribution")
    manual_override: ManualPriorityOverride | None = Field(default=None, alias="manualOverride")


class TopicPriorityHistoryEntry(CamelModel):
    id: str
    topic_id: str = Field(alias="topicId")
    previous_priority: TopicPriorityLevel | None = Field(default=None, alias="previousPriority")
    new_priority: TopicPriorityLevel = Field(alias="newPriority")
    previous_score: float | None = Field(default=None, alias="previousScore")
    new_score: float = Field(alias="newScore")
    changed_at: str = Field(alias="changedAt")
    algorithm_version: str = Field(alias="algorithmVersion")
    primary_drivers: list[str] = Field(default_factory=list, alias="primaryDrivers")
    trigger: str
    source_knowledge_item_ids: list[str] = Field(default_factory=list, alias="sourceKnowledgeItemIds")


class PriorityOverrideUpdate(CamelModel):
    priority: TopicPriorityLevel | None = None
    reason: str | None = None


class StatusUpdate(CamelModel):
    status: OpenClosed


class Topic(CamelModel):
    id: str
    name: str
    status: OpenClosed = "Open"
    items: list[KnowledgeItem]
    stakeholders: list[str]
    priority: TopicPriorityInfo | None = None
    notes: list[Note] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    images: list[TopicImage] = Field(default_factory=list)


class TopicCreate(CamelModel):
    name: str


class TopicUpdate(CamelModel):
    name: str


class ItemTopicUpdate(CamelModel):
    topic_id: str | None = Field(default=None, alias="topicId")


class ItemsTopicBulkUpdate(CamelModel):
    item_ids: list[str] = Field(alias="itemIds")
    topic_id: str | None = Field(default=None, alias="topicId")


class ReviewStatusUpdate(CamelModel):
    status: Literal["ACCEPTED", "REJECTED"]
    # ACCEPTED only: existing topic to file the new item under. "" = Uncategorized; omitted/null = auto-match
    topic_id: str | None = Field(default=None, alias="topicId")


class FollowUpRelatedItem(CamelModel):
    item: KnowledgeItem
    topic_id: str = Field(alias="topicId")
    topic_name: str = Field(alias="topicName")
    reason: str


class FollowUpTopic(CamelModel):
    topic: Topic
    follow_up_items: list[KnowledgeItem] = Field(default_factory=list, alias="followUpItems")
    escalated_recently: bool = Field(alias="escalatedRecently")
    escalation_drivers: list[str] = Field(default_factory=list, alias="escalationDrivers")
    related_from_other_topics: list[FollowUpRelatedItem] = Field(default_factory=list, alias="relatedFromOtherTopics")


class FollowUpResponse(CamelModel):
    topics: list[FollowUpTopic]
    generated_at: str = Field(alias="generatedAt")


class TopicMerge(CamelModel):
    target_topic_id: str = Field(alias="targetTopicId")


class TopicMergeSuggestion(CamelModel):
    topic_a: Topic = Field(alias="topicA")
    topic_b: Topic = Field(alias="topicB")
    similarity: float


class RelatedTopic(CamelModel):
    id: str
    name: str
    status: str
    similarity: float
    item_count: int = Field(alias="itemCount")


class TopicProposal(CamelModel):
    """A new topic name the extractor proposed for a group of items; nothing is created until a human accepts it."""
    name: str
    items: list[KnowledgeItem]
    suggested_existing_topic_id: str | None = Field(default=None, alias="suggestedExistingTopicId")


class TopicProposalAccept(CamelModel):
    suggested_name: str = Field(alias="suggestedName")
    # rename the new topic before it is created
    topic_name: str | None = Field(default=None, alias="topicName")
    # file the items under this existing topic instead of creating a new one
    existing_topic_id: str | None = Field(default=None, alias="existingTopicId")


class TopicProposalReject(CamelModel):
    suggested_name: str = Field(alias="suggestedName")


class TopicCandidate(CamelModel):
    """A lightweight reference to an existing topic ranked for an item (see app/topic_suggestions.py)."""
    topic_id: str = Field(alias="topicId")
    topic_name: str = Field(alias="topicName")
    item_count: int = Field(alias="itemCount")
    score: float
    centroid_similarity: float = Field(alias="centroidSimilarity")


class ItemTopicSuggestion(CamelModel):
    item: KnowledgeItem
    # best first, up to 3
    candidates: list[TopicCandidate]
    score: float
    confidence: Confidence


class Meeting(CamelModel):
    id: str
    title: str
    date: str
    source_url: str = Field(alias="sourceUrl")
    items: list[KnowledgeItem]
    review_candidates: list[ReviewCandidate] = Field(alias="reviewCandidates")
    topics: list[Topic]


class ItemDetail(CamelModel):
    item: KnowledgeItem
    related: list[KnowledgeItem]
    # pgvector nearest neighbors, distinct from `related` (which is evidence-grounded only)
    similar: list[KnowledgeItem] = Field(default_factory=list)


class SearchResult(CamelModel):
    items: list[KnowledgeItem]
    # topics owning at least one matched item, each carrying its full item list (not just the match)
    topics: list[Topic]


class GraphNode(CamelModel):
    id: str
    type: ItemType
    description: str
    confidence: Confidence
    owner: str | None = None
    topic_id: str | None = Field(default=None, alias="topicId")
    topic_name: str | None = Field(default=None, alias="topicName")
    meeting_id: str = Field(alias="meetingId")
    # effective (override-aware) priority of the node's owning topic, if calculated
    priority: TopicPriorityLevel | None = None


class GraphEdge(CamelModel):
    source: str
    target: str
    kind: Literal["related", "topic", "semantic"]
    # 1.0 for related/topic edges; cosine similarity (0-1) for semantic edges
    weight: float = 1.0


class GraphTopic(CamelModel):
    id: str
    name: str
    item_count: int = Field(alias="itemCount")


class TopicLink(CamelModel):
    """Directed: `target` is one of the topics most related to `source` (same as RelatedTopic)."""

    source: str
    target: str
    similarity: float


class GraphData(CamelModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    topics: list[GraphTopic] = []
    topic_links: list[TopicLink] = Field(default=[], alias="topicLinks")
