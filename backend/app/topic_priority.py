"""Legacy import path for topic priority. The scorer, its facts and config live in
app.domain.services.topic_priority; the classifier providers in app.infrastructure. What remains here is
the SQLAlchemy-backed fact gathering and Pydantic-returning wrappers that app.data still uses."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import KnowledgeItemRow, MeetingRow, TopicRow
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


class TopicPrioritySignalExtractor:
    """Reads the topic's items + related meetings + cross-topic related_ids graph."""

    def extract(self, session: Session, topic_row: TopicRow, reference_date: date | None = None) -> TopicPriorityFacts:
        items = list(topic_row.items)
        item_ids = [item.id for item in items]
        meeting_ids = list({item.meeting_id for item in items})
        meeting_dates: dict[str, str] = {}
        if meeting_ids:
            rows = session.execute(select(MeetingRow.id, MeetingRow.date).where(MeetingRow.id.in_(meeting_ids))).all()
            meeting_dates = {row.id: row.date for row in rows}

        ref_date = reference_date or datetime.now(timezone.utc).date()
        all_rows = session.execute(
            select(KnowledgeItemRow.id, KnowledgeItemRow.topic_id, KnowledgeItemRow.related_ids)
        ).all()

        return TopicPriorityFacts(
            topic_id=topic_row.id,
            items=[
                _domain.item_fact(
                    item_id=item.id,
                    item_type=item.type,
                    status_text=item.status,
                    confidence=item.confidence,
                    due_date=item.due_date,
                    due_date_source_text=item.due_date_source_text,
                    stakeholders=item.stakeholders,
                    description=item.description,
                    rationale=item.rationale,
                    resolution=item.resolution,
                    evidence_quote=item.evidence_quote,
                )
                for item in items
            ],
            distinct_meeting_ages_days=_domain.meeting_ages_days(
                (meeting_dates.get(meeting_id) for meeting_id in meeting_ids), ref_date
            ),
            decision_count=sum(1 for item in items if item.type == "DECISION"),
            stakeholder_total=len({s for item in items for s in (item.stakeholders or [])}),
            external_dependency_reach=_domain.dependency_reach(
                topic_row.id,
                item_ids,
                {row.id: row.topic_id for row in all_rows},
                {row.id: (row.related_ids or []) for row in all_rows},
            ),
            reference_date=ref_date,
        )


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
