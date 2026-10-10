"""The REST and MCP contracts must not change by accident (no database needed).
After an intended change, regenerate with `python -m tests.contract_snapshots` and review the diff."""
from __future__ import annotations

from tests.contract_snapshots import MCP_SNAPSHOT, OPENAPI_SNAPSHOT, dump, mcp_catalog, openapi_document


def test_openapi_document_matches_snapshot():
    assert dump(openapi_document()) == OPENAPI_SNAPSHOT.read_text(encoding="utf-8")


def test_mcp_catalog_matches_snapshot():
    assert dump(mcp_catalog()) == MCP_SNAPSHOT.read_text(encoding="utf-8")
