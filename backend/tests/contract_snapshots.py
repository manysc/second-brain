"""Builds the public-contract snapshots (REST OpenAPI document, MCP tool/resource catalog) that the refactor must
keep stable. Regenerate deliberately with `python -m tests.contract_snapshots` from backend/ after an intended
contract change, and review the diff."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parent / "fixtures"
OPENAPI_SNAPSHOT = FIXTURES / "openapi.snapshot.json"
MCP_SNAPSHOT = FIXTURES / "mcp-tools.snapshot.json"


def openapi_document() -> dict[str, Any]:
    from app.main import app

    return app.openapi()


def mcp_catalog() -> dict[str, Any]:
    from mcp.client import Client

    from app.presentation.mcp.config import load_config
    from app.presentation.mcp.server import create_server

    async def go() -> dict[str, Any]:
        async with Client(create_server(load_config({}))) as client:
            tools = (await client.list_tools()).tools
            templates = (await client.list_resource_templates()).resource_templates
            return {
                "tools": [t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in sorted(tools, key=lambda t: t.name)],
                "resourceTemplates": [
                    r.model_dump(mode="json", by_alias=True, exclude_none=True)
                    for r in sorted(templates, key=lambda r: r.uri_template)
                ],
            }

    return asyncio.run(go())


def dump(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    OPENAPI_SNAPSHOT.write_text(dump(openapi_document()), encoding="utf-8")
    MCP_SNAPSHOT.write_text(dump(mcp_catalog()), encoding="utf-8")
    print(f"wrote {OPENAPI_SNAPSHOT.name} and {MCP_SNAPSHOT.name}")
