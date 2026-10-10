# Brain Assistant MCP server

A project-local [MCP](https://modelcontextprotocol.io) server that lets Claude Code search and traverse Brain Assistant knowledge (ideas, decisions, actions, questions, topics, meetings), cite the underlying records, and make a few controlled updates.

## Architecture

```
Claude Code ──stdio──> scripts/mcp-server.mjs ──> python -m app.presentation.mcp
                                                    tools (server.py: validation, annotations, error mapping)
                                                      -> service.py / writes.py (shaping, filters, bounds, write guard)
                                                        -> application use cases (the same ones the REST API calls)
                                                          -> domain entities -> repositories -> Postgres
```

- **Python, not TypeScript.** The backend is Python (FastAPI, SQLAlchemy). The official Python SDK `mcp` 2.x is used, so there is no second runtime and the server calls the application use cases directly instead of going through the REST API. Pydantic models play the role Zod would in a TypeScript server.
- The adapter holds no business rules. It lives in the presentation layer (`backend/app/presentation/mcp/`, see [architecture.md](../architecture.md)) next to the REST API, and search, priority, topics, notes and status changes all go through the use cases in `backend/app/application/use_cases/`. `__main__.py` is its composition root: it builds the `Container` and passes it to the tools through `context.py`.
- Failures arrive as domain and application exceptions (`ItemNotFound`, `StorageUnavailable`, ...) and `errors.py` maps them to the error codes below.
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

Optional lint and types: `pip install -r backend/requirements-dev.txt`, then, from `backend/`, `ruff check app/presentation/mcp` and `mypy app/presentation/mcp --ignore-missing-imports`.

## Claude Code configuration

[.mcp.json](../.mcp.json) is project-scoped and contains no secrets or absolute paths. It starts the launcher with `${CLAUDE_PROJECT_DIR:-.}/scripts/mcp-server.mjs`.

**Approval.** Claude Code asks you to approve project-scoped servers the first time. Run `claude` in the repo and accept the prompt. Until then `claude mcp list` shows `Pending approval`.

**Check status**

- In a session: `/mcp`
- `claude mcp list`
- `claude mcp get brain-assistant`

**Writes** are on by default for Claude Code in this repo: `.mcp.json` passes `BRAIN_MCP_ALLOW_WRITES` through with a default of `true`. To turn them off, export `BRAIN_MCP_ALLOW_WRITES=false` before starting Claude Code. The server itself still defaults to `false` when the variable is unset, so any other client must opt in. Reconnect (`/mcp`) after changing it.

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
| `brain_add_item` | write | Add an idea, question, decision or action to an existing topic. Recorded as a manual entry (evidence "Added manually") on the synthetic `manual` meeting. |
| `brain_edit_item` | write | Edit description, owner, `dueDate`, rationale, or type (type only for manual items). Needs a reason; optional `expectedCurrent` (including `description`). Blank owner/`dueDate`/rationale clears the field. |
| `brain_delete_item` | write | Permanently delete a **manually added** item and its notes. Needs a reason. Items extracted from meetings are refused (`FORBIDDEN`) because the next ingest would re-create them. |
| `brain_create_topic` | write | Create a new, empty topic. A taken name fails with `CONFLICT`. |
| `brain_move_items` | write | Move 1-25 items into one existing topic, all or nothing (an unknown item id moves nothing); priorities are recalculated once. Needs a reason. Use `brain_update_item` for a single item. |

**Resources:** `brain://items/{itemId}`, `brain://topics/{topicId}/context`, `brain://meetings/{meetingId}/summary`.

**Not implemented, on purpose.** `brain_create_relationship`: relationships are the extractor's `relatedIds` plus similarity, with no relationships table, so there is nothing to reuse safely. `brain_delete_item` is the only delete and works on one manual item at a time. There are no bulk, SQL, shell, filesystem or HTTP tools.

Note: re-ingesting a meeting upserts by item id, so edits to meeting-extracted items may be overwritten by a later ingest.

### Provenance labels

Every result marks where information came from: `retrieved` (stored fact), `generated` (computed by the app, e.g. topic priority), `inferred` (embedding similarity, never an assertion), `human_confirmed` (set by a person in the app), `agent_asserted` (written through this server by an AI agent).

## Example requests

- "Use Brain Assistant to summarize what changed on topic X during the last seven days."
- "Find all open high-priority actions assigned to me."
- "What unresolved questions are blocking this decision?"
- "Show the evidence behind this relationship."
- "Add a note to this action saying the vendor replied."
- "Trace how this idea led to the current decision."

- "Create a topic called Vendor Onboarding and move these three actions into it."
- "Create a follow-up action on this topic" (`brain_add_item`).

## Ask page

`/ask` answers free-form questions through the same tools Claude Code uses. The route handlers under `src/app/api/ask/` delegate to
`src/Presentation/Controllers/askController.ts`, which calls the ask use cases (`src/Application/UseCases/ask.ts`: validation, limits,
the tool policy and the system prompt). `src/Infrastructure/ExternalServices/ClaudeAgentSdkAsk.ts` runs the Claude Agent SDK
(`@anthropic-ai/claude-agent-sdk`) with this MCP server attached, and the controller streams newline-delimited JSON events
(`meta`, `text`, `tool`, `done`, `error`) to `src/Presentation/Components/AskConversation.tsx`.

- Requires `ANTHROPIC_API_KEY` (or a logged-in Claude Code) in the Next.js server environment.
- Read/write, but only through the brain tools: built-in tools are disabled and only the `brain_*` tools are allowed. The server is
  launched with `BRAIN_MCP_ALLOW_WRITES=true` and `BRAIN_MCP_ACTOR=second-brain-ask` regardless of your shell, so writes are attributable.
  `brain_delete_item` (irreversible) is explicitly denied (`DENIED_TOOLS` in `ask.ts`); the system prompt tells the model to change
  data only when asked and to say exactly what changed.
- Project and user Claude settings are not loaded (`settingSources: []`, `strictMcpConfig`), so answers do not depend on the developer's machine.
- Limits: prompts are capped at 2000 characters, 12 agent turns, 120 seconds of silence (any streamed event restarts the clock) and 10 minutes in total per request.
- `SYSTEM_PROMPT` in `src/Application/UseCases/ask.ts` mirrors `INSTRUCTIONS` in `backend/app/presentation/mcp/server.py`, and its
  `READ_TOOLS` / `WRITE_TOOLS` lists must match the tool names registered there; keep them in sync.
- Answers cite record IDs as `[id]`; topic IDs link to `/topics/{id}` and item IDs link to their meeting.
- Follow-ups: the first `meta` event carries a `sessionId`; the page sends it back with each follow-up and the route resumes
  that Agent SDK session (`resume`), so the model keeps earlier tool results. The allowlist, `dontAsk` and the server env are
  re-applied on every turn. A conversation is capped at 20 questions in the UI.
- Session safety: the SDK resolves a session id across all projects, so a client-supplied id could otherwise resume (and append
  to) an unrelated Claude Code session. The route therefore only accepts ids it issued itself, recorded as marker files in
  `<tmpdir>/second-brain-ask/issued/`, and answers anything else with HTTP 410. Ask transcripts live under that directory's project.
- Session history: the page lists past conversations from `GET /api/ask/sessions` (Agent SDK `listSessions` scoped to the Ask
  directory, filtered to issued ids). Opening one calls `GET /api/ask/sessions/{id}`, which rebuilds the turns from the SDK
  transcript (`getSessionMessages`) so you can keep asking follow-ups; `DELETE` removes the transcript and its marker. Reads and
  deletes apply the same issued-id check, so real Claude Code sessions are reported as 404. The reasoning effort of a past
  turn is not stored in the transcript and is not shown when reopened.
- History lives in the OS temp directory (`<tmpdir>/second-brain-ask`), so it is per machine and disappears when the OS clears it.

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

1. Add the operation as an application use case first if it does not exist (rule on the entity, use case in `backend/app/application/use_cases/`, registered in `backend/app/container.py`), with its tests. The MCP layer must not own business logic.
2. Add output models to `schemas.py` and the logic to `service.py` (reads) or `writes.py` (writes, behind `WriteGuard`).
3. Register it in `server.py` with a precise description (when to use, when not to, limits, whether it changes data), constrained parameters, accurate annotations, and the shared `_adapt` wrapper.
4. Test the pure logic in `tests/mcp_tests`, add a happy path and a failure case to the stdio integration test, and confirm `stdout` stays clean. Regenerate the tool-catalog snapshot (`python -m tests.contract_snapshots` from `backend/`); `tests/test_contracts.py` fails until you do.
5. Add its name to `READ_TOOLS` or `WRITE_TOOLS` in `src/Application/UseCases/ask.ts`. A write tool is callable from `/ask` unless it is also listed in `DENIED_TOOLS`.
6. Add it to the catalog above.
