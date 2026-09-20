"""Integration tests for the /api/graph node/edge computation against a real Postgres+pgvector
instance. Auto-skips (module-scoped) if DATABASE_URL isn't reachable, mirroring test_topics.py.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import selectinload

from app import data, db
from app.db_models import KnowledgeItemRow


@pytest.fixture(scope="module")
def db_ready():
    try:
        db.init_db()
    except OperationalError:
        pytest.skip("Postgres is not reachable at DATABASE_URL; skipping DB integration tests")
    yield


def test_every_item_produces_a_node(db_ready):
    meetings = data.load_meetings()
    items = data.all_items(meetings)
    if not items:
        pytest.skip("no seeded knowledge items available")

    graph = data.build_graph()
    node_ids = {node.id for node in graph.nodes}
    assert node_ids == {item.id for item in items}


def test_related_ids_produce_related_edge(db_ready):
    with db.get_session() as session:
        rows = session.execute(
            select(KnowledgeItemRow).where(KnowledgeItemRow.related_ids != [])
        ).scalars().all()
    if not rows:
        pytest.skip("no seeded item has related_ids to exercise")
    source = rows[0]

    graph = data.build_graph()
    related_pair_edges = [
        edge for edge in graph.edges if edge.kind == "related" and source.id in (edge.source, edge.target)
    ]
    assert related_pair_edges, "expected at least one related edge for an item with related_ids"


def test_same_topic_items_produce_topic_edge(db_ready):
    with db.get_session() as session:
        stmt = select(KnowledgeItemRow).options(selectinload(KnowledgeItemRow.topic))
        rows = session.execute(stmt).scalars().all()
    groups: dict[str, list[str]] = {}
    for row in rows:
        if row.topic_id is None or row.topic is None or row.topic.name == "Uncategorized":
            continue
        groups.setdefault(row.topic_id, []).append(row.id)
    eligible = next((ids for ids in groups.values() if len(ids) >= 2), None)
    if eligible is None:
        pytest.skip("no non-Uncategorized topic with 2+ items available")

    graph = data.build_graph()
    a, b = eligible[0], eligible[1]
    assert any(
        edge.kind in ("related", "topic") and {edge.source, edge.target} == {a, b} for edge in graph.edges
    )


def test_impossible_semantic_threshold_yields_no_semantic_edges(db_ready):
    graph = data.build_graph(min_semantic_similarity=1.01)
    assert not any(edge.kind == "semantic" for edge in graph.edges)


def test_graph_topic_links_match_related_topics(db_ready):
    graph = data.build_graph()
    topic_ids = {topic.id for topic in graph.topics}
    assert all(link.source in topic_ids and link.target in topic_ids for link in graph.topic_links)

    for topic in graph.topics:
        expected = {related.id for related in data.related_topics(topic.id) or []}
        actual = {link.target for link in graph.topic_links if link.source == topic.id}
        assert actual == expected
