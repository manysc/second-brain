from __future__ import annotations

from typing import Protocol

from app.domain.value_objects.priority import SemanticContribution


class SemanticClassifier(Protocol):
    """Optional, pluggable enhancement to topic priority. Must never be required for the system to work:
    an implementation returns None when it has nothing to say (disabled, model unavailable, ...)."""

    def classify(self, context: str) -> SemanticContribution | None: ...
