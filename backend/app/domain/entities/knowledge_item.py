from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from app.domain.entities.base import ReadOnly
from app.domain.entities.note import Note, edit_note, remove_note
from app.domain.exceptions import ItemNotDeletable, ItemNotEditable
from app.domain.policies import MANUAL_MEETING_ID
from app.domain.value_objects.evidence import Evidence
from app.domain.value_objects.extraction import ExtractedItem
from app.domain.value_objects.item_type import ItemType, normalize_item_type
from app.domain.value_objects.priority import ManualPriorityOverride, TopicPriorityLevel
from app.domain.value_objects.status import (
    OpenClosed,
    is_resolved_status,
    to_open_closed,
)
from app.domain.value_objects.tag import with_tag, without_tag

if TYPE_CHECKING:
    from app.domain.entities.review_candidate import ReviewCandidate
    from app.domain.entities.topic import Topic

Embedding = np.ndarray | Sequence[float]


@dataclass(frozen=True)
class ItemEdit:
    """A partial edit: only the fields named in `fields` are touched. A None value clears owner, due date or
    rationale; type and description can only be replaced."""

    fields: frozenset[str]
    type: ItemType | None = None
    description: str | None = None
    owner: str | None = None
    due_date: str | None = None
    rationale: str | None = None


class KnowledgeItem:
    """An idea, decision, action or question, grounded in the evidence it was extracted from (or written by hand).

    Who owns what: the extractor owns the wording, evidence and links; a human owns the open/closed status,
    the topic the item is filed under, proposal decisions, priority overrides, tags and notes. Re-ingesting an
    extract refreshes only the extractor-owned fields (see apply_extraction)."""

    id: str = ReadOnly()  # type: ignore[assignment]
    meeting_id: str = ReadOnly()  # type: ignore[assignment]
    topic_id: str | None = ReadOnly()  # type: ignore[assignment]
    type: str = ReadOnly()  # type: ignore[assignment]
    description: str = ReadOnly()  # type: ignore[assignment]
    theme: str | None = ReadOnly()  # type: ignore[assignment]
    suggested_topic: str | None = ReadOnly()  # type: ignore[assignment]
    status: str = ReadOnly()  # type: ignore[assignment]
    confidence: str = ReadOnly()  # type: ignore[assignment]
    owner: str | None = ReadOnly()  # type: ignore[assignment]
    stakeholders: tuple[str, ...] = ReadOnly()  # type: ignore[assignment]
    due_date: str | None = ReadOnly()  # type: ignore[assignment]
    due_date_source_text: str | None = ReadOnly()  # type: ignore[assignment]
    rationale: str | None = ReadOnly()  # type: ignore[assignment]
    resolution: str | None = ReadOnly()  # type: ignore[assignment]
    evidence: Evidence = ReadOnly()  # type: ignore[assignment]
    related_ids: tuple[str, ...] = ReadOnly()  # type: ignore[assignment]
    embedding: Embedding | None = ReadOnly()  # type: ignore[assignment]
    manual_override: ManualPriorityOverride | None = ReadOnly()  # type: ignore[assignment]
    tags: tuple[str, ...] = ReadOnly()  # type: ignore[assignment]
    notes: tuple[Note, ...] = ReadOnly()  # type: ignore[assignment]

    def __init__(
        self,
        *,
        id: str,
        meeting_id: str,
        type: str,
        description: str,
        status: str,
        confidence: str,
        evidence: Evidence,
        topic_id: str | None = None,
        theme: str | None = None,
        suggested_topic: str | None = None,
        owner: str | None = None,
        stakeholders: Sequence[str] = (),
        due_date: str | None = None,
        due_date_source_text: str | None = None,
        rationale: str | None = None,
        resolution: str | None = None,
        related_ids: Sequence[str] = (),
        embedding: Embedding | None = None,
        manual_override: ManualPriorityOverride | None = None,
        tags: Sequence[str] = (),
        notes: Sequence[Note] = (),
    ) -> None:
        self._id = id
        self._meeting_id = meeting_id
        self._topic_id = topic_id
        self._type = type
        self._description = description
        self._theme = theme
        self._suggested_topic = suggested_topic
        self._status = status
        self._confidence = confidence
        self._owner = owner
        self._stakeholders = tuple(stakeholders)
        self._due_date = due_date
        self._due_date_source_text = due_date_source_text
        self._rationale = rationale
        self._resolution = resolution
        self._evidence = evidence
        self._related_ids = tuple(related_ids)
        self._embedding = embedding
        self._manual_override = manual_override
        self._tags = tuple(tags)
        self._notes = tuple(notes)

    # -- factories -------------------------------------------------------------------------------------

    @classmethod
    def manual(
        cls,
        *,
        unique_id: str,
        topic: Topic,
        type: ItemType,
        description: str,
        owner: str | None,
        due_date: str | None,
        rationale: str | None,
        embedding: Embedding,
    ) -> KnowledgeItem:
        """An item a person wrote directly under a topic. It hangs off the synthetic manual meeting."""
        return cls(
            id=f"{MANUAL_MEETING_ID}:{unique_id}",
            meeting_id=MANUAL_MEETING_ID,
            topic_id=topic.id,
            type=type,
            description=description,
            theme=topic.name,
            status="Open",
            confidence="HIGH",
            owner=owner,
            stakeholders=[owner] if owner else [],
            due_date=due_date,
            rationale=rationale,
            evidence=Evidence(quote="Added manually"),
            embedding=embedding,
        )

    @classmethod
    def from_review_candidate(
        cls, candidate: ReviewCandidate, *, topic_id: str, topic_name: str, embedding: Embedding
    ) -> KnowledgeItem:
        """A review candidate a person accepted: promoted with HIGH confidence, the speaker as its owner."""
        owner = candidate.evidence.speaker
        return cls(
            id=f"{candidate.meeting_id}:accepted-{candidate.local_key}",
            meeting_id=candidate.meeting_id,
            topic_id=topic_id,
            type=normalize_item_type(candidate.type),
            description=candidate.description,
            theme=topic_name,
            status="Open",
            confidence="HIGH",
            owner=owner,
            stakeholders=[owner] if owner else [],
            rationale=candidate.reason,
            evidence=candidate.evidence,
            embedding=embedding,
        )

    @classmethod
    def from_extraction(
        cls,
        extracted: ExtractedItem,
        *,
        topic_id: str,
        topic_name: str,
        suggested_topic: str | None,
        embedding: Embedding,
    ) -> KnowledgeItem:
        """A newly ingested item, filed where ingestion matched it. `suggested_topic` keeps the extractor's
        theme as a proposal when nothing matched and the item landed in Uncategorized."""
        return cls(
            id=extracted.id,
            meeting_id=extracted.meeting_id,
            topic_id=topic_id,
            type=extracted.type,
            description=extracted.description,
            theme=topic_name,
            suggested_topic=suggested_topic,
            status=extracted.status,
            confidence=extracted.confidence,
            owner=extracted.owner,
            stakeholders=extracted.stakeholders,
            due_date=extracted.due_date,
            due_date_source_text=extracted.due_date_source_text,
            rationale=extracted.rationale,
            resolution=extracted.resolution,
            evidence=extracted.evidence,
            related_ids=extracted.related_ids,
            embedding=embedding,
        )

    # -- queries ---------------------------------------------------------------------------------------

    @property
    def is_manual(self) -> bool:
        return self._meeting_id == MANUAL_MEETING_ID

    @property
    def is_resolved(self) -> bool:
        return is_resolved_status(self._status)

    @property
    def open_closed(self) -> OpenClosed:
        return to_open_closed(self._status)

    @property
    def local_key(self) -> str:
        """The id without its meeting prefix: what other items' related_ids usually carry."""
        return self._id.split(":", 1)[-1]

    def effective_priority(self, topic: Topic | None) -> TopicPriorityLevel | None:
        """An item has no automatic scoring of its own: its own override wins, else it inherits its
        owning topic's effective priority."""
        if self._manual_override is not None:
            return self._manual_override.priority
        return topic.effective_priority if topic is not None else None

    # -- human decisions -------------------------------------------------------------------------------

    def set_status(self, status: str) -> None:
        self._status = status

    def override_priority(self, priority: TopicPriorityLevel | None, reason: str | None, at: str) -> None:
        """Sets a manual priority, or clears it (with its reason and timestamp) when `priority` is None.
        Independent of, and never touched by, the topic's automatic recalculation."""
        self._manual_override = (
            ManualPriorityOverride(priority=priority, reason=reason, overridden_at=at) if priority is not None else None
        )

    def add_tag(self, tag: str) -> None:
        self._tags = tuple(with_tag(self._tags, tag))

    def remove_tag(self, tag: str) -> None:
        self._tags = tuple(without_tag(self._tags, tag))

    def add_note(self, note: Note) -> None:
        self._notes = (*self._notes, note)

    def edit_note(self, note_id: str, body: str) -> None:
        self._notes = edit_note(self._notes, note_id, body)

    def remove_note(self, note_id: str) -> None:
        self._notes = remove_note(self._notes, note_id)

    def file_under(self, topic: Topic | None) -> None:
        """Moves the item to a topic (None = unassigned); the theme always mirrors the topic name."""
        self._topic_id = topic.id if topic is not None else None
        self._theme = topic.name if topic is not None else None

    def accept_proposal(self, topic: Topic) -> None:
        """A person decided where the extractor's proposed topic goes: file there and close the proposal."""
        self.file_under(topic)
        self._suggested_topic = None

    def dismiss_proposal(self) -> None:
        """A person rejected the proposed topic: the item stays where it is."""
        self._suggested_topic = None

    def follow_topic_rename(self, name: str) -> None:
        self._theme = name

    def edit(self, changes: ItemEdit) -> bool:
        """Applies a partial edit and returns whether the description changed (the embedding is then stale
        and must be refreshed with reembed). Only manually added items can change type."""
        fields = changes.fields
        if "type" in fields and changes.type != self._type and not self.is_manual:
            raise ItemNotEditable("The type of an item extracted from a meeting cannot be changed")
        description_changed = False
        if "type" in fields:
            self._type = changes.type  # type: ignore[assignment]
        if "description" in fields and changes.description != self._description:
            self._description = changes.description  # type: ignore[assignment]
            description_changed = True
        if "owner" in fields:
            self._owner = changes.owner
            self._stakeholders = (changes.owner,) if changes.owner else ()
        if "due_date" in fields:
            self._due_date = changes.due_date
            self._due_date_source_text = None
        if "rationale" in fields:
            self._rationale = changes.rationale
        return description_changed

    def reembed(self, embedding: Embedding) -> None:
        self._embedding = embedding

    def ensure_deletable(self) -> None:
        """Meeting-extracted items cannot be deleted: the next ingest would simply re-create them."""
        if not self.is_manual:
            raise ItemNotDeletable(self._id)

    # -- ingestion -------------------------------------------------------------------------------------

    def reinforce(self) -> bool:
        """A second source confirmed this item (a duplicate review candidate or another extract of the same
        meeting): confidence becomes HIGH. Returns whether that changed anything."""
        if self._confidence == "HIGH":
            return False
        self._confidence = "HIGH"
        return True

    def differs_from_extraction(self, extracted: ExtractedItem) -> bool:
        """Whether a re-ingested extract says something new about this item. Status is human-owned after the
        first insert, so it never counts. A stored HIGH confidence may be a reinforcement rather than this
        extract's own value; treating that as a difference would revert and re-apply it on every run."""
        theirs = _extractor_owned(extracted)
        mine = self._extractor_owned()
        if self._confidence == "HIGH":
            theirs.pop("confidence")
            mine.pop("confidence")
        return mine != theirs

    def apply_extraction(self, extracted: ExtractedItem, embedding: Embedding | None = None) -> None:
        """Refreshes the extractor-owned fields from a re-ingested extract. Status, topic, theme and the
        proposal state are deliberately left alone: they belong to a person."""
        self._type = extracted.type
        self._description = extracted.description
        self._confidence = extracted.confidence
        self._owner = extracted.owner
        self._stakeholders = extracted.stakeholders
        self._due_date = extracted.due_date
        self._due_date_source_text = extracted.due_date_source_text
        self._rationale = extracted.rationale
        self._resolution = extracted.resolution
        self._evidence = extracted.evidence
        self._related_ids = extracted.related_ids
        if embedding is not None:
            self._embedding = embedding

    def _extractor_owned(self) -> dict[str, object]:
        return {
            "type": self._type,
            "description": self._description,
            "confidence": self._confidence,
            "owner": self._owner,
            "stakeholders": self._stakeholders,
            "due_date": self._due_date,
            "due_date_source_text": self._due_date_source_text,
            "rationale": self._rationale,
            "resolution": self._resolution,
            "evidence": self._evidence,
            "related_ids": self._related_ids,
        }


def _extractor_owned(extracted: ExtractedItem) -> dict[str, object]:
    return {
        "type": extracted.type,
        "description": extracted.description,
        "confidence": extracted.confidence,
        "owner": extracted.owner,
        "stakeholders": extracted.stakeholders,
        "due_date": extracted.due_date,
        "due_date_source_text": extracted.due_date_source_text,
        "rationale": extracted.rationale,
        "resolution": extracted.resolution,
        "evidence": extracted.evidence,
        "related_ids": extracted.related_ids,
    }
