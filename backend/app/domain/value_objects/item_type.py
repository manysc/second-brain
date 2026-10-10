from __future__ import annotations

from typing import Literal, get_args

ItemType = Literal["IDEA", "DECISION", "ACTION", "QUESTION"]
ITEM_TYPES: tuple[str, ...] = get_args(ItemType)


def normalize_item_type(value: str) -> ItemType:
    """Extractor/review types outside the four known kinds are filed as ideas."""
    normalized = value.upper()
    return normalized if normalized in ITEM_TYPES else "IDEA"  # type: ignore[return-value]
