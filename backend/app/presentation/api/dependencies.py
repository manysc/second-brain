from __future__ import annotations

from typing import Annotated, Any, TypeVar

from fastapi import Depends, Request
from pydantic import BaseModel

from app.container import Container

_S = TypeVar("_S", bound=BaseModel)


def get_container(request: Request) -> Container:
    """The use cases this API instance was built with (see app_factory.create_app)."""
    return request.app.state.container


# every route receives the application through this dependency
App = Annotated[Container, Depends(get_container)]


def to_schema(schema: type[_S], dto: Any) -> _S:
    return schema.model_validate(dto, from_attributes=True)


def to_schemas(schema: type[_S], dtos: Any) -> list[_S]:
    return [to_schema(schema, dto) for dto in dtos]
