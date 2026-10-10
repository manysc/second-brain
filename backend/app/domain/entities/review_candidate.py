from __future__ import annotations

from app.domain.entities.base import ReadOnly
from app.domain.exceptions import ReviewCandidateAlreadyDecided
from app.domain.value_objects.evidence import Evidence
from app.domain.value_objects.extraction import ExtractedReviewCandidate
from app.domain.value_objects.status import ReviewStatus


class ReviewCandidate:
    """Something the extractor was unsure about. It stays PENDING until a person accepts or rejects it,
    and that decision is final: ingestion never reopens it."""

    id: str = ReadOnly()  # type: ignore[assignment]
    meeting_id: str = ReadOnly()  # type: ignore[assignment]
    type: str = ReadOnly()  # type: ignore[assignment]
    description: str = ReadOnly()  # type: ignore[assignment]
    reason: str = ReadOnly()  # type: ignore[assignment]
    confidence: str = ReadOnly()  # type: ignore[assignment]
    evidence: Evidence = ReadOnly()  # type: ignore[assignment]
    status: str = ReadOnly()  # type: ignore[assignment]

    def __init__(
        self,
        *,
        id: str,
        meeting_id: str,
        type: str,
        description: str,
        reason: str,
        confidence: str,
        evidence: Evidence,
        status: str = "PENDING",
    ) -> None:
        self._id = id
        self._meeting_id = meeting_id
        self._type = type
        self._description = description
        self._reason = reason
        self._confidence = confidence
        self._evidence = evidence
        self._status = status

    @classmethod
    def from_extraction(cls, extracted: ExtractedReviewCandidate, meeting_id: str) -> ReviewCandidate:
        return cls(
            id=extracted.id,
            meeting_id=meeting_id,
            type=extracted.type,
            description=extracted.description,
            reason=extracted.reason,
            confidence=extracted.confidence,
            evidence=extracted.evidence,
        )

    @property
    def is_pending(self) -> bool:
        return self._status == "PENDING"

    @property
    def local_key(self) -> str:
        """The id without its meeting prefix."""
        return self._id.split(":", 1)[1]

    def decide(self, status: ReviewStatus) -> None:
        if not self.is_pending:
            raise ReviewCandidateAlreadyDecided(self._id)
        self._status = status

    def differs_from_extraction(self, extracted: ExtractedReviewCandidate) -> bool:
        return (
            self._type,
            self._description,
            self._reason,
            self._confidence,
            self._evidence,
        ) != (extracted.type, extracted.description, extracted.reason, extracted.confidence, extracted.evidence)

    def apply_extraction(self, extracted: ExtractedReviewCandidate) -> None:
        """Refreshes the extractor's wording. The status is a human decision and is never touched."""
        self._type = extracted.type
        self._description = extracted.description
        self._reason = extracted.reason
        self._confidence = extracted.confidence
        self._evidence = extracted.evidence
