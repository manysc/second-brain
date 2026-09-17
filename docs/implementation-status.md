# Implementation status

## Automatic Topic Priority Classification (2026-09-16)

Deterministic, explainable Topic priority classification (CRITICAL / MAJOR / MINOR), with an
optional bounded semantic contribution, manual overrides, and priority history.

### What was built

**Backend** (`backend/app/`)
- `topic_priority.py` - the domain service:
  - `TopicPrioritySignalExtractor` (DB-touching) reads a topic's items, their meetings' dates,
    and cross-topic `related_ids` reach into a plain `TopicPriorityFacts` dataclass.
  - `TopicPriorityScorer.score()` is a **pure function** (no DB) that turns facts into a
    `TopicPriorityInfo`: six weighted dimensions (Impact 25 / Urgency 20 / Risk 20 /
    Dependency Reach 15 / Execution Pressure 10 / Momentum 10), diminishing-returns
    normalization (never raw linear counts), one hard-escalation rule (confirmed blocked status
    + imminent/overdue deadline -> CRITICAL, bypassing hysteresis upward only), a confidence
    checklist independent of the score, and threshold + hysteresis classification
    (promote immediately, demote only past a lower threshold - CRITICAL->MAJOR below 70,
    MAJOR->MINOR below 40).
  - `TopicPrioritySemanticClassifier` abstraction: `DisabledSemanticClassifier` (default, no
    network access) and `HuggingFaceZeroShotClassifier` (optional, lazy-imports `transformers`
    only when `TOPIC_PRIORITY_SEMANTIC_CLASSIFIER=huggingface` is set). Its contribution is
    bounded to ±10 points and disagreement with the deterministic result is recorded, never
    silently overriding it.
  - `PRIORITY_CONFIG` centralizes every weight/threshold/decay/cap; `TOPIC_PRIORITY_ALGORITHM_VERSION`
    is persisted with every calculation for future comparability.
- `db_models.py` / `db.py` - priority columns added to `topics` (calculated priority/score/
  confidence/signals/explanation/algorithm version/semantic contribution + manual override
  fields, never overwritten by recalculation) via an idempotent `_backfill_topic_priority`
  migration; new `topic_priority_history` table (`ON DELETE CASCADE` so deleting a topic doesn't
  get blocked by its own history).
- `models.py` - new Pydantic models (`TopicPrioritySignal`, `HardEscalation`,
  `SemanticContribution`, `ManualPriorityOverride`, `TopicPriorityInfo`,
  `TopicPriorityHistoryEntry`); `Topic.priority` and `GraphNode.priority` added.
- `data.py` - recalculation is synchronous and targeted: `assign_item_topic`, `merge_topics`, and
  `set_review_status` (ACCEPTED path) each recalculate only the affected topic(s) after commit.
  `ingest.py`'s `ingest_and_commit()` recalculates *all* topics after a bulk ingestion run (the
  documented exception to "only affected topics", since ingestion is a bulk load). Manual
  `recalculate_priority_for_topic` / `recalculate_all_topic_priorities` / `set_priority_override`
  / `get_priority_history` / `get_recent_priority_escalations` are also exposed.
- `main.py` - new routes: `POST /api/topics/{id}/recalculate-priority`,
  `POST /api/topics/recalculate-priority`, `PATCH /api/topics/{id}/priority-override`,
  `GET /api/topics/{id}/priority-history`, `GET /api/priority-history/recent`.

**Frontend** (`src/`)
- `lib/domain.ts` / `lib/api.ts` / `lib/actions.ts` mirror the new types/endpoints/server actions.
- `components/PriorityBadge.tsx`, `components/PriorityOverrideForm.tsx` - new.
- `components/TopicGrid.tsx` - hardcoded "ACTIVE" status badge replaced with the real
  `PriorityBadge`.
- `app/topics/page.tsx` - topics sorted by priority rank then score; a priority filter row added.
- `app/topics/[id]/page.tsx` - hardcoded "WATCH" health badge replaced with the real priority;
  new Priority section (score breakdown, explanation, hard escalations, semantic contribution if
  present) and the manual override form.
- `app/dashboard/page.tsx` - Critical/Major/"Escalated recently" cards, computed from real data.
- `app/briefing/page.tsx` - a "Became more critical" section sourced from persisted priority
  history (not LLM-invented text).
- `app/graph/page.tsx` / `components/GraphView.tsx` - Critical/Major/Minor filter toggles;
  priority is shown as a **ring around the node** (not node size, to avoid implying
  connectivity/degree = business importance).

**Tests**: `backend/tests/test_topic_priority.py` - pure-scorer unit tests (minor/major/critical
topics, ambiguous due dates, old-recurring-topic-not-critical, high-volume-topic capping, single
severe blocker hard escalation, structural-status vs keyword-heuristic weighting, bounded
semantic disagreement, hysteresis) plus one DB integration test (recalculation -> history ->
manual override preservation), following the existing `db_ready`-gated pattern.

### Adaptations from the generic spec (this repo's real domain is simpler)

This codebase has no separate Action/Question/Decision/Outcome/Relationship/TopicMembership/
StatusHistory models (everything is one `KnowledgeItem` with a `type`), no typed
BLOCKS/DEPENDS_ON relationships (only an untyped, evidence-grounded `related_ids` list), no
production/security/compliance/milestone fields, and `status` is free text (observed value in
real data: almost always `"Open"`). Adaptations made, confirmed with the user beforehand:

- **Bounded keyword heuristics**: Impact and Risk each include a small, capped, low-confidence
  signal from scanning item text (description/rationale/resolution/evidence quote) for relevant
  terms. These are clearly labeled as text heuristics (not confirmed structural signals) and can
  **never** by themselves trigger a hard escalation rule - only the structural `status` field
  (containing "blocked"/"blocker") and a parsed `due_date` can.
- **Dependency reach** uses the existing untyped `related_ids` graph (both directions) and is
  explicitly called "connectivity/reach", never "importance".
- **Urgency** only uses `due_date` when it parses as a strict ISO date; `due_date_source_text`
  present with no parseable `due_date` is treated as an ambiguous date and contributes zero
  urgency (never inferred/invented).
- **Semantic classifier**: optional, disabled by default, and never performs a network/model
  download unless explicitly enabled via `TOPIC_PRIORITY_SEMANTIC_CLASSIFIER=huggingface`. Not
  verified against a live model in this dev environment (HuggingFace model-weight downloads are
  blocked by this machine's network policy - see `/memories/repo/environment-notes.md`).

### Known limitations

- No async job queue: recalculation is synchronous, triggered only from the specific mutation
  paths listed above, plus the manual/batch recalculation endpoints.
- No API exists to edit an existing item's `due_date`/`status` after ingestion, so the "action
  becomes overdue" recalculation trigger is covered by a direct DB + service-level test, not a
  full HTTP round-trip.
- `/actions`, `/questions`, `/decisions` pages were left untouched (static demo pages, unrelated
  to Topic priority).
- Impact scoring is intentionally conservative for most topics given how little canonical
  "importance" data this repo captures - most CRITICAL classifications will come from
  Urgency + Risk (due dates + confirmed blocked status), not Impact.
