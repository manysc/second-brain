from __future__ import annotations

from datetime import date


def parse_iso_date(value: str | None) -> date | None:
    """Only a strict ISO 'YYYY-MM-DD' prefix counts as a real date; anything else (or None) is
    treated as unknown, never as overdue - ambiguous source text must never be normalized into
    an invented date."""
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None
