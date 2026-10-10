from __future__ import annotations

from fastapi import APIRouter

from app.presentation.api.dependencies import App, to_schema, to_schemas
from app.presentation.api.schemas import Meeting

router = APIRouter()


@router.post("/api/ingest")
def trigger_ingestion(app: App) -> dict[str, int]:
    """Re-runs the startup ingestion on demand, so new extracts in SeaweedFS show up without a restart."""
    summary = app.ingest_extracts()
    return {
        "meetings": summary.new + summary.updated + summary.unchanged,
        "new": summary.new,
        "updated": summary.updated,
        "unchanged": summary.unchanged,
    }


@router.get("/api/meetings", response_model=list[Meeting])
def get_meetings(app: App) -> list[Meeting]:
    return to_schemas(Meeting, app.list_meetings())


@router.get("/api/meetings/{meeting_id}", response_model=Meeting)
def get_meeting_by_id(meeting_id: str, app: App) -> Meeting:
    return to_schema(Meeting, app.get_meeting(meeting_id))


@router.get("/api/meeting", response_model=Meeting)
def get_meeting(app: App) -> Meeting:
    return to_schema(Meeting, app.get_most_recent_meeting())
