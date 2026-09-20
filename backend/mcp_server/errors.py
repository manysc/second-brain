"""Expected-failure vocabulary, exception mapping, and log/error redaction."""
import logging
import re
from typing import Literal

from pydantic import ValidationError
from sqlalchemy.exc import InterfaceError, OperationalError

from app import data

ErrorCode = Literal[
    "NOT_FOUND",
    "VALIDATION_ERROR",
    "UNAUTHORIZED",
    "FORBIDDEN",
    "CONFLICT",
    "DEPENDENCY_UNAVAILABLE",
    "RATE_LIMITED",
    "INTERNAL_ERROR",
]

logger = logging.getLogger("brain_mcp")

# credentials embedded in URLs, key=value secrets, and AWS-style access key ids
_REDACTIONS = [
    (re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^\s/@:]+:[^\s/@]+@"), r"\1***:***@"),
    (re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key|access[_-]?key)\s*[=:]\s*\S+"), r"\1=***"),
    (re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{12,}\b"), "***"),
]


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        return True


class BrainError(Exception):
    """An anticipated failure whose message is safe and useful to show Claude."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code: ErrorCode = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


def not_found(kind: str, identifier: str) -> BrainError:
    return BrainError("NOT_FOUND", f"{kind} '{identifier}' was not found. Use brain_search_items to find valid IDs.")


def map_exception(exc: BaseException) -> BrainError:
    """Turns any exception into a BrainError without leaking SQL, paths, stack traces or secrets."""
    if isinstance(exc, BrainError):
        return exc
    if isinstance(exc, (data.TopicNameConflict, data.ReviewCandidateAlreadyDecided, data.TopicHasItems)):
        return BrainError("CONFLICT", "The operation conflicts with the current state of the record.")
    if isinstance(exc, ValidationError):
        # loc + message only: pydantic's default text echoes input values
        details = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'input'}: {e['msg']}" for e in exc.errors()[:3])
        return BrainError("VALIDATION_ERROR", details[:300])
    if isinstance(exc, ValueError):
        return BrainError("VALIDATION_ERROR", redact(str(exc))[:300] or "Invalid input.")
    if isinstance(exc, (OperationalError, InterfaceError)):
        return BrainError("DEPENDENCY_UNAVAILABLE", "The Brain Assistant database is unreachable. Is Postgres running?")
    if isinstance(exc, RuntimeError) and "DATABASE_URL" in str(exc):
        return BrainError("DEPENDENCY_UNAVAILABLE", "DATABASE_URL is not configured for the MCP server.")
    # unknown: log only the type; the message may contain SQL or data
    logger.error("unexpected %s in tool call", type(exc).__name__)
    return BrainError("INTERNAL_ERROR", "Unexpected server error. See the MCP server's stderr log.")
