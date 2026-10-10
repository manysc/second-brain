from __future__ import annotations

from dataclasses import dataclass

from app.application.interfaces.repositories import UnitOfWorkFactory


@dataclass(frozen=True)
class StorageHealth:
    reachable: bool
    item_count: int | None = None
    # the kind of failure only (an exception class name): never a message, which could carry connection details
    error: str | None = None


@dataclass(frozen=True)
class CheckStorageHealth:
    """Reports whether the knowledge base can be read. Never raises: a health check must always answer."""

    uow: UnitOfWorkFactory

    def __call__(self) -> StorageHealth:
        try:
            with self.uow() as uow:
                count = uow.items.count_all()
        except Exception as error:
            cause = error.__cause__ or error
            return StorageHealth(reachable=False, error=type(cause).__name__)
        return StorageHealth(reachable=True, item_count=int(count))
