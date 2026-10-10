from __future__ import annotations

from fastapi import APIRouter

from app.presentation.api.dependencies import App, to_schema, to_schemas
from app.presentation.api.schemas import (
    KnowledgeItem,
    ReviewCandidate,
    ReviewStatusUpdate,
    TopicProposal,
    TopicProposalAccept,
    TopicProposalReject,
)

router = APIRouter()


@router.get("/api/review", response_model=list[ReviewCandidate])
def get_review(app: App) -> list[ReviewCandidate]:
    return to_schemas(ReviewCandidate, app.list_pending_review())


@router.get("/api/review/topic-proposals", response_model=list[TopicProposal])
def get_topic_proposals(app: App) -> list[TopicProposal]:
    return to_schemas(TopicProposal, app.list_topic_proposals())


@router.post("/api/review/topic-proposals/accept", response_model=list[KnowledgeItem])
def accept_topic_proposal(payload: TopicProposalAccept, app: App) -> list[KnowledgeItem]:
    filed = app.accept_topic_proposal(payload.suggested_name, payload.topic_name, payload.existing_topic_id)
    return to_schemas(KnowledgeItem, filed)


@router.post("/api/review/topic-proposals/reject", status_code=204)
def reject_topic_proposal(payload: TopicProposalReject, app: App) -> None:
    app.reject_topic_proposal(payload.suggested_name)


@router.patch("/api/review/{candidate_id}", response_model=ReviewCandidate)
def update_review_status(candidate_id: str, payload: ReviewStatusUpdate, app: App) -> ReviewCandidate:
    return to_schema(ReviewCandidate, app.decide_review_candidate(candidate_id, payload.status, payload.topic_id))
