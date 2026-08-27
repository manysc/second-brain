"""REST API exposing the meeting knowledge base. Replaces the logic that used to live in src/lib/data.ts."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.data import load_meeting, related_items
from app.models import ItemDetail, ItemType, KnowledgeItem, Meeting, ReviewCandidate, Topic

app = FastAPI(title="second-brain backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/meeting", response_model=Meeting)
def get_meeting() -> Meeting:
    return load_meeting()


@app.get("/api/items", response_model=list[KnowledgeItem])
def get_items(item_type: ItemType | None = Query(default=None, alias="type")) -> list[KnowledgeItem]:
    meeting = load_meeting()
    if item_type is None:
        return meeting.items
    return [item for item in meeting.items if item.type == item_type]


@app.get("/api/items/{item_id}", response_model=ItemDetail)
def get_item(item_id: str) -> ItemDetail:
    meeting = load_meeting()
    item = next((candidate for candidate in meeting.items if candidate.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return ItemDetail(item=item, related=related_items(item, meeting))


@app.get("/api/topics", response_model=list[Topic])
def get_topics() -> list[Topic]:
    return load_meeting().topics


@app.get("/api/topics/{name}", response_model=Topic)
def get_topic(name: str) -> Topic:
    meeting = load_meeting()
    topic = next((candidate for candidate in meeting.topics if candidate.name == name), None)
    # mirror the frontend's previous fallback: show the first topic instead of 404ing
    if topic is None and meeting.topics:
        topic = meeting.topics[0]
    if topic is None:
        raise HTTPException(status_code=404, detail="No topics available")
    return topic


@app.get("/api/review", response_model=list[ReviewCandidate])
def get_review() -> list[ReviewCandidate]:
    return load_meeting().review_candidates
