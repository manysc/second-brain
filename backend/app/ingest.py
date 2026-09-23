"""Parses raw meeting extraction JSON (from S3) into domain models, and upserts them into Postgres.

Moved from app/data.py, which now only queries Postgres.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Iterable

import numpy as np
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, defer, selectinload

from app import db, embeddings, s3_store
from app.data import (
    DUPLICATE_MATCH_THRESHOLD,
    ITEM_TOPIC_MATCH_SIMILARITY,
    UNCATEGORIZED_TOPIC,
    _closest_topic,
    _get_or_create_uncategorized_topic,
)
from app.db_models import KnowledgeItemRow, MeetingRow, ReviewCandidateRow, TopicRow
from app.models import (
    Confidence,
    Evidence,
    ItemType,
    KnowledgeItem,
    Meeting,
    RawCandidate,
    RawEvidence,
    RawExtraction,
    RawMeetingInfo,
    ReviewCandidate,
    Topic,
)


def _normalize_confidence(value: str) -> Confidence:
    normalized = value.upper()
    return normalized if normalized in ("HIGH", "LOW") else "MEDIUM"


def _normalize_evidence(raw: RawEvidence) -> Evidence:
    return Evidence(speaker=raw.speaker, timestamp=raw.timestamp, quote=raw.quote, context=raw.context)


def _normalize_meeting_date(value: str, meeting_id: str) -> str:
    """Meeting dates must already be strict ISO 'YYYY-MM-DD'; fail loudly instead of guessing at
    ambiguous formats (same policy as due_date parsing, spec section 9)."""
    candidate = value.strip()
    try:
        date.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(
            f"meeting '{meeting_id}' has a non-ISO date {value!r}; expected 'YYYY-MM-DD'"
        ) from exc
    return candidate


def _item_id_prefix(meeting_id: str, variant: str) -> str:
    # variant namespaces ids so two LLM extracts of the same meeting never collide on candidate_id
    return f"{meeting_id}:{variant}" if variant else meeting_id


def _normalize_item(candidate: RawCandidate, item_type: ItemType, meeting_id: str, variant: str) -> KnowledgeItem:
    owner = candidate.owner or candidate.proposed_by or candidate.decision_owner
    speaker = candidate.evidence.speaker
    stakeholders = list(dict.fromkeys(value for value in (owner, speaker) if value))
    return KnowledgeItem(
        id=f"{_item_id_prefix(meeting_id, variant)}:{candidate.candidate_id}",
        type=item_type,
        description=candidate.description,
        theme=candidate.theme,
        status=candidate.status,
        confidence=_normalize_confidence(candidate.confidence),
        owner=owner,
        stakeholders=stakeholders,
        due_date=candidate.due_date,
        due_date_source_text=candidate.due_date_source_text,
        rationale=candidate.rationale,
        resolution=candidate.resolution,
        evidence=_normalize_evidence(candidate.evidence),
        related_ids=candidate.related_candidate_ids,
        meeting_id=meeting_id,
    )


def _repair_json(text: str) -> dict:
    original = text.strip()
    # the source file is sometimes missing its enclosing braces
    repaired = original if original.startswith("{") else f"{{{original}}}"
    return json.loads(repaired)


def _derive_meeting_identity(key: str) -> tuple[str, str]:
    # the extraction JSON's own meeting_id is sometimes blank or duplicated across files;
    # the S3 key is always unique, so it's the source of truth for id-namespacing.
    # "<meeting-key>--<variant>.json" lets two different LLM extracts of the same meeting
    # (e.g. "standup--gpt4.json" / "standup--claude.json") share one canonical meeting_id.
    # Split before sanitizing so sanitization can't accidentally manufacture a "--".
    stem = Path(key).stem
    meeting_part, sep, variant_part = stem.partition("--")
    meeting_id = re.sub(r"[^A-Za-z0-9_-]", "-", meeting_part)
    variant = re.sub(r"[^A-Za-z0-9_-]", "-", variant_part) if sep else ""
    return meeting_id, variant


def _normalize_extraction(parsed: RawExtraction, meeting_id: str, variant: str) -> Meeting:
    items = [
        *(_normalize_item(c, "IDEA", meeting_id, variant) for c in parsed.ideas),
        *(_normalize_item(c, "DECISION", meeting_id, variant) for c in parsed.decisions),
        *(_normalize_item(c, "ACTION", meeting_id, variant) for c in parsed.actions),
        *(_normalize_item(c, "QUESTION", meeting_id, variant) for c in parsed.questions),
    ]

    review_candidates = [
        ReviewCandidate(
            id=f"{_item_id_prefix(meeting_id, variant)}:review-{index + 1}",
            type=candidate.candidate_type,
            description=candidate.description,
            reason=candidate.reason_for_review,
            confidence=_normalize_confidence(candidate.confidence),
            evidence=_normalize_evidence(candidate.evidence),
            status="PENDING",
        )
        for index, candidate in enumerate(parsed.review_candidates)
    ]

    topic_map: dict[str, list[KnowledgeItem]] = {}
    for item in items:
        topic_map.setdefault(item.theme or "Uncategorized", []).append(item)

    topics = [
        Topic(
            id=f"{meeting_id}:{name}",
            name=name,
            items=topic_items,
            stakeholders=list(dict.fromkeys(s for item in topic_items for s in item.stakeholders)),
        )
        for name, topic_items in topic_map.items()
    ]

    return Meeting(
        id=meeting_id,
        title=parsed.meeting.title,
        date=_normalize_meeting_date(parsed.meeting.date, meeting_id),
        source_url=parsed.meeting.source_url,
        items=items,
        review_candidates=review_candidates,
        topics=topics,
    )


def parse_meeting_from_s3(key: str) -> Meeting:
    parsed = RawExtraction.model_validate(_repair_json(s3_store.fetch_object_text(key)))
    meeting_id, variant = _derive_meeting_identity(key)
    return _normalize_extraction(parsed, meeting_id, variant)


_SOURCE_MEETING_PATTERN = re.compile(r"source meeting (MTG-\d{8}-\d{3}) \((\d{4}-\d{2}-\d{2}),")
_MEETING_COUNT_SUFFIX = re.compile(r"\s*\(\d+\s+meetings?\)\s*$", re.IGNORECASE)


def _embedded_source_meeting(candidate: RawCandidate) -> tuple[str, str] | None:
    match = _SOURCE_MEETING_PATTERN.search(candidate.evidence.context or "")
    return (match.group(1), match.group(2)) if match else None


def _strip_meeting_count_suffix(title: str) -> str:
    # a flattened register's own title (e.g. "DC-MS 1:1 Meeting Register (12 meetings)") describes
    # the whole file, not any individual meeting split out of it - drop the aggregate count
    return _MEETING_COUNT_SUFFIX.sub("", title).strip()


def _split_by_embedded_source_meeting(parsed: RawExtraction) -> list[RawExtraction] | None:
    """Some single-meeting-shaped files are actually a flattened export of several real meetings,
    recoverable only from a "source meeting MTG-... (date, ...)" annotation the extraction tool
    writes into each candidate's evidence.context (seen so far only in register exports that
    merge everything into one meeting instead of nesting per-meeting entries like
    `_find_bundle_entries` handles). Returns None when no candidate carries the annotation, i.e.
    this is a genuine single meeting."""
    field_lists = {
        "ideas": parsed.ideas,
        "decisions": parsed.decisions,
        "actions": parsed.actions,
        "questions": parsed.questions,
    }
    tagged = {
        field: [(candidate, _embedded_source_meeting(candidate)) for candidate in candidates]
        for field, candidates in field_lists.items()
    }
    if not any(source for pairs in tagged.values() for _, source in pairs):
        return None
    untagged = sum(1 for pairs in tagged.values() for _, source in pairs if source is None)
    if untagged:
        raise ValueError(
            f"{untagged} candidate(s) lack the 'source meeting' annotation needed to split this "
            "flattened register file by meeting"
        )

    groups: dict[tuple[str, str], dict[str, list[RawCandidate]]] = {}
    for field, pairs in tagged.items():
        for candidate, source in pairs:
            groups.setdefault(source, {name: [] for name in field_lists})[field].append(candidate)

    return [
        RawExtraction(
            schema_version=parsed.schema_version,
            meeting=RawMeetingInfo(
                meeting_id=source_id,
                title=_strip_meeting_count_suffix(parsed.meeting.title),
                date=source_date,
                source_url=parsed.meeting.source_url,
            ),
            review_candidates=[],
            **bucket,
        )
        for (source_id, source_date), bucket in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0]))
    ]


def _find_bundle_entries(raw: dict) -> list[dict] | None:
    # the extraction tool isn't stable about what it calls a multi-meeting bundle's list of
    # per-meeting entries ("extractions", "meetings", ... seen so far), so find it structurally:
    # the one top-level list whose items are each shaped like a single-meeting extraction (they
    # carry a "meeting" key). This also correctly skips look-alike lists such as a "coverage"
    # summary array, whose entries are flat (meeting_id/date/counts) and lack a "meeting" key.
    for value in raw.values():
        if isinstance(value, list) and value and all(isinstance(item, dict) and "meeting" in item for item in value):
            return value
    return None


def parse_meetings_from_s3(key: str) -> list[Meeting]:
    """Like `parse_meeting_from_s3`, but also handles a "bundle" file covering several meetings
    (e.g. a register export), whose per-meeting entries live under some top-level list (see
    `_find_bundle_entries`). Each embedded extraction becomes its own Meeting, keyed
    "<meeting-key>-<n>" so they never collide with each other or with the plain single-meeting id
    the same key would otherwise produce."""
    raw = _repair_json(s3_store.fetch_object_text(key))
    meeting_id, variant = _derive_meeting_identity(key)
    try:
        parsed = RawExtraction.model_validate(raw)
    except ValidationError:
        pass
    else:
        split = _split_by_embedded_source_meeting(parsed)
        if split is None:
            return [_normalize_extraction(parsed, meeting_id, variant)]
        meetings = [_normalize_extraction(sub, f"{meeting_id}-{index + 1}", variant) for index, sub in enumerate(split)]
        if parsed.review_candidates:
            review_only = parsed.model_copy(
                update={
                    "ideas": [],
                    "decisions": [],
                    "actions": [],
                    "questions": [],
                    "meeting": parsed.meeting.model_copy(
                        update={"title": _strip_meeting_count_suffix(parsed.meeting.title)}
                    ),
                }
            )
            meetings.append(_normalize_extraction(review_only, f"{meeting_id}-review", variant))
        return meetings

    bundle_entries = _find_bundle_entries(raw)
    if bundle_entries is None:
        raise ValueError(f"'{key}' is not a recognized single-meeting or bundle extraction file")
    return [
        _normalize_extraction(RawExtraction.model_validate(entry), f"{meeting_id}-{index + 1}", variant)
        for index, entry in enumerate(bundle_entries)
    ]


class _TopicMatcher:
    """Files new items under an *existing* topic. Ingestion never creates a topic: when nothing
    matches, the item lands in "Uncategorized" with the extractor's theme kept as a proposal
    (`suggested_topic`) for a human to accept, rename or redirect on the review page.

    Match order: (1) exact topic name == theme, (2) the topic most of the item's related items
    already sit in, (3) the topic whose centroid is semantically closest (>= the same similarity
    used for item-topic suggestions)."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._uncategorized_id: str | None = None
        self._ids_by_name: dict[str, str] = {}
        self._names_by_id: dict[str, str] = {}
        self._sums: dict[str, np.ndarray] = {}
        self._counts: dict[str, int] = {}
        rows = session.execute(select(TopicRow).options(selectinload(TopicRow.items))).scalars().all()
        for row in rows:
            self._ids_by_name[row.name.casefold()] = row.id
            self._names_by_id[row.id] = row.name
            if row.name == UNCATEGORIZED_TOPIC:
                self._uncategorized_id = row.id
                continue
            vectors = [np.array(item.embedding) for item in row.items if item.embedding is not None]
            if vectors:
                self._sums[row.id] = np.sum(vectors, axis=0)
                self._counts[row.id] = len(vectors)

    def _uncategorized(self) -> str:
        if self._uncategorized_id is None:
            self._uncategorized_id = _get_or_create_uncategorized_topic(self._session)
            self._ids_by_name[UNCATEGORIZED_TOPIC.casefold()] = self._uncategorized_id
            self._names_by_id[self._uncategorized_id] = UNCATEGORIZED_TOPIC
        return self._uncategorized_id

    @staticmethod
    def _full_related_ids(item: KnowledgeItem) -> list[str]:
        # related_ids are candidate ids local to the item's own extract; full ids share its prefix
        prefix = item.id.rsplit(":", 1)[0]
        return [f"{prefix}:{related_id}" for related_id in item.related_ids]

    def _by_related_items(self, item: KnowledgeItem, batch_topic_ids: Iterable[str] = ()) -> str | None:
        """Majority topic among the item's related items already in the DB plus `batch_topic_ids`
        (topics of related items from the same extract, which aren't inserted yet)."""
        full_ids = self._full_related_ids(item)
        topic_ids = list(batch_topic_ids)
        if full_ids:
            topic_ids += [
                topic_id
                for (topic_id,) in self._session.execute(
                    select(KnowledgeItemRow.topic_id).where(
                        KnowledgeItemRow.id.in_(full_ids), KnowledgeItemRow.topic_id.is_not(None)
                    )
                )
                if topic_id != self._uncategorized_id
            ]
        return Counter(topic_ids).most_common(1)[0][0] if topic_ids else None

    def resolve(
        self, item: KnowledgeItem, vector: list[float], batch_topic_ids: Iterable[str] = ()
    ) -> tuple[str, str | None]:
        """Returns (topic_id, proposed_topic_name). The proposal is set only when unmatched."""
        theme = (item.theme or "").strip()
        if not theme or theme.casefold() == UNCATEGORIZED_TOPIC.casefold():
            return self._uncategorized(), None
        matched = self._ids_by_name.get(theme.casefold()) or self._by_related_items(item, batch_topic_ids)
        if matched is None:
            centroids = {tid: total / self._counts[tid] for tid, total in self._sums.items()}
            matched, _ = _closest_topic(np.array(vector), centroids, ITEM_TOPIC_MATCH_SIMILARITY)
        if matched is not None:
            return matched, None
        return self._uncategorized(), theme

    def resolve_batch(
        self, entries: list[tuple[KnowledgeItem, list[float]]]
    ) -> dict[str, tuple[str, str | None]]:
        """Resolves every new item of an extract at once, so related items are found regardless of
        order or link direction (B -> A, A -> B, or chains): links are treated as undirected, and
        items left in "Uncategorized" adopt a related item's topic until nothing changes."""
        known_ids = {item.id for item, _ in entries}
        neighbours: dict[str, set[str]] = defaultdict(set)
        for item, _ in entries:
            for other_id in self._full_related_ids(item):
                if other_id in known_ids and other_id != item.id:
                    neighbours[item.id].add(other_id)
                    neighbours[other_id].add(item.id)

        resolved: dict[str, tuple[str, str | None]] = {}
        matched: dict[str, str] = {}  # item id -> existing (non-Uncategorized) topic it was filed under

        def note(item_id: str, topic_id: str, proposal: str | None) -> None:
            resolved[item_id] = (topic_id, proposal)
            if topic_id != self._uncategorized_id:
                matched[item_id] = topic_id

        for item, vector in entries:
            batch_topic_ids = [matched[other] for other in neighbours[item.id] if other in matched]
            note(item.id, *self.resolve(item, vector, batch_topic_ids))

        changed = True
        while changed:
            changed = False
            for item, _ in entries:
                if item.id in matched:
                    continue
                votes = Counter(matched[other] for other in neighbours[item.id] if other in matched)
                if votes:
                    note(item.id, votes.most_common(1)[0][0], None)
                    changed = True

        # fold vectors in only once each item's final topic is known
        for item, vector in entries:
            self.record(resolved[item.id][0], vector)
        return resolved

    def name_of(self, topic_id: str) -> str:
        return self._names_by_id[topic_id]

    def record(self, topic_id: str, vector: list[float]) -> None:
        """Folds a newly filed item into its topic's centroid so later items in the run can match it."""
        if topic_id == self._uncategorized_id:
            return
        self._sums[topic_id] = self._sums.get(topic_id, 0) + np.array(vector)
        self._counts[topic_id] = self._counts.get(topic_id, 0) + 1


