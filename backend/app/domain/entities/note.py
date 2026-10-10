from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Note:
    """A human-written note attached to exactly one knowledge item or topic; independent of ingestion."""

    id: str
    body: str
    created_at: str

    def with_body(self, body: str) -> Note:
        return replace(self, body=body)


def edit_note(notes: tuple[Note, ...], note_id: str, body: str) -> tuple[Note, ...]:
    """Editing a note that does not exist is a no-op."""
    return tuple(note.with_body(body) if note.id == note_id else note for note in notes)


def remove_note(notes: tuple[Note, ...], note_id: str) -> tuple[Note, ...]:
    """Removing a note that does not exist is a no-op."""
    return tuple(note for note in notes if note.id != note_id)
