"""Time and identity from the host system."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class UuidGenerator:
    def new_id(self) -> str:
        return str(uuid.uuid4())

    def new_short_id(self) -> str:
        return uuid.uuid4().hex
