"""Pydantic models mirroring src/lib/domain.ts, serialized with the same camelCase keys."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ItemType = Literal["IDEA", "DECISION", "ACTION", "QUESTION"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]
ReviewStatus = Literal["PENDING", "ACCEPTED", "REJECTED"]


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


class Topic(CamelModel):
    id: str
    name: str
    items: list[KnowledgeItem]
    stakeholders: list[str]


class TopicCreate(CamelModel):
    name: str


class TopicUpdate(CamelModel):
    name: str


class ItemTopicUpdate(CamelModel):
    topic_id: str | None = Field(default=None, alias="topicId")


class ReviewStatusUpdate(CamelModel):
    status: Literal["ACCEPTED", "REJECTED"]


class TopicMerge(CamelModel):
    target_topic_id: str = Field(alias="targetTopicId")


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
