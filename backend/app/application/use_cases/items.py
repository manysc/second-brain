"""Knowledge item use cases: browse, add/edit/delete by hand, status, priority override, filing under a topic,
tags and notes. Priority recalculation of the affected topics runs after the change is committed."""
from __future__ import annotations

from dataclasses import dataclass

from app.application.dtos import ItemDetailDTO, KnowledgeItemDTO, NewItem
from app.application.interfaces.repositories import UnitOfWork, UnitOfWorkFactory
from app.application.interfaces.services import Clock, Embedder, IdGenerator
from app.application.services import assembler
from app.application.services.priority_recalculation import PriorityRecalculator
from app.domain.entities.knowledge_item import ItemEdit, KnowledgeItem
from app.domain.entities.meeting import Meeting
from app.domain.entities.note import Note
from app.domain.exceptions import ItemNotFound, ItemsNotFound, TopicNotFound
from app.domain.policies import MANUAL_MEETING_ID
from app.domain.services.item_graph import related_items


def _get(uow: UnitOfWork, item_id: str) -> KnowledgeItem:
    item = uow.items.get(item_id)
    if item is None:
        raise ItemNotFound(item_id)
    return item


def filter_items(
    items: list[KnowledgeItemDTO],
    item_type: str | None = None,
    status: str | None = None,
    priority: str | None = None,
) -> list[KnowledgeItemDTO]:
    """Shared by the REST API and the MCP server so the filter semantics live in one place."""
    if item_type is not None:
        items = [item for item in items if item.type == item_type]
    if status is not None:
        items = [item for item in items if item.status == status]
    if priority is not None:
        items = [item for item in items if item.effective_priority == priority]
    return items


def similar_items(uow: UnitOfWork, item: KnowledgeItemDTO, limit: int) -> list[KnowledgeItemDTO]:
    """Nearest neighbours by embedding - a supplement to (not a replacement for) the evidence-grounded
    `related_ids` links, so callers must keep the two clearly separate."""
    excluded_ids = {item.id, *item.related_ids, *(f"{item.meeting_id}:{rid}" for rid in item.related_ids)}
    source = uow.items.get(item.id)
    if source is None or source.embedding is None:
        return []
    neighbours = [neighbour for neighbour, _ in uow.items.nearest(source.embedding, limit, exclude_ids=sorted(excluded_ids))]
    topics_by_id = {topic.id: topic for topic in uow.topics.list_by_ids([n.topic_id for n in neighbours if n.topic_id])}
    return list(assembler.item_dtos(neighbours, topics_by_id))


@dataclass(frozen=True)
class ListItems:
    uow: UnitOfWorkFactory

    def __call__(
        self, item_type: str | None = None, status: str | None = None, priority: str | None = None
    ) -> list[KnowledgeItemDTO]:
        """Every item, newest meeting first, optionally filtered by type, Open/Closed status and priority."""
        with self.uow() as uow:
            items = [item for meeting in assembler.load_meetings(uow) for item in meeting.items]
        return filter_items(items, item_type=item_type, status=status, priority=priority)


@dataclass(frozen=True)
class GetItemDetail:
    uow: UnitOfWorkFactory

    def __call__(self, item_id: str, similar_limit: int = 5) -> ItemDetailDTO:
        with self.uow() as uow:
            items = [item for meeting in assembler.load_meetings(uow) for item in meeting.items]
            item = next((candidate for candidate in items if candidate.id == item_id), None)
            if item is None:
                raise ItemNotFound(item_id)
            return ItemDetailDTO(
                item=item,
                related=tuple(related_items(item, items)),
                similar=tuple(similar_items(uow, item, similar_limit)),
            )


@dataclass(frozen=True)
class FindSimilarItems:
    uow: UnitOfWorkFactory

    def __call__(self, item: KnowledgeItemDTO, limit: int = 5) -> list[KnowledgeItemDTO]:
        with self.uow() as uow:
            return similar_items(uow, item, limit)


@dataclass(frozen=True)
class CreateItem:
    """Files a manually written item under a topic. Manual items hang off a synthetic "Manual entries"
    meeting because every item must belong to a meeting."""

    uow: UnitOfWorkFactory
    embedder: Embedder
    clock: Clock
    ids: IdGenerator
    recalculator: PriorityRecalculator

    def __call__(self, topic_id: str, new_item: NewItem) -> KnowledgeItemDTO:
        with self.uow() as uow:
            topic = uow.topics.get(topic_id)
            if topic is None:
                raise TopicNotFound(topic_id)
            if uow.meetings.get(MANUAL_MEETING_ID) is None:
                uow.meetings.add(Meeting.manual(self.clock.now().date().isoformat()))
            item = KnowledgeItem.manual(
                unique_id=self.ids.new_id(),
                topic=topic,
                type=new_item.type,  # type: ignore[arg-type]
                description=new_item.description,
                owner=new_item.owner,
                due_date=new_item.due_date,
                rationale=new_item.rationale,
                embedding=self.embedder.embed_text(new_item.description),
            )
            uow.items.add(item)
            uow.commit()
            created = assembler.item_dto(item, topic)
        self.recalculator.recalculate_topics({topic_id}, trigger="item_added")
        return created


@dataclass(frozen=True)
class UpdateItem:
    """Edits description/owner/due date/rationale (and type, manual items only)."""

    uow: UnitOfWorkFactory
    embedder: Embedder
    recalculator: PriorityRecalculator

    def __call__(self, item_id: str, changes: ItemEdit) -> KnowledgeItemDTO:
        with self.uow() as uow:
            item = _get(uow, item_id)
            if item.edit(changes):
                item.reembed(self.embedder.embed_text(item.description))
            uow.items.save(item)
            uow.commit()
            updated, topic_id = assembler.load_item_dto(uow, item), item.topic_id
        if topic_id:
            self.recalculator.recalculate_topics({topic_id}, trigger="item_edited")
        return updated


