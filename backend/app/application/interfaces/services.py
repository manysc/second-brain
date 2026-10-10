"""Ports for everything outside the database: models, object storage, the extract source, time and ids."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from app.domain.value_objects.extraction import ExtractedMeeting
from app.domain.value_objects.image_upload import ImageUpload


class Embedder(Protocol):
    """Turns text into the vectors that similarity search and topic matching compare."""

    def embed_text(self, text: str) -> list[float]: ...

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]: ...


class ImageStore(Protocol):
    """Private object storage for topic images."""

    def store(self, topic_id: str, image_id: str, upload: ImageUpload) -> str:
        """Stores the bytes and returns the key that locates them."""
        ...

    def load(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...


class ExtractSource(Protocol):
    """Where meeting extracts come from. Raises ExtractSourceUnavailable when it cannot be reached and
    MalformedExtract when a file cannot be understood."""

    def list_keys(self) -> list[str]:
        """Every extract, in the stable order they must be ingested in."""
        ...

    def load(self, key: str) -> list[ExtractedMeeting]:
        """The meeting(s) one extract file describes (a file may bundle several)."""
        ...


class Clock(Protocol):
    def now(self) -> datetime:
        """The current time, timezone-aware, in UTC."""
        ...


class IdGenerator(Protocol):
    def new_id(self) -> str:
        """A unique id in canonical UUID form (topics, items, history entries)."""
        ...

    def new_short_id(self) -> str:
        """A unique id without dashes (notes, images)."""
        ...
