"""Legacy facade over the application layer.

Everything here delegates to a use case in app.application (wired in app.container) and converts the result
back into the Pydantic models and the None/False/ValueError conventions the existing callers expect. New code
should call the use cases directly; this module goes away once the REST routes, the MCP server and the tests
have moved over."""
from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import db  # noqa: F401  (tests reach the session helpers through `data.db`)
from app.application.dtos import NewItem
from app.application.services.assembler import candidate_dto
from app.application.services.uncategorized import ensure_uncategorized_topic
from app.application.use_cases import items as item_use_cases
from app.container import get_container
from app.db_models import KnowledgeItemRow
from app.domain.entities.knowledge_item import ItemEdit
from app.domain.exceptions import (  # noqa: F401  (re-exported)
    ImageTooLarge,
    InvalidTopicMerge,
    InvalidTopicName,
    ItemNotDeletable,
    ItemNotEditable,
    ItemNotFound,
    ItemsNotFound,
    MeetingNotFound,
    NoMeetingsAvailable,
    ProposalTargetTopicNotFound,
    ReviewCandidateAlreadyDecided,
    ReviewCandidateNotFound,
    TooManyTags,
    TopicHasItems,
    TopicNameConflict,
    TopicNotFound,
    TopicProposalNotFound,
    UnsupportedImageType,
)
from app.domain.policies import (  # noqa: F401  (re-exported)
    DUPLICATE_MATCH_THRESHOLD,
    ITEM_TOPIC_MATCH_SIMILARITY,
    MANUAL_MEETING_ID,
    PROPOSAL_HINT_SIMILARITY,
    UNCATEGORIZED_TOPIC,
)
from app.domain.services.item_graph import related_items as _related_items
from app.domain.services.similarity import closest_topic as _closest_topic  # noqa: F401
from app.domain.services.topic_ranking import DEFAULT_CANDIDATES, confident_topic_id
from app.domain.value_objects.image_upload import MAX_IMAGE_BYTES  # noqa: F401
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from app.models import (
    FollowUpResponse,
    GraphData,
    ItemCreate,
    ItemTopicSuggestion,
    ItemUpdate,
    KnowledgeItem,
    Meeting,
    RelatedTopic,
    ReviewCandidate,
    ReviewStatus,
    Topic,
    TopicMergeSuggestion,
    TopicPriorityHistoryEntry,
    TopicProposal,
)

logger = logging.getLogger(__name__)

_M = TypeVar("_M", bound=BaseModel)


def _as(model: type[_M], dto: Any) -> _M:
    return model.model_validate(dto, from_attributes=True)


def _as_list(model: type[_M], dtos: Iterable[Any]) -> list[_M]:
    return [_as(model, dto) for dto in dtos]


# -- meetings and items (read) ------------------------------------------------------------------------------


def load_meetings() -> list[Meeting]:
    return _as_list(Meeting, get_container().list_meetings())


def get_meeting(meeting_id: str) -> Meeting | None:
    try:
        return _as(Meeting, get_container().get_meeting(meeting_id))
    except MeetingNotFound:
        return None


def most_recent_meeting() -> Meeting | None:
    try:
        return _as(Meeting, get_container().get_most_recent_meeting())
    except NoMeetingsAvailable:
        return None


def all_items(meetings: list[Meeting]) -> list[KnowledgeItem]:
    return [item for meeting in meetings for item in meeting.items]


def find_item(item_id: str, meetings: list[Meeting]) -> KnowledgeItem | None:
    return next((candidate for candidate in all_items(meetings) if candidate.id == item_id), None)


def filter_items(
    items: list[KnowledgeItem],
    item_type: str | None = None,
    status: str | None = None,
    priority: str | None = None,
) -> list[KnowledgeItem]:
    return item_use_cases.filter_items(items, item_type=item_type, status=status, priority=priority)  # type: ignore[arg-type,return-value]


