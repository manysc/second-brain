"""REST API exposing the meeting knowledge base. Replaces the logic that used to live in src/lib/data.ts."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app import data, db, ingest
from app.models import (
    ItemDetail,
    ItemTopicUpdate,
    ItemType,
    KnowledgeItem,
    Meeting,
    ReviewCandidate,
    ReviewStatusUpdate,
    SearchResult,
    Topic,
    TopicCreate,
    TopicMerge,
    TopicMergeSuggestion,
    TopicUpdate,
)

# picks up backend/.env so S3_* config survives across process restarts
load_dotenv()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db.init_db()
    if os.environ.get("INGEST_ON_STARTUP", "true").lower() not in ("false", "0"):
        try:
            count = ingest.ingest_and_commit()
            logger.info("startup ingestion: %d meeting(s)", count)
        except Exception:
            # SeaweedFS/network hiccups shouldn't stop the API from serving existing Postgres data
            logger.exception("startup ingestion failed; continuing with existing data")
    yield


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
def get_items(item_type: ItemType | None = Query(default=None, alias="type")) -> list[KnowledgeItem]:
    items = data.all_items(data.load_meetings())
    if item_type is None:
        return items
    return [item for item in items if item.type == item_type]


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


# declared before /api/topics/{topic_id} - otherwise FastAPI would match "suggested-merges" as a topic_id
@app.get("/api/topics/suggested-merges", response_model=list[TopicMergeSuggestion])
def get_suggested_topic_merges() -> list[TopicMergeSuggestion]:
    return data.suggested_topic_merges()


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


@app.post("/api/topics/{topic_id}/merge", response_model=Topic)
def merge_topic(topic_id: str, payload: TopicMerge) -> Topic:
    try:
        return data.merge_topics(topic_id, payload.target_topic_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except LookupError:
        raise HTTPException(status_code=404, detail="Topic not found")


@app.get("/api/review", response_model=list[ReviewCandidate])
def get_review() -> list[ReviewCandidate]:
    return [c for c in data.all_review_candidates(data.load_meetings()) if c.status == "PENDING"]


@app.patch("/api/review/{candidate_id}", response_model=ReviewCandidate)
def update_review_status(candidate_id: str, payload: ReviewStatusUpdate) -> ReviewCandidate:
    try:
        candidate = data.set_review_status(candidate_id, payload.status)
    except data.ReviewCandidateAlreadyDecided:
        raise HTTPException(status_code=409, detail="Review candidate already decided")
    if candidate is None:
        raise HTTPException(status_code=404, detail="Review candidate not found")
    return candidate

