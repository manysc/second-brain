from __future__ import annotations

from typing import Any


class ReadOnly:
    """Exposes an entity's private attribute (`_name`) for reading only. Entities have no public setters:
    their state changes through methods that enforce the business rules."""

    def __set_name__(self, owner: type, name: str) -> None:
        self._name = name
        self._private = f"_{name}"

    def __get__(self, instance: Any, owner: type | None = None) -> Any:
        return self if instance is None else getattr(instance, self._private)

    def __set__(self, instance: Any, value: Any) -> None:
        raise AttributeError(f"{type(instance).__name__}.{self._name} is read-only; use the entity's methods")
