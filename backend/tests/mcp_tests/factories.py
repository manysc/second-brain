"""In-memory application DTOs, and a stand-in for the application, for DB-free unit tests of the MCP layer."""
from __future__ import annotations

from types import SimpleNamespace

from app.application.dtos import (
    KnowledgeItemDTO,
    MeetingDTO,
    NoteDTO,
    SearchResultDTO,
    TopicDTO,
)
from app.application.use_cases.health import StorageHealth
from app.domain.value_objects.evidence import Evidence
from app.domain.value_objects.priority import ManualPriorityOverride


def note(note_id: str, body: str, created_at: str) -> NoteDTO:
    return NoteDTO(id=note_id, body=body, created_at=created_at)


def item(
    item_id: str,
    item_type: str = "ACTION",
    description: str = "Do the thing. Then more.",
    status: str = "Open",
    owner: str | None = None,
    due_date: str | None = None,
    related_ids: list[str] | None = None,
    meeting_id: str = "m1",
    priority: str | None = None,
    override: str | None = None,
    notes: list[NoteDTO] | None = None,
    quote: str = "we said so",
) -> KnowledgeItemDTO:
    return KnowledgeItemDTO(
        id=item_id,
        type=item_type,
        description=description,
        theme=None,
        topic_id=None,
        topic_name=None,
        status=status,
        confidence="HIGH",
        owner=owner,
        stakeholders=(),
        due_date=due_date,
        due_date_source_text=None,
        rationale=None,
        resolution=None,
        evidence=Evidence(speaker="Ada", timestamp="00:01:00", quote=quote),
        related_ids=tuple(related_ids or []),
        meeting_id=meeting_id,
        effective_priority=override or priority,
        manual_override=ManualPriorityOverride(priority=override, reason="because", overridden_at="2026-09-10T00:00:00+00:00")
        if override
        else None,
        notes=tuple(notes or []),
        tags=(),
    )


def meeting(meeting_id: str, day: str, items: list[KnowledgeItemDTO], title: str | None = None) -> MeetingDTO:
    return MeetingDTO(
        id=meeting_id, title=title or f"Meeting {meeting_id}", date=day, source_url=f"https://example.test/{meeting_id}",
        items=tuple(items), review_candidates=(), topics=(),
    )


def topic(topic_id: str, name: str, items: list[KnowledgeItemDTO]) -> TopicDTO:
    return TopicDTO(id=topic_id, name=name, status="Open", items=tuple(items), stakeholders=())


def application(**use_cases) -> SimpleNamespace:
    """A stand-in for the Container: the read use cases answer "nothing" unless a test supplies its own.
    Write use cases are absent on purpose, so a test must stub the ones it expects to be called."""
    defaults = {
        "get_priority_history": lambda topic_id, require_topic=True: [],
        "find_similar_items": lambda item, limit=5: [],
        "get_related_topics": lambda topic_id, **kwargs: [],
        "search": lambda query, limit=20: SearchResultDTO(items=(), topics=()),
        "check_storage_health": lambda: StorageHealth(reachable=True, item_count=0),
    }
    return SimpleNamespace(**{**defaults, **use_cases})
