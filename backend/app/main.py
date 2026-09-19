"""REST API exposing the meeting knowledge base. Replaces the logic that used to live in src/lib/data.ts."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app import data, db, ingest
from app.models import (
    FollowUpResponse,
    GraphData,
    ItemDetail,
    ItemsTopicBulkUpdate,
    ItemTopicSuggestion,
    ItemTopicUpdate,
    ItemType,
    KnowledgeItem,
    Meeting,
    NoteCreate,
    OpenClosed,
    PriorityOverrideUpdate,
    ReviewCandidate,
    ReviewStatusUpdate,
    SearchResult,
    StatusUpdate,
    Topic,
    TopicCreate,
    TopicMerge,
    TopicMergeSuggestion,
    TopicPriorityHistoryEntry,
    TopicPriorityLevel,
    TopicProposal,
    TopicProposalAccept,
    TopicProposalReject,
    TopicUpdate,
)

# picks up backend/.env so S3_* config survives across process restarts
load_dotenv()

logger = logging.getLogger(__name__)


def _run_startup_ingest() -> None:
    try:
        count = ingest.ingest_and_commit()
        logger.info("startup ingestion: %d meeting(s)", count)
    except Exception:
        # SeaweedFS/network hiccups shouldn't stop the API from serving existing Postgres data
        logger.exception("startup ingestion failed; continuing with existing data")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db.init_db()
    ingest_task: asyncio.Task[None] | None = None
    if os.environ.get("INGEST_ON_STARTUP", "true").lower() not in ("false", "0"):
        # off the startup path: the API serves existing Postgres data while ingestion catches up
        ingest_task = asyncio.create_task(asyncio.to_thread(_run_startup_ingest))
    yield
    if ingest_task is not None and not ingest_task.done():
        ingest_task.cancel()


app = FastAPI(title="second-brain backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


@app.get("/api/meetings", response_model=list[Meeting])
def get_meetings() -> list[Meeting]:
    return data.load_meetings()


@app.get("/api/meetings/{meeting_id}", response_model=Meeting)
def get_meeting_by_id(meeting_id: str) -> Meeting:
    meeting = data.get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


@app.get("/api/meeting", response_model=Meeting)
def get_meeting() -> Meeting:
    meeting = data.most_recent_meeting()
    if meeting is None:
        raise HTTPException(status_code=404, detail="No meetings available")
    return meeting


@app.get("/api/items", response_model=list[KnowledgeItem])
def get_items(
    item_type: ItemType | None = Query(default=None, alias="type"),
    priority: TopicPriorityLevel | None = Query(default=None),
    status: OpenClosed | None = Query(default=None),
) -> list[KnowledgeItem]:
    items = data.all_items(data.load_meetings())
    if item_type is not None:
        items = [item for item in items if item.type == item_type]
    if status is not None:
        items = [item for item in items if item.status == status]
    if priority is not None:
        items = [item for item in items if item.effective_priority == priority]
    return items


@app.get("/api/search", response_model=SearchResult)
def search_items(q: str = Query(..., min_length=1, description="Free-text search query")) -> SearchResult:
    items, topics = data.search(q)
    return SearchResult(items=items, topics=topics)


@app.get("/api/items/{item_id}", response_model=ItemDetail)
def get_item(item_id: str) -> ItemDetail:
    meetings = data.load_meetings()
    item = next((candidate for candidate in data.all_items(meetings) if candidate.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return ItemDetail(
        item=item,
        related=data.related_items(item, meetings),
        similar=data.semantic_similar_items(item),
    )


@app.get("/api/topics", response_model=list[Topic])
def get_topics() -> list[Topic]:
    return data.all_topics()


@app.get("/api/graph", response_model=GraphData)
def get_graph(min_similarity: float = Query(default=0.35, alias="minSimilarity")) -> GraphData:
    return data.build_graph(min_similarity)


@app.get("/api/follow-up", response_model=FollowUpResponse)
def get_follow_up(
    limit: int = Query(default=5, ge=1),
    due_soon_days: int = Query(default=7, ge=0, alias="dueSoonDays"),
) -> FollowUpResponse:
    return data.get_follow_up(limit=limit, due_soon_days=due_soon_days)


# declared before /api/topics/{topic_id} - otherwise FastAPI would match "suggested-merges" as a topic_id
@app.get("/api/topics/suggested-merges", response_model=list[TopicMergeSuggestion])
def get_suggested_topic_merges(
    max_related_items: int = Query(default=5, alias="maxRelatedItems"),
) -> list[TopicMergeSuggestion]:
    return data.suggested_topic_merges(max_related_items=max_related_items)


# same path-ordering reason as suggested-merges above
@app.get("/api/topics/suggested-item-topics", response_model=list[ItemTopicSuggestion])
def get_suggested_item_topics() -> list[ItemTopicSuggestion]:
    return data.suggested_item_topics()


@app.get("/api/topics/{topic_id}", response_model=Topic)
def get_topic(topic_id: str) -> Topic:
    topic = data.get_topic_by_id(topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


@app.post("/api/topics", response_model=Topic, status_code=201)
def create_topic(payload: TopicCreate) -> Topic:
    try:
        return data.create_topic(payload.name)
    except data.TopicNameConflict:
        raise HTTPException(status_code=409, detail=f"Topic '{payload.name}' already exists")


@app.patch("/api/topics/{topic_id}", response_model=Topic)
def update_topic(topic_id: str, payload: TopicUpdate) -> Topic:
    try:
        topic = data.update_topic(topic_id, payload.name)
    except data.TopicNameConflict:
        raise HTTPException(status_code=409, detail=f"Topic '{payload.name}' already exists")
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


@app.delete("/api/topics/{topic_id}", status_code=204)
def delete_topic(topic_id: str) -> None:
    try:
        deleted = data.delete_topic(topic_id)
    except data.TopicHasItems as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Topic still has {exc.item_count} item(s) assigned; reassign them before deleting",
        )
    if not deleted:
        raise HTTPException(status_code=404, detail="Topic not found")


@app.patch("/api/items/{item_id}/topic", response_model=KnowledgeItem)
def set_item_topic(item_id: str, payload: ItemTopicUpdate) -> KnowledgeItem:
    try:
        item = data.assign_item_topic(item_id, payload.topic_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Topic not found")
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@app.patch("/api/items/topic", response_model=list[KnowledgeItem])
def set_items_topic(payload: ItemsTopicBulkUpdate) -> list[KnowledgeItem]:
    if not payload.item_ids:
        raise HTTPException(status_code=400, detail="itemIds must not be empty")
    try:
        return data.assign_items_topic(payload.item_ids, payload.topic_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/topics/{topic_id}/merge", response_model=Topic)
def merge_topic(topic_id: str, payload: TopicMerge) -> Topic:
    try:
        return data.merge_topics(topic_id, payload.target_topic_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except LookupError:
        raise HTTPException(status_code=404, detail="Topic not found")


# declared before /api/topics/{topic_id}/... routes for the same reason as suggested-merges above
@app.post("/api/topics/recalculate-priority")
def recalculate_all_topic_priorities() -> dict[str, int]:
    return {"recalculated": data.recalculate_all_topic_priorities()}


@app.get("/api/priority-history/recent", response_model=list[TopicPriorityHistoryEntry])
def get_recent_priority_escalations(days: int = Query(default=14, ge=1)) -> list[TopicPriorityHistoryEntry]:
    return data.get_recent_priority_escalations(days)


@app.post("/api/topics/{topic_id}/recalculate-priority", response_model=Topic)
def recalculate_topic_priority(topic_id: str) -> Topic:
    topic = data.recalculate_priority_for_topic(topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


@app.patch("/api/topics/{topic_id}/priority-override", response_model=Topic)
def set_topic_priority_override(topic_id: str, payload: PriorityOverrideUpdate) -> Topic:
    topic = data.set_priority_override(topic_id, payload.priority, payload.reason)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


@app.get("/api/topics/{topic_id}/priority-history", response_model=list[TopicPriorityHistoryEntry])
def get_topic_priority_history(topic_id: str) -> list[TopicPriorityHistoryEntry]:
    if data.get_topic_by_id(topic_id) is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return data.get_priority_history(topic_id)


@app.patch("/api/items/{item_id}/priority-override", response_model=KnowledgeItem)
def set_item_priority_override(item_id: str, payload: PriorityOverrideUpdate) -> KnowledgeItem:
    item = data.set_item_priority_override(item_id, payload.priority, payload.reason)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@app.patch("/api/items/{item_id}/status", response_model=KnowledgeItem)
def set_item_status(item_id: str, payload: StatusUpdate) -> KnowledgeItem:
    item = data.set_item_status(item_id, payload.status)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@app.patch("/api/topics/{topic_id}/status", response_model=Topic)
def set_topic_status(topic_id: str, payload: StatusUpdate) -> Topic:
    topic = data.set_topic_status(topic_id, payload.status)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


@app.post("/api/items/{item_id}/notes", response_model=KnowledgeItem)
def add_item_note(item_id: str, payload: NoteCreate) -> KnowledgeItem:
    item = data.add_item_note(item_id, payload.body)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@app.delete("/api/items/{item_id}/notes/{note_id}", response_model=KnowledgeItem)
def delete_item_note(item_id: str, note_id: str) -> KnowledgeItem:
    item = data.delete_item_note(item_id, note_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@app.patch("/api/items/{item_id}/notes/{note_id}", response_model=KnowledgeItem)
def update_item_note(item_id: str, note_id: str, payload: NoteCreate) -> KnowledgeItem:
    item = data.update_item_note(item_id, note_id, payload.body)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@app.patch("/api/topics/{topic_id}/notes/{note_id}", response_model=Topic)
def update_topic_note(topic_id: str, note_id: str, payload: NoteCreate) -> Topic:
    topic = data.update_topic_note(topic_id, note_id, payload.body)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


@app.post("/api/topics/{topic_id}/notes", response_model=Topic)
def add_topic_note(topic_id: str, payload: NoteCreate) -> Topic:
    topic = data.add_topic_note(topic_id, payload.body)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


@app.delete("/api/topics/{topic_id}/notes/{note_id}", response_model=Topic)
def delete_topic_note(topic_id: str, note_id: str) -> Topic:
    topic = data.delete_topic_note(topic_id, note_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


@app.get("/api/review", response_model=list[ReviewCandidate])
def get_review() -> list[ReviewCandidate]:
    pending = [c for c in data.all_review_candidates(data.load_meetings()) if c.status == "PENDING"]
    return data.with_suggested_topics(pending)


@app.get("/api/review/topic-proposals", response_model=list[TopicProposal])
def get_topic_proposals() -> list[TopicProposal]:
    return data.topic_proposals()


@app.post("/api/review/topic-proposals/accept", response_model=list[KnowledgeItem])
def accept_topic_proposal(payload: TopicProposalAccept) -> list[KnowledgeItem]:
    try:
        return data.accept_topic_proposal(payload.suggested_name, payload.topic_name, payload.existing_topic_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Topic proposal not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/review/topic-proposals/reject", status_code=204)
def reject_topic_proposal(payload: TopicProposalReject) -> None:
    if data.reject_topic_proposal(payload.suggested_name) == 0:
        raise HTTPException(status_code=404, detail="Topic proposal not found")


@app.patch("/api/review/{candidate_id}", response_model=ReviewCandidate)
def update_review_status(candidate_id: str, payload: ReviewStatusUpdate) -> ReviewCandidate:
    try:
        candidate = data.set_review_status(candidate_id, payload.status, payload.topic_id)
    except data.ReviewCandidateAlreadyDecided:
        raise HTTPException(status_code=409, detail="Review candidate already decided")
    except ValueError:
        raise HTTPException(status_code=404, detail="Topic not found")
    if candidate is None:
        raise HTTPException(status_code=404, detail="Review candidate not found")
    return candidate

