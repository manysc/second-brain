"""Contract tests over a real MCP client session (in-memory transport, no database needed)."""
import asyncio

import pytest
from mcp.client import Client
from sqlalchemy.exc import OperationalError

from mcp_server import service
from mcp_server.config import load_config
from mcp_server.server import create_server

READ_TOOLS = {
    "brain_health", "brain_search_items", "brain_get_item", "brain_get_topic_context", "brain_get_relationship_graph",
    "brain_list_open_actions", "brain_list_unresolved_questions", "brain_get_recent_changes",
}
WRITE_TOOLS = {"brain_update_item", "brain_add_note", "brain_add_item", "brain_edit_item", "brain_delete_item"}


def run(scenario, **config):
    async def go():
        async with Client(create_server(load_config(config))) as client:
            return await scenario(client)

    return asyncio.run(go())


def test_tool_discovery_annotations_and_schemas():
    async def scenario(client):
        return (await client.list_tools()).tools

    tools = {t.name: t for t in run(scenario)}
    assert set(tools) == READ_TOOLS | WRITE_TOOLS
    for name, tool in tools.items():
        assert len(tool.description) > 60, name
        assert tool.output_schema, name
        assert tool.input_schema.get("additionalProperties") is False, name
        assert tool.annotations.open_world_hint is False, name
        if name in READ_TOOLS:
            assert (tool.annotations.read_only_hint, tool.annotations.destructive_hint, tool.annotations.idempotent_hint) == (True, False, True)
    assert tools["brain_update_item"].annotations.read_only_hint is False
    assert tools["brain_update_item"].annotations.destructive_hint is True
    assert tools["brain_add_note"].annotations.destructive_hint is False
    assert tools["brain_add_note"].annotations.idempotent_hint is False
    assert tools["brain_add_item"].annotations.destructive_hint is False
    assert tools["brain_add_item"].annotations.idempotent_hint is False
    assert tools["brain_edit_item"].annotations.destructive_hint is True
    assert tools["brain_delete_item"].annotations.destructive_hint is True


def test_no_dangerous_generic_tools_are_exposed():
    async def scenario(client):
        return {t.name for t in (await client.list_tools()).tools}

    names = run(scenario)
    # brain_delete_item is the one deliberate delete: single record, manual items only, reason required
    assert not [
        n for n in names - {"brain_delete_item"} if any(bad in n for bad in ("sql", "shell", "exec", "fetch", "file", "delete", "bulk"))
    ]


def test_resource_templates_are_registered():
    async def scenario(client):
        return {t.uri_template for t in (await client.list_resource_templates()).resource_templates}

    assert run(scenario) == {"brain://items/{itemId}", "brain://topics/{topicId}/context", "brain://meetings/{meetingId}/summary"}


BAD_CALLS = [
    ("brain_search_items", {"limit": 0}),
    ("brain_search_items", {"limit": 51}),
    ("brain_search_items", {"types": ["SECRET"]}),
    ("brain_search_items", {"fromDate": "not-a-date"}),
    ("brain_search_items", {"query": "x" * 501}),
    ("brain_search_items", {"unexpected": True}),
    ("brain_get_item", {"itemId": "x; DROP TABLE knowledge_items"}),
    ("brain_get_item", {}),
    ("brain_get_relationship_graph", {"rootItemId": "a", "depth": 4}),
    ("brain_get_relationship_graph", {"rootItemId": "a", "maxNodes": 201}),
    ("brain_get_relationship_graph", {"rootItemId": "a", "relationshipTypes": []}),
    ("brain_get_topic_context", {"topicId": "t", "maxItemsPerType": 100}),
    ("brain_list_open_actions", {"priority": "URGENT"}),
    ("brain_update_item", {"itemId": "a", "patch": {}, "reason": "valid reason", "provenance": "test"}),
    ("brain_update_item", {"itemId": "a", "patch": {"owner": "x"}, "reason": "valid reason", "provenance": "test"}),
    ("brain_update_item", {"itemId": "a", "patch": {"status": "Closed"}, "reason": "no", "provenance": "test"}),
    ("brain_add_note", {"itemId": "a", "body": "", "provenance": "test"}),
    ("brain_add_item", {"topicId": "t", "type": "NOTE", "description": "x", "provenance": "test"}),
    ("brain_add_item", {"topicId": "t", "type": "IDEA", "description": "", "provenance": "test"}),
    ("brain_add_item", {"topicId": "t", "type": "IDEA", "description": "x" * 2001, "provenance": "test"}),
    ("brain_edit_item", {"itemId": "a", "patch": {}, "reason": "valid reason", "provenance": "test"}),
    ("brain_edit_item", {"itemId": "a", "patch": {"status": "Closed"}, "reason": "valid reason", "provenance": "test"}),
    ("brain_edit_item", {"itemId": "a", "patch": {"description": "x"}, "reason": "no", "provenance": "test"}),
    ("brain_delete_item", {"itemId": "a", "reason": "no", "provenance": "test"}),
    ("brain_delete_item", {"itemId": "x; DROP TABLE knowledge_items", "reason": "valid reason", "provenance": "test"}),
]


