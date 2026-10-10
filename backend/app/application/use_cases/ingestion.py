"""Ingests meeting extracts into the knowledge base. Idempotent: an unchanged extract changes nothing, and a
re-ingested one refreshes only what the extractor owns - never a human decision (review status, an item's
open/closed status, the topic it was filed under, a resolved topic proposal)."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from app.application.dtos import IngestSummary
from app.application.exceptions import IngestionAlreadyRunning
from app.application.interfaces.repositories import UnitOfWork, UnitOfWorkFactory
from app.application.interfaces.services import Embedder, ExtractSource, IdGenerator
from app.application.services import assembler
from app.application.services.priority_recalculation import PriorityRecalculator
from app.application.services.uncategorized import ensure_uncategorized_topic
from app.domain.entities.knowledge_item import KnowledgeItem
from app.domain.entities.meeting import Meeting
from app.domain.entities.review_candidate import ReviewCandidate
from app.domain.policies import DUPLICATE_MATCH_THRESHOLD
from app.domain.services.topic_matching import TopicMatcher, TopicSnapshot
from app.domain.value_objects.extraction import ExtractedMeeting

MAX_PARALLEL_DOWNLOADS = 8


@dataclass(frozen=True)
class IngestExtracts:
    uow: UnitOfWorkFactory
    source: ExtractSource
    embedder: Embedder
    ids: IdGenerator
    recalculator: PriorityRecalculator
    # startup and manual runs must not overlap: two concurrent upserts of the same extract race on the
    # near-duplicate check and can insert duplicate rows
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def __call__(self, *, wait: bool = False) -> IngestSummary:
        """Runs one ingestion. With `wait=False` a run already in progress raises IngestionAlreadyRunning;
        with `wait=True` this call queues behind it."""
        if not self._lock.acquire(blocking=wait):
            raise IngestionAlreadyRunning()
        try:
            summary = self.ingest_all()
            if summary.changed:
                # bulk load, not a fine-grained edit - recalculating every topic is the documented
                # exception to "recalculate only affected topics"
                self.recalculator.recalculate_all(trigger="ingestion")
            return summary
        finally:
            self._lock.release()

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def ingest_all(self) -> IngestSummary:
        with self.uow() as uow:
            summary = self.ingest_into(uow)
            uow.commit()
        return summary

    def ingest_into(self, uow: UnitOfWork) -> IngestSummary:
        """Ingests every extract inside the caller's unit of work (the caller commits)."""
        keys = self.source.list_keys()
        processed = 0
        existed: dict[str, bool] = {}  # meeting id -> already stored before this run
        changed_ids: set[str] = set()
        # extracts are downloaded/parsed concurrently, but merged sequentially in key order so topic
        # matching (which depends on what earlier extracts filed) stays deterministic
        with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_DOWNLOADS, len(keys) or 1)) as pool:
            for meetings in pool.map(self.source.load, keys):
                for extracted in meetings:
                    if extracted.id not in existed:
                        existed[extracted.id] = uow.meetings.get(extracted.id) is not None
                    if self.merge_meeting(uow, extracted):
                        changed_ids.add(extracted.id)
                    processed += 1
        new = sum(1 for present in existed.values() if not present)
        updated = sum(1 for meeting_id, present in existed.items() if present and meeting_id in changed_ids)
        return IngestSummary(processed=processed, new=new, updated=updated, unchanged=len(existed) - new - updated)

    def merge_meeting(self, uow: UnitOfWork, extracted: ExtractedMeeting) -> bool:
        """Merges one extracted meeting, skipping whatever is already up to date (and its embedding work).
        Returns whether anything was added or changed."""
        changed = False

        meeting = uow.meetings.get(extracted.id)
        if meeting is None:
            uow.meetings.add(Meeting.from_extraction(extracted))
            changed = True
        elif meeting.differs_from_extraction(extracted):
            meeting.apply_extraction(extracted)
            uow.meetings.save(meeting)
            changed = True

        if extracted.items:
            stored = {
                item.id: item
                for item in uow.items.list_by_ids([item.id for item in extracted.items], with_embeddings=False)
            }
            # a stored embedding stays valid unless the description changed, so only embed new/edited
            # items - on an unchanged restart this skips loading the embedding model altogether
            to_embed = [
                item for item in extracted.items if item.id not in stored or stored[item.id].description != item.description
            ]
            vectors = dict(
                zip((item.id for item in to_embed), self.embedder.embed_texts([item.description for item in to_embed]))
            )
            new_items = [item for item in extracted.items if item.id not in stored]
            matcher = self._topic_matcher(uow) if new_items else None
            # resolved together (not one by one) so a related item later in the extract is still found;
            # an item skipped below as a near-duplicate keeps its slot here, which is harmless
            assignments = (
                matcher.resolve_batch([(item, vectors[item.id]) for item in new_items]) if matcher is not None else {}
            )
            for incoming in extracted.items:
                current = stored.get(incoming.id)
                vector = vectors.get(incoming.id)
                if current is None:
                    assert vector is not None and matcher is not None
                    duplicate = uow.items.find_duplicate(
                        vector, max_distance=DUPLICATE_MATCH_THRESHOLD, meeting_id=extracted.id
                    )
                    if duplicate is not None:
                        # a different LLM's near-duplicate of an item already ingested for this
                        # meeting - reinforce it instead of adding a second, duplicate item
                        if duplicate.reinforce():
                            uow.items.save(duplicate)
                            changed = True
                        continue
                    # only genuinely new items are filed - re-ingesting an item that already exists must
                    # not undo a manual topic assignment or resolved proposal
                    topic_id, suggested_topic = assignments[incoming.id]
                    created = KnowledgeItem.from_extraction(
                        incoming,
                        topic_id=topic_id,
                        topic_name=matcher.name_of(topic_id),
                        suggested_topic=suggested_topic,
                        embedding=vector,
                    )
                    uow.items.add(created)
                    # an extract that repeats an id: the later entry refreshes the one just added
                    stored[incoming.id] = created
                elif vector is None and not current.differs_from_extraction(incoming):
                    continue
                else:
                    current.apply_extraction(incoming, vector)
                    uow.items.save(current)
                changed = True

        if extracted.review_candidates:
            stored_candidates = {
                candidate.id: candidate
                for candidate in uow.review_candidates.list_by_ids([c.id for c in extracted.review_candidates])
            }
            for incoming_candidate in extracted.review_candidates:
                current_candidate = stored_candidates.get(incoming_candidate.id)
                if current_candidate is None:
                    uow.review_candidates.add(ReviewCandidate.from_extraction(incoming_candidate, extracted.id))
                elif current_candidate.differs_from_extraction(incoming_candidate):
                    # the status is a human decision and is never touched
                    current_candidate.apply_extraction(incoming_candidate)
                    uow.review_candidates.save(current_candidate)
                else:
                    continue
                changed = True

        return changed

    def _topic_matcher(self, uow: UnitOfWork) -> TopicMatcher:
        topics, items_by_topic = assembler.load_topics(uow)
        return TopicMatcher(
            [
                TopicSnapshot(topic.id, topic.name, [item.embedding for item in items_by_topic[topic.id]])
                for topic in topics
            ],
            related_topic_ids=uow.items.topic_ids_of,
            ensure_uncategorized=lambda: ensure_uncategorized_topic(uow, self.ids).id,
        )