@dataclass(frozen=True)
class DeleteItem:
    """Deletes a manually added item (its notes go with it)."""

    uow: UnitOfWorkFactory
    recalculator: PriorityRecalculator

    def __call__(self, item_id: str) -> None:
        with self.uow() as uow:
            item = _get(uow, item_id)
            item.ensure_deletable()
            topic_id = item.topic_id
            uow.items.delete(item)
            uow.commit()
        if topic_id:
            self.recalculator.recalculate_topics({topic_id}, trigger="item_deleted")


@dataclass(frozen=True)
class SetItemStatus:
    uow: UnitOfWorkFactory

    def __call__(self, item_id: str, status: str) -> KnowledgeItemDTO:
        with self.uow() as uow:
            item = _get(uow, item_id)
            item.set_status(status)
            uow.items.save(item)
            uow.commit()
            return assembler.load_item_dto(uow, item)


@dataclass(frozen=True)
class SetItemPriorityOverride:
    """Sets/clears a manual priority override directly on an item - independent of, and never touched by,
    its topic's automatic priority recalculation."""

    uow: UnitOfWorkFactory
    clock: Clock

    def __call__(self, item_id: str, priority: str | None, reason: str | None) -> KnowledgeItemDTO:
        with self.uow() as uow:
            item = _get(uow, item_id)
            item.override_priority(priority, reason, self.clock.now().isoformat())  # type: ignore[arg-type]
            uow.items.save(item)
            uow.commit()
            return assembler.load_item_dto(uow, item)


@dataclass(frozen=True)
class AssignItemTopic:
    uow: UnitOfWorkFactory
    recalculator: PriorityRecalculator

    def __call__(self, item_id: str, topic_id: str | None) -> KnowledgeItemDTO:
        with self.uow() as uow:
            item = _get(uow, item_id)
            old_topic_id = item.topic_id
            topic = None
            if topic_id is not None:
                topic = uow.topics.get(topic_id)
                if topic is None:
                    raise TopicNotFound(topic_id)
            item.file_under(topic)
            uow.items.save(item)
            uow.commit()
            moved = assembler.item_dto(item, topic)
        self.recalculator.recalculate_topics({old_topic_id, topic_id}, trigger="item_topic_reassigned")
        return moved


@dataclass(frozen=True)
class AssignItemsTopic:
    """Bulk version of AssignItemTopic - one transaction and one priority recalculation pass for all
    affected items."""

    uow: UnitOfWorkFactory
    recalculator: PriorityRecalculator

    def __call__(self, item_ids: list[str], topic_id: str | None) -> list[KnowledgeItemDTO]:
        with self.uow() as uow:
            topic = None
            if topic_id is not None:
                topic = uow.topics.get(topic_id)
                if topic is None:
                    raise TopicNotFound(topic_id)
            items = uow.items.list_by_ids(item_ids)
            missing = set(item_ids) - {item.id for item in items}
            if missing:
                raise ItemsNotFound(missing)
            old_topic_ids = {item.topic_id for item in items}
            for item in items:
                item.file_under(topic)
                uow.items.save(item)
            uow.commit()
            moved = [assembler.item_dto(item, topic) for item in items]
        self.recalculator.recalculate_topics(old_topic_ids | {topic_id}, trigger="items_topic_bulk_reassigned")
        return moved


@dataclass(frozen=True)
class AddItemTag:
    uow: UnitOfWorkFactory

    def __call__(self, item_id: str, tag: str) -> KnowledgeItemDTO:
        with self.uow() as uow:
            item = _get(uow, item_id)
            item.add_tag(tag)
            uow.items.save(item)
            uow.commit()
            return assembler.load_item_dto(uow, item)


@dataclass(frozen=True)
class RemoveItemTag:
    uow: UnitOfWorkFactory

    def __call__(self, item_id: str, tag: str) -> KnowledgeItemDTO:
        with self.uow() as uow:
            item = _get(uow, item_id)
            item.remove_tag(tag)
            uow.items.save(item)
            uow.commit()
            return assembler.load_item_dto(uow, item)


@dataclass(frozen=True)
class AddItemNote:
    uow: UnitOfWorkFactory
    clock: Clock
    ids: IdGenerator

    def __call__(self, item_id: str, body: str) -> KnowledgeItemDTO:
        with self.uow() as uow:
            item = _get(uow, item_id)
            item.add_note(Note(id=self.ids.new_short_id(), body=body, created_at=self.clock.now().isoformat()))
            uow.items.save(item)
            uow.commit()
            return assembler.load_item_dto(uow, item)


@dataclass(frozen=True)
class EditItemNote:
    uow: UnitOfWorkFactory

    def __call__(self, item_id: str, note_id: str, body: str) -> KnowledgeItemDTO:
        with self.uow() as uow:
            item = _get(uow, item_id)
            item.edit_note(note_id, body)
            uow.items.save(item)
            uow.commit()
            return assembler.load_item_dto(uow, item)


@dataclass(frozen=True)
class DeleteItemNote:
    uow: UnitOfWorkFactory

    def __call__(self, item_id: str, note_id: str) -> KnowledgeItemDTO:
        with self.uow() as uow:
            item = _get(uow, item_id)
            item.remove_note(note_id)
            uow.items.save(item)
            uow.commit()
            return assembler.load_item_dto(uow, item)
