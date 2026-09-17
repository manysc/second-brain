"""Deterministic Topic priority classification (CRITICAL/MAJOR/MINOR).

Architecture (see docs/implementation-status.md for the full design writeup):

    TopicPrioritySignalExtractor  (DB-touching: reads items/meetings/related_ids)
            -> TopicPriorityFacts (plain dataclass, no DB)
    TopicPriorityScorer.score()  (pure function: facts -> TopicPriorityInfo)
            -> optionally adjusted by an optional, bounded semantic classifier

The scorer is intentionally DB-free so it can be unit-tested and calibrated without a database
(see backend/tests/test_topic_priority.py).

This repo's real domain is simpler than a generic "priority classification" spec would assume:
there are no typed BLOCKS/DEPENDS_ON relationships, Outcomes, or production/security flags -
only a free-text `status` field (observed value: almost always "Open"), an untyped `related_ids`
link list, and a raw `due_date` string. Signals below are adapted accordingly: structural
evidence (status text, parsed due dates, related_ids graph reach) is weighted more heavily than
bounded, capped keyword heuristics over free text, and heuristics can never alone trigger a hard
escalation rule.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import KnowledgeItemRow, MeetingRow, TopicRow
from app.models import (
    HardEscalation,
    ManualPriorityOverride,
    PriorityConfidence,
    SemanticContribution,
    TopicPriorityInfo,
    TopicPriorityLevel,
    TopicPrioritySignal,
)

TOPIC_PRIORITY_ALGORITHM_VERSION = "1.0"

# Centralized configuration so weights/thresholds/decay never get scattered as magic numbers.
PRIORITY_CONFIG = {
    "weights": {
        "impact": 25,
        "urgency": 20,
        "risk": 20,
        "dependency": 15,
        "execution": 10,
        "momentum": 10,
    },
    # sub-caps within a dimension must sum to that dimension's weight above
    "impact_subcaps": {"decisions": 14, "stakeholders": 5, "keyword_heuristic": 6},
    "risk_subcaps": {"structural_blocked": 16, "keyword_heuristic": 4},
    "execution_subcaps": {"unresolved_volume": 7, "overdue_bonus": 3},
    "thresholds": {"critical": 75, "major": 45},
    "hysteresis": {"critical_demote_below": 70, "major_demote_below": 40},
    "urgency_buckets_days": [(0, 20), (3, 18), (7, 14), (14, 8)],  # (max_days_until, score)
    "momentum_decay_buckets": [(7, 1.0), (14, 0.7), (30, 0.4), (60, 0.2)],  # (max_age_days, weight)
    "momentum_decay_floor": 0.05,
    "momentum_scale": 2.5,
    "dependency_reach_cap": 8,
    "decision_diminishing_cap": 4,
    "stakeholder_diminishing_cap": 6,
    "impact_keyword_diminishing_cap": 3,
    "risk_keyword_diminishing_cap": 3,
    "unresolved_diminishing_cap": 6,
    "semantic_max_adjustment": 10,
    "blocked_status_keywords": ("blocked", "blocker"),
    "resolved_status_keywords": ("resolved", "closed", "done", "answered"),
    "impact_keywords": ("production", "customer", "outage", "compliance", "security", "revenue", "release"),
    "risk_keywords": ("block", "blocker", "at risk", "risk of", "escalat"),
}


def _diminishing_returns(count: int, cap: int) -> float:
    """0..1, sub-linear so e.g. 1->2 matters far more than 51->52 (spec section 11/13)."""
    if count <= 0 or cap <= 0:
        return 0.0
    return min(1.0, math.log2(1 + count) / math.log2(1 + cap))


def _parse_iso_date(value: str | None) -> date | None:
    """Only a strict ISO 'YYYY-MM-DD' prefix counts as a real date; anything else (or None) is
    treated as unknown, never as overdue - ambiguous source text must never be normalized into
    an invented date (spec section 9)."""
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _is_structurally_blocked(status_text: str) -> bool:
    lowered = status_text.lower()
    return any(keyword in lowered for keyword in PRIORITY_CONFIG["blocked_status_keywords"])


def _is_resolved_status(status_text: str) -> bool:
    lowered = status_text.lower()
    return any(keyword in lowered for keyword in PRIORITY_CONFIG["resolved_status_keywords"])


def _keyword_hits(text: str, keywords: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(1 for keyword in keywords if keyword in lowered)


@dataclass
class ItemFact:
    id: str
    type: str
    status_text: str
    confidence: str
    due_date: date | None
    has_ambiguous_due_date: bool
    stakeholder_count: int
    heuristic_text: str


@dataclass
class TopicPriorityFacts:
    topic_id: str
    items: list[ItemFact] = field(default_factory=list)
    distinct_meeting_ages_days: list[int] = field(default_factory=list)
    decision_count: int = 0
    stakeholder_total: int = 0
    external_dependency_reach: int = 0
    reference_date: date = field(default_factory=lambda: datetime.now(timezone.utc).date())


class TopicPrioritySignalExtractor:
    """Reads the topic's items + related meetings + cross-topic related_ids graph. The only
    DB-touching piece of the pipeline - kept separate from TopicPriorityScorer so scoring stays
    pure and unit-testable."""

    def extract(self, session: Session, topic_row: TopicRow, reference_date: date | None = None) -> TopicPriorityFacts:
        items = list(topic_row.items)
        item_ids = [item.id for item in items]
        meeting_ids = list({item.meeting_id for item in items})
        meeting_dates: dict[str, str] = {}
        if meeting_ids:
            rows = session.execute(select(MeetingRow.id, MeetingRow.date).where(MeetingRow.id.in_(meeting_ids))).all()
            meeting_dates = {row.id: row.date for row in rows}

        ref_date = reference_date or datetime.now(timezone.utc).date()

        item_facts: list[ItemFact] = []
        for item in items:
            due = _parse_iso_date(item.due_date)
            ambiguous = due is None and bool(item.due_date_source_text)
            heuristic_text = " ".join(
                part
                for part in (item.description, item.rationale, item.resolution, item.evidence_quote)
                if part
            )
            item_facts.append(
                ItemFact(
                    id=item.id,
                    type=item.type,
                    status_text=item.status or "",
                    confidence=item.confidence,
                    due_date=due,
                    has_ambiguous_due_date=ambiguous,
                    stakeholder_count=len(item.stakeholders or []),
                    heuristic_text=heuristic_text,
                )
            )

        meeting_ages: list[int] = []
        for meeting_id in meeting_ids:
            parsed = _parse_iso_date(meeting_dates.get(meeting_id))
            if parsed is not None:
                meeting_ages.append((ref_date - parsed).days)

        decision_count = sum(1 for item in items if item.type == "DECISION")
        stakeholder_total = len({s for item in items for s in (item.stakeholders or [])})
        dependency_reach = self._dependency_reach(session, topic_row.id, item_ids)

        return TopicPriorityFacts(
            topic_id=topic_row.id,
            items=item_facts,
            distinct_meeting_ages_days=meeting_ages,
            decision_count=decision_count,
            stakeholder_total=stakeholder_total,
            external_dependency_reach=dependency_reach,
            reference_date=ref_date,
        )

    @staticmethod
    def _dependency_reach(session: Session, topic_id: str, item_ids: list[str]) -> int:
        """Distinct OTHER topics reached via the untyped related_ids link, in either direction.
        Called "dependency reach / connectivity" deliberately, not "importance" (spec section 11)."""
        all_rows = session.execute(
            select(KnowledgeItemRow.id, KnowledgeItemRow.topic_id, KnowledgeItemRow.related_ids)
        ).all()
        topic_by_id = {row.id: row.topic_id for row in all_rows}
        related_by_id = {row.id: (row.related_ids or []) for row in all_rows}
        item_id_set = set(item_ids)
        reached: set[str] = set()
        for iid in item_ids:
            for rid in related_by_id.get(iid, []):
                other_topic = topic_by_id.get(rid)
                if other_topic and other_topic != topic_id:
                    reached.add(other_topic)
        for row in all_rows:
            if row.topic_id and row.topic_id != topic_id:
                if any(rid in item_id_set for rid in (row.related_ids or [])):
                    reached.add(row.topic_id)
        return len(reached)


@dataclass
class PreviousPriorityState:
    priority: TopicPriorityLevel
    score: float


class TopicPriorityScorer:
    """Pure scoring function: facts (+ optional previous state / semantic contribution) -> a
    TopicPriorityInfo. No DB access - this is what calibration and unit tests exercise directly."""

    def score(
        self,
        facts: TopicPriorityFacts,
        previous: PreviousPriorityState | None = None,
        semantic: SemanticContribution | None = None,
    ) -> TopicPriorityInfo:
        signals: list[TopicPrioritySignal] = []

        impact_score, impact_signals = self._score_impact(facts)
        urgency_score, urgency_signals = self._score_urgency(facts)
        risk_score, risk_signals = self._score_risk(facts)
        dependency_score, dependency_signals = self._score_dependency(facts)
        execution_score, execution_signals = self._score_execution(facts)
        momentum_score, momentum_signals = self._score_momentum(facts)
        signals.extend(impact_signals + urgency_signals + risk_signals + dependency_signals + execution_signals + momentum_signals)

        deterministic_score = impact_score + urgency_score + risk_score + dependency_score + execution_score + momentum_score
        deterministic_score = min(100.0, deterministic_score)

        escalations = self._hard_escalations(facts)

        score = deterministic_score
        semantic_contribution: SemanticContribution | None = None
        if semantic is not None:
            score, semantic_contribution = self._apply_semantic(deterministic_score, semantic)

        previous_priority = previous.priority if previous else None
        calculated_priority = self._classify(score, previous_priority)

        if escalations and calculated_priority != "CRITICAL":
            # hard escalation bypasses hysteresis upward only - never used to demote
            calculated_priority = "CRITICAL"
            score = max(score, PRIORITY_CONFIG["thresholds"]["critical"])

        confidence = self._confidence(facts, disagreement=bool(semantic_contribution and semantic_contribution.disagreement))

        explanation = self._explain(calculated_priority, score, signals, escalations)

        return TopicPriorityInfo(
            calculated_priority=calculated_priority,
            calculated_score=round(score, 1),
            effective_priority=calculated_priority,  # caller overlays manual override if present
            confidence=confidence,
            signals=signals,
            hard_escalations=escalations,
            explanation=explanation,
            calculated_at=datetime.now(timezone.utc).isoformat(),
            algorithm_version=TOPIC_PRIORITY_ALGORITHM_VERSION,
            semantic_contribution=semantic_contribution,
            manual_override=None,
        )

    # -- dimension scorers -------------------------------------------------

    def _score_impact(self, facts: TopicPriorityFacts) -> tuple[float, list[TopicPrioritySignal]]:
        caps = PRIORITY_CONFIG["impact_subcaps"]
        decision_component = _diminishing_returns(facts.decision_count, PRIORITY_CONFIG["decision_diminishing_cap"]) * caps["decisions"]
        stakeholder_component = _diminishing_returns(facts.stakeholder_total, PRIORITY_CONFIG["stakeholder_diminishing_cap"]) * caps["stakeholders"]
        keyword_hits = sum(_keyword_hits(item.heuristic_text, PRIORITY_CONFIG["impact_keywords"]) for item in facts.items)
        keyword_component = _diminishing_returns(keyword_hits, PRIORITY_CONFIG["impact_keyword_diminishing_cap"]) * caps["keyword_heuristic"]
        total = decision_component + stakeholder_component + keyword_component
        source_ids = [item.id for item in facts.items]
        signals = [
            TopicPrioritySignal(
                type="impact_decisions",
                raw_value=facts.decision_count,
                normalized_score=decision_component / caps["decisions"] if caps["decisions"] else 0,
                weighted_score=round(decision_component, 1),
                max_score=caps["decisions"],
                explanation=f"{facts.decision_count} decision(s) recorded for this topic",
                source_knowledge_item_ids=[i.id for i in facts.items if i.type == "DECISION"],
            ),
            TopicPrioritySignal(
                type="impact_stakeholder_breadth",
                raw_value=facts.stakeholder_total,
                normalized_score=stakeholder_component / caps["stakeholders"] if caps["stakeholders"] else 0,
                weighted_score=round(stakeholder_component, 1),
                max_score=caps["stakeholders"],
                explanation=f"{facts.stakeholder_total} distinct stakeholder(s) involved",
                source_knowledge_item_ids=source_ids,
            ),
            TopicPrioritySignal(
                type="impact_keyword_heuristic",
                raw_value=keyword_hits,
                normalized_score=keyword_component / caps["keyword_heuristic"] if caps["keyword_heuristic"] else 0,
                weighted_score=round(keyword_component, 1),
                max_score=caps["keyword_heuristic"],
                explanation=(
                    f"{keyword_hits} mention(s) of impact-related terms in item text (bounded, "
                    "low-confidence text heuristic - not a confirmed structural signal)"
                ),
                source_knowledge_item_ids=source_ids,
            ),
        ]
        return total, signals

    def _score_urgency(self, facts: TopicPriorityFacts) -> tuple[float, list[TopicPrioritySignal]]:
        buckets = PRIORITY_CONFIG["urgency_buckets_days"]
        best_score = 0.0
        best_item: ItemFact | None = None
        ambiguous_ids: list[str] = []
        for item in facts.items:
            if item.has_ambiguous_due_date:
                ambiguous_ids.append(item.id)
                continue
            if item.due_date is None:
                continue
            days_until = (item.due_date - facts.reference_date).days
            for max_days, bucket_score in buckets:
                if days_until <= max_days:
                    if bucket_score > best_score:
                        best_score = bucket_score
                        best_item = item
                    break
        signals = []
        if best_item is not None:
            days_until = (best_item.due_date - facts.reference_date).days  # type: ignore[operator]
            descriptor = "overdue" if days_until < 0 else f"due in {days_until} day(s)"
            signals.append(
                TopicPrioritySignal(
                    type="urgency_due_date",
                    raw_value=str(best_item.due_date),
                    normalized_score=best_score / PRIORITY_CONFIG["weights"]["urgency"],
                    weighted_score=round(best_score, 1),
                    max_score=PRIORITY_CONFIG["weights"]["urgency"],
                    explanation=f"Most urgent item is {descriptor}",
                    source_knowledge_item_ids=[best_item.id],
                )
            )
        else:
            signals.append(
                TopicPrioritySignal(
                    type="urgency_due_date",
                    raw_value=None,
                    normalized_score=0,
                    weighted_score=0,
                    max_score=PRIORITY_CONFIG["weights"]["urgency"],
                    explanation="No confirmed due date found; no deadline-based urgency applied",
                    source_knowledge_item_ids=[],
                )
            )
        if ambiguous_ids:
            signals.append(
                TopicPrioritySignal(
                    type="urgency_ambiguous_due_date_ignored",
                    raw_value=len(ambiguous_ids),
                    normalized_score=0,
                    weighted_score=0,
                    max_score=0,
                    explanation="Item(s) had unparseable/ambiguous due-date source text; not treated as overdue or scored",
                    source_knowledge_item_ids=ambiguous_ids,
                )
            )
        return best_score, signals

    def _score_risk(self, facts: TopicPriorityFacts) -> tuple[float, list[TopicPrioritySignal]]:
        caps = PRIORITY_CONFIG["risk_subcaps"]
        blocked_items = [item for item in facts.items if _is_structurally_blocked(item.status_text)]
        structural_component = _diminishing_returns(len(blocked_items), 2) * caps["structural_blocked"]
        keyword_hits = sum(_keyword_hits(item.heuristic_text, PRIORITY_CONFIG["risk_keywords"]) for item in facts.items)
        keyword_component = _diminishing_returns(keyword_hits, PRIORITY_CONFIG["risk_keyword_diminishing_cap"]) * caps["keyword_heuristic"]
        total = structural_component + keyword_component
        signals = [
            TopicPrioritySignal(
                type="risk_structural_blocked_status",
                raw_value=len(blocked_items),
                normalized_score=structural_component / caps["structural_blocked"] if caps["structural_blocked"] else 0,
                weighted_score=round(structural_component, 1),
                max_score=caps["structural_blocked"],
                explanation=f"{len(blocked_items)} item(s) have a confirmed blocked status",
                source_knowledge_item_ids=[i.id for i in blocked_items],
            ),
            TopicPrioritySignal(
                type="risk_keyword_heuristic",
                raw_value=keyword_hits,
                normalized_score=keyword_component / caps["keyword_heuristic"] if caps["keyword_heuristic"] else 0,
                weighted_score=round(keyword_component, 1),
                max_score=caps["keyword_heuristic"],
                explanation=(
                    f"{keyword_hits} mention(s) of blocking/risk-related terms in item text (bounded, "
                    "low-confidence text heuristic)"
                ),
                source_knowledge_item_ids=[item.id for item in facts.items],
            ),
        ]
        return total, signals

    def _score_dependency(self, facts: TopicPriorityFacts) -> tuple[float, list[TopicPrioritySignal]]:
        weight = PRIORITY_CONFIG["weights"]["dependency"]
        component = _diminishing_returns(facts.external_dependency_reach, PRIORITY_CONFIG["dependency_reach_cap"]) * weight
        signal = TopicPrioritySignal(
            type="dependency_reach",
            raw_value=facts.external_dependency_reach,
            normalized_score=component / weight if weight else 0,
            weighted_score=round(component, 1),
            max_score=weight,
            explanation=f"Connected to {facts.external_dependency_reach} other topic(s) via related evidence links",
            source_knowledge_item_ids=[item.id for item in facts.items],
        )
        return component, [signal]

    def _score_execution(self, facts: TopicPriorityFacts) -> tuple[float, list[TopicPrioritySignal]]:
        caps = PRIORITY_CONFIG["execution_subcaps"]
        unresolved = [
            item
            for item in facts.items
            if item.type in ("ACTION", "QUESTION") and not _is_resolved_status(item.status_text)
        ]
        volume_component = _diminishing_returns(len(unresolved), PRIORITY_CONFIG["unresolved_diminishing_cap"]) * caps["unresolved_volume"]
        overdue_actions = [
            item for item in unresolved if item.type == "ACTION" and item.due_date and item.due_date < facts.reference_date
        ]
        overdue_bonus = caps["overdue_bonus"] if overdue_actions else 0
        total = min(PRIORITY_CONFIG["weights"]["execution"], volume_component + overdue_bonus)
        signals = [
            TopicPrioritySignal(
                type="execution_unresolved_volume",
                raw_value=len(unresolved),
                normalized_score=volume_component / caps["unresolved_volume"] if caps["unresolved_volume"] else 0,
                weighted_score=round(volume_component, 1),
                max_score=caps["unresolved_volume"],
                explanation=f"{len(unresolved)} unresolved action(s)/question(s) (capped, not raw count)",
                source_knowledge_item_ids=[i.id for i in unresolved],
            ),
            TopicPrioritySignal(
                type="execution_overdue_action_bonus",
                raw_value=len(overdue_actions),
                normalized_score=1.0 if overdue_actions else 0.0,
                weighted_score=overdue_bonus,
                max_score=caps["overdue_bonus"],
                explanation=f"{len(overdue_actions)} overdue action(s) add a severity bonus over raw count",
                source_knowledge_item_ids=[i.id for i in overdue_actions],
            ),
        ]
        return total, signals

    def _score_momentum(self, facts: TopicPriorityFacts) -> tuple[float, list[TopicPrioritySignal]]:
        buckets = PRIORITY_CONFIG["momentum_decay_buckets"]
        floor = PRIORITY_CONFIG["momentum_decay_floor"]
        raw = 0.0
        for age_days in facts.distinct_meeting_ages_days:
            weight = floor
            for max_age, bucket_weight in buckets:
                if age_days <= max_age:
                    weight = bucket_weight
                    break
            raw += weight
        weight_cap = PRIORITY_CONFIG["weights"]["momentum"]
        component = min(weight_cap, raw * PRIORITY_CONFIG["momentum_scale"])
        signal = TopicPrioritySignal(
            type="momentum_recency_weighted_meetings",
            raw_value=len(facts.distinct_meeting_ages_days),
            normalized_score=component / weight_cap if weight_cap else 0,
            weighted_score=round(component, 1),
            max_score=weight_cap,
            explanation=(
                f"{len(facts.distinct_meeting_ages_days)} distinct meeting(s) reference this topic, "
                "weighted by recency (older activity decays toward zero)"
            ),
            source_knowledge_item_ids=[item.id for item in facts.items],
        )
        return component, [signal]

    # -- hard escalation -----------------------------------------------------

    def _hard_escalations(self, facts: TopicPriorityFacts) -> list[HardEscalation]:
        escalations: list[HardEscalation] = []
        for item in facts.items:
            if not _is_structurally_blocked(item.status_text):
                continue
            if item.due_date is None:
                continue
            days_until = (item.due_date - facts.reference_date).days
            if days_until <= 7:
                escalations.append(
                    HardEscalation(
                        rule_id="confirmed-block-imminent-deadline",
                        reason=(
                            "Item has a confirmed blocked status and an imminent or overdue deadline, "
                            "escalating regardless of accumulated score"
                        ),
                        source_knowledge_item_ids=[item.id],
                    )
                )
        return escalations

    # -- confidence ------------------------------------------------------

    def _confidence(self, facts: TopicPriorityFacts, disagreement: bool) -> PriorityConfidence:
        points = 0
        if len(facts.distinct_meeting_ages_days) >= 2:
            points += 1
        if any(item.confidence == "HIGH" for item in facts.items):
            points += 1
        if facts.items and all(item.confidence == "LOW" for item in facts.items):
            points -= 1
        if any(item.due_date is not None for item in facts.items):
            points += 1
        if any(_is_structurally_blocked(item.status_text) for item in facts.items):
            points += 1
        if len(facts.items) >= 3:
            points += 1
        if len(facts.items) <= 1:
            points -= 1
        level: PriorityConfidence = "HIGH" if points >= 3 else "MEDIUM" if points >= 0 else "LOW"
        if disagreement and level == "HIGH":
            level = "MEDIUM"
        return level

    # -- classification / hysteresis -----------------------------------------

    def _classify(self, score: float, previous_priority: TopicPriorityLevel | None) -> TopicPriorityLevel:
        thresholds = PRIORITY_CONFIG["thresholds"]
        hysteresis = PRIORITY_CONFIG["hysteresis"]
        if previous_priority == "CRITICAL":
            if score < hysteresis["critical_demote_below"]:
                return "MAJOR" if score >= thresholds["major"] else "MINOR"
            return "CRITICAL"
        if previous_priority == "MAJOR":
            if score >= thresholds["critical"]:
                return "CRITICAL"
            if score < hysteresis["major_demote_below"]:
                return "MINOR"
            return "MAJOR"
        # MINOR or first-ever calculation: plain thresholds, promotion is never delayed
        if score >= thresholds["critical"]:
            return "CRITICAL"
        if score >= thresholds["major"]:
            return "MAJOR"
        return "MINOR"

    # -- semantic adjustment (bounded, optional) -----------------------------

    def _apply_semantic(self, deterministic_score: float, semantic: SemanticContribution) -> tuple[float, SemanticContribution]:
        max_adjustment = PRIORITY_CONFIG["semantic_max_adjustment"]
        deterministic_priority = self._classify(deterministic_score, None)
        rank = {"MINOR": 0, "MAJOR": 1, "CRITICAL": 2}
        # semantic.scores keys are lowercase ("critical"/"major"/"minor" per spec section 18)
        top_label = max(semantic.scores, key=lambda k: semantic.scores[k]).upper()
        sorted_scores = sorted(semantic.scores.values(), reverse=True)
        margin = sorted_scores[0] - (sorted_scores[1] if len(sorted_scores) > 1 else 0.0)
        direction = 1 if rank[top_label] > rank[deterministic_priority] else (-1 if rank[top_label] < rank[deterministic_priority] else 0)
        contribution = direction * min(max_adjustment, margin * max_adjustment * 2)
        disagreement = abs(rank[top_label] - rank[deterministic_priority]) >= 1 and margin > 0.2
        adjusted = max(0.0, min(100.0, deterministic_score + contribution))
        result = SemanticContribution(
            provider=semantic.provider,
            model=semantic.model,
            scores=semantic.scores,
            contribution=round(contribution, 1),
            disagreement=disagreement,
        )
        return adjusted, result

    def _explain(
        self,
        priority: TopicPriorityLevel,
        score: float,
        signals: list[TopicPrioritySignal],
        escalations: list[HardEscalation],
    ) -> str:
        if escalations:
            return f"{priority} ({round(score, 1)}/100): " + "; ".join(e.reason for e in escalations)
        top_drivers = sorted((s for s in signals if s.weighted_score > 0), key=lambda s: s.weighted_score, reverse=True)[:3]
        driver_text = "; ".join(f"{s.explanation}" for s in top_drivers) or "limited supporting evidence"
        return f"{priority} ({round(score, 1)}/100): {driver_text}"


# --- optional semantic classifier abstraction -------------------------------------------------

Provider = Literal["disabled", "huggingface"]

HYPOTHESES = {
    "CRITICAL": (
        "This topic represents an immediate, high-impact concern that requires urgent attention "
        "because it materially blocks delivery, creates significant operational risk, affects a "
        "critical outcome, or has severe near-term consequences."
    ),
    "MAJOR": (
        "This topic materially affects delivery, outcomes, coordination, or risk and requires "
        "deliberate attention, but the evidence does not indicate an immediate crisis."
    ),
    "MINOR": (
        "This topic has limited current impact, urgency, dependency reach, or execution risk and "
        "can reasonably receive lower attention than other active topics."
    ),
}


class TopicPrioritySemanticClassifier:
    """Optional, pluggable enhancement. Must never be required for the system to work."""

    def classify(self, context: str) -> SemanticContribution | None:
        raise NotImplementedError


class DisabledSemanticClassifier(TopicPrioritySemanticClassifier):
    """Default provider - performs no network/model access at all."""

    def classify(self, context: str) -> SemanticContribution | None:
        return None


class HuggingFaceZeroShotClassifier(TopicPrioritySemanticClassifier):
    """Optional zero-shot provider. Only constructed when explicitly enabled via
    TOPIC_PRIORITY_SEMANTIC_CLASSIFIER=huggingface - `transformers` is imported lazily inside
    classify() so importing this module never triggers a model download."""

    MODEL_NAME = "MoritzLaurer/ModernBERT-large-zeroshot-v2.0"

    def classify(self, context: str) -> SemanticContribution | None:
        try:
            from transformers import pipeline  # lazy import: optional dependency
        except Exception:
            return None
        try:
            classifier = pipeline("zero-shot-classification", model=self.MODEL_NAME)
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


def get_semantic_classifier() -> TopicPrioritySemanticClassifier:
    provider = os.environ.get("TOPIC_PRIORITY_SEMANTIC_CLASSIFIER", "disabled").strip().lower()
    if provider == "huggingface":
        return HuggingFaceZeroShotClassifier()
    return DisabledSemanticClassifier()


def build_semantic_context(topic_row: TopicRow, facts: TopicPriorityFacts) -> str:
    """Grounded-only context string for the semantic classifier - no invented assumptions."""
    lines = [f"Topic: {topic_row.name}"]
    for item in facts.items[:20]:
        lines.append(f"- [{item.type}] status={item.status_text or 'unknown'} due={item.due_date or 'none'}")
    return "\n".join(lines)