def all_review_candidates(meetings: list[Meeting]) -> list[ReviewCandidate]:
    return [candidate for meeting in meetings for candidate in meeting.review_candidates]


def related_items(item: KnowledgeItem, meetings: list[Meeting]) -> list[KnowledgeItem]:
    return _related_items(item, all_items(meetings))


def semantic_similar_items(item: KnowledgeItem, limit: int = 5) -> list[KnowledgeItem]:
    return _as_list(KnowledgeItem, get_container().find_similar_items(item, limit))  # type: ignore[arg-type]


def search(query: str, limit: int = 20) -> tuple[list[KnowledgeItem], list[Topic]]:
    result = get_container().search(query, limit)
    return _as_list(KnowledgeItem, result.items), _as_list(Topic, result.topics)


def build_graph(min_semantic_similarity: float = 0.35) -> GraphData:
    return _as(GraphData, get_container().build_graph(min_semantic_similarity))


def get_follow_up(limit: int = 5, due_soon_days: int = 7) -> FollowUpResponse:
    return _as(FollowUpResponse, get_container().get_follow_up(limit=limit, due_soon_days=due_soon_days))


# -- review -------------------------------------------------------------------------------------------------


def pending_review_candidates() -> list[ReviewCandidate]:
    container = get_container()
    with container.uow() as uow:
        return _as_list(ReviewCandidate, (candidate_dto(candidate) for candidate in uow.review_candidates.list_pending()))


def with_suggested_topics(candidates: list[ReviewCandidate]) -> list[ReviewCandidate]:
    if not candidates:
        return candidates
    container = get_container()
    descriptions = [candidate.description for candidate in candidates]
    vectors = container.embedder.embed_texts(descriptions)
    with container.uow() as uow:
        ranker = container.rankers.get(uow)
    ranked = ranker.rank_many(vectors, descriptions, top_n=1)
    return [
        candidate.model_copy(update={"suggested_topic_id": confident_topic_id(best)})
        for candidate, best in zip(candidates, ranked)
    ]


def set_review_status(candidate_id: str, status: ReviewStatus, topic_id: str | None = None) -> ReviewCandidate | None:
    try:
        return _as(ReviewCandidate, get_container().decide_review_candidate(candidate_id, status, topic_id))
    except ReviewCandidateNotFound:
        return None
    except TopicNotFound:
        raise ValueError("topic not found") from None


def topic_proposals() -> list[TopicProposal]:
    return _as_list(TopicProposal, get_container().list_topic_proposals())


def accept_topic_proposal(
    suggested_name: str, topic_name: str | None = None, existing_topic_id: str | None = None
) -> list[KnowledgeItem]:
    try:
        filed = get_container().accept_topic_proposal(suggested_name, topic_name, existing_topic_id)
    except TopicProposalNotFound:
        raise LookupError(suggested_name) from None
    except (ProposalTargetTopicNotFound, InvalidTopicName) as error:
        raise ValueError(str(error)) from None
    return _as_list(KnowledgeItem, filed)


def reject_topic_proposal(suggested_name: str) -> int:
    try:
        return get_container().reject_topic_proposal(suggested_name)
    except TopicProposalNotFound:
        return 0


def _get_or_create_uncategorized_topic(session: Session) -> str:
    return ensure_uncategorized_topic(SqlAlchemyUnitOfWork(session), get_container().ids).id


# -- topics -------------------------------------------------------------------------------------------------


def all_topics() -> list[Topic]:
    return _as_list(Topic, get_container().list_topics())


def get_topic_by_id(topic_id: str) -> Topic | None:
    try:
        return _as(Topic, get_container().get_topic(topic_id))
    except TopicNotFound:
        return None


def create_topic(name: str) -> Topic:
    return _as(Topic, get_container().create_topic(name))


def update_topic(topic_id: str, name: str) -> Topic | None:
    try:
        return _as(Topic, get_container().rename_topic(topic_id, name))
    except TopicNotFound:
        return None


