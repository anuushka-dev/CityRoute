# tests/test_astar_edge_cases.py

from math import isclose

import networkx as nx
import pytest

from app.core.a_star import astar_shortest_path, haversine_m


def _add_node(graph: nx.MultiDiGraph, node: int, lat: float, lon: float) -> None:
    graph.add_node(node, y=lat, x=lon)


def test_astar_same_start_and_goal_returns_zero_distance():
    graph = nx.MultiDiGraph()
    _add_node(graph, 1, 26.44, 80.30)

    result = astar_shortest_path(graph, 1, 1)

    assert result.path == [1]
    assert result.distance_m == 0.0
    assert result.nodes_expanded == 0
    assert result.route_time_ms >= 0


def test_astar_raises_node_not_found_for_missing_start_node():
    graph = nx.MultiDiGraph()
    _add_node(graph, 1, 26.44, 80.30)

    with pytest.raises(nx.NodeNotFound):
        astar_shortest_path(graph, 999, 1)


def test_astar_raises_node_not_found_for_missing_goal_node():
    graph = nx.MultiDiGraph()
    _add_node(graph, 1, 26.44, 80.30)

    with pytest.raises(nx.NodeNotFound):
        astar_shortest_path(graph, 1, 999)


def test_astar_raises_no_path_for_disconnected_directed_graph():
    graph = nx.MultiDiGraph()

    _add_node(graph, 1, 26.44, 80.30)
    _add_node(graph, 2, 26.441, 80.301)
    _add_node(graph, 3, 26.45, 80.35)
    _add_node(graph, 4, 26.451, 80.351)

    graph.add_edge(1, 2, length=100.0)
    graph.add_edge(3, 4, length=100.0)

    with pytest.raises(nx.NetworkXNoPath):
        astar_shortest_path(graph, 1, 4)


def test_astar_prefers_shorter_indirect_path_over_longer_direct_path():
    graph = nx.MultiDiGraph()

    _add_node(graph, 1, 0.0, 0.0)
    _add_node(graph, 2, 0.0, 0.001)
    _add_node(graph, 3, 0.0, 0.0005)

    graph.add_edge(1, 2, length=200.0)
    graph.add_edge(1, 3, length=60.0)
    graph.add_edge(3, 2, length=60.0)

    result = astar_shortest_path(graph, 1, 2)

    assert result.path == [1, 3, 2]
    assert isclose(result.distance_m, 120.0, rel_tol=0, abs_tol=1e-9)


def test_astar_uses_shortest_parallel_edge_in_multidigraph():
    graph = nx.MultiDiGraph()

    _add_node(graph, 1, 0.0, 0.0)
    _add_node(graph, 2, 0.0, 0.001)

    graph.add_edge(1, 2, length=250.0)
    graph.add_edge(1, 2, length=100.0)

    result = astar_shortest_path(graph, 1, 2)

    assert result.path == [1, 2]
    assert isclose(result.distance_m, 100.0, rel_tol=0, abs_tol=1e-9)


def test_haversine_returns_zero_for_same_coordinate():
    assert haversine_m(26.44, 80.30, 26.44, 80.30) == 0.0


def test_haversine_returns_positive_for_different_coordinates():
    distance = haversine_m(26.44, 80.30, 26.45, 80.35)

    assert distance > 0