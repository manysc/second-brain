"""In-memory domain objects for DB-free unit tests of the MCP layer."""
from app.models import Evidence, KnowledgeItem, ManualPriorityOverride, Meeting, Note, Topic


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
    notes: list[Note] | None = None,
    quote: str = "we said so",
) -> KnowledgeItem:
    return KnowledgeItem(
        id=item_id,
        type=item_type,
        description=description,
        status=status,
        confidence="HIGH",
        owner=owner,
        stakeholders=[],
        due_date=due_date,
        evidence=Evidence(speaker="Ada", timestamp="00:01:00", quote=quote),
        related_ids=related_ids or [],
        meeting_id=meeting_id,
        effective_priority=override or priority,
        manual_override=ManualPriorityOverride(priority=override, reason="because", overridden_at="2026-09-10T00:00:00+00:00")
        if override
        else None,
        notes=notes or [],
    )


def meeting(meeting_id: str, day: str, items: list[KnowledgeItem], title: str | None = None) -> Meeting:
    return Meeting(
        id=meeting_id, title=title or f"Meeting {meeting_id}", date=day, source_url=f"https://example.test/{meeting_id}",
        items=items, review_candidates=[], topics=[],
    )


def topic(topic_id: str, name: str, items: list[KnowledgeItem]) -> Topic:
    return Topic(id=topic_id, name=name, items=items, stakeholders=[])
