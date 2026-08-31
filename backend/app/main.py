"""REST API exposing the meeting knowledge base. Replaces the logic that used to live in src/lib/data.ts."""
from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app import data
from app.models import ItemDetail, ItemType, KnowledgeItem, Meeting, ReviewCandidate, Topic

# picks up backend/.env so S3_* config survives across process restarts
load_dotenv()

app = FastAPI(title="second-brain backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET"],
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


@app.get("/api/items/{item_id}", response_model=ItemDetail)
def get_item(item_id: str) -> ItemDetail:
    meetings = data.load_meetings()
    item = next((candidate for candidate in data.all_items(meetings) if candidate.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return ItemDetail(item=item, related=data.related_items(item, meetings))


@app.get("/api/topics", response_model=list[Topic])
def get_topics() -> list[Topic]:
    return data.all_topics(data.load_meetings())


@app.get("/api/topics/{name}", response_model=Topic)
def get_topic(name: str) -> Topic:
    topics = data.all_topics(data.load_meetings())
    topic = next((candidate for candidate in topics if candidate.name == name), None)
    # mirror the frontend's previous fallback: show the first topic instead of 404ing
    if topic is None and topics:
        topic = topics[0]
    if topic is None:
        raise HTTPException(status_code=404, detail="No topics available")
    return topic


@app.get("/api/review", response_model=list[ReviewCandidate])
def get_review() -> list[ReviewCandidate]:
    return data.all_review_candidates(data.load_meetings())

