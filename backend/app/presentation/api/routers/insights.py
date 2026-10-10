from __future__ import annotations

from fastapi import APIRouter, Query

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
    limit: int = Query(default=5, ge=1),
    due_soon_days: int = Query(default=7, ge=0, alias="dueSoonDays"),
) -> FollowUpResponse:
    return to_schema(FollowUpResponse, app.get_follow_up(limit=limit, due_soon_days=due_soon_days))
