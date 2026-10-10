"""ASGI entry point and composition root for the REST API: `uvicorn app.main:app`.

This is the only place where the API meets the infrastructure. It loads configuration, builds the Container
(app.container) and hands it to the presentation layer."""
from __future__ import annotations

import os

from dotenv import load_dotenv

from app.container import get_container
from app.infrastructure.persistence import database
from app.presentation.api.app_factory import create_app

# picks up backend/.env so the database and S3 settings survive across process restarts
load_dotenv()

app = create_app(
    get_container(),
    initialize=database.init_db,
    ingest_on_startup=os.environ.get("INGEST_ON_STARTUP", "true").lower() not in ("false", "0"),
)
