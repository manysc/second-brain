"""Postgres connection setup and schema bootstrap (pgvector extension + tables)."""
from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.db_models import Base


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is required")
    return url


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_engine(_database_url())
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def init_db() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    _backfill_topics(engine)


def _backfill_topics(engine: Engine) -> None:
    """Idempotent migration: adds knowledge_items.topic_id (new DBs get it via create_all
    already) and populates a topics row + topic_id for any pre-existing theme-grouped rows."""
    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE knowledge_items ADD COLUMN IF NOT EXISTS topic_id VARCHAR REFERENCES topics(id)")
        )
        themes = conn.execute(
            text("SELECT DISTINCT theme FROM knowledge_items WHERE topic_id IS NULL")
        ).fetchall()
        for (theme,) in themes:
            name = theme or "Uncategorized"
            existing = conn.execute(text("SELECT id FROM topics WHERE name = :name"), {"name": name}).fetchone()
            topic_id = existing[0] if existing else str(uuid.uuid4())
            if existing is None:
                conn.execute(text("INSERT INTO topics (id, name) VALUES (:id, :name)"), {"id": topic_id, "name": name})
            conn.execute(
                text(
                    "UPDATE knowledge_items SET topic_id = :tid "
                    "WHERE topic_id IS NULL AND theme IS NOT DISTINCT FROM :theme"
                ),
                {"tid": topic_id, "theme": theme},
            )


@contextmanager
def get_session() -> Iterator[Session]:
    get_engine()  # ensures _SessionLocal is initialized
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()


def reset_engine_cache() -> None:
    """Test helper: forces get_engine() to rebuild from the current DATABASE_URL."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None

