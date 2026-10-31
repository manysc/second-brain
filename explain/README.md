# second-brain

A meeting-knowledge app. LLM extraction JSON stored in SeaweedFS S3 is ingested by FastAPI into Postgres + pgvector and curated in a Next.js 16 UI. A stdio MCP server, `brain-assistant`, exposes the same use cases.

## Purpose

Turns meeting extracts into reviewed topics and items: ideas, decisions, actions and questions. On top of that it provides human-in-the-loop review, priority scoring, semantic search, a graph view, a briefing page, and an `/ask` chat that runs Claude through the Agent SDK against the MCP server. `CLAUDE.md` covers commands, layer rules and ingestion invariants. `README.md` is the long feature reference. This file is the module and interface index.

## Main modules (path → role)

**Backend: `backend/app/`.** Clean Architecture; the dependency rule is enforced by `backend/tests/test_architecture.py`.
- `domain/entities/` → `meeting`, `topic`, `knowledge_item`, `review_candidate`, `note`, `topic_image`.
- `domain/value_objects/` → `item_type`, `status`, `priority`, `confidence`, `evidence`, `tag`, `dates`, `extraction`, `image_upload`.
- `domain/services/` → `topic_priority/` (`scorer`, `config`, `facts`, `semantic`), `topic_ranking`, `topic_matching`, `similarity`, `search_ranking`, `item_graph`, `follow_up`.
- `application/use_cases/` → `ingestion` (`IngestExtracts`), `items`, `topics`, `topic_content`, `review`, `priority`, `queries`, `health`.
- `application/interfaces/` → the ports.
- `application/services/` → assembler, priority recalculation, topic-ranker cache, uncategorized.
- `infrastructure/persistence/` → `orm_models.py`, `repositories.py`, `mappers.py`, `unit_of_work.py`, and `database.py` (`init_db()` plus the `_backfill_*` steps).
- `infrastructure/external_services/` → `extraction_parser.py`, `embeddings.py`, `s3_storage.py`, `semantic_classifiers.py`, `tfidf_description_index.py`, `system.py`.
- `presentation/api/` → `app_factory.py` (startup ingest retried 5 times; embedding warm-up), `routers/{items,topics,meetings,review,priority,insights}.py`, `schemas.py`, `error_handlers.py`.
- `presentation/mcp/` → `server.py` (tools and `INSTRUCTIONS`), `service.py`, `writes.py`, `config.py`, `schemas.py`, `pagination.py`, `__main__.py`.
- `container.py` → the composition root.
- `main.py` → the ASGI app, `app.main:app`.

**Frontend: `src/`**
- `app/` → the routing shell.
- `Presentation/Components/*`.
- `Presentation/Controllers/*Actions.ts` → server actions.
- `Application/UseCases/{knowledge,items,topics,ask}.ts`.
- `Domain/` → API types, mirrored by hand.
- `Infrastructure/ExternalServices/{BackendApiClient,ClaudeAgentSdkAsk,ClaudeModelCatalog}.ts`.
- `Infrastructure/Persistence/FsAskSessionStore.ts`.
- `composition.ts`.

**Scripts:** `scripts/mcp-server.mjs` (MCP launcher with `--check` and `--test`), `seed_seaweedfs.py`, `ingest_to_postgres.py`, `backup_s3_bucket.py`.

## Interfaces

**REST** (FastAPI on `:8000`). All paths are under `/api`; the snapshot is `backend/tests/fixtures/openapi.snapshot.json`.

| Area | Routes |
|---|---|
| Items | `GET /items`<br>`GET`, `PATCH`, `DELETE /items/{item_id}`<br>`PATCH /items/topic` (bulk)<br>`PATCH /items/{id}/status`, `/items/{id}/topic`, `/items/{id}/priority-override`<br>`POST`, `DELETE /items/{id}/tags`<br>`POST /items/{id}/notes`; `PATCH`, `DELETE /items/{id}/notes/{note_id}` |
| Topics | `GET`, `POST /topics`<br>`GET`, `PATCH`, `DELETE /topics/{topic_id}`<br>`POST /topics/{id}/items`, `/merge`, `/notes`, `/recalculate-priority`<br>`PATCH /topics/{id}/status`, `/priority-override`<br>`POST`, `DELETE /topics/{id}/tags`<br>`PATCH`, `DELETE /topics/{id}/notes/{note_id}`<br>`GET /topics/{id}/related`, `/priority-history` |
| Topic images and suggestions | `POST /topics/{id}/images`<br>`GET`, `DELETE /topics/{id}/images/{image_id}`<br>`POST /topics/recalculate-priority`<br>`GET /topics/suggested-merges`, `/topics/suggested-item-topics` |
| Meetings | `GET /meetings`, `GET /meetings/{meeting_id}`<br>`GET /meeting` (the most recent one)<br>`POST /ingest` |
| Review | `GET /review`, `PATCH /review/{candidate_id}`<br>`GET /review/topic-proposals`<br>`POST /review/topic-proposals/accept`, `/reject` |
| Insights | `GET /search?q=`, `GET /graph?minSimilarity=` (default 0.35), `GET /follow-up`, `GET /priority-history/recent` |

