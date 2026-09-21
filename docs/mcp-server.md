# Brain Assistant MCP server

A project-local [MCP](https://modelcontextprotocol.io) server that lets Claude Code search and traverse Brain Assistant knowledge (ideas, decisions, actions, questions, topics, meetings), cite the underlying records, and make a few controlled updates.

## Architecture

```
Claude Code ──stdio──> scripts/mcp-server.mjs ──> python -m mcp_server
                                                    tools (server.py: validation, annotations, error mapping)
                                                      -> service.py / writes.py (shaping, filters, bounds, write guard)
                                                        -> app.data  (the existing domain layer, unchanged rules)
                                                          -> Postgres
```

- **Python, not TypeScript.** The backend is Python (FastAPI, SQLAlchemy). The official Python SDK `mcp` 2.x is used, so there is no second runtime and the server imports `app.data` directly instead of calling the REST API. Pydantic models play the role Zod would in a TypeScript server.
- The adapter holds no business rules. Search, priority, topics, notes and status changes all go through `app.data`. The only backend edit is extracting `find_item` and `filter_items` from the REST handlers into `data.py` so both callers share them.
- `stdout` carries only JSON-RPC. Logs go to `stderr` through a redacting filter.

## Prerequisites

Node 20+ (launcher), Python 3.11+, Docker (Postgres with pgvector), `claude` CLI or the VS Code extension.

## Install

```bash
docker compose up -d                                   # Postgres + SeaweedFS
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
cd .. && npm run mcp:build                             # expect "build check passed"
```

`backend/.env` must define `DATABASE_URL` (see [backend/.env.example](../backend/.env.example), names only).

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | none | Postgres connection, from `backend/.env`. Never echoed. |
| `BRAIN_ENV` | `development` | Anything other than `development`/`dev`/`test` refuses to start unless `BRAIN_MCP_ALLOW_PRODUCTION=true` **and** `BRAIN_MCP_ACTOR` is set. |
| `BRAIN_MCP_ALLOW_WRITES` | `false` | Write tools fail with `FORBIDDEN` unless `true`. |
| `BRAIN_MCP_ACTOR` | `claude-code-dev` (dev only) | Identity stamped on writes and audit lines. |
| `BRAIN_MCP_WRITE_RATE_PER_MINUTE` | `30` | Write rate limit. |
| `BRAIN_MCP_PYTHON` | `backend/.venv` interpreter | Override the interpreter used by the launcher. |

## Commands

| Command | Does |
| --- | --- |
| `npm run mcp:build` | Verifies the interpreter and that the server builds. |
| `npm run mcp:start` | Runs the stdio server (waits for a client on stdin). |
| `npm run mcp:test` | Runs the MCP unit, contract and stdio integration tests (needs Postgres for the integration ones). |
| `npm run mcp:inspect` | Opens the MCP Inspector against the server. |

Optional lint and types: `pip install -r backend/requirements-dev.txt`, then `ruff check mcp_server` and `mypy mcp_server --ignore-missing-imports`.

## Claude Code configuration

[.mcp.json](../.mcp.json) is project-scoped and contains no secrets or absolute paths. It starts the launcher with `${CLAUDE_PROJECT_DIR:-.}/scripts/mcp-server.mjs`.

**Approval.** Claude Code asks you to approve project-scoped servers the first time. Run `claude` in the repo and accept the prompt. Until then `claude mcp list` shows `Pending approval`.

**Check status**

- In a session: `/mcp`
- `claude mcp list`
- `claude mcp get brain-assistant`

**Enable writes** (off by default): export `BRAIN_MCP_ALLOW_WRITES=true` before starting Claude Code. `.mcp.json` passes it through.

A server added while a session is running is not discovered until the session restarts or you run `/mcp` and reconnect.

## Inspector

```bash
npm run mcp:inspect
# CLI example:
npx @modelcontextprotocol/inspector --cli node scripts/mcp-server.mjs --method tools/call --tool-name brain_health
```

## Tool catalog

| Tool | Type | Use |
| --- | --- | --- |
| `brain_health` | read | Dependency and capability check. |
| `brain_search_items` | read | Semantic search plus filters (types, statuses, priorities, owner, topic, meeting, meeting-date range), paginated. |
| `brain_get_item` | read | Full item context: evidence, notes, relationships, history. |
| `brain_get_topic_context` | read | Topic briefing: items by type, outcomes, risks, meetings, follow-ups. |
| `brain_get_relationship_graph` | read | Bounded graph (depth ≤ 3, ≤ 200 nodes per page) from an item or topic. |
| `brain_list_open_actions` | read | Open actions, overdue first, with owner, priority, due-range and topic filters. |
| `brain_list_unresolved_questions` | read | Open questions, oldest first, with related decisions and actions. |
| `brain_get_recent_changes` | read | Changes in a window of at most 90 days. |
| `brain_update_item` | write | Status, manual priority override, or topic, with a reason and optional `expectedCurrent`. |
| `brain_add_note` | write | Append a note. Additive only. |

**Resources:** `brain://items/{itemId}`, `brain://topics/{topicId}/context`, `brain://meetings/{meetingId}/summary`.

**Not implemented, on purpose.** `brain_create_item` and `brain_create_relationship`: the application has no service for either. Items come from ingestion and review-accept, and relationships are the extractor's `relatedIds` plus similarity, with no relationships table. Nothing to reuse safely, so nothing was invented. There are also no delete, bulk, SQL, shell, filesystem or HTTP tools.

### Provenance labels

Every result marks where information came from: `retrieved` (stored fact), `generated` (computed by the app, e.g. topic priority), `inferred` (embedding similarity, never an assertion), `human_confirmed` (set by a person in the app), `agent_asserted` (written through this server by an AI agent).

## Example requests

- "Use Brain Assistant to summarize what changed on topic X during the last seven days."
- "Find all open high-priority actions assigned to me."
- "What unresolved questions are blocking this decision?"
- "Show the evidence behind this relationship."
- "Add a note to this action saying the vendor replied."
- "Trace how this idea led to the current decision."

"Create a follow-up action" is not possible today, since the application cannot create items. Claude can add a note or move an existing item instead.

## Ask page

`/ask` answers free-form questions through the same tools Claude Code uses. `src/app/api/ask/route.ts` runs the Claude Agent SDK
(`@anthropic-ai/claude-agent-sdk`) with this MCP server attached and streams newline-delimited JSON events
(`text`, `tool`, `done`, `error`) to `src/components/AskConversation.tsx`.

- Requires `ANTHROPIC_API_KEY` (or a logged-in Claude Code) in the Next.js server environment.
- Read-only by construction: built-in tools are disabled, only the `brain_*` read tools are allowed, the two write tools
  are explicitly denied, and the server is launched with `BRAIN_MCP_ALLOW_WRITES=false` regardless of your shell.
- Project and user Claude settings are not loaded (`settingSources: []`, `strictMcpConfig`), so answers do not depend on the developer's machine.
- Limits: prompts are capped at 2000 characters, 12 agent turns and 120 seconds per request.
- The system prompt mirrors `INSTRUCTIONS` in `backend/mcp_server/server.py`; keep the two in sync.
- Answers cite record IDs as `[id]`; topic IDs link to `/topics/{id}` and item IDs link to their meeting.

## Security and privacy

- Read tools are annotated read-only. Write tools are off unless the operator sets `BRAIN_MCP_ALLOW_WRITES`. Annotations are hints. Enforcement is in code.
- **The application has no authentication or authorization.** The server does not fake it: a dev identity is used, it cannot silently activate outside development, and writes are gated, rate limited and serialized within the process.
- Inputs are strict: unknown properties rejected, enums, length limits, ID patterns, page size ≤ 50, graph bounds, 120 KB result cap.
- Stored text is untrusted. Every result carries a notice, and instructions inside records are never acted on.
- Errors use `NOT_FOUND`, `VALIDATION_ERROR`, `UNAUTHORIZED`, `FORBIDDEN`, `CONFLICT`, `DEPENDENCY_UNAVAILABLE`, `RATE_LIMITED`, `INTERNAL_ERROR`. Stack traces, SQL and connection strings are never returned, and logs and errors are redacted.
- Writes are logged to `stderr` as ids and field names only. The app has no item audit table. `brain_update_item` cannot be made atomic across several fields, so ask for one field per call when that matters.
- Optimistic concurrency is best effort: `expectedCurrent` compares status, priority, topic or `lastUpdated` before writing. The app has no version column, so another process can still race between the check and the write.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Pending approval` | Run `claude` in the repo and approve the server. |
| Server missing in a running session | Restart the session or run `/mcp` to reconnect. |
| `Python interpreter not found` | Create `backend/.venv` and install requirements, or set `BRAIN_MCP_PYTHON`. |
| `DEPENDENCY_UNAVAILABLE` | `docker compose up -d`, check `DATABASE_URL` in `backend/.env`, run `brain_health`. |
| `FORBIDDEN` on a write | Set `BRAIN_MCP_ALLOW_WRITES=true` and restart. |
| First search is slow | The embedding model loads once (about 10 s); the server warms it in the background. |
| Refuses to start | `BRAIN_ENV` is not a development value; see the table above. |
| Integration tests skip | Postgres is not reachable at `DATABASE_URL`. |

## Known limits

- Search is semantic only and exposes no relevance score. It looks at the 100 nearest items, then filters and paginates.
- "Recent changes" cannot see status, owner or topic changes, because the app does not record them. Item dates are meeting dates.
- Each call loads the whole knowledge base into memory, fine for a local dataset.
- The app's own `build_graph` matches bare related IDs across meetings. This server resolves `related_to` edges within the item's own meeting; the REST graph is unchanged.

## Adding a tool safely

1. Add the operation to `app.data` first if it does not exist, with its rules and tests. The MCP layer must not own business logic.
2. Add output models to `schemas.py` and the logic to `service.py` (reads) or `writes.py` (writes, behind `WriteGuard`).
3. Register it in `server.py` with a precise description (when to use, when not to, limits, whether it changes data), constrained parameters, accurate annotations, and the shared `_adapt` wrapper.
4. Test the pure logic in `tests/mcp_tests`, add a happy path and a failure case to the stdio integration test, and confirm `stdout` stays clean.
5. Add it to the catalog above.
