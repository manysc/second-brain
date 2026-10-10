"""The application this MCP server talks to. The entry point (or a test) calls configure(); the read and write
adapters fetch use cases through use_cases() at call time, so the server itself can be built without a database."""
from __future__ import annotations

from app.container import Container, get_container

_container: Container | None = None


def configure(container: Container | None) -> None:
    """Sets the application to use; None goes back to the process-wide default."""
    global _container
    _container = container


def use_cases() -> Container:
    return _container if _container is not None else get_container()
