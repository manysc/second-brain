"""Providers for the optional semantic adjustment of topic priority (application.interfaces.SemanticClassifier)."""
from __future__ import annotations

import os
from functools import lru_cache

from app.domain.services.topic_priority import HYPOTHESES
from app.domain.value_objects.priority import SemanticContribution


class DisabledSemanticClassifier:
    """Default provider - performs no network/model access at all."""

    def classify(self, context: str) -> SemanticContribution | None:
        return None


class HuggingFaceZeroShotClassifier:
    """Optional zero-shot provider. Only constructed when explicitly enabled via
    TOPIC_PRIORITY_SEMANTIC_CLASSIFIER=huggingface - `transformers` is imported lazily inside
    classify() so importing this module never triggers a model download."""

    MODEL_NAME = "MoritzLaurer/ModernBERT-large-zeroshot-v2.0"

    @staticmethod
    @lru_cache(maxsize=1)
    def _pipeline(model_name: str):
        # built once per process - constructing it loads the model, and priority recalculation runs on
        # every review accept
        from transformers import pipeline  # lazy import: optional dependency

        return pipeline("zero-shot-classification", model=model_name)

    def classify(self, context: str) -> SemanticContribution | None:
        try:
            classifier = self._pipeline(self.MODEL_NAME)
        except Exception:
            return None
        try:
            result = classifier(context, list(HYPOTHESES.values()), multi_label=False)
            label_by_hypothesis = {v: k for k, v in HYPOTHESES.items()}
            scores = {label_by_hypothesis[label]: score for label, score in zip(result["labels"], result["scores"])}
        except Exception:
            return None
        return SemanticContribution(
            provider="huggingface",
            model=self.MODEL_NAME,
            scores={k: scores.get(k, 0.0) for k in ("critical", "major", "minor")},
            contribution=0.0,
            disagreement=False,
        )


def semantic_classifier_from_env() -> DisabledSemanticClassifier | HuggingFaceZeroShotClassifier:
    provider = os.environ.get("TOPIC_PRIORITY_SEMANTIC_CLASSIFIER", "disabled").strip().lower()
    if provider == "huggingface":
        return HuggingFaceZeroShotClassifier()
    return DisabledSemanticClassifier()
