"""Seeds and removes the self-contained dataset the Playwright suite (tests/e2e) runs against.

    python -m tests.e2e_fixture seed <run>      -> prints the seeded ids as JSON
    python -m tests.e2e_fixture cleanup <run>   -> deletes everything tagged with <run>

Every record carries the run id (meetings `e2e-<run>` and `e2e-<run>-old`, topics named `E2E <run>...`), so cleanup
never touches real data.
Review candidates cannot be created through the API, which is why this seeds through the backend directly.
"""
from __future__ import annotations

import json
import sys
from datetime import date

from dotenv import load_dotenv
from sqlalchemy import delete, select

from app.application.dtos import NewItem
from app.infrastructure.persistence import database as db
from app.infrastructure.persistence.orm_models import (
    KnowledgeItemRow,
    MeetingRow,
    ReviewCandidateRow,
    TopicRow,
)
from tests.support import brain


def _names(run: str) -> dict[str, str]:
    return {
        "meeting": f"e2e-{run}",
        "old_meeting": f"e2e-{run}-old",
        "topic": f"E2E {run}",
        "target": f"E2E {run} target",
        "owner": f"E2E Owner {run}",
    }


# Deliberately unrelated sentences: accepting a candidate whose text is near-identical to an existing item is treated
# as a duplicate (see DUPLICATE_MATCH_THRESHOLD) and creates no new item.
_CANDIDATES = {
    "c-accept": "Migrate the billing exports to columnar parquet files",
    "c-reject": "Rename the weekly platform sync to a fortnightly forum",
    "c-meeting": "Archive the legacy onboarding wiki into the shared drive",
}
_ITEM = "Order replacement badge readers for the lobby"
# two open questions for the Briefing page: one from today's meeting, one from a meeting old enough to be hidden
_FRESH_QUESTION = "Confirm the catering headcount for the offsite"
_STALE_QUESTION = "Decide what replaces the retired fax gateway"


def _question(item_id: str, meeting_id: str, topic: object, description: str, owner: str) -> KnowledgeItemRow:
    return KnowledgeItemRow(
        id=item_id,
        meeting_id=meeting_id,
        topic_id=topic.id,  # type: ignore[attr-defined]
        type="QUESTION",
        description=description,
        theme=topic.name,  # type: ignore[attr-defined]
        status="Open",
        confidence="MEDIUM",
        owner=owner,
        stakeholders=[owner],
        evidence_quote="quote",
        related_ids=[],
        embedding=None,
    )


def seed(run: str) -> dict[str, object]:
    names = _names(run)
    with db.get_session() as session:
        session.add(MeetingRow(id=names["meeting"], title=f"E2E meeting {run}", date=date.today().isoformat(), source_url=""))
        for key, sentence in _CANDIDATES.items():
            session.add(
                ReviewCandidateRow(
                    id=f"{names['meeting']}:{key}",
                    meeting_id=names["meeting"],
                    type="DECISION",
                    description=f"{sentence} ({run})",
                    reason="Seeded by the end-to-end suite",
                    confidence="MEDIUM",
                    evidence_quote=f"quote for {key}",
                    evidence_context="e2e",
                    status="PENDING",
                )
            )
        session.commit()
    topic = brain.create_topic(names["topic"])
    target = brain.create_topic(names["target"])
    item = brain.create_item(topic.id, NewItem(type="ACTION", description=f"{_ITEM} ({run})"))
    fresh_question, stale_question = f"{_FRESH_QUESTION} ({run})", f"{_STALE_QUESTION} ({run})"
    with db.get_session() as session:
        session.add(MeetingRow(id=names["old_meeting"], title=f"E2E meeting {run}, long ago", date="2020-01-01", source_url=""))
        session.add(_question(f"{names['meeting']}:Q-fresh", names["meeting"], topic, fresh_question, names["owner"]))
        session.add(_question(f"{names['old_meeting']}:Q-stale", names["old_meeting"], topic, stale_question, names["owner"]))
        session.commit()
    return {
        "run": run,
        "meetingId": names["meeting"],
        "topicId": topic.id,
        "topicName": topic.name,
        "targetTopicId": target.id,
        "targetTopicName": target.name,
        "itemId": item.id,
        "itemDescription": item.description,
        "acceptDescription": f"{_CANDIDATES['c-accept']} ({run})",
        "rejectDescription": f"{_CANDIDATES['c-reject']} ({run})",
        "meetingCandidateDescription": f"{_CANDIDATES['c-meeting']} ({run})",
        "owner": names["owner"],
        "freshQuestion": fresh_question,
        "staleQuestion": stale_question,
    }


def cleanup(run: str) -> None:
    names = _names(run)
    prefix = f"E2E {run}"
    with db.get_session() as session:
        topic_ids = session.execute(select(TopicRow.id).where(TopicRow.name.startswith(prefix))).scalars().all()
        session.execute(
            delete(KnowledgeItemRow).where(
                KnowledgeItemRow.meeting_id.in_([names["meeting"], names["old_meeting"]])
                | KnowledgeItemRow.id.startswith(f"{names['meeting']}:")
                | KnowledgeItemRow.topic_id.in_(topic_ids)
                | KnowledgeItemRow.description.endswith(f"({run})")
            )
        )
        session.execute(delete(ReviewCandidateRow).where(ReviewCandidateRow.meeting_id == names["meeting"]))
        session.execute(delete(MeetingRow).where(MeetingRow.id.in_([names["meeting"], names["old_meeting"]])))
        session.commit()
    for topic_id in topic_ids:
        brain.delete_topic(topic_id)  # also removes the topic's images from S3


if __name__ == "__main__":
    load_dotenv()
    command, run_id = sys.argv[1], sys.argv[2]
    if command == "seed":
        print(json.dumps(seed(run_id)))
    elif command == "cleanup":
        cleanup(run_id)
    else:
        raise SystemExit(f"unknown command {command!r}")
