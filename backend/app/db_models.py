"""SQLAlchemy ORM tables backing the domain models in app/models.py."""
from __future__ import annotations

from sqlalchemy import ARRAY, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from pgvector.sqlalchemy import Vector

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2 output size


class Base(DeclarativeBase):
    pass


class MeetingRow(Base):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    date: Mapped[str] = mapped_column(String)
    source_url: Mapped[str] = mapped_column(String)

    items: Mapped[list["KnowledgeItemRow"]] = relationship(back_populates="meeting", cascade="all, delete-orphan")
    review_candidates: Mapped[list["ReviewCandidateRow"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )


class TopicRow(Base):
    __tablename__ = "topics"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)

    items: Mapped[list["KnowledgeItemRow"]] = relationship(back_populates="topic")

    # -- automatic priority classification (calculated_* set only by topic_priority.py) --
    calculated_priority: Mapped[str | None] = mapped_column(String, nullable=True)
    calculated_priority_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    priority_confidence: Mapped[str | None] = mapped_column(String, nullable=True)
    priority_signals: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    priority_hard_escalations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    priority_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority_algorithm_version: Mapped[str | None] = mapped_column(String, nullable=True)
    priority_semantic_contribution: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    priority_calculated_at: Mapped[str | None] = mapped_column(String, nullable=True)
    # human override - never overwritten by automatic recalculation
    manual_priority_override: Mapped[str | None] = mapped_column(String, nullable=True)
    manual_override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_override_at: Mapped[str | None] = mapped_column(String, nullable=True)


class KnowledgeItemRow(Base):
    __tablename__ = "knowledge_items"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"))
    topic_id: Mapped[str | None] = mapped_column(ForeignKey("topics.id"), nullable=True)
    type: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String)
    # legacy free-text grouping key, kept in sync with topic.name for the per-meeting view
    theme: Mapped[str | None] = mapped_column(String, nullable=True)
    # new-topic name proposed by the extractor when ingestion found no existing topic to file the item
    # under; non-null = a human has yet to accept/reject it (see data.accept_topic_proposal)
    suggested_topic: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String)
    confidence: Mapped[str] = mapped_column(String)
    owner: Mapped[str | None] = mapped_column(String, nullable=True)
    stakeholders: Mapped[list[str]] = mapped_column(ARRAY(String))
    due_date: Mapped[str | None] = mapped_column(String, nullable=True)
    due_date_source_text: Mapped[str | None] = mapped_column(String, nullable=True)
    rationale: Mapped[str | None] = mapped_column(String, nullable=True)
    resolution: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence_speaker: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence_timestamp: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence_quote: Mapped[str] = mapped_column(String)
    evidence_context: Mapped[str | None] = mapped_column(String, nullable=True)
    related_ids: Mapped[list[str]] = mapped_column(ARRAY(String))
    # nullable so rows can exist pre-embedding; ingestion always populates it
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    # human override - never overwritten by automatic Topic priority recalculation
    manual_priority_override: Mapped[str | None] = mapped_column(String, nullable=True)
    manual_override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_override_at: Mapped[str | None] = mapped_column(String, nullable=True)

    meeting: Mapped[MeetingRow] = relationship(back_populates="items")
    topic: Mapped[TopicRow | None] = relationship(back_populates="items")


class ReviewCandidateRow(Base):
    __tablename__ = "review_candidates"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"))
    type: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    confidence: Mapped[str] = mapped_column(String)
    evidence_speaker: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence_timestamp: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence_quote: Mapped[str] = mapped_column(String)
    evidence_context: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="PENDING")

    meeting: Mapped[MeetingRow] = relationship(back_populates="review_candidates")


class TopicPriorityHistoryRow(Base):
    __tablename__ = "topic_priority_history"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    # ON DELETE CASCADE: deleting a topic must not be blocked by its own priority history
    topic_id: Mapped[str] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"))
    previous_priority: Mapped[str | None] = mapped_column(String, nullable=True)
    new_priority: Mapped[str] = mapped_column(String)
    previous_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    new_score: Mapped[float] = mapped_column(Float)
    changed_at: Mapped[str] = mapped_column(String)
    algorithm_version: Mapped[str] = mapped_column(String)
    primary_drivers: Mapped[list[str]] = mapped_column(ARRAY(String))
    trigger: Mapped[str] = mapped_column(String)
    source_knowledge_item_ids: Mapped[list[str]] = mapped_column(ARRAY(String))