def delete_topic(topic_id: str) -> bool:
    try:
        get_container().delete_topic(topic_id)
    except TopicNotFound:
        return False
    return True


def set_topic_status(topic_id: str, status: str) -> Topic | None:
    try:
        return _as(Topic, get_container().set_topic_status(topic_id, status))
    except TopicNotFound:
        return None


def merge_topics(source_topic_id: str, target_topic_id: str) -> Topic:
    try:
        return _as(Topic, get_container().merge_topics(source_topic_id, target_topic_id))
    except InvalidTopicMerge as error:
        raise ValueError(str(error)) from None
    except TopicNotFound:
        raise LookupError("topic not found") from None


def suggested_topic_merges(
    min_similarity: float = 0.5, limit: int = 10, max_related_items: int = 5
) -> list[TopicMergeSuggestion]:
    return _as_list(TopicMergeSuggestion, get_container().suggest_topic_merges(min_similarity, limit, max_related_items))


def related_topics(
    topic_id: str, min_similarity: float = PROPOSAL_HINT_SIMILARITY, limit: int = 5
) -> list[RelatedTopic] | None:
    try:
        return _as_list(RelatedTopic, get_container().get_related_topics(topic_id, min_similarity, limit))
    except TopicNotFound:
        return None


def suggested_item_topics(
    min_score: float = 0.0, limit: int | None = None, candidates: int = DEFAULT_CANDIDATES
) -> list[ItemTopicSuggestion]:
    return _as_list(ItemTopicSuggestion, get_container().suggest_item_topics(min_score, limit, candidates))


def add_topic_tag(topic_id: str, tag: str) -> Topic | None:
    try:
        return _as(Topic, get_container().add_topic_tag(topic_id, tag))
    except TopicNotFound:
        return None


def remove_topic_tag(topic_id: str, tag: str) -> Topic | None:
    try:
        return _as(Topic, get_container().remove_topic_tag(topic_id, tag))
    except TopicNotFound:
        return None


def add_topic_note(topic_id: str, body: str) -> Topic | None:
    try:
        return _as(Topic, get_container().add_topic_note(topic_id, body))
    except TopicNotFound:
        return None


def update_topic_note(topic_id: str, note_id: str, body: str) -> Topic | None:
    try:
        return _as(Topic, get_container().edit_topic_note(topic_id, note_id, body))
    except TopicNotFound:
        return None


def delete_topic_note(topic_id: str, note_id: str) -> Topic | None:
    try:
        return _as(Topic, get_container().delete_topic_note(topic_id, note_id))
    except TopicNotFound:
        return None


def add_topic_image(topic_id: str, filename: str | None, body: bytes) -> Topic | None:
    try:
        return _as(Topic, get_container().add_topic_image(topic_id, filename, body))
    except TopicNotFound:
        return None


def delete_topic_image(topic_id: str, image_id: str) -> Topic | None:
    try:
        return _as(Topic, get_container().delete_topic_image(topic_id, image_id))
    except TopicNotFound:
        return None


def get_topic_image(topic_id: str, image_id: str) -> tuple[bytes, str] | None:
    image = get_container().get_topic_image(topic_id, image_id)
    return (image.body, image.content_type) if image is not None else None


# -- priority -----------------------------------------------------------------------------------------------


def recalculate_priority_for_topic(topic_id: str, trigger: str = "manual") -> Topic | None:
    try:
        return _as(Topic, get_container().recalculate_topic_priority(topic_id, trigger))
    except TopicNotFound:
        return None


def recalculate_priority_for_topics(topic_ids: set[str], trigger: str) -> None:
    get_container().recalculator.recalculate_topics(topic_ids, trigger)


def recalculate_all_topic_priorities(trigger: str = "recalculate_all") -> int:
    return get_container().recalculate_all_priorities(trigger)


