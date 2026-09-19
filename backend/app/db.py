"""Postgres connection setup and schema bootstrap (pgvector extension + tables)."""
from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Connection, Engine, create_engine, text
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
    # one connection/transaction for the whole bootstrap rather than one per migration step
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(conn)
        _backfill_topics(conn)
        _backfill_topic_priority(conn)
        _backfill_item_priority_override(conn)
        _backfill_suggested_topic(conn)


def _backfill_suggested_topic(conn: Connection) -> None:
    """Idempotent migration: adds knowledge_items.suggested_topic (new-topic proposals awaiting review)."""
    conn.execute(text("ALTER TABLE knowledge_items ADD COLUMN IF NOT EXISTS suggested_topic VARCHAR"))


def _backfill_topics(conn: Connection) -> None:
    """Idempotent migration: adds knowledge_items.topic_id (new DBs get it via create_all
    already) and populates a topics row + topic_id for any pre-existing theme-grouped rows."""
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


def _backfill_topic_priority(conn: Connection) -> None:
    """Idempotent migration: adds the priority-classification columns to a pre-existing
    `topics` table. The new `topic_priority_history` table itself is created by create_all."""
    columns = [
        ("calculated_priority", "VARCHAR"),
        ("calculated_priority_score", "DOUBLE PRECISION"),
        ("priority_confidence", "VARCHAR"),
        ("priority_signals", "JSONB"),
        ("priority_hard_escalations", "JSONB"),
        ("priority_explanation", "TEXT"),
        ("priority_algorithm_version", "VARCHAR"),
        ("priority_semantic_contribution", "JSONB"),
        ("priority_calculated_at", "VARCHAR"),
        ("manual_priority_override", "VARCHAR"),
        ("manual_override_reason", "TEXT"),
        ("manual_override_at", "VARCHAR"),
    ]
    for name, sql_type in columns:
        conn.execute(text(f"ALTER TABLE topics ADD COLUMN IF NOT EXISTS {name} {sql_type}"))


def _backfill_item_priority_override(conn: Connection) -> None:
    """Idempotent migration: adds the manual priority-override columns to a pre-existing
    `knowledge_items` table. Items have no automatic calculation of their own (Option A) - only
    an optional override that falls back to the owning Topic's priority when unset."""
    columns = [
        ("manual_priority_override", "VARCHAR"),
        ("manual_override_reason", "TEXT"),
        ("manual_override_at", "VARCHAR"),
    ]
    for name, sql_type in columns:
        conn.execute(text(f"ALTER TABLE knowledge_items ADD COLUMN IF NOT EXISTS {name} {sql_type}"))


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

