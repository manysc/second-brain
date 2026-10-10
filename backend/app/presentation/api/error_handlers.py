"""Translates domain and application errors into HTTP responses, in one place. Routes only handle an error
themselves when its wording depends on the route."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.application.exceptions import (
    ExtractSourceUnavailable,
    IngestionAlreadyRunning,
    MalformedExtract,
)
from app.domain import exceptions as domain
from app.domain.value_objects.image_upload import MAX_IMAGE_BYTES

logger = logging.getLogger(__name__)


def _error(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


def _fixed(status_code: int, detail: str):
    def handler(request: Request, error: Exception) -> JSONResponse:
        return _error(status_code, detail)

    return handler


def _own_message(status_code: int):
    def handler(request: Request, error: Exception) -> JSONResponse:
        return _error(status_code, str(error))

    return handler


def _topic_name_conflict(request: Request, error: Exception) -> JSONResponse:
    name = error.args[0] if error.args else ""
    return _error(409, f"Topic '{name}' already exists")


def _topic_has_items(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, domain.TopicHasItems)
    return _error(409, f"Topic still has {error.item_count} item(s) assigned; reassign them before deleting")


def _extract_source_unavailable(request: Request, error: Exception) -> JSONResponse:
    logger.error("ingestion could not reach the extract source", exc_info=error)
    return _error(503, "Could not reach SeaweedFS")


def install_error_handlers(app: FastAPI) -> None:
    handlers = {
        # not found
        domain.TopicNotFound: _fixed(404, "Topic not found"),
        domain.ItemNotFound: _fixed(404, "Item not found"),
        domain.ItemsNotFound: _own_message(404),
        domain.MeetingNotFound: _fixed(404, "Meeting not found"),
        domain.NoMeetingsAvailable: _fixed(404, "No meetings available"),
        domain.ReviewCandidateNotFound: _fixed(404, "Review candidate not found"),
        domain.TopicProposalNotFound: _fixed(404, "Topic proposal not found"),
        # a topic named in a request body that does not exist is the caller's bad input, not a missing resource
        domain.ProposalTargetTopicNotFound: _own_message(400),
        # conflicts with the current state
        domain.TopicNameConflict: _topic_name_conflict,
        domain.TopicHasItems: _topic_has_items,
        domain.ItemNotDeletable: _own_message(409),
        domain.ReviewCandidateAlreadyDecided: _fixed(409, "Review candidate already decided"),
        IngestionAlreadyRunning: _fixed(409, "Ingestion is already running"),
        # invalid requests
        domain.ItemNotEditable: _own_message(400),
        domain.InvalidTopicMerge: _own_message(400),
        domain.InvalidTopicName: _own_message(400),
        domain.ImageTooLarge: _fixed(413, f"Image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB"),
        domain.UnsupportedImageType: _fixed(415, "Only PNG, JPEG, GIF and WebP images are supported"),
        MalformedExtract: _own_message(422),
        # the surroundings
        ExtractSourceUnavailable: _extract_source_unavailable,
    }
    for error_type, handler in handlers.items():
        app.add_exception_handler(error_type, handler)
