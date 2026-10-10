"""Unit tests: config, error mapping/redaction, pagination, write allowlist + guard."""
import pytest
from pydantic import ValidationError

from app.application.exceptions import StorageNotConfigured, StorageUnavailable
from app.domain import exceptions as domain
from app.presentation.mcp import context, writes
from app.presentation.mcp.config import ConfigError, load_config
from app.presentation.mcp.errors import BrainError, map_exception, redact
from app.presentation.mcp.pagination import decode_cursor, encode_cursor, paginate
from tests.mcp_tests import factories as f


# ---- config ----
def test_config_defaults_to_dev_identity_and_read_only():
    cfg = load_config({})
    assert cfg.is_development and cfg.actor == "claude-code-dev" and cfg.allow_writes is False


def test_config_refuses_production_without_explicit_override():
    with pytest.raises(ConfigError, match="refusing to start"):
        load_config({"BRAIN_ENV": "production"})


def test_config_production_needs_explicit_actor_even_with_override():
    with pytest.raises(ConfigError, match="BRAIN_MCP_ACTOR"):
        load_config({"BRAIN_ENV": "production", "BRAIN_MCP_ALLOW_PRODUCTION": "true"})
    cfg = load_config({"BRAIN_ENV": "production", "BRAIN_MCP_ALLOW_PRODUCTION": "true", "BRAIN_MCP_ACTOR": "svc"})
    assert cfg.actor == "svc" and not cfg.is_development


def test_config_rejects_bad_rate():
    with pytest.raises(ConfigError):
        load_config({"BRAIN_MCP_WRITE_RATE_PER_MINUTE": "abc"})
    with pytest.raises(ConfigError):
        load_config({"BRAIN_MCP_WRITE_RATE_PER_MINUTE": "0"})


# ---- errors ----
def test_error_mapping_covers_expected_codes():
    assert map_exception(BrainError("NOT_FOUND", "x")).code == "NOT_FOUND"
    assert map_exception(ValueError("bad")).code == "VALIDATION_ERROR"
    assert map_exception(domain.TopicNameConflict()).code == "CONFLICT"
    assert map_exception(domain.TopicHasItems(2)).code == "CONFLICT"
    assert map_exception(domain.ReviewCandidateAlreadyDecided("c")).code == "CONFLICT"
    unreachable = map_exception(StorageUnavailable("connection refused password=hunter2"))
    assert unreachable.code == "DEPENDENCY_UNAVAILABLE" and "hunter2" not in str(unreachable)
    assert "DATABASE_URL" in str(map_exception(StorageNotConfigured("no url")))
    assert map_exception(StorageNotConfigured("no url")).code == "DEPENDENCY_UNAVAILABLE"


def test_domain_errors_map_to_useful_codes():
    assert str(map_exception(domain.ItemNotFound("m1:A-9"))).startswith("NOT_FOUND: Item 'm1:A-9' was not found")
    assert str(map_exception(domain.TopicNotFound("t9"))).startswith("NOT_FOUND: Topic 't9' was not found")
    not_editable = map_exception(domain.ItemNotEditable("The type of an item extracted from a meeting cannot be changed"))
    assert (not_editable.code, not_editable.message) == (
        "VALIDATION_ERROR", "The type of an item extracted from a meeting cannot be changed",
    )


def test_unknown_errors_never_leak_details():
    mapped = map_exception(Exception("SELECT * FROM users WHERE password=hunter2 at C:\\secret\\path.py"))
    assert mapped.code == "INTERNAL_ERROR"
    assert "hunter2" not in str(mapped) and "SELECT" not in str(mapped) and "secret" not in str(mapped)


def test_validation_errors_do_not_echo_input_values():
    with pytest.raises(ValidationError) as caught:
        writes.ItemPatch.model_validate({"priorityOverride": "SUPER-SECRET-VALUE"})
    mapped = map_exception(caught.value)
    assert mapped.code == "VALIDATION_ERROR" and "SUPER-SECRET-VALUE" not in mapped.message


def test_redact_hides_credentials():
    text = redact("postgresql+psycopg://user:pw123@localhost/db token=abc AKIAABCDEFGHIJKLMNOP")
    assert "pw123" not in text and "abc" not in text and "AKIAABCDEFGHIJKLMNOP" not in text


# ---- pagination ----
def test_paginate_walks_all_pages_deterministically():
    rows, params = list(range(7)), {"q": "x"}
    seen, cursor = [], None
    while True:
        page, cursor = paginate(rows, 3, cursor, params)
        seen += page
        if cursor is None:
            break
    assert seen == rows


def test_cursor_bound_to_filters_and_validated():
    cursor = encode_cursor(3, {"q": "a"})
    assert decode_cursor(cursor, {"q": "a"}) == 3
    with pytest.raises(BrainError, match="does not match"):
        decode_cursor(cursor, {"q": "b"})
    with pytest.raises(BrainError, match="Invalid cursor"):
        decode_cursor("!!!not-a-cursor", {})


# ---- write allowlist ----
@pytest.mark.parametrize(
    "payload",
    [{}, {"owner": "x"}, {"status": "Done"}, {"priorityOverride": "URGENT"}, {"topicId": "bad id!"}, {"status": "Open", "extra": 1}],
)
def test_item_patch_rejects_invalid(payload):
    with pytest.raises(ValidationError):
        writes.ItemPatch.model_validate(payload)


def test_item_patch_accepts_allowlisted_fields():
    p = writes.ItemPatch.model_validate({"status": "Closed", "priorityOverride": "CLEAR", "topicId": "t1"})
    assert p.status == "Closed" and p.priority_override == "CLEAR"


