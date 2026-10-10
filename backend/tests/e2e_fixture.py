"""Seeds and removes the self-contained dataset the Playwright suite (tests/e2e) runs against.

    python -m tests.e2e_fixture seed <run>      -> prints the seeded ids as JSON
    python -m tests.e2e_fixture cleanup <run>   -> deletes everything tagged with <run>

Every record carries the run id (meeting `e2e-<run>`, topics named `E2E <run>...`), so cleanup never touches real data.
Review candidates cannot be created through the API, which is why this seeds through the backend directly.
"""
from __future__ import annotations

import json
import sys
from datetime import date

from dotenv import load_dotenv
from sqlalchemy import delete, select

from tests.support import brain
from app.infrastructure.persistence import database as db
from app.infrastructure.persistence.orm_models import KnowledgeItemRow, MeetingRow, ReviewCandidateRow, TopicRow
from app.models import ItemCreate


def _names(run: str) -> dict[str, str]:
    return {"meeting": f"e2e-{run}", "topic": f"E2E {run}", "target": f"E2E {run} target"}


# Deliberately unrelated sentences: accepting a candidate whose text is near-identical to an existing item is treated
# as a duplicate (see DUPLICATE_MATCH_THRESHOLD) and creates no new item.
_CANDIDATES = {
    "c-accept": "Migrate the billing exports to columnar parquet files",
    "c-reject": "Rename the weekly platform sync to a fortnightly forum",
}
_ITEM = "Order replacement badge readers for the lobby"


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
    item = brain.create_item(topic.id, ItemCreate(type="ACTION", description=f"{_ITEM} ({run})"))
    assert item is not None
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
    }


def cleanup(run: str) -> None:
    names = _names(run)
    prefix = f"E2E {run}"
    with db.get_session() as session:
        topic_ids = session.execute(select(TopicRow.id).where(TopicRow.name.startswith(prefix))).scalars().all()
        session.execute(
            delete(KnowledgeItemRow).where(
                (KnowledgeItemRow.meeting_id == names["meeting"])
                | KnowledgeItemRow.id.startswith(f"{names['meeting']}:")
                | KnowledgeItemRow.topic_id.in_(topic_ids)
                | KnowledgeItemRow.description.endswith(f"({run})")
            )
        )
        session.execute(delete(ReviewCandidateRow).where(ReviewCandidateRow.meeting_id == names["meeting"]))
        session.execute(delete(MeetingRow).where(MeetingRow.id == names["meeting"]))
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
