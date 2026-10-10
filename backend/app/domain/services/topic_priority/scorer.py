"""Deterministic Topic priority classification (CRITICAL/MAJOR/MINOR).

    TopicPriorityFacts (plain data gathered by the caller)
        -> TopicPriorityScorer.score()  (pure function: facts -> TopicPriorityInfo)
        -> optionally adjusted by an optional, bounded semantic classifier

The scorer does no I/O, so it can be unit-tested and calibrated without a database
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
from datetime import datetime, timezone

from app.domain.services.topic_priority.config import (
    PRIORITY_CONFIG,
    TOPIC_PRIORITY_ALGORITHM_VERSION,
)
from app.domain.services.topic_priority.facts import (
    ItemFact,
    PreviousPriorityState,
    TopicPriorityFacts,
)
from app.domain.value_objects.priority import (
    HardEscalation,
    PriorityConfidence,
    SemanticContribution,
    TopicPriorityInfo,
    TopicPriorityLevel,
    TopicPrioritySignal,
)
from app.domain.value_objects.status import is_resolved_status


def _diminishing_returns(count: int, cap: int) -> float:
    """0..1, sub-linear so e.g. 1->2 matters far more than 51->52 (spec section 11/13)."""
    if count <= 0 or cap <= 0:
        return 0.0
    return min(1.0, math.log2(1 + count) / math.log2(1 + cap))


def _is_structurally_blocked(status_text: str) -> bool:
    lowered = status_text.lower()
    return any(keyword in lowered for keyword in PRIORITY_CONFIG["blocked_status_keywords"])


def _keyword_hits(text: str, keywords: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(1 for keyword in keywords if keyword in lowered)


class TopicPriorityScorer:
    """Pure scoring function: facts (+ optional previous state / semantic contribution) -> a
    TopicPriorityInfo. No DB access - this is what calibration and unit tests exercise directly."""

    def score(
        self,
        facts: TopicPriorityFacts,
        previous: PreviousPriorityState | None = None,
        semantic: SemanticContribution | None = None,
        calculated_at: str | None = None,
    ) -> TopicPriorityInfo:
        """`calculated_at` (ISO timestamp) lets the caller supply the clock; it defaults to now (UTC)."""
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
            calculated_at=calculated_at or datetime.now(timezone.utc).isoformat(),
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
            if item.type in ("ACTION", "QUESTION") and not is_resolved_status(item.status_text)
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
