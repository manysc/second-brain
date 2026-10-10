"""In-memory implementations of every application port, so use cases can be tested without Postgres, S3 or a
model. The fake unit of work is deliberately strict: entities are copied on the way in and out, and nothing
reaches the store without save()/add() followed by commit() - a forgotten save or commit fails a test."""
from __future__ import annotations

import copy
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

import numpy as np

from app.application.exceptions import ExtractSourceUnavailable
from app.container import Container, build_container
from app.domain.entities.knowledge_item import KnowledgeItem
from app.domain.entities.meeting import Meeting
from app.domain.entities.review_candidate import ReviewCandidate
from app.domain.entities.topic import Topic
from app.domain.exceptions import TopicNameConflict
from app.domain.policies import UNCATEGORIZED_TOPIC
from app.domain.services.topic_ranking import TopicProfile
from app.domain.value_objects.extraction import ExtractedMeeting
from app.domain.value_objects.image_upload import ImageUpload
from app.domain.value_objects.priority import TopicPriorityHistoryEntry


class State:
    def __init__(self) -> None:
        self.meetings: dict[str, Meeting] = {}
        self.items: dict[str, KnowledgeItem] = {}
        self.topics: dict[str, Topic] = {}
        self.candidates: dict[str, ReviewCandidate] = {}
        self.history: list[TopicPriorityHistoryEntry] = []
        self.version = 0


def _distance(a, b) -> float:
    va, vb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return 1.0 - float(np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb)))


class _Meetings:
    def __init__(self, state: State) -> None:
        self._s = state

    def get(self, meeting_id):
        return copy.deepcopy(self._s.meetings.get(meeting_id))

    def list_all(self):
        return copy.deepcopy(list(self._s.meetings.values()))

    def dates_by_id(self, meeting_ids):
        return {m.id: m.date for m in self._s.meetings.values() if m.id in set(meeting_ids)}

    def add(self, meeting):
        assert meeting.id not in self._s.meetings, "meeting added twice"
        self._s.meetings[meeting.id] = copy.deepcopy(meeting)

    def save(self, meeting):
        assert meeting.id in self._s.meetings, "save() of a meeting that was never added"
        self._s.meetings[meeting.id] = copy.deepcopy(meeting)


class _Items:
    def __init__(self, state: State) -> None:
        self._s = state

    def _out(self, items):
        return copy.deepcopy(list(items))

    def get(self, item_id):
        return copy.deepcopy(self._s.items.get(item_id))

    def list_all(self):
        return self._out(self._s.items.values())

    def list_by_ids(self, item_ids, *, with_embeddings=True):
        return self._out(i for i in self._s.items.values() if i.id in set(item_ids))

    def list_by_topic(self, topic_id):
        return self._out(i for i in self._s.items.values() if i.topic_id == topic_id)

    def list_by_topics(self, topic_ids):
        return self._out(i for i in self._s.items.values() if i.topic_id in set(topic_ids))

    def list_with_proposal(self, suggested_topic=None):
        if suggested_topic is None:
            return self._out(sorted((i for i in self._s.items.values() if i.suggested_topic), key=lambda i: i.id))
        return self._out(i for i in self._s.items.values() if i.suggested_topic == suggested_topic)

    def count_by_topic(self, topic_id):
        return sum(1 for i in self._s.items.values() if i.topic_id == topic_id)

    def count_all(self):
        return len(self._s.items)

    def topic_ids_of(self, item_ids):
        return [i.topic_id for i in self._s.items.values() if i.id in set(item_ids) and i.topic_id]

    def link_index(self):
        return (
            {i.id: i.topic_id for i in self._s.items.values()},
            {i.id: i.related_ids for i in self._s.items.values()},
        )

    def find_duplicate(self, embedding, *, max_distance, meeting_id=None):
        candidates = [
            (_distance(embedding, i.embedding), i)
            for i in self._s.items.values()
            if i.embedding is not None and (meeting_id is None or i.meeting_id == meeting_id)
        ]
        if not candidates:
            return None
        distance, nearest = min(candidates, key=lambda pair: pair[0])
        return copy.deepcopy(nearest) if distance < max_distance else None

    def nearest(self, embedding, limit, *, exclude_ids=()):
        scored = sorted(
            (
                (_distance(embedding, i.embedding), i)
                for i in self._s.items.values()
                if i.embedding is not None and i.id not in set(exclude_ids)
            ),
            key=lambda pair: pair[0],
        )
        return [(copy.deepcopy(i), d) for d, i in scored[:limit]]

    def add(self, item):
        assert item.id not in self._s.items, f"item {item.id} added twice"
        self._s.items[item.id] = copy.deepcopy(item)

    def save(self, item):
        assert item.id in self._s.items, "save() of an item that was never added"
        self._s.items[item.id] = copy.deepcopy(item)

    def delete(self, item):
        self._s.items.pop(item.id, None)


