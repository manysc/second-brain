"""Business-rule violations. Technology-agnostic: nothing here knows about HTTP, SQL or MCP."""
from __future__ import annotations


class DomainError(Exception):
    """Base class for every business-rule violation."""


class TopicNotFound(DomainError):
    def __init__(self, topic_id: str | None = None) -> None:
        super().__init__("topic not found")
        self.topic_id = topic_id


class TopicNameConflict(DomainError):
    """Creating/renaming a topic to a name that is already taken."""


class InvalidTopicName(DomainError):
    def __init__(self) -> None:
        super().__init__("topic name must not be empty")


class InvalidTopicMerge(DomainError):
    def __init__(self) -> None:
        super().__init__("cannot merge a topic into itself")


class TopicHasItems(DomainError):
    """Deleting a topic that still has knowledge items assigned to it."""

    def __init__(self, item_count: int) -> None:
        super().__init__(item_count)
        self.item_count = item_count


class TopicProposalNotFound(DomainError):
    """No item is still waiting for a decision on this proposed topic name."""


class ItemNotFound(DomainError):
    def __init__(self, item_id: str | None = None) -> None:
        super().__init__("item not found")
        self.item_id = item_id


class ItemsNotFound(DomainError):
    def __init__(self, missing: set[str]) -> None:
        super().__init__(f"items not found: {sorted(missing)}")
        self.missing = missing


# ValueError stays a base until the MCP adapter maps this class explicitly (it reports ValueError as a
# validation error today).
class ItemNotEditable(DomainError, ValueError):
    """An edit touches a field that is fixed for meeting-extracted items."""


class ItemNotDeletable(DomainError):
    """Deleting an item that was extracted from a meeting rather than added manually."""

    def __init__(self, item_id: str) -> None:
        super().__init__("Only manually added items can be deleted")
        self.item_id = item_id


class ReviewCandidateAlreadyDecided(DomainError):
    """Accepting/rejecting a review candidate that is not PENDING anymore."""


class TooManyTags(DomainError):
    """args[0] is the limit."""


class UnsupportedImageType(DomainError):
    pass


class ImageTooLarge(DomainError):
    """args[0] is the limit in bytes."""
