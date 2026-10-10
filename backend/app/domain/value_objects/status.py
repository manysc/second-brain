"""Item/topic status. Items keep the extractor's free-text status; everything user-facing is Open/Closed."""
from __future__ import annotations

from typing import Literal

OpenClosed = Literal["Open", "Closed"]
ReviewStatus = Literal["PENDING", "ACCEPTED", "REJECTED"]

RESOLVED_STATUS_KEYWORDS: tuple[str, ...] = ("resolved", "closed", "done", "answered")
BLOCKED_STATUS_KEYWORDS: tuple[str, ...] = ("blocked", "blocker")


def is_resolved_status(status_text: str) -> bool:
    lowered = status_text.lower()
    return any(keyword in lowered for keyword in RESOLVED_STATUS_KEYWORDS)


def is_blocked_status(status_text: str) -> bool:
    lowered = status_text.lower()
    return any(keyword in lowered for keyword in BLOCKED_STATUS_KEYWORDS)


def to_open_closed(status_text: str) -> OpenClosed:
    """Legacy free-text statuses ("Answered", "Resolved", ...) collapse to the binary Open/Closed."""
    return "Closed" if is_resolved_status(status_text) else "Open"