class _Recorder:
    def __init__(self, monkeypatch, snapshot):
        self.calls: list[tuple] = []
        monkeypatch.setattr(writes.Snapshot, "load", classmethod(lambda cls: snapshot))
        monkeypatch.setattr(
            context,
            "_container",
            f.application(
                set_item_status=lambda i, s: self.calls.append(("status", i, s)),
                set_item_priority_override=lambda i, p, r: self.calls.append(("priority", i, p, r)),
                assign_item_topic=lambda i, t: self.calls.append(("topic", i, t)),
                add_item_note=lambda i, b: self.calls.append(("note", i, b)) or f.item(i, notes=[]),
            ),
        )


def _snapshot():
    from app.presentation.mcp.service import Snapshot

    a = f.item("m1:A-1", status="Open", priority="MAJOR")
    return Snapshot(
        meetings=[f.meeting("m1", "2026-09-10", [a])], topics=[f.topic("t1", "Alpha", [a]), f.topic("t2", "Beta", [])], items=[a]
    )


def _guard(**overrides):
    cfg = load_config({"BRAIN_MCP_ALLOW_WRITES": "true", **overrides})
    return writes.WriteGuard(cfg)


def test_update_applies_only_changed_allowlisted_fields(monkeypatch):
    rec = _Recorder(monkeypatch, _snapshot())
    patch = writes.ItemPatch.model_validate({"status": "Closed", "topicId": "t2"})
    out = writes.update_item(_guard(), "m1:A-1", patch, None, "closing out", "unit test")
    assert out.applied == ["status", "topicId"]
    assert rec.calls == [("status", "m1:A-1", "Closed"), ("topic", "m1:A-1", "t2")]
    assert out.audit.actor == "claude-code-dev"


def test_update_forbidden_when_writes_disabled(monkeypatch):
    rec = _Recorder(monkeypatch, _snapshot())
    guard = writes.WriteGuard(load_config({}))
    with pytest.raises(BrainError) as caught:
        writes.update_item(guard, "m1:A-1", writes.ItemPatch(status="Closed"), None, "closing out", "unit")
    assert caught.value.code == "FORBIDDEN" and rec.calls == []


def test_update_requires_reason(monkeypatch):
    _Recorder(monkeypatch, _snapshot())
    with pytest.raises(BrainError) as caught:
        writes.update_item(_guard(), "m1:A-1", writes.ItemPatch(status="Closed"), None, " ", "unit")
    assert caught.value.code == "VALIDATION_ERROR"


def test_update_conflict_when_expected_value_is_stale(monkeypatch):
    rec = _Recorder(monkeypatch, _snapshot())
    expected = writes.ExpectedCurrent.model_validate({"status": "Closed"})
    with pytest.raises(BrainError) as caught:
        writes.update_item(_guard(), "m1:A-1", writes.ItemPatch(status="Closed"), expected, "closing out", "unit")
    assert caught.value.code == "CONFLICT" and rec.calls == []
    fresh = writes.ExpectedCurrent.model_validate({"status": "Open", "priority": "MAJOR", "topicId": "t1"})
    out = writes.update_item(_guard(), "m1:A-1", writes.ItemPatch(status="Closed"), fresh, "closing out", "unit")
    assert out.applied == ["status"]


def test_update_not_found_and_unknown_topic_change_nothing(monkeypatch):
    rec = _Recorder(monkeypatch, _snapshot())
    with pytest.raises(BrainError) as missing:
        writes.update_item(_guard(), "nope", writes.ItemPatch(status="Closed"), None, "closing out", "unit")
    assert missing.value.code == "NOT_FOUND"
    bad = writes.ItemPatch.model_validate({"status": "Closed", "topicId": "zzz"})
    with pytest.raises(BrainError) as bad_topic:
        writes.update_item(_guard(), "m1:A-1", bad, None, "closing", "unit")
    assert bad_topic.value.code == "NOT_FOUND" and rec.calls == []


def test_clear_priority_override(monkeypatch):
    rec = _Recorder(monkeypatch, _snapshot())
    patch = writes.ItemPatch.model_validate({"priorityOverride": "CLEAR"})
    writes.update_item(_guard(), "m1:A-1", patch, None, "no longer special", "unit")
    assert rec.calls == [("priority", "m1:A-1", None, None)]


def test_note_is_stamped_with_actor_and_provenance(monkeypatch):
    rec = _Recorder(monkeypatch, _snapshot())
    writes.add_note(_guard(), "m1:A-1", "  follow up Friday  ", "user request")
    body = rec.calls[0][2]
    assert body.startswith("follow up Friday") and "claude-code-dev" in body and "user request" in body


def test_write_rate_limit():
    clock = iter([0.0, 1.0, 2.0])
    cfg = load_config({"BRAIN_MCP_ALLOW_WRITES": "true", "BRAIN_MCP_WRITE_RATE_PER_MINUTE": "2"})
    guard = writes.WriteGuard(cfg, clock=lambda: next(clock))
    guard.check()
    guard.check()
    with pytest.raises(BrainError) as caught:
        guard.check()
    assert caught.value.code == "RATE_LIMITED"


def test_agent_written_overrides_are_stamped_and_not_reported_as_human_confirmed(monkeypatch):
    from app.presentation.mcp.service import override_provenance

    rec = _Recorder(monkeypatch, _snapshot())
    patch = writes.ItemPatch.model_validate({"priorityOverride": "CRITICAL"})
    writes.update_item(_guard(), "m1:A-1", patch, None, "blocks release", "unit")
    reason = rec.calls[0][3]
    assert reason == "[via MCP:claude-code-dev] blocks release"
    assert override_provenance(reason) == "agent_asserted"
    assert override_provenance("set in the UI by a person") == "human_confirmed"
    assert override_provenance(None) == "human_confirmed"