class _Topics:
    def __init__(self, state: State) -> None:
        self._s = state

    def get(self, topic_id):
        return copy.deepcopy(self._s.topics.get(topic_id))

    def get_by_name(self, name):
        return copy.deepcopy(next((t for t in self._s.topics.values() if t.name == name), None))

    def list_all(self):
        return copy.deepcopy(list(self._s.topics.values()))

    def list_by_ids(self, topic_ids):
        return copy.deepcopy([t for t in self._s.topics.values() if t.id in set(topic_ids)])

    def _check_name(self, topic):
        if any(t.name == topic.name and t.id != topic.id for t in self._s.topics.values()):
            raise TopicNameConflict(topic.name)

    def add(self, topic):
        assert topic.id not in self._s.topics, "topic added twice"
        self._check_name(topic)
        self._s.topics[topic.id] = copy.deepcopy(topic)

    def save(self, topic):
        assert topic.id in self._s.topics, "save() of a topic that was never added"
        self._check_name(topic)
        self._s.topics[topic.id] = copy.deepcopy(topic)

    def delete(self, topic):
        self._s.topics.pop(topic.id, None)

    def merge(self, source, target):
        stored_target = self._s.topics[target.id]
        stored_source = self._s.topics.pop(source.id)
        for item in self._s.items.values():
            if item.topic_id == source.id:
                item.file_under(stored_target)
        for note in stored_source.notes:
            stored_target.add_note(note)
        for image in stored_source.images:
            stored_target.attach_image(image)

    def ranking_version(self):
        return str(self._s.version)

    def ranking_profiles(self):
        return [
            TopicProfile(
                topic_id=t.id,
                name=t.name,
                tags=list(t.tags),
                item_embeddings=[i.embedding for i in self._s.items.values() if i.topic_id == t.id and i.embedding is not None],
                item_descriptions=[i.description for i in self._s.items.values() if i.topic_id == t.id],
            )
            for t in self._s.topics.values()
            if t.name != UNCATEGORIZED_TOPIC
        ]


class _Candidates:
    def __init__(self, state: State) -> None:
        self._s = state

    def get(self, candidate_id):
        return copy.deepcopy(self._s.candidates.get(candidate_id))

    def list_all(self):
        return copy.deepcopy(list(self._s.candidates.values()))

    def list_pending(self):
        dates = {m.id: m.date for m in self._s.meetings.values()}
        pending = [c for c in self._s.candidates.values() if c.is_pending]
        pending.sort(key=lambda c: c.id)
        pending.sort(key=lambda c: dates.get(c.meeting_id, ""), reverse=True)
        return copy.deepcopy(pending)

    def list_by_ids(self, candidate_ids):
        return copy.deepcopy([c for c in self._s.candidates.values() if c.id in set(candidate_ids)])

    def add(self, candidate):
        assert candidate.id not in self._s.candidates, "candidate added twice"
        self._s.candidates[candidate.id] = copy.deepcopy(candidate)

    def save(self, candidate):
        assert candidate.id in self._s.candidates, "save() of a candidate that was never added"
        self._s.candidates[candidate.id] = copy.deepcopy(candidate)


class _History:
    def __init__(self, state: State) -> None:
        self._s = state

    def add(self, entry):
        self._s.history.append(entry)

    def list_for_topic(self, topic_id):
        return sorted((e for e in self._s.history if e.topic_id == topic_id), key=lambda e: e.changed_at, reverse=True)

    def list_since(self, cutoff_iso):
        return sorted((e for e in self._s.history if e.changed_at >= cutoff_iso), key=lambda e: e.changed_at, reverse=True)


