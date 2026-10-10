from __future__ import annotations

from app.domain.entities.base import ReadOnly
from app.domain.policies import MANUAL_MEETING_ID, MANUAL_MEETING_TITLE
from app.domain.value_objects.extraction import ExtractedMeeting


class Meeting:
    """A meeting whose extract was ingested. Knowledge items and review candidates refer to it by id."""

    id: str = ReadOnly()  # type: ignore[assignment]
    title: str = ReadOnly()  # type: ignore[assignment]
    date: str = ReadOnly()  # type: ignore[assignment]
    source_url: str = ReadOnly()  # type: ignore[assignment]

    def __init__(self, *, id: str, title: str, date: str, source_url: str) -> None:
        self._id = id
        self._title = title
        self._date = date
        self._source_url = source_url

    @classmethod
    def manual(cls, today: str) -> Meeting:
        """The synthetic meeting that owns items added by hand (every item must belong to a meeting)."""
        return cls(id=MANUAL_MEETING_ID, title=MANUAL_MEETING_TITLE, date=today, source_url="")

    @classmethod
    def from_extraction(cls, extracted: ExtractedMeeting) -> Meeting:
        return cls(id=extracted.id, title=extracted.title, date=extracted.date, source_url=extracted.source_url)

    def differs_from_extraction(self, extracted: ExtractedMeeting) -> bool:
        return (self._title, self._date, self._source_url) != (extracted.title, extracted.date, extracted.source_url)

    def apply_extraction(self, extracted: ExtractedMeeting) -> None:
        self._title = extracted.title
        self._date = extracted.date
        self._source_url = extracted.source_url
