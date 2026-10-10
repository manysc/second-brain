from __future__ import annotations

from app.application.interfaces.repositories import UnitOfWork
from app.application.interfaces.services import IdGenerator
from app.domain.entities.topic import Topic
from app.domain.policies import UNCATEGORIZED_TOPIC


def ensure_uncategorized_topic(uow: UnitOfWork, ids: IdGenerator) -> Topic:
    """The catch-all topic for items nobody has filed yet, created on first use. It is the only topic the
    system ever creates on its own; every other topic exists because a person accepted it."""
    existing = uow.topics.get_by_name(UNCATEGORIZED_TOPIC)
    if existing is not None:
        return existing
    topic = Topic(id=ids.new_id(), name=UNCATEGORIZED_TOPIC)
    uow.topics.add(topic)
    return topic
