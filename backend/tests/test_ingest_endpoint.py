"""POST /api/ingest: the manual counterpart of the startup ingestion. ingest_and_commit is stubbed, so
these need neither Postgres nor S3."""
from __future__ import annotations

import pytest
from botocore.exceptions import EndpointConnectionError
from fastapi.testclient import TestClient

from app import main
from app.ingest import IngestSummary
from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)  # no `with`: skips the startup ingestion


def _stub(monkeypatch, behaviour) -> None:
    monkeypatch.setattr(main.ingest, "ingest_and_commit", behaviour)


def _summary(new: int = 0, updated: int = 0, unchanged: int = 0) -> IngestSummary:
    return IngestSummary(processed=new + updated + unchanged, new=new, updated=updated, unchanged=unchanged)


def test_reports_new_updated_and_unchanged_meetings(client, monkeypatch):
    _stub(monkeypatch, lambda: _summary(new=2, updated=1, unchanged=61))
    response = client.post("/api/ingest")
    assert response.status_code == 200
    assert response.json() == {"meetings": 64, "new": 2, "updated": 1, "unchanged": 61}


def test_rejects_overlapping_run(client, monkeypatch):
    _stub(monkeypatch, lambda: _summary(unchanged=3))
    with main._ingest_lock:
        response = client.post("/api/ingest")
    assert response.status_code == 409


def test_unreachable_s3_is_a_503(client, monkeypatch):
    def unreachable() -> int:
        raise EndpointConnectionError(endpoint_url="http://seaweedfs:8333")

    _stub(monkeypatch, unreachable)
    response = client.post("/api/ingest")
    assert response.status_code == 503
    assert response.json()["detail"] == "Could not reach SeaweedFS"


def test_malformed_extract_is_a_422_and_releases_the_lock(client, monkeypatch):
    def malformed() -> int:
        raise ValueError("'bad.json' is not a recognized single-meeting or bundle extraction file")

    _stub(monkeypatch, malformed)
    response = client.post("/api/ingest")
    assert response.status_code == 422
    assert "bad.json" in response.json()["detail"]

    _stub(monkeypatch, lambda: _summary(new=1))
    assert client.post("/api/ingest").json()["new"] == 1
