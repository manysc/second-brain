from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.application.dtos import NewItem
from app.domain.entities.knowledge_item import ItemEdit
from app.domain.exceptions import TooManyTags, TopicNotFound
from app.presentation.api.dependencies import App, to_schema, to_schemas
from app.presentation.api.schemas import (
    ItemCreate,
    ItemDetail,
    ItemsTopicBulkUpdate,
    ItemTopicUpdate,
    ItemType,
    ItemUpdate,
    KnowledgeItem,
    NoteCreate,
    OpenClosed,
    PriorityOverrideUpdate,
    StatusUpdate,
    TagCreate,
    TopicPriorityLevel,
)

router = APIRouter()


@router.get("/api/items", response_model=list[KnowledgeItem])
def get_items(
    app: App,
    item_type: ItemType | None = Query(default=None, alias="type"),
    priority: TopicPriorityLevel | None = Query(default=None),
    status: OpenClosed | None = Query(default=None),
) -> list[KnowledgeItem]:
    return to_schemas(KnowledgeItem, app.list_items(item_type=item_type, status=status, priority=priority))


@router.get("/api/items/{item_id}", response_model=ItemDetail)
def get_item(item_id: str, app: App) -> ItemDetail:
    return to_schema(ItemDetail, app.get_item_detail(item_id))


@router.patch("/api/items/{item_id}/topic", response_model=KnowledgeItem)
def set_item_topic(item_id: str, payload: ItemTopicUpdate, app: App) -> KnowledgeItem:
    return to_schema(KnowledgeItem, app.assign_item_topic(item_id, payload.topic_id))


# declared before /api/items/{item_id} - otherwise FastAPI would match "topic" as an item_id
@router.patch("/api/items/topic", response_model=list[KnowledgeItem])
def set_items_topic(payload: ItemsTopicBulkUpdate, app: App) -> list[KnowledgeItem]:
    if not payload.item_ids:
        raise HTTPException(status_code=400, detail="itemIds must not be empty")
    try:
        return to_schemas(KnowledgeItem, app.assign_items_topic(payload.item_ids, payload.topic_id))
    except TopicNotFound as error:
        # this route has always reported the error's own wording
        raise HTTPException(status_code=404, detail=str(error)) from None


@router.patch("/api/items/{item_id}", response_model=KnowledgeItem)
def update_item(item_id: str, payload: ItemUpdate, app: App) -> KnowledgeItem:
    changes = ItemEdit(
        fields=frozenset(payload.model_fields_set),
        type=payload.type,
        description=payload.description,
        owner=payload.owner,
        due_date=payload.due_date,
        rationale=payload.rationale,
    )
    return to_schema(KnowledgeItem, app.update_item(item_id, changes))


@router.delete("/api/items/{item_id}", status_code=204)
def delete_item(item_id: str, app: App) -> None:
    app.delete_item(item_id)


@router.patch("/api/items/{item_id}/priority-override", response_model=KnowledgeItem)
def set_item_priority_override(item_id: str, payload: PriorityOverrideUpdate, app: App) -> KnowledgeItem:
    return to_schema(KnowledgeItem, app.set_item_priority_override(item_id, payload.priority, payload.reason))


@router.patch("/api/items/{item_id}/status", response_model=KnowledgeItem)
def set_item_status(item_id: str, payload: StatusUpdate, app: App) -> KnowledgeItem:
    return to_schema(KnowledgeItem, app.set_item_status(item_id, payload.status))


@router.post("/api/items/{item_id}/tags", response_model=KnowledgeItem)
def add_item_tag(item_id: str, payload: TagCreate, app: App) -> KnowledgeItem:
    try:
        return to_schema(KnowledgeItem, app.add_item_tag(item_id, payload.tag))
    except TooManyTags as error:
        raise HTTPException(status_code=400, detail=f"An item can have at most {error.args[0]} tags") from None


# the tag travels as a query param, not a path segment: tags are free text and may contain "/"
@router.delete("/api/items/{item_id}/tags", response_model=KnowledgeItem)
def remove_item_tag(item_id: str, app: App, tag: str = Query(min_length=1)) -> KnowledgeItem:
    return to_schema(KnowledgeItem, app.remove_item_tag(item_id, tag))


@router.post("/api/items/{item_id}/notes", response_model=KnowledgeItem)
def add_item_note(item_id: str, payload: NoteCreate, app: App) -> KnowledgeItem:
    return to_schema(KnowledgeItem, app.add_item_note(item_id, payload.body))


@router.delete("/api/items/{item_id}/notes/{note_id}", response_model=KnowledgeItem)
def delete_item_note(item_id: str, note_id: str, app: App) -> KnowledgeItem:
    return to_schema(KnowledgeItem, app.delete_item_note(item_id, note_id))


@router.patch("/api/items/{item_id}/notes/{note_id}", response_model=KnowledgeItem)
def update_item_note(item_id: str, note_id: str, payload: NoteCreate, app: App) -> KnowledgeItem:
    return to_schema(KnowledgeItem, app.edit_item_note(item_id, note_id, payload.body))


def new_item(payload: ItemCreate) -> NewItem:
    return NewItem(
        type=payload.type,
        description=payload.description,
        owner=payload.owner,
        due_date=payload.due_date,
        rationale=payload.rationale,
    )
