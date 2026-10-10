from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TopicImage:
    """An image attached to a topic. `key` locates the bytes in object storage and never reaches a client."""

    id: str
    key: str
    filename: str
    content_type: str
    size: int
    created_at: str
