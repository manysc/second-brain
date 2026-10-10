"""Free-text labels a human puts on topics and items; stored normalised."""
from __future__ import annotations

from collections.abc import Sequence

from app.domain.exceptions import TooManyTags

MAX_TAG_LENGTH = 40
MAX_TAGS = 20


def normalize_tag(value: str) -> str:
    """Trims, lowercases and collapses inner whitespace so 'Q3  Launch' and 'q3 launch' are one tag."""
    return " ".join(value.split()).lower()


def with_tag(current: Sequence[str] | None, tag: str) -> list[str]:
    """`current` plus the normalised tag; a tag already present is a no-op."""
    tag = normalize_tag(tag)
    tags = list(current or [])
    if tag in tags:
        return tags
    if len(tags) >= MAX_TAGS:
        raise TooManyTags(MAX_TAGS)
    return [*tags, tag]


def without_tag(current: Sequence[str] | None, tag: str) -> list[str]:
    tag = normalize_tag(tag)
    return [t for t in (current or []) if t != tag]
