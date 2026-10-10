from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Evidence:
    """The words an item or review candidate was extracted from."""

    speaker: str | None = None
    timestamp: str | None = None
    quote: str = ""
    context: str | None = None
