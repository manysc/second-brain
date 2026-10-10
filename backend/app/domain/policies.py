"""Named business constants shared across entities, services and use cases."""
from __future__ import annotations

# catch-all topic for items nobody has filed yet; never a signal for matching, ranking or merging
UNCATEGORIZED_TOPIC = "Uncategorized"

# synthetic meeting that owns items added by hand rather than extracted from a meeting
MANUAL_MEETING_ID = "manual"
MANUAL_MEETING_TITLE = "Manual entries"

# cosine similarity between an item and a topic's centroid at/above which the item is filed under that
# existing topic with no human in the loop (ingestion, review accept without a topic). Suggestions a
# human confirms use the looser hybrid ranking in domain/services/topic_ranking.py instead.
ITEM_TOPIC_MATCH_SIMILARITY = 0.6
# looser bar for listing a topic as related to another
PROPOSAL_HINT_SIMILARITY = 0.4

# cosine distance (embeddings are normalized, so 0=identical..~2=opposite) below which an
# accepted review candidate is treated as a duplicate of an existing item rather than promoted
DUPLICATE_MATCH_THRESHOLD = 0.2
