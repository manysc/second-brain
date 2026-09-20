"""Opaque offset cursors, bound to the query they were issued for."""
import base64
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import TypeVar

from mcp_server.errors import BrainError

T = TypeVar("T")

MAX_LIMIT = 50
DEFAULT_LIMIT = 20


def _fingerprint(params: Mapping[str, object]) -> str:
    blob = json.dumps(params, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


def encode_cursor(offset: int, params: Mapping[str, object]) -> str:
    raw = json.dumps({"o": offset, "f": _fingerprint(params)}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str | None, params: Mapping[str, object]) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
        offset, fingerprint = int(payload["o"]), str(payload["f"])
    except (ValueError, KeyError, TypeError) as exc:
        raise BrainError("VALIDATION_ERROR", "Invalid cursor. Omit it to start from the first page.") from exc
    if offset < 0 or fingerprint != _fingerprint(params):
        raise BrainError("VALIDATION_ERROR", "Cursor does not match these filters. Omit it to restart.")
    return offset


def paginate(
    rows: Sequence[T], limit: int, cursor: str | None, params: Mapping[str, object]
) -> tuple[list[T], str | None]:
    """Slices an already deterministically-ordered list; returns (page, nextCursor)."""
    offset = decode_cursor(cursor, params)
    page = list(rows[offset : offset + limit])
    next_offset = offset + limit
    return page, (encode_cursor(next_offset, params) if next_offset < len(rows) else None)
