"""Weights, thresholds and decay for topic priority, centralized so they never get scattered as magic numbers."""
from __future__ import annotations

from app.domain.value_objects.status import (
    BLOCKED_STATUS_KEYWORDS,
    RESOLVED_STATUS_KEYWORDS,
)

TOPIC_PRIORITY_ALGORITHM_VERSION = "1.0"

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
    "blocked_status_keywords": BLOCKED_STATUS_KEYWORDS,
    "resolved_status_keywords": RESOLVED_STATUS_KEYWORDS,
    "impact_keywords": ("production", "customer", "outage", "compliance", "security", "revenue", "release"),
    "risk_keywords": ("block", "blocker", "at risk", "risk of", "escalat"),
}