def _find_similar_item_in_meeting(session: Session, meeting_id: str, embedding: list[float]) -> KnowledgeItemRow | None:
    # scoped to one meeting so two LLM extracts of the same meeting merge, without risking
    # false merges against unrelated meetings the way a global similarity search would
    distance_expr = KnowledgeItemRow.embedding.cosine_distance(embedding)
    stmt = (
        select(KnowledgeItemRow, distance_expr)
        .where(KnowledgeItemRow.meeting_id == meeting_id, KnowledgeItemRow.embedding.is_not(None))
        .order_by(distance_expr)
        .limit(1)
    )
    result = session.execute(stmt).first()
    if result is None:
        return None
    row, distance = result
    return row if distance < DUPLICATE_MATCH_THRESHOLD else None


_ITEM_UPDATE_COLS = (
    # topic_id, theme (kept equal to the topic name), suggested_topic and status intentionally
    # excluded: preserves manual topic reassignments, proposal decisions and open/closed status
    # across re-ingestion (status is still set on first insert)
    "type",
    "description",
    "confidence",
    "owner",
    "stakeholders",
    "due_date",
    "due_date_source_text",
    "rationale",
    "resolution",
    "evidence_speaker",
    "evidence_timestamp",
    "evidence_quote",
    "evidence_context",
    "related_ids",
)

