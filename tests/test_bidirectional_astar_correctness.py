# tests/test_bidirectional_astar_correctness.py

from __future__ import annotations

from math import isclose

import networkx as nx
from fastapi.testclient import TestClient

from app.core.a_star import astar_shortest_path
from app.core.bidirectional_a_star import bidirectional_astar_shortest_path
from app.main import app


DISTANCE_TOLERANCE_M = 1e-3


def _dijkstra_weight(u, v, edge_data) -> float:
    """
    Match CityRoute edge-length behavior.

    For OSMnx MultiDiGraph, NetworkX gives edge_data like:
    {
        0: {"length": 50.0},
        1: {"length": 40.0}
    }

    CityRoute A* chooses the shortest parallel edge.
    This Dijkstra test oracle must do the same.
    """
    if not edge_data:
        return 0.0

    if all(isinstance(value, dict) for value in edge_data.values()):
        lengths = [
            float(attrs["length"])
            for attrs in edge_data.values()
            if "length" in attrs
        ]
        return min(lengths) if lengths else 0.0

    return float(edge_data.get("length", 0.0))


def _assert_same_distance(
    *,
    astar_distance: float,
    bidirectional_distance: float,
    dijkstra_distance: float,
) -> None:
    assert isclose(
        bidirectional_distance,
        astar_distance,
        rel_tol=0,
        abs_tol=DISTANCE_TOLERANCE_M,
    )

    assert isclose(
        bidirectional_distance,
        dijkstra_distance,
        rel_tol=0,
        abs_tol=DISTANCE_TOLERANCE_M,
    )


def test_bidirectional_astar_matches_astar_and_dijkstra_for_known_docker_route_nodes() -> None:
    """
    Known Phase 3 Docker route evidence:

    start input: 26.44, 80.30
    end input:   26.45, 80.35

    snapped start node: 5317312245
    snapped end node:   6288159135
    """
    with TestClient(app) as client:
        graph = client.app.state.graph

        start_node = 5317312245
        end_node = 6288159135

        assert start_node in graph
        assert end_node in graph

        astar_result = astar_shortest_path(graph, start_node, end_node)
        bidirectional_result = bidirectional_astar_shortest_path(
            graph,
            start_node,
            end_node,
        )

        dijkstra_distance = nx.shortest_path_length(
            graph,
            source=start_node,
            target=end_node,
            weight=_dijkstra_weight,
        )

        assert bidirectional_result.path[0] == start_node
        assert bidirectional_result.path[-1] == end_node
        assert bidirectional_result.distance_m > 0
        assert bidirectional_result.nodes_expanded > 0
        assert bidirectional_result.route_time_ms >= 0
        assert bidirectional_result.meeting_node is not None

        _assert_same_distance(
            astar_distance=astar_result.distance_m,
            bidirectional_distance=bidirectional_result.distance_m,
            dijkstra_distance=dijkstra_distance,
        )


def test_bidirectional_astar_matches_astar_and_dijkstra_on_deterministic_real_graph_pairs() -> None:
    """
    Deterministic real-graph correctness check.

    This avoids random flakes while still testing multiple real road-graph pairs.
    No-path pairs are valid in a directed road graph, so they are skipped here.
    """
    with TestClient(app) as client:
        graph = client.app.state.graph
        nodes = list(graph.nodes)

        assert len(nodes) > 12000

        index_pairs = [
            (10, 500),
            (100, 1000),
            (250, 2500),
            (700, 3000),
            (1200, 4500),
            (2000, 6500),
            (3500, 8000),
            (5000, 10000),
            (7500, 12000),
            (9000, 11000),
        ]

        checked = 0
        skipped_no_path = 0

        for start_index, end_index in index_pairs:
            start_node = nodes[start_index]
            end_node = nodes[end_index]

            try:
                astar_result = astar_shortest_path(
                    graph,
                    start_node,
                    end_node,
                )

                bidirectional_result = bidirectional_astar_shortest_path(
                    graph,
                    start_node,
                    end_node,
                )

                dijkstra_distance = nx.shortest_path_length(
                    graph,
                    source=start_node,
                    target=end_node,
                    weight=_dijkstra_weight,
                )

            except nx.NetworkXNoPath:
                skipped_no_path += 1
                continue

            assert bidirectional_result.path[0] == start_node
            assert bidirectional_result.path[-1] == end_node
            assert bidirectional_result.distance_m >= 0
            assert bidirectional_result.nodes_expanded >= 0
            assert bidirectional_result.forward_nodes_expanded >= 0
            assert bidirectional_result.backward_nodes_expanded >= 0
            assert bidirectional_result.nodes_expanded == (
                bidirectional_result.forward_nodes_expanded
                + bidirectional_result.backward_nodes_expanded
            )

            _assert_same_distance(
                astar_distance=astar_result.distance_m,
                bidirectional_distance=bidirectional_result.distance_m,
                dijkstra_distance=dijkstra_distance,
            )

            checked += 1

        assert checked >= 5
        assert skipped_no_path >= 0


def test_bidirectional_astar_same_start_goal_matches_astar_on_real_graph() -> None:
    with TestClient(app) as client:
        graph = client.app.state.graph
        node = list(graph.nodes)[100]

        astar_result = astar_shortest_path(graph, node, node)
        bidirectional_result = bidirectional_astar_shortest_path(graph, node, node)

        assert astar_result.path == [node]
        assert bidirectional_result.path == [node]
        assert astar_result.distance_m == 0.0
        assert bidirectional_result.distance_m == 0.0
        assert bidirectional_result.nodes_expanded == 0