# Software Architecture Blueprint

Both halves of this codebase follow **Clean Architecture**: the Python backend (`backend/app/`) and the Next.js frontend (`src/`). Each has the same four layers and the same dependency rule, and each has automated checks that fail when the rule is broken.

---

## 1. The dependency rule

```text
Presentation ──┐
               ├──> Application ──> Domain
Infrastructure ┘
```

- **Domain** depends on nothing.
- **Application** depends only on Domain. It declares the interfaces (ports) it needs; it never knows who implements them.
- **Infrastructure** implements those ports. It may import Application and Domain, never Presentation.
- **Presentation** turns requests into use-case calls and results into responses. It may import Application and Domain, never Infrastructure.
- A **composition root** is the only code that imports every layer. It builds the infrastructure adapters and hands them to the use cases.

---

## 2. Directory map

### Backend (`backend/app/`, Python packages are lowercase)

```text
backend/app/
├── domain/
│   ├── entities/         KnowledgeItem, Topic, ReviewCandidate, Meeting, Note, TopicImage
│   ├── value_objects/    item type, confidence, status, priority, tag, evidence, image upload, extraction
│   ├── services/         topic_priority/ (scorer), topic_ranking, topic_matching, similarity, follow_up,
│   │                     item_graph, search_ranking
│   ├── policies.py       thresholds and constants (UNCATEGORIZED_TOPIC, DUPLICATE_MATCH_THRESHOLD, ...)
│   └── exceptions.py     business-rule violations (TopicNameConflict, ItemNotEditable, ...)
├── application/
│   ├── interfaces/       ports: UnitOfWork and repositories, Embedder, ImageStore, ExtractSource, Clock, ...
│   ├── dtos/             frozen dataclasses that cross the boundary
│   ├── use_cases/        one class per operation (CreateTopic, DecideReviewCandidate, IngestExtracts, ...)
│   ├── services/         orchestration shared by use cases (priority recalculation, ranker cache, assembler)
│   └── exceptions.py     technical failures in neutral terms (StorageUnavailable, ExtractSourceUnavailable, ...)
├── infrastructure/
│   ├── persistence/      database.py (engine, init_db, _backfill_*), orm_models.py, mappers.py,
│   │                     repositories.py, unit_of_work.py
│   └── external_services/ embeddings, s3_storage, extraction_parser, semantic_classifiers, system (clock, ids)
├── presentation/
│   ├── api/              FastAPI: app_factory.py, routers/, schemas.py (Pydantic), error_handlers.py
│   └── mcp/              the MCP server: server.py (tools), service.py (reads), writes.py (write guard)
├── container.py          composition root: builds every adapter and use case
└── main.py               ASGI entry (`uvicorn app.main:app`): container -> create_app
```

`app/presentation/mcp/__main__.py` is the composition root for the MCP server process.

### Frontend (`src/`)

```text
src/
├── Domain/
│   ├── Entities/         KnowledgeItem, Topic, TopicSuggestion, Meeting, Graph, FollowUp (types + pure rules)
│   └── ValueObjects/     ItemType, Confidence, OpenClosed, Priority, Tag, Evidence, RecordId
├── Application/
│   ├── Interfaces/       KnowledgeRepository, AskAgent, AskSessionStore, ModelCatalog
│   ├── DTOs/             Knowledge.ts, Ask.ts
│   ├── UseCases/         items.ts, topics.ts, knowledge.ts, ask.ts
│   └── Errors.ts         ValidationError, NotFoundError
├── Infrastructure/
│   ├── ExternalServices/ BackendApiClient (HTTP to FastAPI), ClaudeAgentSdkAsk, ClaudeModelCatalog
│   └── Persistence/      FsAskSessionStore
├── Presentation/
│   ├── Controllers/      server actions (*Actions.ts, "use server") and route-handler logic (*Controller.ts)
│   └── Components/       React components
├── composition.ts        composition root: exports `useCases` (server only)
└── app/                  Next.js routing shell
```