def set_priority_override(topic_id: str, priority: str | None, reason: str | None) -> Topic | None:
    try:
        return _as(Topic, get_container().set_topic_priority_override(topic_id, priority, reason))
    except TopicNotFound:
        return None


def get_priority_history(topic_id: str) -> list[TopicPriorityHistoryEntry]:
    return _as_list(TopicPriorityHistoryEntry, get_container().get_priority_history(topic_id, require_topic=False))


def get_recent_priority_escalations(days: int = 14) -> list[TopicPriorityHistoryEntry]:
    return _as_list(TopicPriorityHistoryEntry, get_container().get_recent_escalations(days))


# -- items (write) ------------------------------------------------------------------------------------------


def create_item(topic_id: str, payload: ItemCreate) -> KnowledgeItem | None:
    new_item = NewItem(
        type=payload.type,
        description=payload.description,
        owner=payload.owner,
        due_date=payload.due_date,
        rationale=payload.rationale,
    )
    try:
        return _as(KnowledgeItem, get_container().create_item(topic_id, new_item))
    except TopicNotFound:
        return None


def is_manual_item(row: KnowledgeItemRow) -> bool:
    return row.meeting_id == MANUAL_MEETING_ID


def update_item(item_id: str, payload: ItemUpdate) -> KnowledgeItem | None:
    changes = ItemEdit(
        fields=frozenset(payload.model_fields_set),
        type=payload.type,
        description=payload.description,
        owner=payload.owner,
        due_date=payload.due_date,
        rationale=payload.rationale,
    )
    try:
        return _as(KnowledgeItem, get_container().update_item(item_id, changes))
    except ItemNotFound:
        return None


def delete_item(item_id: str) -> bool:
    try:
        get_container().delete_item(item_id)
    except ItemNotFound:
        return False
    return True


def set_item_status(item_id: str, status: str) -> KnowledgeItem | None:
    try:
        return _as(KnowledgeItem, get_container().set_item_status(item_id, status))
    except ItemNotFound:
        return None


def set_item_priority_override(item_id: str, priority: str | None, reason: str | None) -> KnowledgeItem | None:
    try:
        return _as(KnowledgeItem, get_container().set_item_priority_override(item_id, priority, reason))
    except ItemNotFound:
        return None


def assign_item_topic(item_id: str, topic_id: str | None) -> KnowledgeItem | None:
    try:
        return _as(KnowledgeItem, get_container().assign_item_topic(item_id, topic_id))
    except ItemNotFound:
        return None
    except TopicNotFound:
        raise ValueError("topic not found") from None


def assign_items_topic(item_ids: list[str], topic_id: str | None) -> list[KnowledgeItem]:
    try:
        return _as_list(KnowledgeItem, get_container().assign_items_topic(item_ids, topic_id))
    except (TopicNotFound, ItemsNotFound) as error:
        raise ValueError(str(error)) from None


def add_item_tag(item_id: str, tag: str) -> KnowledgeItem | None:
    try:
        return _as(KnowledgeItem, get_container().add_item_tag(item_id, tag))
    except ItemNotFound:
        return None


def remove_item_tag(item_id: str, tag: str) -> KnowledgeItem | None:
    try:
        return _as(KnowledgeItem, get_container().remove_item_tag(item_id, tag))
    except ItemNotFound:
        return None


def add_item_note(item_id: str, body: str) -> KnowledgeItem | None:
    try:
        return _as(KnowledgeItem, get_container().add_item_note(item_id, body))
    except ItemNotFound:
        return None


def update_item_note(item_id: str, note_id: str, body: str) -> KnowledgeItem | None:
    try:
        return _as(KnowledgeItem, get_container().edit_item_note(item_id, note_id, body))
    except ItemNotFound:
        return None


def delete_item_note(item_id: str, note_id: str) -> KnowledgeItem | None:
    try:
        return _as(KnowledgeItem, get_container().delete_item_note(item_id, note_id))
    except ItemNotFound:
        return None