@pytest.mark.parametrize("name,args", BAD_CALLS)
def test_invalid_input_is_rejected_before_any_data_access(name, args):
    async def scenario(client):
        return await client.call_tool(name, args)

    result = run(scenario, BRAIN_MCP_ALLOW_WRITES="true")
    assert result.is_error


def test_writes_are_forbidden_unless_the_operator_enabled_them():
    async def scenario(client):
        return await client.call_tool(
            "brain_update_item",
            {"itemId": "a", "patch": {"status": "Closed"}, "reason": "valid reason", "provenance": "test"},
        )

    result = run(scenario)
    assert result.is_error and "FORBIDDEN" in result.content[0].text


@pytest.mark.parametrize(
    "name,args",
    [
        ("brain_add_item", {"topicId": "t", "type": "IDEA", "description": "x", "provenance": "test"}),
        ("brain_edit_item", {"itemId": "a", "patch": {"description": "x"}, "reason": "valid reason", "provenance": "test"}),
        ("brain_delete_item", {"itemId": "a", "reason": "valid reason", "provenance": "test"}),
    ],
)
def test_new_write_tools_are_forbidden_unless_enabled(name, args):
    async def scenario(client):
        return await client.call_tool(name, args)

    result = run(scenario)
    assert result.is_error and "FORBIDDEN" in result.content[0].text


def test_unexpected_failures_are_masked(monkeypatch):
    def boom(config):
        raise Exception("SELECT secret FROM t WHERE password=hunter2")

    monkeypatch.setattr(service, "health", boom)

    async def scenario(client):
        return await client.call_tool("brain_health", {})

    result = run(scenario)
    assert result.is_error and "INTERNAL_ERROR" in result.content[0].text
    assert "hunter2" not in result.content[0].text and "SELECT" not in result.content[0].text


def test_dependency_failure_is_reported_as_dependency_unavailable(monkeypatch):
    def down(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused password=hunter2"))

    monkeypatch.setattr(service.Snapshot, "load", classmethod(lambda cls: down()))

    async def scenario(client):
        return await client.call_tool("brain_get_item", {"itemId": "abc"})

    result = run(scenario)
    assert result.is_error and "DEPENDENCY_UNAVAILABLE" in result.content[0].text
    assert "hunter2" not in result.content[0].text


def test_health_degrades_instead_of_failing_and_hides_connection_details(monkeypatch):
    from app import db

    monkeypatch.setattr(db, "get_session", lambda: (_ for _ in ()).throw(RuntimeError("postgresql://u:p@h/db")))

    async def scenario(client):
        return await client.call_tool("brain_health", {})

    result = run(scenario)
    assert not result.is_error and result.structured_content["status"] == "degraded"
    assert "postgresql" not in str(result.structured_content) and result.structured_content["capabilities"]["writesEnabled"] is False
