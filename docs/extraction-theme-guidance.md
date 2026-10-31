# Extraction prompt: set a `theme` on every item

The LLM prompt that writes the meeting-extract JSON lives outside this repo. This page is the addendum to paste into
it, and why.

## Why

Ingestion files a new item under an existing topic in this order (`backend/app/domain/services/topic_matching.py`):

1. **Theme.** The item's `theme` equals a topic name. Case and surrounding spaces are ignored.
2. **Related items.** Most of the item's `related_candidate_ids` already sit in one topic.
3. **Ranker.** The hybrid topic ranker is at least MEDIUM-confident about one topic.

If none applies, the item goes to Uncategorized. A `theme` that matched no topic is kept as a proposal you can
accept, rename or redirect on `/review`. A missing `theme`, or "Uncategorized", proposes nothing.

Step 1 is the only deterministic one. As of 2026-10-31 the extractor sets `theme` on 95% of ideas but on none of the
decisions, actions or questions. Those 1,361 items depend on steps 2 and 3, and the ranker is unsure about meetings
that touch many topics, such as 1:1s. That left 60 items to file by hand.

## Addendum to paste into the extraction prompt

```text
TOPIC THEME (required on every item)
- Every object in "ideas", "decisions", "actions" and "questions" MUST have a "theme" field.
- Choose the theme from EXISTING TOPICS below and copy the name exactly. Pick the topic the item is about,
  not the meeting it came from. For example, an action from a 1:1 about a test plan for the EMS integration
  belongs to "FMS/EMS Integration", not to a people topic.
- Only if no existing topic fits, write a short new topic name (2-4 words, Title Case). It will be reviewed by
  a person before any topic is created.
- Never write "Uncategorized", "General", "Misc", "Other" or an empty string.
- Items in "related_candidate_ids" of each other usually share a theme; keep them consistent.

EXISTING TOPICS
<paste the current topic names here, one per line>
```

## Getting the current topic names

With the backend running:

```bash
curl -s http://127.0.0.1:8000/api/topics | python -c "import json,sys; print('\n'.join(sorted(t['name'] for t in json.load(sys.stdin) if t['name'] != 'Uncategorized')))"
```

Or ask Claude Code, which has the `brain-assistant` MCP server: "list every topic name" (it uses
`brain_search_items` with `types: ["TOPIC"]`).

Refresh the list in the prompt when topics are created, renamed or merged. A stale name only means the item is
proposed instead of filed; nothing breaks.

## Example item

```json
{
  "candidate_id": "A-003",
  "type": "action",
  "description": "Review the EMS test plan, starting with its executive summary tab, and give feedback.",
  "theme": "FMS/EMS Integration",
  "owner": "Manuel",
  "related_candidate_ids": ["D-001"]
}
```

The parser (`backend/app/infrastructure/external_services/extraction_parser.py`, `RawCandidate.theme`) already reads
`theme` on every item type, so no backend change is needed for this.
