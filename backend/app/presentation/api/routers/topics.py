from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response, UploadFile

from app.domain.exceptions import TooManyTags
from app.domain.value_objects.image_upload import MAX_IMAGE_BYTES
from app.presentation.api.dependencies import App, to_schema, to_schemas
from app.presentation.api.schemas import (
    ItemCreate,
    ItemTopicSuggestion,
    KnowledgeItem,
    NoteCreate,
    RelatedTopic,
    StatusUpdate,
    TagCreate,
    Topic,
    TopicCreate,
    TopicMerge,
    TopicMergeSuggestion,
    TopicUpdate,
)

router = APIRouter()


@router.get("/api/topics", response_model=list[Topic])
def get_topics(app: App) -> list[Topic]:
    return to_schemas(Topic, app.list_topics())


# declared before /api/topics/{topic_id} - otherwise FastAPI would match "suggested-merges" as a topic_id
@router.get("/api/topics/suggested-merges", response_model=list[TopicMergeSuggestion])
def get_suggested_topic_merges(
    app: App,
    max_related_items: int = Query(default=5, alias="maxRelatedItems"),
) -> list[TopicMergeSuggestion]:
    return to_schemas(TopicMergeSuggestion, app.suggest_topic_merges(max_related_items=max_related_items))


# same path-ordering reason as suggested-merges above
@router.get("/api/topics/suggested-item-topics", response_model=list[ItemTopicSuggestion])
def get_suggested_item_topics(app: App, limit: int | None = Query(default=None, ge=1)) -> list[ItemTopicSuggestion]:
    return to_schemas(ItemTopicSuggestion, app.suggest_item_topics(limit=limit))


@router.get("/api/topics/{topic_id}", response_model=Topic)
def get_topic(topic_id: str, app: App) -> Topic:
    return to_schema(Topic, app.get_topic(topic_id))


@router.get("/api/topics/{topic_id}/related", response_model=list[RelatedTopic])
def get_related_topics(topic_id: str, app: App) -> list[RelatedTopic]:
    return to_schemas(RelatedTopic, app.get_related_topics(topic_id))


@router.post("/api/topics", response_model=Topic, status_code=201)
def create_topic(payload: TopicCreate, app: App) -> Topic:
    return to_schema(Topic, app.create_topic(payload.name))


@router.patch("/api/topics/{topic_id}", response_model=Topic)
def update_topic(topic_id: str, payload: TopicUpdate, app: App) -> Topic:
    return to_schema(Topic, app.rename_topic(topic_id, payload.name))


@router.delete("/api/topics/{topic_id}", status_code=204)
def delete_topic(topic_id: str, app: App) -> None:
    app.delete_topic(topic_id)


@router.post("/api/topics/{topic_id}/merge", response_model=Topic)
def merge_topic(topic_id: str, payload: TopicMerge, app: App) -> Topic:
    return to_schema(Topic, app.merge_topics(topic_id, payload.target_topic_id))


@router.patch("/api/topics/{topic_id}/status", response_model=Topic)
def set_topic_status(topic_id: str, payload: StatusUpdate, app: App) -> Topic:
    return to_schema(Topic, app.set_topic_status(topic_id, payload.status))


@router.patch("/api/topics/{topic_id}/notes/{note_id}", response_model=Topic)
def update_topic_note(topic_id: str, note_id: str, payload: NoteCreate, app: App) -> Topic:
    return to_schema(Topic, app.edit_topic_note(topic_id, note_id, payload.body))


@router.post("/api/topics/{topic_id}/notes", response_model=Topic)
def add_topic_note(topic_id: str, payload: NoteCreate, app: App) -> Topic:
    return to_schema(Topic, app.add_topic_note(topic_id, payload.body))


@router.post("/api/topics/{topic_id}/tags", response_model=Topic)
def add_topic_tag(topic_id: str, payload: TagCreate, app: App) -> Topic:
    try:
        return to_schema(Topic, app.add_topic_tag(topic_id, payload.tag))
    except TooManyTags as error:
        raise HTTPException(status_code=400, detail=f"A topic can have at most {error.args[0]} tags") from None


# the tag travels as a query param, not a path segment: tags are free text and may contain "/"
@router.delete("/api/topics/{topic_id}/tags", response_model=Topic)
def remove_topic_tag(topic_id: str, app: App, tag: str = Query(min_length=1)) -> Topic:
    return to_schema(Topic, app.remove_topic_tag(topic_id, tag))


@router.post("/api/topics/{topic_id}/items", response_model=KnowledgeItem, status_code=201)
def create_topic_item(topic_id: str, payload: ItemCreate, app: App) -> KnowledgeItem:
    return to_schema(KnowledgeItem, app.create_item(topic_id, payload.to_new_item()))


@router.delete("/api/topics/{topic_id}/notes/{note_id}", response_model=Topic)
def delete_topic_note(topic_id: str, note_id: str, app: App) -> Topic:
    return to_schema(Topic, app.delete_topic_note(topic_id, note_id))


@router.post("/api/topics/{topic_id}/images", response_model=Topic)
def add_topic_image(topic_id: str, file: UploadFile, app: App) -> Topic:
    # read one byte past the limit so an oversize upload is rejected without buffering all of it
    body = file.file.read(MAX_IMAGE_BYTES + 1)
    return to_schema(Topic, app.add_topic_image(topic_id, file.filename, body))


@router.delete("/api/topics/{topic_id}/images/{image_id}", response_model=Topic)
def delete_topic_image(topic_id: str, image_id: str, app: App) -> Topic:
    return to_schema(Topic, app.delete_topic_image(topic_id, image_id))


@router.get("/api/topics/{topic_id}/images/{image_id}")
def get_topic_image(topic_id: str, image_id: str, app: App) -> Response:
    image = app.get_topic_image(topic_id, image_id)
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    # image ids are never reused, so the bytes behind a URL never change
    return Response(
        content=image.body, media_type=image.content_type, headers={"Cache-Control": "private, max-age=3600"}
    )