class FakeUnitOfWork:
    def __init__(self, database: FakeDatabase) -> None:
        self._database = database

    def __enter__(self) -> FakeUnitOfWork:
        self._work = copy.deepcopy(self._database.state)
        self.meetings = _Meetings(self._work)
        self.items = _Items(self._work)
        self.topics = _Topics(self._work)
        self.review_candidates = _Candidates(self._work)
        self.priority_history = _History(self._work)
        return self

    def __exit__(self, *exc_info: object) -> None:
        del self._work

    def commit(self) -> None:
        self._work.version += 1
        self._database.state = copy.deepcopy(self._work)
        self._database.commits += 1

    def rollback(self) -> None:
        self.__enter__()


class FakeDatabase:
    """What is committed. `uow` is the UnitOfWorkFactory to hand to use cases."""

    def __init__(self) -> None:
        self.state = State()
        self.commits = 0

    def uow(self) -> FakeUnitOfWork:
        return FakeUnitOfWork(self)

    # direct seeding/inspection helpers for tests
    def seed(self, *entities) -> None:
        for entity in entities:
            target = {
                Meeting: self.state.meetings,
                KnowledgeItem: self.state.items,
                Topic: self.state.topics,
                ReviewCandidate: self.state.candidates,
            }[type(entity)]
            target[entity.id] = copy.deepcopy(entity)
        self.state.version += 1

    def item(self, item_id: str) -> KnowledgeItem:
        return self.state.items[item_id]

    def topic(self, topic_id: str) -> Topic:
        return self.state.topics[topic_id]

    def topic_named(self, name: str) -> Topic | None:
        return next((t for t in self.state.topics.values() if t.name == name), None)


class FakeEmbedder:
    """Looks vectors up by exact text; unknown text gets a vector unlike any registered one."""

    def __init__(self, vectors: dict[str, Sequence[float]] | None = None, dim: int = 4) -> None:
        self.vectors = dict(vectors or {})
        self.dim = dim
        self.calls: list[list[str]] = []

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [list(self.vectors.get(text, self._unknown(text))) for text in texts]

    def _unknown(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        vector[-1] = 1.0
        return vector

    @property
    def embedded(self) -> list[str]:
        return [text for call in self.calls for text in call]


class FakeImageStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_delete = False

    def store(self, topic_id: str, image_id: str, upload: ImageUpload) -> str:
        key = f"images/topics/{topic_id}/{image_id}.{upload.extension}"
        self.objects[key] = upload.body
        return key

    def load(self, key: str) -> bytes:
        return self.objects[key]

    def delete(self, key: str) -> None:
        if self.fail_delete:
            raise RuntimeError("storage is down")
        self.objects.pop(key, None)


class FakeExtractSource:
    def __init__(self, extracts: dict[str, list[ExtractedMeeting]] | None = None) -> None:
        self.extracts = dict(extracts or {})
        self.unreachable = False

    def list_keys(self) -> list[str]:
        if self.unreachable:
            raise ExtractSourceUnavailable("cannot reach the bucket")
        return sorted(self.extracts)

    def load(self, key: str) -> list[ExtractedMeeting]:
        return self.extracts[key]


class FakeClock:
    def __init__(self, now: datetime | None = None) -> None:
        self.current = now or datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.current

    def advance(self, **delta) -> None:
        self.current += timedelta(**delta)


class SequentialIds:
    def __init__(self) -> None:
        self._next = 0

    def new_id(self) -> str:
        self._next += 1
        return f"id-{self._next}"

    def new_short_id(self) -> str:
        self._next += 1
        return f"short{self._next}"


class NoSemanticClassifier:
    def classify(self, context: str):
        return None


class World:
    """A fully wired application over in-memory fakes."""

    def __init__(self, vectors: dict[str, Sequence[float]] | None = None) -> None:
        self.db = FakeDatabase()
        self.embedder = FakeEmbedder(vectors)
        self.images = FakeImageStore()
        self.source = FakeExtractSource()
        self.clock = FakeClock()
        self.ids = SequentialIds()
        self.app: Container = build_container(
            uow=self.db.uow,
            embedder=self.embedder,
            images=self.images,
            extract_source=self.source,
            clock=self.clock,
            ids=self.ids,
            classifier=NoSemanticClassifier(),
        )
