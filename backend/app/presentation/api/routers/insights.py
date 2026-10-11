from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.domain.policies import FOLLOW_UP_MAX_AGE_DAYS
from app.presentation.api.dependencies import App, to_schema
from app.presentation.api.schemas import FollowUpResponse, GraphData, SearchResult

router = APIRouter()


@router.get("/api/search", response_model=SearchResult)
def search_items(app: App, q: str = Query(..., min_length=1, description="Free-text search query")) -> SearchResult:
    return to_schema(SearchResult, app.search(q))


@router.get("/api/graph", response_model=GraphData)
def get_graph(app: App, min_similarity: float = Query(default=0.35, alias="minSimilarity")) -> GraphData:
    return to_schema(GraphData, app.build_graph(min_similarity))


@router.get("/api/follow-up", response_model=FollowUpResponse)
def get_follow_up(
    app: App,
    stakeholders: Annotated[
        list[str], Query(default_factory=list, alias="stakeholder", description="Repeatable: only items of these people")
    ],
    meeting_ids: Annotated[
        list[str], Query(default_factory=list, alias="meetingId", description="Repeatable: only items from these meetings")
    ],
    topic_ids: Annotated[
        list[str], Query(default_factory=list, alias="topicId", description="Repeatable: only these topics")
    ],
    limit: int = Query(default=5, ge=1),
    due_soon_days: int = Query(default=7, ge=0, alias="dueSoonDays"),
    max_age_days: int = Query(
        default=FOLLOW_UP_MAX_AGE_DAYS,
        ge=0,
        alias="maxAgeDays",
        description="Leave out items with no activity in this many days; 0 turns the cut-off off",
    ),
) -> FollowUpResponse:
    return to_schema(
        FollowUpResponse,
        app.get_follow_up(
            limit=limit,
            due_soon_days=due_soon_days,
            max_age_days=max_age_days,
            stakeholders=stakeholders,
            meeting_ids=meeting_ids,
            topic_ids=topic_ids,
        ),
    )
