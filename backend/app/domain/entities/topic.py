from __future__ import annotations

from collections.abc import Sequence

from app.domain.entities.base import ReadOnly
from app.domain.entities.note import Note, edit_note, remove_note
from app.domain.entities.topic_image import TopicImage
from app.domain.exceptions import InvalidTopicMerge, TopicHasItems
from app.domain.policies import UNCATEGORIZED_TOPIC
from app.domain.services.topic_priority.facts import PreviousPriorityState
from app.domain.value_objects.priority import (
    ManualPriorityOverride,
    TopicPriorityHistoryEntry,
    TopicPriorityInfo,
    TopicPriorityLevel,
)
from app.domain.value_objects.tag import with_tag, without_tag


class Topic:
    """A persistent thread of knowledge that items are filed under.

    Its priority has two independent parts: `calculation`, written only by automatic recalculation, and
    `manual_override`, written only by a person. Neither ever overwrites the other."""

    id: str = ReadOnly()  # type: ignore[assignment]
    name: str = ReadOnly()  # type: ignore[assignment]
    status: str = ReadOnly()  # type: ignore[assignment]
    tags: tuple[str, ...] = ReadOnly()  # type: ignore[assignment]
    notes: tuple[Note, ...] = ReadOnly()  # type: ignore[assignment]
    images: tuple[TopicImage, ...] = ReadOnly()  # type: ignore[assignment]
    calculation: TopicPriorityInfo | None = ReadOnly()  # type: ignore[assignment]
    manual_override: ManualPriorityOverride | None = ReadOnly()  # type: ignore[assignment]

    def __init__(
        self,
        *,
        id: str,
        name: str,
        status: str = "Open",
        tags: Sequence[str] = (),
        notes: Sequence[Note] = (),
        images: Sequence[TopicImage] = (),
        calculation: TopicPriorityInfo | None = None,
        manual_override: ManualPriorityOverride | None = None,
    ) -> None:
        self._id = id
        self._name = name
        self._status = status
        self._tags = tuple(tags)
        self._notes = tuple(notes)
        self._images = tuple(images)
        self._calculation = calculation
        self._manual_override = manual_override

    # -- queries ---------------------------------------------------------------------------------------

    @property
    def is_uncategorized(self) -> bool:
        return self._name == UNCATEGORIZED_TOPIC

    @property
    def effective_priority(self) -> TopicPriorityLevel | None:
        """The manual override when one is set, else the calculated priority (None until first calculated)."""
        if self._manual_override is not None:
            return self._manual_override.priority
        return self._calculation.calculated_priority if self._calculation is not None else None

    @property
    def priority(self) -> TopicPriorityInfo | None:
        """The calculation seen through the manual override; None until priority has been calculated."""
        if self._calculation is None:
            return None
        return self._calculation.with_override(self._manual_override)

    @property
    def previous_priority_state(self) -> PreviousPriorityState | None:
        """What the scorer needs for hysteresis: the last calculated level and score."""
        if self._calculation is None:
            return None
        return PreviousPriorityState(
            priority=self._calculation.calculated_priority, score=self._calculation.calculated_score
        )

    # -- human decisions -------------------------------------------------------------------------------

    def rename(self, name: str) -> None:
        self._name = name

    def set_status(self, status: str) -> None:
        self._status = status

    def add_tag(self, tag: str) -> None:
        self._tags = tuple(with_tag(self._tags, tag))

    def remove_tag(self, tag: str) -> None:
        self._tags = tuple(without_tag(self._tags, tag))

    def add_note(self, note: Note) -> None:
        self._notes = (*self._notes, note)

    def edit_note(self, note_id: str, body: str) -> None:
        self._notes = edit_note(self._notes, note_id, body)

    def remove_note(self, note_id: str) -> None:
        self._notes = remove_note(self._notes, note_id)

    def attach_image(self, image: TopicImage) -> None:
        self._images = (*self._images, image)

    def detach_image(self, image_id: str) -> TopicImage | None:
        """Removes the image and returns it so its stored bytes can be deleted; None if there is no such image."""
        removed = next((image for image in self._images if image.id == image_id), None)
        self._images = tuple(image for image in self._images if image.id != image_id)
        return removed

    def find_image(self, image_id: str) -> TopicImage | None:
        return next((image for image in self._images if image.id == image_id), None)

    def override_priority(self, priority: TopicPriorityLevel | None, reason: str | None, at: str) -> None:
        """Sets a manual priority, or clears it (with its reason and timestamp) when `priority` is None."""
        self._manual_override = (
            ManualPriorityOverride(priority=priority, reason=reason, overridden_at=at) if priority is not None else None
        )

    def ensure_deletable(self, item_count: int) -> None:
        """A topic can only be deleted once every item has been reassigned."""
        if item_count:
            raise TopicHasItems(item_count)

    def ensure_can_merge_into(self, target: Topic) -> None:
        if self._id == target.id:
            raise InvalidTopicMerge()

    # -- automatic priority ----------------------------------------------------------------------------

    def record_priority(
        self, result: TopicPriorityInfo, *, trigger: str, history_id: str
    ) -> TopicPriorityHistoryEntry | None:
        """Stores a fresh calculation and returns a history entry iff the priority category changed.
        The manual override is never touched."""
        previous = self._calculation
        self._calculation = result
        if previous is None or previous.calculated_priority == result.calculated_priority:
            return None
        return TopicPriorityHistoryEntry(
            id=history_id,
            topic_id=self._id,
            previous_priority=previous.calculated_priority,
            new_priority=result.calculated_priority,
            previous_score=previous.calculated_score,
            new_score=result.calculated_score,
            changed_at=result.calculated_at,
            algorithm_version=result.algorithm_version,
            primary_drivers=[driver.explanation for driver in result.top_drivers()],
            trigger=trigger,
            source_knowledge_item_ids=result.source_item_ids(),
        )
