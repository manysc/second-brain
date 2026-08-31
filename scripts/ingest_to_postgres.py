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

from app import db, ingest  # noqa: E402  (must follow load_dotenv/sys.path setup)


def main() -> None:
    db.init_db()
    with db.get_session() as session:
        count = ingest.ingest_all_from_s3(session)
        session.commit()
    print(f"ingested {count} meeting(s) into postgres")


if __name__ == "__main__":
    main()
