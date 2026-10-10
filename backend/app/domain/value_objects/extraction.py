"""What one meeting extract says, after parsing: the extractor's claims, before any human decision.
Ingestion merges these into the knowledge base without ever overwriting what a person has decided."""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.value_objects.confidence import Confidence
from app.domain.value_objects.evidence import Evidence
from app.domain.value_objects.item_type import ItemType


@dataclass(frozen=True)
class ExtractedItem:
    id: str
    meeting_id: str
    type: ItemType
    description: str
    status: str
    confidence: Confidence
    evidence: Evidence
    theme: str | None = None
    owner: str | None = None
    stakeholders: tuple[str, ...] = ()
    due_date: str | None = None
    due_date_source_text: str | None = None
    rationale: str | None = None
    resolution: str | None = None
    related_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "stakeholders", tuple(self.stakeholders))
        object.__setattr__(self, "related_ids", tuple(self.related_ids))

    def full_related_ids(self) -> list[str]:
        """related_ids are candidate ids local to the item's own extract; full ids share its prefix."""
        prefix = self.id.rsplit(":", 1)[0]
        return [f"{prefix}:{related_id}" for related_id in self.related_ids]


@dataclass(frozen=True)
class ExtractedReviewCandidate:
    id: str
    type: str
    description: str
    reason: str
    confidence: Confidence
    evidence: Evidence


@dataclass(frozen=True)
class ExtractedMeeting:
    id: str
    title: str
    date: str
    source_url: str
    items: tuple[ExtractedItem, ...] = ()
    review_candidates: tuple[ExtractedReviewCandidate, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        object.__setattr__(self, "review_candidates", tuple(self.review_candidates))
