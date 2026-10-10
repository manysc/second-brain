"""Shared pytest fixtures: loads backend/.env so DATABASE_URL/S3_* config is available to tests."""
from __future__ import annotations

from pathlib import Path

import pytest
from dotenv import load_dotenv
from sqlalchemy.exc import OperationalError

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@pytest.fixture(scope="module")
def db_ready():
    """Bootstraps the schema; skips the module's DB tests when Postgres is not reachable."""
    from app.infrastructure.persistence import database

    try:
        database.init_db()
    except OperationalError:
        pytest.skip("Postgres is not reachable at DATABASE_URL; skipping DB integration tests")
    yield