**MCP tools** (`brain-assistant`, stdio, registered in `.mcp.json`; the snapshot is `backend/tests/fixtures/mcp-tools.snapshot.json`)
- Read: `brain_health`, `brain_search_items`, `brain_get_item`, `brain_get_topic_context`, `brain_list_open_actions`, `brain_list_unresolved_questions`, `brain_get_recent_changes`, `brain_get_relationship_graph`.
- Write: `brain_add_item`, `brain_add_note`, `brain_edit_item`, `brain_update_item`, `brain_create_topic`, `brain_move_items` (at most 25), `brain_delete_item` (manual items only). These require `BRAIN_MCP_ALLOW_WRITES=true` and are rate-limited.

**Next.js routes**
- Route handlers: `/api/ask`, `/api/ask/models`, `/api/ask/sessions`, `/api/ask/sessions/[id]`, `/api/topics/[id]/images/[imageId]`.
- Pages: `/`, `/dashboard`, `/briefing`, `/topics`, `/topics/[id]`, `/items`, `/actions`, `/decisions`, `/questions`, `/meetings`, `/meetings/[id]`, `/review`, `/graph`, `/ask`, `/growth`, `/growth/career`, `/growth/impact`.

**Database** (`pgvector/pgvector:pg16`; models in `infrastructure/persistence/orm_models.py`):
- Tables: `meetings`, `topics`, `knowledge_items`, `review_candidates`, `notes`, `topic_images`, `topic_priority_history`.
- `knowledge_items.embedding` is `Vector(EMBEDDING_DIM)`.
- There is no migration tool. A schema change means adding a `_backfill_*` step in `database.py`.

**External services**
- SeaweedFS S3 through boto3: extracts, plus topic images under `S3_IMAGES_PREFIX` (default `images/`).
- sentence-transformers `all-MiniLM-L6-v2`, downloaded from Hugging Face, with a `HashingVectorizer` fallback when offline.
- An optional Hugging Face zero-shot classifier, used when `TOPIC_PRIORITY_SEMANTIC_CLASSIFIER=huggingface` (default `disabled`).
- Claude through `@anthropic-ai/claude-agent-sdk`: `query()` with `permissionMode: "dontAsk"`, and `startup()` for the model list. Sessions are stored under `os.tmpdir()/second-brain-ask`.

**Env vars (names only)**
- Backend (`backend/.env`, template `backend/.env.example`): `DATABASE_URL`, `S3_BUCKET`, `S3_ENDPOINT_URL` (both required), `S3_PREFIX`, `S3_IMAGES_PREFIX`, `S3_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `INGEST_ON_STARTUP` (default true), `TOPIC_PRIORITY_SEMANTIC_CLASSIFIER`.
- MCP (`presentation/mcp/config.py`): `BRAIN_ENV`, `BRAIN_MCP_ALLOW_WRITES`, `BRAIN_MCP_ALLOW_PRODUCTION`, `BRAIN_MCP_ACTOR` (dev default `claude-code-dev`), `BRAIN_MCP_WRITE_RATE_PER_MINUTE` (default 30). `BRAIN_MCP_PYTHON` is read by the launcher.
- Frontend (`.env.local`): `API_BASE_URL` (default `http://localhost:8000`). Playwright reads `PW_CHANNEL` (default `msedge`).
- Backup script: `S3_CONFIG_PATH`, `S3_BACKUP_DIR`, `S3_BACKUP_INTERVAL_DAYS`.

## Related repos in this workspace

- `personalexpensesapp`: same infrastructure pattern. `scripts/backup_s3_bucket.py` was copied from it; its docstring still mentions `personal_expenses_app`. Both `docker-compose.yml` files publish host ports 5432, 5050, 8333 and 23646, so the two stacks cannot run at the same time. The container names here are prefixed `second_brain_`.
- `logseq-mcp-client`: no references either way.

## Build, run & test

- `docker compose up -d`
- `cd backend && .venv/Scripts/python -m uvicorn app.main:app --reload`
- `npm run dev`
- Frontend checks: `npm run lint`, `npx tsc --noEmit`, `npm test` (Vitest), `npm run test:e2e` (Playwright).
- Backend tests, run from `backend/`: `.venv/Scripts/python -m pytest -q`. DB tests skip when Postgres is down; `-rs` lists the skips.
- MCP: `npm run mcp:test`, `npm run mcp:build`, `npm run mcp:inspect`.
- Contract snapshots: `.venv/Scripts/python -m tests.contract_snapshots` from `backend/`.

## Where to look

- `backend/app/container.py` and `backend/app/presentation/api/app_factory.py`: wiring and startup.
- `backend/app/infrastructure/external_services/extraction_parser.py` and `application/use_cases/ingestion.py`: ingestion and identity rules. `README.md` describes them under the old `ingest.*` names.
- `backend/app/presentation/mcp/server.py` and `src/Application/UseCases/ask.ts`: `INSTRUCTIONS`/`SYSTEM_PROMPT` and the tool lists must stay in sync.
- `backend/app/presentation/api/schemas.py` and `src/Domain/`: the API types are mirrored by hand.
- `architecture.md` (layer map), `docs/mcp-server.md`, `docs/implementation-status.md` (a dated change log).