# status is intentionally excluded: ingestion must not clobber a human review decision
_CANDIDATE_UPDATE_COLS = (
    "type",
    "description",
    "reason",
    "confidence",
    "evidence_speaker",
    "evidence_timestamp",
    "evidence_quote",
    "evidence_context",
)


def _item_fields(item: KnowledgeItem) -> dict[str, object]:
    return {
        "type": item.type,
        "description": item.description,
        "status": item.status,
        "confidence": item.confidence,
        "owner": item.owner,
        "stakeholders": item.stakeholders,
        "due_date": item.due_date,
        "due_date_source_text": item.due_date_source_text,
        "rationale": item.rationale,
        "resolution": item.resolution,
        "evidence_speaker": item.evidence.speaker,
        "evidence_timestamp": item.evidence.timestamp,
        "evidence_quote": item.evidence.quote,
        "evidence_context": item.evidence.context,
        "related_ids": item.related_ids,
    }


def _candidate_fields(candidate: ReviewCandidate) -> dict[str, object]:
    return {
        "type": candidate.type,
        "description": candidate.description,
        "reason": candidate.reason,
        "confidence": candidate.confidence,
        "evidence_speaker": candidate.evidence.speaker,
        "evidence_timestamp": candidate.evidence.timestamp,
        "evidence_quote": candidate.evidence.quote,
        "evidence_context": candidate.evidence.context,
    }