`src/app/` must keep its name because Next.js routes from it. It holds no logic of its own: a page loads data through `useCases` and renders components; a `route.ts` re-exports a controller.

---

## 3. Layer rules

### Domain
- Pure language code. Backend: standard library only, plus `numpy` for vector math in the similarity and ranking services (the one allowed exception). Frontend: no React, no Next.js, no Node APIs, no SDKs.
- Backend entities keep state in private attributes exposed through the `ReadOnly` descriptor and change only through methods that enforce the rules (`item.set_status()`, `topic.rename()`, `candidate.decide()`), never through public setters. Value objects are frozen dataclasses.
- The frontend domain mirrors the backend's API schemas by hand (a backend schema change needs a matching edit in `src/Domain`) and holds the rules the UI applies to them (`isUncategorized`, `canDeleteTopic`, `byPriorityDesc`, `groupByTopSuggestion`).

### Application
- Use cases orchestrate: open a unit of work, load entities through repositories, call entity methods, commit, return DTOs.
- Ports are `typing.Protocol`s (backend) or TypeScript interfaces (frontend).
- Input a person typed is validated here or in the domain, so every entry point (REST, MCP, UI) gets the same rules.

### Infrastructure
- Maps between rows and entities in `mappers.py`; ORM types never leave this layer.
- Translates technical failures into application or domain exceptions before they cross the boundary (a unique-constraint violation becomes `TopicNameConflict`, a lost connection `StorageUnavailable`, an HTTP 404 for a topic `NotFoundError`).
- There is no migration tool: `database.init_db()` runs `create_all` plus idempotent `_backfill_*` steps. A schema change is one more `_backfill_*` function.

### Presentation
- Pydantic appears only here (and in the extraction parser). Responses are built from DTOs with `Schema.model_validate(dto, from_attributes=True)`.
- `presentation/api/error_handlers.py` maps each domain and application exception to its HTTP status once, so routers contain no `try/except`. The MCP server does the same in `presentation/mcp/errors.py`.
- Frontend controllers parse `FormData`, call one use case, then `revalidatePath`/`redirect`. Components never import Infrastructure or `composition.ts`, which keeps Node-only code out of the browser bundle.

---

## 4. Request flow

1. Presentation receives the input and shapes it into a DTO or plain arguments.
2. It calls a use case obtained from the composition root (`Container` on the backend, `useCases` on the frontend).
3. The use case loads entities through a port, applies domain logic and saves through the port.
4. The use case returns a DTO; Presentation renders it as JSON, an MCP result or a page.

---

## 5. Enforcement

| Check | What it enforces | Run with |
| --- | --- | --- |
| `backend/tests/test_architecture.py` | Backend import rules by scanning every module's imports; every module must sit in a layer or be a composition root | `pytest` (from `backend/`) |
| `eslint.config.mjs` (`no-restricted-imports`) | Frontend import rules per layer | `npm run lint` |
| `tests/frontend/architecture.test.ts` | That the ESLint rules really report a forbidden import | `npm test` |
| `backend/tests/test_contracts.py` | The REST (OpenAPI) and MCP tool contracts match their snapshots | `pytest` |
| `tests/frontend/api-contract.test.ts` | Every request the frontend makes exists in the OpenAPI snapshot | `npm test` |

After an intended contract change, regenerate the snapshots from `backend/` with `python -m tests.contract_snapshots`.

---

## 6. Adding a feature

1. **Domain:** put the rule on the entity or in a domain service, with a unit test that needs no database.
2. **Application:** add a use case (and a port method if it needs new I/O), tested against fakes (`backend/tests/application/fakes.py`, `tests/frontend/support/fakeKnowledge.ts`).
3. **Infrastructure:** implement the port method.
4. **Composition root:** register the use case in `backend/app/container.py` or `src/composition.ts`.
5. **Presentation:** add the route, MCP tool, server action or page that calls it.
