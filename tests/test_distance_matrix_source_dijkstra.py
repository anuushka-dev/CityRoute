# tests/test_distance_matrix_source_dijkstra.py

from __future__ import annotations

from typing import Any

import networkx as nx

from app.core.distance_matrix import build_distance_matrix
from app.utils.snap_index import build_snap_index


def _small_route_graph() -> nx.DiGraph:
    """
    Small directed graph with GPS coordinates.

    Edges:
        1 -> 2 = 10
        2 -> 3 = 20
        1 -> 3 = 50
        3 -> 1 = 15

    Shortest matrix:
        1 -> 1 = 0
        1 -> 2 = 10
        1 -> 3 = 30 via 2

        2 -> 1 = 35 via 3
        2 -> 2 = 0
        2 -> 3 = 20

        3 -> 1 = 15
        3 -> 2 = 25 via 1
        3 -> 3 = 0
    """

    graph = nx.DiGraph()

    graph.add_node(1, y=26.4400, x=80.3000)
    graph.add_node(2, y=26.4401, x=80.3001)
    graph.add_node(3, y=26.4402, x=80.3002)

    graph.add_edge(1, 2, length=10.0)
    graph.add_edge(2, 3, length=20.0)
    graph.add_edge(1, 3, length=50.0)
    graph.add_edge(3, 1, length=15.0)

    return graph


def _disconnected_route_graph() -> nx.DiGraph:
    graph = nx.DiGraph()

    graph.add_node(1, y=26.4400, x=80.3000)
    graph.add_node(2, y=26.4401, x=80.3001)
    graph.add_node(3, y=26.4500, x=80.3100)
    graph.add_node(4, y=26.4501, x=80.3101)

    graph.add_edge(1, 2, length=10.0)
    graph.add_edge(3, 4, length=20.0)

    return graph


def _locations() -> list[Any]:
    """
    Use objects that behave like MatrixLocation enough for build_distance_matrix.

    We intentionally use the real app model in most production tests, but this
    helper keeps this file focused on source_dijkstra matrix behavior.
    """

    from app.models.matrix_model import MatrixLocation

    return [
        MatrixLocation(id="node_1", lat=26.4400, lon=80.3000),
        MatrixLocation(id="node_2", lat=26.4401, lon=80.3001),
        MatrixLocation(id="node_3", lat=26.4402, lon=80.3002),
    ]


def test_source_dijkstra_distance_matrix_returns_expected_shortest_paths():
    graph = _small_route_graph()
    snap_index = build_snap_index(graph)

    result = build_distance_matrix(
        locations=_locations(),
        graph=graph,
        snap_index=snap_index,
        algorithm="source_dijkstra",
        workers=8,
    )

    assert result.pair_count == 9
    assert result.computed_pairs == 9
    assert result.failed_pairs == 0
    assert result.failures == []

    assert result.matrix_distance_m == [
        [0.0, 10.0, 30.0],
        [35.0, 0.0, 20.0],
        [15.0, 25.0, 0.0],
    ]

    assert result.matrix_eta_s[0][0] == 0.0
    assert result.matrix_eta_s[1][1] == 0.0
    assert result.matrix_eta_s[2][2] == 0.0

    assert result.matrix_eta_s[0][1] > 0
    assert result.matrix_eta_s[0][2] > result.matrix_eta_s[0][1]


def test_source_dijkstra_preserves_directed_asymmetry():
    graph = _small_route_graph()
    snap_index = build_snap_index(graph)

    result = build_distance_matrix(
        locations=_locations(),
        graph=graph,
        snap_index=snap_index,
        algorithm="source_dijkstra",
        workers=8,
    )

    assert result.matrix_distance_m[0][2] == 30.0
    assert result.matrix_distance_m[2][0] == 15.0
    assert result.matrix_distance_m[0][2] != result.matrix_distance_m[2][0]


def test_source_dijkstra_handles_unreachable_pairs_as_failures():
    from app.models.matrix_model import MatrixLocation

    graph = _disconnected_route_graph()
    snap_index = build_snap_index(graph)

    locations = [
        MatrixLocation(id="node_1", lat=26.4400, lon=80.3000),
        MatrixLocation(id="node_2", lat=26.4401, lon=80.3001),
        MatrixLocation(id="node_3", lat=26.4500, lon=80.3100),
        MatrixLocation(id="node_4", lat=26.4501, lon=80.3101),
    ]

    result = build_distance_matrix(
        locations=locations,
        graph=graph,
        snap_index=snap_index,
        algorithm="source_dijkstra",
        workers=8,
    )

    assert result.pair_count == 16
    assert result.matrix_distance_m[0][0] == 0.0
    assert result.matrix_distance_m[0][1] == 10.0
    assert result.matrix_distance_m[0][2] is None
    assert result.matrix_distance_m[0][3] is None

    assert result.matrix_distance_m[2][3] == 20.0
    assert result.matrix_distance_m[2][0] is None

    assert result.failed_pairs > 0
    assert len(result.failures) == result.failed_pairs

    failure_pairs = {
        (failure.from_id, failure.to_id)
        for failure in result.failures
    }

    assert ("node_1", "node_3") in failure_pairs
    assert ("node_3", "node_1") in failure_pairs


def test_source_dijkstra_single_location_matrix():
    from app.models.matrix_model import MatrixLocation

    graph = _small_route_graph()
    snap_index = build_snap_index(graph)

    locations = [
        MatrixLocation(id="node_1", lat=26.4400, lon=80.3000),
    ]

    result = build_distance_matrix(
        locations=locations,
        graph=graph,
        snap_index=snap_index,
        algorithm="source_dijkstra",
        workers=8,
    )

    assert result.pair_count == 1
    assert result.computed_pairs == 1
    assert result.failed_pairs == 0
    assert result.matrix_distance_m == [[0.0]]
    assert result.matrix_eta_s == [[0.0]]
    assert result.failures == []


def test_source_dijkstra_matches_bidirectional_astar_on_small_graph():
    graph = _small_route_graph()
    snap_index = build_snap_index(graph)

    source_result = build_distance_matrix(
        locations=_locations(),
        graph=graph,
        snap_index=snap_index,
        algorithm="source_dijkstra",
        workers=8,
    )

    bidirectional_result = build_distance_matrix(
        locations=_locations(),
        graph=graph,
        snap_index=snap_index,
        algorithm="bidirectional_astar",
        workers=8,
    )

    assert source_result.matrix_distance_m == bidirectional_result.matrix_distance_m
    assert source_result.failed_pairs == bidirectional_result.failed_pairs
    assert source_result.failures == bidirectional_result.failures