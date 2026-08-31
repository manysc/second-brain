"""Shared pytest fixtures: loads backend/.env so DATABASE_URL/S3_* config is available to tests."""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
