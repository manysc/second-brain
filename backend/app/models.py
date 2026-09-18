"""Pydantic models mirroring src/lib/domain.ts, serialized with the same camelCase keys."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ItemType = Literal["IDEA", "DECISION", "ACTION", "QUESTION"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]
ReviewStatus = Literal["PENDING", "ACCEPTED", "REJECTED"]
TopicPriorityLevel = Literal["CRITICAL", "MAJOR", "MINOR"]
PriorityConfidence = Literal["HIGH", "MEDIUM", "LOW"]


class CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class Evidence(CamelModel):
    speaker: str | None = None
    timestamp: str | None = None
    quote: str = ""
    context: str | None = None


class KnowledgeItem(CamelModel):
    id: str
    type: ItemType
    description: str
    theme: str | None = None
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


class ReviewCandidate(CamelModel):
    id: str
    type: str
    description: str
    reason: str
    confidence: Confidence
    evidence: Evidence
    status: ReviewStatus = "PENDING"


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


class ManualPriorityOverride(CamelModel):
    priority: TopicPriorityLevel
    reason: str | None = None
    overridden_at: str = Field(alias="overriddenAt")


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


class Topic(CamelModel):
    id: str
    name: str
    items: list[KnowledgeItem]
    stakeholders: list[str]
    priority: TopicPriorityInfo | None = None


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


class ItemTopicSuggestion(CamelModel):
    item: KnowledgeItem
    suggested_topic: Topic = Field(alias="suggestedTopic")
    similarity: float


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


class GraphData(CamelModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


# --- Raw extraction file shape (mirrors the zod schemas previously in src/lib/data.ts) ---


class RawEvidence(BaseModel):
    speaker: str | None = None
    timestamp: str | None = None
    quote: str = ""
    context: str | None = None


class RawCandidate(BaseModel):
    candidate_id: str
    type: str
    description: str
    theme: str | None = None
    status: str = "Open"
    owner: str | None = None
    proposed_by: str | None = None
    decision_owner: str | None = None
    due_date: str | None = None
    due_date_source_text: str | None = None
    priority: str | None = None
    confidence: str = "Medium"
    rationale: str | None = None
    resolution: str | None = None
    evidence: RawEvidence
    related_candidate_ids: list[str] = Field(default_factory=list)


class RawMeetingInfo(BaseModel):
    meeting_id: str
    title: str
    date: str
    source_url: str


class RawReviewCandidate(BaseModel):
    candidate_type: str
    description: str
    reason_for_review: str
    confidence: str
    evidence: RawEvidence


class RawExtraction(BaseModel):
    schema_version: str
    meeting: RawMeetingInfo
    ideas: list[RawCandidate]
    decisions: list[RawCandidate]
    actions: list[RawCandidate]
    questions: list[RawCandidate]
    review_candidates: list[RawReviewCandidate]
