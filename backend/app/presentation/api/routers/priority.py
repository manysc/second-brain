from __future__ import annotations

from fastapi import APIRouter, Query

from app.presentation.api.dependencies import App, to_schema, to_schemas
from app.presentation.api.schemas import (
    PriorityOverrideUpdate,
    Topic,
    TopicPriorityHistoryEntry,
)

router = APIRouter()


@router.post("/api/topics/recalculate-priority")
def recalculate_all_topic_priorities(app: App) -> dict[str, int]:
    return {"recalculated": app.recalculate_all_priorities()}


@router.get("/api/priority-history/recent", response_model=list[TopicPriorityHistoryEntry])
def get_recent_priority_escalations(app: App, days: int = Query(default=14, ge=1)) -> list[TopicPriorityHistoryEntry]:
    return to_schemas(TopicPriorityHistoryEntry, app.get_recent_escalations(days))


@router.post("/api/topics/{topic_id}/recalculate-priority", response_model=Topic)
def recalculate_topic_priority(topic_id: str, app: App) -> Topic:
    return to_schema(Topic, app.recalculate_topic_priority(topic_id))


@router.patch("/api/topics/{topic_id}/priority-override", response_model=Topic)
def set_topic_priority_override(topic_id: str, payload: PriorityOverrideUpdate, app: App) -> Topic:
    return to_schema(Topic, app.set_topic_priority_override(topic_id, payload.priority, payload.reason))


@router.get("/api/topics/{topic_id}/priority-history", response_model=list[TopicPriorityHistoryEntry])
def get_topic_priority_history(topic_id: str, app: App) -> list[TopicPriorityHistoryEntry]:
    return to_schemas(TopicPriorityHistoryEntry, app.get_priority_history(topic_id))
