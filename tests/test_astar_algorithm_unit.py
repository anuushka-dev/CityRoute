# tests/test_astar_algorithm_unit.py

from math import isclose

import networkx as nx
import pytest

from app.core.a_star import astar_shortest_path, haversine_m


def _add_node(graph: nx.Graph, node: int, lat: float = 0.0, lon: float = 0.0) -> None:
    graph.add_node(node, y=lat, x=lon)


def test_haversine_zero_distance():
    distance = haversine_m(26.44, 80.30, 26.44, 80.30)

    assert distance == 0.0


def test_haversine_positive_distance():
    distance = haversine_m(26.44, 80.30, 26.45, 80.35)

    assert distance > 0


def test_astar_finds_shortest_path_on_simple_directed_graph():
    graph = nx.DiGraph()

    # Same coordinates keep heuristic = 0, so this unit test checks pure path logic.
    _add_node(graph, 1)
    _add_node(graph, 2)
    _add_node(graph, 3)
    _add_node(graph, 4)

    graph.add_edge(1, 2, length=10.0)
    graph.add_edge(2, 4, length=10.0)
    graph.add_edge(1, 3, length=100.0)
    graph.add_edge(3, 4, length=1.0)

    result = astar_shortest_path(graph, 1, 4)

    assert result.path == [1, 2, 4]
    assert result.distance_m == 20.0
    assert result.nodes_expanded > 0
    assert result.route_time_ms >= 0


def test_astar_returns_single_node_for_same_start_and_goal():
    graph = nx.DiGraph()
    _add_node(graph, 1, 26.44, 80.30)

    result = astar_shortest_path(graph, 1, 1)

    assert result.path == [1]
    assert result.distance_m == 0.0
    assert result.nodes_expanded == 0
    assert result.route_time_ms >= 0


def test_astar_raises_for_missing_start_node():
    graph = nx.DiGraph()
    _add_node(graph, 1)

    with pytest.raises(nx.NodeNotFound):
        astar_shortest_path(graph, 999, 1)


def test_astar_raises_for_missing_goal_node():
    graph = nx.DiGraph()
    _add_node(graph, 1)

    with pytest.raises(nx.NodeNotFound):
        astar_shortest_path(graph, 1, 999)


def test_astar_raises_no_path_on_disconnected_directed_graph():
    graph = nx.DiGraph()

    _add_node(graph, 1)
    _add_node(graph, 2)
    _add_node(graph, 3)

    graph.add_edge(1, 2, length=10.0)

    with pytest.raises(nx.NetworkXNoPath):
        astar_shortest_path(graph, 1, 3)


def test_astar_respects_directed_edges():
    graph = nx.DiGraph()

    _add_node(graph, 1)
    _add_node(graph, 2)

    graph.add_edge(1, 2, length=10.0)

    result = astar_shortest_path(graph, 1, 2)

    assert result.path == [1, 2]
    assert result.distance_m == 10.0

    with pytest.raises(nx.NetworkXNoPath):
        astar_shortest_path(graph, 2, 1)


def test_astar_uses_shortest_parallel_edge_on_multidigraph():
    graph = nx.MultiDiGraph()

    _add_node(graph, 1)
    _add_node(graph, 2)
    _add_node(graph, 3)

    graph.add_edge(1, 2, length=50.0)
    graph.add_edge(1, 2, length=10.0)
    graph.add_edge(2, 3, length=5.0)

    result = astar_shortest_path(graph, 1, 3)

    assert result.path == [1, 2, 3]
    assert result.distance_m == 15.0


def test_astar_falls_back_to_haversine_when_edge_length_missing():
    graph = nx.DiGraph()

    _add_node(graph, 1, 26.44, 80.30)
    _add_node(graph, 2, 26.4401, 80.3001)

    graph.add_edge(1, 2)

    result = astar_shortest_path(graph, 1, 2)
    expected_distance = haversine_m(26.44, 80.30, 26.4401, 80.3001)

    assert result.path == [1, 2]
    assert result.distance_m > 0
    assert isclose(result.distance_m, expected_distance, abs_tol=0.001)


def test_astar_updates_to_better_path_when_found_later():
    graph = nx.DiGraph()

    _add_node(graph, 1)
    _add_node(graph, 2)
    _add_node(graph, 3)
    _add_node(graph, 4)

    graph.add_edge(1, 2, length=100.0)
    graph.add_edge(1, 3, length=10.0)
    graph.add_edge(3, 2, length=10.0)
    graph.add_edge(2, 4, length=10.0)
    graph.add_edge(3, 4, length=100.0)

    result = astar_shortest_path(graph, 1, 4)

    assert result.path == [1, 3, 2, 4]
    assert result.distance_m == 30.0