def _row_differs(row: object, fields: dict[str, object]) -> bool:
    return any(getattr(row, column) != value for column, value in fields.items())


def _item_row_differs(row: KnowledgeItemRow, fields: dict[str, object]) -> bool:
    # a stored HIGH may be a near-duplicate reinforcement from a second extract (see upsert_meeting)
    # rather than this extract's own value; treating that as a diff would revert it on every start
    # and have the duplicate re-apply it, so the two would churn forever. Trade-off: an extract
    # edited from HIGH down to a lower confidence isn't picked up.
    if row.confidence == "HIGH":
        fields = {column: value for column, value in fields.items() if column != "confidence"}
    # status is human-owned after first insert (not in _ITEM_UPDATE_COLS), so it can't count as a diff
    fields = {column: value for column, value in fields.items() if column != "status"}
    return _row_differs(row, fields)


def upsert_meeting(session: Session, meeting: Meeting) -> bool:
    """Upserts one meeting, skipping rows (and embedding work) that are already up to date.
    Returns whether anything in the database was inserted or changed."""
    changed = False

    meeting_fields = {"title": meeting.title, "date": meeting.date, "source_url": meeting.source_url}
    existing_meeting = session.get(MeetingRow, meeting.id)
    if existing_meeting is None or _row_differs(existing_meeting, meeting_fields):
        meeting_stmt = pg_insert(MeetingRow).values(id=meeting.id, **meeting_fields)
        meeting_stmt = meeting_stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={column: getattr(meeting_stmt.excluded, column) for column in meeting_fields},
        )
        session.execute(meeting_stmt)
        changed = True

    if meeting.items:
        existing_rows = {
            row.id: row
            for row in session.execute(
                select(KnowledgeItemRow)
                .options(defer(KnowledgeItemRow.embedding))
                .where(KnowledgeItemRow.id.in_([item.id for item in meeting.items]))
            ).scalars()
        }
        # a stored embedding stays valid unless the description changed, so only embed new/edited
        # items - on an unchanged restart this skips loading the embedding model altogether
        to_embed = [
            item
            for item in meeting.items
            if item.id not in existing_rows or existing_rows[item.id].description != item.description
        ]
        vectors = dict(zip((item.id for item in to_embed), embeddings.embed_texts([i.description for i in to_embed])))
        new_items = [item for item in meeting.items if item.id not in existing_rows]
        matcher = _TopicMatcher(session) if new_items else None
        # resolved together (not one by one) so a related item later in the extract is still found;
        # an item skipped below as a near-duplicate keeps its slot here, which is harmless
        assignments = (
            matcher.resolve_batch([(item, vectors[item.id]) for item in new_items]) if matcher is not None else {}
        )
        for item in meeting.items:
            existing = existing_rows.get(item.id)
            fields = _item_fields(item)
            vector = vectors.get(item.id)
            if existing is None:
                assert vector is not None
                duplicate = _find_similar_item_in_meeting(session, meeting.id, vector)
                if duplicate is not None:
                    # a different LLM's near-duplicate of an item already ingested for this
                    # meeting - reinforce it instead of inserting a second, duplicate row
                    if duplicate.confidence != "HIGH":
                        duplicate.confidence = "HIGH"
                        changed = True
                    continue
            elif vector is None and not _item_row_differs(existing, fields):
                continue
            # only file genuinely new items - re-ingesting an item that already exists must not
            # undo a manual topic assignment or resolved proposal
            topic_id: str | None = None
            suggested_topic: str | None = None
            theme = item.theme
            if existing is None:
                assert matcher is not None
                topic_id, suggested_topic = assignments[item.id]
                theme = matcher.name_of(topic_id)
            values = {**fields, "embedding": vector} if vector is not None else fields
            item_stmt = pg_insert(KnowledgeItemRow).values(
                id=item.id, meeting_id=meeting.id, topic_id=topic_id, theme=theme, suggested_topic=suggested_topic, **values
            )
            update_cols = {
                col: getattr(item_stmt.excluded, col)
                for col in (*_ITEM_UPDATE_COLS, *(("embedding",) if vector is not None else ()))
            }
            item_stmt = item_stmt.on_conflict_do_update(index_elements=["id"], set_=update_cols)
            session.execute(item_stmt)
            changed = True

    if meeting.review_candidates:
        existing_candidates = {
            row.id: row
            for row in session.execute(
                select(ReviewCandidateRow).where(
                    ReviewCandidateRow.id.in_([candidate.id for candidate in meeting.review_candidates])
                )
            ).scalars()
        }
        for candidate in meeting.review_candidates:
            fields = _candidate_fields(candidate)
            existing_candidate = existing_candidates.get(candidate.id)
            if existing_candidate is not None and not _row_differs(existing_candidate, fields):
                continue
            candidate_stmt = pg_insert(ReviewCandidateRow).values(
                id=candidate.id, meeting_id=meeting.id, status=candidate.status, **fields
            )
            update_cols = {col: getattr(candidate_stmt.excluded, col) for col in _CANDIDATE_UPDATE_COLS}
            candidate_stmt = candidate_stmt.on_conflict_do_update(index_elements=["id"], set_=update_cols)
            session.execute(candidate_stmt)
            changed = True

    return changed


def _ingest_all(session: Session) -> tuple[int, bool]:
    keys = s3_store.list_extract_keys()
    count = 0
    changed = False
    # extracts are downloaded/parsed concurrently, but upserted sequentially in key order so topic
    # matching (which depends on what earlier extracts filed) stays deterministic
    with ThreadPoolExecutor(max_workers=min(8, len(keys) or 1)) as pool:
        for meetings in pool.map(parse_meetings_from_s3, keys):
            for meeting in meetings:
                changed |= upsert_meeting(session, meeting)
                count += 1
    return count, changed


def ingest_all_from_s3(session: Session) -> int:
    return _ingest_all(session)[0]


def ingest_and_commit() -> int:
    """Opens a session, ingests everything from S3, and commits. Shared by the FastAPI startup
    hook and the manual scripts/ingest_to_postgres.py CLI entrypoint."""
    with db.get_session() as session:
        count, changed = _ingest_all(session)
        session.commit()
    if changed:
        # bulk load, not a fine-grained edit - recalculating every topic is the documented
        # exception to "recalculate only affected topics" (spec section 21)
        from app import data

        data.recalculate_all_topic_priorities(trigger="ingestion")
    return count
