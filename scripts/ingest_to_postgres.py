"""Dev bootstrap: ingest meeting extraction files from SeaweedFS into Postgres (with embeddings).

Usage (from repo root, with the postgres + seaweedfs docker-compose services running,
after scripts/seed_seaweedfs.py has uploaded the fixtures):
    python scripts/ingest_to_postgres.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
load_dotenv(REPO_ROOT / "backend" / ".env")

from app.container import get_container  # noqa: E402  (must follow load_dotenv/sys.path setup)
from app.infrastructure.persistence import database  # noqa: E402


def main() -> None:
    database.init_db()
    # the same use case the API runs on startup and on POST /api/ingest
    summary = get_container().ingest_extracts()
    print(
        f"ingested into postgres: {summary.new} new, {summary.updated} updated, "
        f"{summary.unchanged} unchanged meeting(s)"
    )


if __name__ == "__main__":
    main()
