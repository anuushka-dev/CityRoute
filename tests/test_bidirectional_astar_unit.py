# tests/test_bidirectional_astar_unit.py

from __future__ import annotations

import networkx as nx
import pytest

from app.core.bidirectional_a_star import (
    BidirectionalAStarResult,
    bidirectional_a_star_shortest_path,
    bidirectional_astar_shortest_path,
)


def _add_node(graph: nx.Graph, node: str, *, lat: float = 26.44, lon: float = 80.30) -> None:
    graph.add_node(node, y=lat, x=lon)


def test_bidirectional_astar_returns_result_object_on_simple_directed_graph() -> None:
    graph = nx.DiGraph()

    _add_node(graph, "A")
    _add_node(graph, "B")
    _add_node(graph, "C")

    graph.add_edge("A", "B", length=100.0)
    graph.add_edge("B", "C", length=200.0)
    graph.add_edge("A", "C", length=1000.0)

    result = bidirectional_astar_shortest_path(graph, "A", "C")

    assert isinstance(result, BidirectionalAStarResult)
    assert result.path == ["A", "B", "C"]
    assert result.distance_m == 300.0
    assert result.nodes_expanded > 0
    assert result.route_time_ms >= 0
    assert result.meeting_node is not None


def test_bidirectional_astar_alias_function_works() -> None:
    graph = nx.DiGraph()

    _add_node(graph, "A")
    _add_node(graph, "B")

    graph.add_edge("A", "B", length=123.0)

    result = bidirectional_a_star_shortest_path(graph, "A", "B")

    assert result.path == ["A", "B"]
    assert result.distance_m == 123.0


def test_bidirectional_astar_returns_single_node_for_same_start_and_goal() -> None:
    graph = nx.DiGraph()

    _add_node(graph, "A")

    result = bidirectional_astar_shortest_path(graph, "A", "A")

    assert result.path == ["A"]
    assert result.distance_m == 0.0
    assert result.nodes_expanded == 0
    assert result.forward_nodes_expanded == 0
    assert result.backward_nodes_expanded == 0
    assert result.meeting_node == "A"


def test_bidirectional_astar_raises_for_missing_start_node() -> None:
    graph = nx.DiGraph()

    _add_node(graph, "B")

    with pytest.raises(nx.NodeNotFound, match="Start node A not found"):
        bidirectional_astar_shortest_path(graph, "A", "B")


def test_bidirectional_astar_raises_for_missing_goal_node() -> None:
    graph = nx.DiGraph()

    _add_node(graph, "A")

    with pytest.raises(nx.NodeNotFound, match="Goal node B not found"):
        bidirectional_astar_shortest_path(graph, "A", "B")


def test_bidirectional_astar_raises_no_path_on_disconnected_directed_graph() -> None:
    graph = nx.DiGraph()

    _add_node(graph, "A")
    _add_node(graph, "B")

    with pytest.raises(nx.NetworkXNoPath, match="No path found between A and B"):
        bidirectional_astar_shortest_path(graph, "A", "B")


def test_bidirectional_astar_respects_directed_edges() -> None:
    graph = nx.DiGraph()

    _add_node(graph, "A")
    _add_node(graph, "B")

    graph.add_edge("A", "B", length=100.0)

    forward_result = bidirectional_astar_shortest_path(graph, "A", "B")

    assert forward_result.path == ["A", "B"]
    assert forward_result.distance_m == 100.0

    with pytest.raises(nx.NetworkXNoPath):
        bidirectional_astar_shortest_path(graph, "B", "A")


def test_bidirectional_astar_prefers_shorter_indirect_path_over_longer_direct_path() -> None:
    graph = nx.DiGraph()

    _add_node(graph, "A")
    _add_node(graph, "B")
    _add_node(graph, "C")

    graph.add_edge("A", "C", length=1000.0)
    graph.add_edge("A", "B", length=100.0)
    graph.add_edge("B", "C", length=100.0)

    result = bidirectional_astar_shortest_path(graph, "A", "C")

    assert result.path == ["A", "B", "C"]
    assert result.distance_m == 200.0


def test_bidirectional_astar_uses_shortest_parallel_edge_on_multidigraph() -> None:
    graph = nx.MultiDiGraph()

    _add_node(graph, "A")
    _add_node(graph, "B")

    graph.add_edge("A", "B", length=500.0)
    graph.add_edge("A", "B", length=125.0)
    graph.add_edge("A", "B", length=300.0)

    result = bidirectional_astar_shortest_path(graph, "A", "B")

    assert result.path == ["A", "B"]
    assert result.distance_m == 125.0


def test_bidirectional_astar_falls_back_to_haversine_when_edge_length_missing() -> None:
    graph = nx.DiGraph()

    _add_node(graph, "A", lat=26.4400, lon=80.3000)
    _add_node(graph, "B", lat=26.4410, lon=80.3010)

    graph.add_edge("A", "B")

    result = bidirectional_astar_shortest_path(graph, "A", "B")

    assert result.path == ["A", "B"]
    assert result.distance_m > 0.0


def test_bidirectional_astar_handles_graph_without_coordinates() -> None:
    graph = nx.DiGraph()

    graph.add_node("A")
    graph.add_node("B")
    graph.add_node("C")

    graph.add_edge("A", "B", length=10.0)
    graph.add_edge("B", "C", length=15.0)

    result = bidirectional_astar_shortest_path(graph, "A", "C")

    assert result.path == ["A", "B", "C"]
    assert result.distance_m == 25.0


def test_bidirectional_astar_tracks_forward_and_backward_expansions() -> None:
    graph = nx.DiGraph()

    _add_node(graph, "A")
    _add_node(graph, "B")
    _add_node(graph, "C")
    _add_node(graph, "D")

    graph.add_edge("A", "B", length=100.0)
    graph.add_edge("B", "C", length=100.0)
    graph.add_edge("C", "D", length=100.0)

    result = bidirectional_astar_shortest_path(graph, "A", "D")

    assert result.path == ["A", "B", "C", "D"]
    assert result.distance_m == 300.0
    assert result.forward_nodes_expanded >= 0
    assert result.backward_nodes_expanded >= 0
    assert result.nodes_expanded == (
        result.forward_nodes_expanded + result.backward_nodes_expanded
    )