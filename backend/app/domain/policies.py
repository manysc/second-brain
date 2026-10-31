"""Named business constants shared across entities, services and use cases."""
from __future__ import annotations

# catch-all topic for items nobody has filed yet; never a signal for matching, ranking or merging
UNCATEGORIZED_TOPIC = "Uncategorized"

# synthetic meeting that owns items added by hand rather than extracted from a meeting
MANUAL_MEETING_ID = "manual"
MANUAL_MEETING_TITLE = "Manual entries"

# days without activity (see domain.services.follow_up.last_activity) after which an open item is left out of
# the follow-up digest: nobody closes old items, so without this the digest only ever grows
FOLLOW_UP_MAX_AGE_DAYS = 30

# Filing an item under an existing topic with no human in the loop (ingestion, review accept without a
# topic) needs a MEDIUM-or-better hybrid ranking: see confident_topic_id in domain/services/topic_ranking.py.

# cosine similarity between topic centroids at/above which a topic is listed as related to another
PROPOSAL_HINT_SIMILARITY = 0.4

# cosine distance (embeddings are normalized, so 0=identical..~2=opposite) below which an
# accepted review candidate is treated as a duplicate of an existing item rather than promoted
DUPLICATE_MATCH_THRESHOLD = 0.2
