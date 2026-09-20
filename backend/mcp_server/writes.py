"""Controlled writes. Each one goes through an existing app.data function; nothing here touches the DB directly."""
import logging
import threading
import time
from collections import deque
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app import data
from app.models import NoteCreate
from mcp_server.config import Config
from mcp_server.errors import BrainError, not_found
from mcp_server.schemas import AuditOut, WriteOut
from mcp_server.service import Snapshot, item_summary

audit_log = logging.getLogger("brain_mcp.audit")

AGENT_REASON_PREFIX = "[via MCP:"  # marks overrides written here so reads can tell them from human ones

_write_lock = threading.Lock()  # serialises check-then-write within this process


class ItemPatch(BaseModel):
    """The complete allowlist of updatable fields. Anything else is rejected."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["Open", "Closed"] | None = Field(default=None, description="New status.")
    priority_override: Literal["CRITICAL", "MAJOR", "MINOR", "CLEAR"] | None = Field(
        default=None,
        alias="priorityOverride",
        description="Manual priority override for this item. 'CLEAR' removes it (item then inherits its topic's priority).",
    )
    topic_id: str | None = Field(
        default=None,
        alias="topicId",
        pattern=r"^[A-Za-z0-9_.:\-]{1,200}$",
        description="Move the item to this existing topic.",
    )

    @model_validator(mode="after")
    def _not_empty(self) -> "ItemPatch":
        if not self.model_fields_set:
            raise ValueError("patch must set at least one field")
        return self


class ExpectedCurrent(BaseModel):
    """Optimistic-concurrency guard: the values the caller last read. The app has no version column."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["Open", "Closed"] | None = None
    priority: Literal["CRITICAL", "MAJOR", "MINOR"] | None = Field(
        default=None, description="The item's current effective priority."
    )
    topic_id: str | None = Field(default=None, alias="topicId")
    last_updated: str | None = Field(default=None, alias="lastUpdated", description="lastUpdated from a previous read.")


class WriteGuard:
    """Capability gate plus a sliding-window rate limit for write tools."""

    def __init__(self, config: Config, clock=time.monotonic) -> None:
        self._config = config
        self._clock = clock
        self._stamps: deque[float] = deque()

    def check(self) -> str:
        if not self._config.allow_writes:
            raise BrainError(
                "FORBIDDEN",
                "Write tools are disabled. The operator must start the server with BRAIN_MCP_ALLOW_WRITES=true.",
            )
        if not self._config.actor:
            raise BrainError("UNAUTHORIZED", "No acting identity is configured (BRAIN_MCP_ACTOR).")
        now = self._clock()
        while self._stamps and now - self._stamps[0] > 60:
            self._stamps.popleft()
        if len(self._stamps) >= self._config.write_rate_per_minute:
            raise BrainError("RATE_LIMITED", "Too many write operations this minute. Wait a moment and retry.")
        self._stamps.append(now)
        return self._config.actor


def _audit(actor: str, tool: str, item_id: str, fields: list[str], provenance: str, reason: str | None) -> AuditOut:
    # ids and field names only: never record body text or reasons that may echo sensitive content
    audit_log.info(
        "write actor=%s tool=%s item=%s fields=%s provenance=%r reason_given=%s",
        actor, tool, item_id, ",".join(fields), provenance[:80], bool(reason),
    )
    return AuditOut(actor=actor, recorded_in="mcp server stderr audit log (the app has no item audit table)", provenance=provenance)


def update_item(guard: WriteGuard, item_id: str, patch: ItemPatch, expected: ExpectedCurrent | None, reason: str | None, provenance: str) -> WriteOut:
    actor = guard.check()
    if not reason or len(reason.strip()) < 5:
        raise BrainError("VALIDATION_ERROR", "A reason (at least 5 characters) is required for status, priority or topic changes.")
    with _write_lock:
        snap = Snapshot.load()
        item = snap.item_or_404(item_id)
        if patch.topic_id is not None and patch.topic_id not in snap.topic_by_id:
            raise not_found("Topic", patch.topic_id)

        if expected is not None:
            current = {
                "status": item.status,
                "priority": item.effective_priority,
                "topicId": getattr(snap.topic_of_item.get(item.id), "id", None),
                "lastUpdated": item_summary(snap, item).last_updated,
            }
            for key, value in expected.model_dump(by_alias=True, exclude_unset=True).items():
                if current[key] != value:
                    raise BrainError(
                        "CONFLICT",
                        f"{key} is now {current[key]!r}, not {value!r}. Re-read the item with brain_get_item and retry.",
                    )

        applied: list[str] = []
        if patch.status is not None and patch.status != item.status:
            data.set_item_status(item_id, patch.status)
            applied.append("status")
        if patch.priority_override is not None:
            override = None if patch.priority_override == "CLEAR" else patch.priority_override
            data.set_item_priority_override(item_id, override, f"{AGENT_REASON_PREFIX}{actor}] {reason.strip()}" if override else None)
            applied.append("priorityOverride")
        if patch.topic_id is not None and patch.topic_id != getattr(snap.topic_of_item.get(item_id), "id", None):
            data.assign_item_topic(item_id, patch.topic_id)
            applied.append("topicId")

        fresh = Snapshot.load()
        audit = _audit(actor, "brain_update_item", item_id, applied, provenance, reason)
        return WriteOut(item=item_summary(fresh, fresh.item_or_404(item_id)), applied=applied, audit=audit)


def add_note(guard: WriteGuard, item_id: str, body: str, provenance: str) -> WriteOut:
    actor = guard.check()
    try:
        clean = NoteCreate(body=body).body  # reuse the app's own note validation
    except ValueError as exc:
        raise BrainError("VALIDATION_ERROR", "Note body must be 1-10000 non-blank characters.") from exc
    stamped = f"{clean}\n\n[Added via Brain MCP by {actor}; source: {provenance}]"
    with _write_lock:
        Snapshot.load().item_or_404(item_id)
        result = data.add_item_note(item_id, stamped)
        if result is None:
            raise not_found("Item", item_id)
        fresh = Snapshot.load()
        audit = _audit(actor, "brain_add_note", item_id, ["notes"], provenance, None)
        return WriteOut(
            item=item_summary(fresh, fresh.item_or_404(item_id)),
            applied=["notes"],
            audit=audit,
            note_id=result.notes[-1].id if result.notes else None,
        )
