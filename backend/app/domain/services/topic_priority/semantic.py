"""What the optional semantic classifier is asked: the hypotheses it scores and the grounded context it sees."""
from __future__ import annotations

from app.domain.services.topic_priority.facts import TopicPriorityFacts

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


def build_semantic_context(topic_name: str, facts: TopicPriorityFacts) -> str:
    """Grounded-only context string for the semantic classifier - no invented assumptions."""
    lines = [f"Topic: {topic_name}"]
    for item in facts.items[:20]:
        lines.append(f"- [{item.type}] status={item.status_text or 'unknown'} due={item.due_date or 'none'}")
    return "\n".join(lines)
