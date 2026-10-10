"""Builds the FastAPI application around a Container of use cases."""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.application.exceptions import ExtractSourceUnavailable
from app.container import Container
from app.presentation.api.error_handlers import install_error_handlers
from app.presentation.api.routers import (
    insights,
    items,
    meetings,
    priority,
    review,
    topics,
)

logger = logging.getLogger(__name__)

STARTUP_INGEST_ATTEMPTS = 5


def run_startup_ingest(container: Container, sleep: Callable[[float], None] = time.sleep) -> None:
    """Ingests once at startup, retrying while the extract source is unreachable. Any failure is logged and
    swallowed: storage hiccups must not stop the API from serving the data it already has."""
    delay = 3.0
    for attempt in range(1, STARTUP_INGEST_ATTEMPTS + 1):
        try:
            # waits behind a manual run that may already be in progress
            summary = container.ingest_extracts(wait=True)
            logger.info(
                "startup ingestion: %d new, %d updated, %d unchanged meeting(s)",
                summary.new, summary.updated, summary.unchanged,
            )
            return
        except ExtractSourceUnavailable as exc:
            if attempt == STARTUP_INGEST_ATTEMPTS:
                logger.exception("startup ingestion failed; continuing with existing data")
                return
            cause = exc.__cause__ or exc
            logger.warning(
                "startup ingestion attempt %d/%d could not reach S3 (%s); retrying in %.0fs",
                attempt, STARTUP_INGEST_ATTEMPTS, cause.__class__.__name__, delay,
            )
            sleep(delay)
            delay = min(delay * 2, 30.0)
        except Exception:
            logger.exception("startup ingestion failed; continuing with existing data")
            return


def warm_embeddings(container: Container) -> None:
    # loads the embedding model up front so the first review page load / accept isn't a multi-second stall
    try:
        container.embedder.embed_text("warm-up")
    except Exception:  # warm-up is best effort
        logger.warning("embedding warm-up failed", exc_info=True)


def create_app(
    container: Container,
    *,
    initialize: Callable[[], None] | None = None,
    ingest_on_startup: bool = True,
) -> FastAPI:
    """`initialize` prepares storage before the first request (the composition root passes the schema
    bootstrap). With `ingest_on_startup`, extracts are ingested in the background once the API is up."""

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if initialize is not None:
            initialize()
        warm_task = asyncio.create_task(asyncio.to_thread(warm_embeddings, container))
        ingest_task: asyncio.Task[None] | None = None
        if ingest_on_startup:
            # off the startup path: the API serves existing data while ingestion catches up
            ingest_task = asyncio.create_task(asyncio.to_thread(run_startup_ingest, container))
        yield
        for task in (warm_task, ingest_task):
            if task is not None and not task.done():
                task.cancel()

    app = FastAPI(title="second-brain backend", lifespan=lifespan)
    app.state.container = container
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    # within a router the declaration order is load-bearing: fixed paths come before parameterized ones
    for module in (meetings, items, insights, topics, priority, review):
        app.include_router(module.router)
    return app
