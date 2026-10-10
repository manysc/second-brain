from __future__ import annotations

from typing import Literal

Confidence = Literal["HIGH", "MEDIUM", "LOW"]

# search ranks HIGH-confidence items first; lower is better
CONFIDENCE_RANK: dict[str, int] = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
