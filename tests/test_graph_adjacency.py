# tests/test_graph_adjacency.py

from __future__ import annotations

import networkx as nx

from app.core.graph_adjacency import (
    AdjacentEdge,
    GraphAdjacency,
    build_adjacency,
    build_graph_adjacency,
    get_edge_count,
    haversine_m,
)


def test_build_graph_adjacency_from_directed_graph_with_lengths():
    graph = nx.DiGraph()

    graph.add_node(1, y=26.44, x=80.30)
    graph.add_node(2, y=26.45, x=80.31)
    graph.add_node(3, y=26.46, x=80.32)

    graph.add_edge(1, 2, length=100.5)
    graph.add_edge(2, 3, length=200.75)
    graph.add_edge(1, 3, length=500.25)

    adjacency = build_graph_adjacency(graph)

    assert isinstance(adjacency, GraphAdjacency)
    assert adjacency.node_count == 3
    assert adjacency.edge_count == 3
    assert adjacency.directed is True
    assert adjacency.multigraph is False
    assert adjacency.build_time_ms >= 0

    assert adjacency.node_coordinates[1] == (26.44, 80.30)
    assert adjacency.node_coordinates[2] == (26.45, 80.31)
    assert adjacency.node_coordinates[3] == (26.46, 80.32)

    assert adjacency.neighbors(1) == [
        AdjacentEdge(neighbor=2, length_m=100.5),
        AdjacentEdge(neighbor=3, length_m=500.25),
    ]

    assert adjacency.neighbors(2) == [
        AdjacentEdge(neighbor=3, length_m=200.75),
    ]

    assert adjacency.neighbors(3) == []


def test_build_graph_adjacency_from_multidigraph_uses_shortest_parallel_edge():
    graph = nx.MultiDiGraph()

    graph.add_node(1, y=26.44, x=80.30)
    graph.add_node(2, y=26.45, x=80.31)

    graph.add_edge(1, 2, key=0, length=300.0)
    graph.add_edge(1, 2, key=1, length=150.0)
    graph.add_edge(1, 2, key=2, length=250.0)

    adjacency = build_graph_adjacency(graph)

    assert adjacency.node_count == 2
    assert adjacency.edge_count == 1
    assert adjacency.directed is True
    assert adjacency.multigraph is True

    assert adjacency.neighbors(1) == [
        AdjacentEdge(neighbor=2, length_m=150.0),
    ]


def test_build_graph_adjacency_from_undirected_graph():
    graph = nx.Graph()

    graph.add_node("A", y=26.44, x=80.30)
    graph.add_node("B", y=26.45, x=80.31)

    graph.add_edge("A", "B", length=123.0)

    adjacency = build_graph_adjacency(graph)

    assert adjacency.directed is False
    assert adjacency.multigraph is False

    # In an undirected graph, NetworkX neighbors expose both directions.
    assert adjacency.neighbors("A") == [
        AdjacentEdge(neighbor="B", length_m=123.0),
    ]
    assert adjacency.neighbors("B") == [
        AdjacentEdge(neighbor="A", length_m=123.0),
    ]

    assert adjacency.edge_count == 2


def test_build_graph_adjacency_uses_haversine_fallback_when_length_missing():
    graph = nx.DiGraph()

    graph.add_node(1, y=26.44, x=80.30)
    graph.add_node(2, y=26.45, x=80.31)

    graph.add_edge(1, 2)

    adjacency = build_graph_adjacency(graph)

    edges = adjacency.neighbors(1)

    assert len(edges) == 1
    assert edges[0].neighbor == 2
    assert edges[0].length_m > 0


def test_build_graph_adjacency_uses_one_meter_fallback_when_coordinates_missing():
    graph = nx.DiGraph()

    graph.add_node(1)
    graph.add_node(2)

    graph.add_edge(1, 2)

    adjacency = build_graph_adjacency(graph)

    assert adjacency.node_coordinates == {}
    assert adjacency.neighbors(1) == [
        AdjacentEdge(neighbor=2, length_m=1.0),
    ]


def test_build_graph_adjacency_keeps_nodes_with_no_edges():
    graph = nx.DiGraph()

    graph.add_node(1, y=26.44, x=80.30)
    graph.add_node(2, y=26.45, x=80.31)
    graph.add_node(3, y=26.46, x=80.32)

    graph.add_edge(1, 2, length=100.0)

    adjacency = build_graph_adjacency(graph)

    assert adjacency.node_count == 3
    assert 3 in adjacency.adjacency
    assert adjacency.neighbors(3) == []


def test_build_adjacency_alias_matches_main_builder():
    graph = nx.DiGraph()

    graph.add_node(1, y=26.44, x=80.30)
    graph.add_node(2, y=26.45, x=80.31)
    graph.add_edge(1, 2, length=100.0)

    adjacency_a = build_graph_adjacency(graph)
    adjacency_b = build_adjacency(graph)

    assert adjacency_a.adjacency == adjacency_b.adjacency
    assert adjacency_a.node_coordinates == adjacency_b.node_coordinates
    assert adjacency_a.node_count == adjacency_b.node_count
    assert adjacency_a.edge_count == adjacency_b.edge_count


def test_get_edge_count_counts_edges_from_adjacency_lists():
    graph = nx.DiGraph()

    graph.add_node(1, y=26.44, x=80.30)
    graph.add_node(2, y=26.45, x=80.31)
    graph.add_node(3, y=26.46, x=80.32)

    graph.add_edge(1, 2, length=100.0)
    graph.add_edge(1, 3, length=200.0)
    graph.add_edge(2, 3, length=300.0)

    adjacency = build_graph_adjacency(graph)

    assert get_edge_count(adjacency) == 3


def test_neighbors_returns_empty_list_for_unknown_node():
    graph = nx.DiGraph()

    graph.add_node(1, y=26.44, x=80.30)

    adjacency = build_graph_adjacency(graph)

    assert adjacency.neighbors("missing") == []


def test_haversine_distance_is_positive_for_different_coordinates():
    distance_m = haversine_m(
        26.44,
        80.30,
        26.45,
        80.31,
    )

    assert distance_m > 0


def test_haversine_distance_is_zero_for_same_coordinates():
    distance_m = haversine_m(
        26.44,
        80.30,
        26.44,
        80.30,
    )

    assert distance_m == 0