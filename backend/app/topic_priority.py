"""Legacy import path for topic priority. The scorer, its facts and config live in
app.domain.services.topic_priority, fact gathering in app.application.services.priority_recalculation and the
classifier providers in app.infrastructure. What remains here are re-exports and a Pydantic-returning scorer
for the existing tests."""
from __future__ import annotations

from app.db_models import TopicRow
from app.domain.services import topic_priority as _domain
from app.domain.services.topic_priority import (  # noqa: F401  (re-exported)
    HYPOTHESES,
    PRIORITY_CONFIG,
    TOPIC_PRIORITY_ALGORITHM_VERSION,
    ItemFact,
    PreviousPriorityState,
    TopicPriorityFacts,
)
from app.domain.value_objects.dates import parse_iso_date  # noqa: F401
from app.domain.value_objects.status import is_resolved_status  # noqa: F401
from app.infrastructure.external_services.semantic_classifiers import (  # noqa: F401
    DisabledSemanticClassifier,
    HuggingFaceZeroShotClassifier,
    semantic_classifier_from_env as get_semantic_classifier,
)
from app.models import SemanticContribution, TopicPriorityInfo


class TopicPriorityScorer(_domain.TopicPriorityScorer):
    """The domain scorer, returning the Pydantic TopicPriorityInfo app.data persists and serves."""

    def score(  # type: ignore[override]
        self,
        facts: TopicPriorityFacts,
        previous: PreviousPriorityState | None = None,
        semantic: SemanticContribution | None = None,
    ) -> TopicPriorityInfo:
        return TopicPriorityInfo.model_validate(super().score(facts, previous, semantic), from_attributes=True)


def build_semantic_context(topic_row: TopicRow, facts: TopicPriorityFacts) -> str:
    return _domain.build_semantic_context(topic_row.name, facts)
