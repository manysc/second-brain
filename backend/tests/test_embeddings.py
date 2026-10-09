"""embed_texts memoizes by exact text, so repeat texts never reach the model."""
from __future__ import annotations

import numpy as np
import pytest

from app import embeddings


class _CountingModel:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts: list[str], **_kwargs):
        self.calls.append(list(texts))
        return np.array([[float(len(text)), 1.0] for text in texts])


@pytest.fixture
def model(monkeypatch):
    fake = _CountingModel()
    monkeypatch.setattr(embeddings, "_model", lambda: fake)
    monkeypatch.setattr(embeddings, "_cache", embeddings.OrderedDict())
    return fake


def test_repeat_texts_are_served_from_the_cache(model):
    first = embeddings.embed_texts(["a", "bb"])
    second = embeddings.embed_texts(["bb", "ccc", "a", "ccc"])

    assert model.calls == [["a", "bb"], ["ccc"]]
    assert first == [[1.0, 1.0], [2.0, 1.0]]
    assert second == [[2.0, 1.0], [3.0, 1.0], [1.0, 1.0], [3.0, 1.0]]
    assert embeddings.embed_text("a") == [1.0, 1.0]
    assert len(model.calls) == 2


def test_mutating_a_result_does_not_touch_the_cache(model):
    embeddings.embed_texts(["a"])[0].append(99.0)
    assert embeddings.embed_text("a") == [1.0, 1.0]


def test_cache_evicts_least_recently_used(model, monkeypatch):
    monkeypatch.setattr(embeddings, "_CACHE_SIZE", 2)
    embeddings.embed_texts(["a", "b"])
    embeddings.embed_text("a")  # refreshes "a", so "b" is the oldest
    embeddings.embed_text("c")
    embeddings.embed_texts(["a", "b"])

    assert model.calls == [["a", "b"], ["c"], ["b"]]
