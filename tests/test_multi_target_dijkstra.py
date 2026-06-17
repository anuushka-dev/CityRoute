# tests/test_multi_target_dijkstra.py

from __future__ import annotations

import pytest

from app.core.graph_adjacency import AdjacentEdge, GraphAdjacency
from app.core.multi_target_dijkstra import (
    MultiTargetDijkstraResult,
    SourceDijkstraMatrixResult,
    build_source_dijkstra_matrix,
    count_computed_pairs,
    count_failed_pairs,
    multi_target_dijkstra,
)


def _sample_adjacency() -> GraphAdjacency:
    """
    Directed graph:

        A -> B = 2
        A -> C = 5
        B -> C = 1
        B -> D = 4
        C -> D = 1

    Shortest:
        A -> B = 2
        A -> C = 3 via B
        A -> D = 4 via B -> C
    """

    return GraphAdjacency(
        adjacency={
            "A": [
                AdjacentEdge(neighbor="B", length_m=2.0),
                AdjacentEdge(neighbor="C", length_m=5.0),
            ],
            "B": [
                AdjacentEdge(neighbor="C", length_m=1.0),
                AdjacentEdge(neighbor="D", length_m=4.0),
            ],
            "C": [
                AdjacentEdge(neighbor="D", length_m=1.0),
            ],
            "D": [],
        },
        node_coordinates={},
        node_count=4,
        edge_count=5,
        directed=True,
        multigraph=False,
        build_time_ms=1.0,
    )


def _disconnected_adjacency() -> GraphAdjacency:
    return GraphAdjacency(
        adjacency={
            "A": [
                AdjacentEdge(neighbor="B", length_m=10.0),
            ],
            "B": [],
            "X": [
                AdjacentEdge(neighbor="Y", length_m=20.0),
            ],
            "Y": [],
        },
        node_coordinates={},
        node_count=4,
        edge_count=2,
        directed=True,
        multigraph=False,
        build_time_ms=1.0,
    )


def test_multi_target_dijkstra_returns_shortest_distances():
    result = multi_target_dijkstra(
        adjacency=_sample_adjacency(),
        source_node="A",
        target_nodes={"B", "C", "D"},
    )

    assert isinstance(result, MultiTargetDijkstraResult)
    assert result.source_node == "A"

    assert result.target_distances_m["B"] == 2.0
    assert result.target_distances_m["C"] == 3.0
    assert result.target_distances_m["D"] == 4.0

    assert result.reached_target_count == 3
    assert result.unreachable_target_count == 0
    assert result.nodes_expanded > 0
    assert result.route_time_ms >= 0


def test_multi_target_dijkstra_supports_source_as_target():
    result = multi_target_dijkstra(
        adjacency=_sample_adjacency(),
        source_node="A",
        target_nodes={"A", "B"},
    )

    assert result.target_distances_m["A"] == 0.0
    assert result.target_distances_m["B"] == 2.0
    assert result.reached_target_count == 2
    assert result.unreachable_target_count == 0


def test_multi_target_dijkstra_marks_unreachable_targets_as_none():
    result = multi_target_dijkstra(
        adjacency=_disconnected_adjacency(),
        source_node="A",
        target_nodes={"B", "X", "Y"},
    )

    assert result.target_distances_m["B"] == 10.0
    assert result.target_distances_m["X"] is None
    assert result.target_distances_m["Y"] is None

    assert result.reached_target_count == 1
    assert result.unreachable_target_count == 2


def test_multi_target_dijkstra_empty_targets_returns_empty_result():
    result = multi_target_dijkstra(
        adjacency=_sample_adjacency(),
        source_node="A",
        target_nodes=set(),
    )

    assert result.source_node == "A"
    assert result.target_distances_m == {}
    assert result.nodes_expanded == 0
    assert result.reached_target_count == 0
    assert result.unreachable_target_count == 0


def test_multi_target_dijkstra_rejects_missing_source_node():
    with pytest.raises(ValueError) as exc_info:
        multi_target_dijkstra(
            adjacency=_sample_adjacency(),
            source_node="missing",
            target_nodes={"A"},
        )

    assert "Source node" in str(exc_info.value)
    assert "not present in adjacency" in str(exc_info.value)


def test_multi_target_dijkstra_rejects_missing_target_node():
    with pytest.raises(ValueError) as exc_info:
        multi_target_dijkstra(
            adjacency=_sample_adjacency(),
            source_node="A",
            target_nodes={"missing"},
        )

    assert "Target node" in str(exc_info.value)
    assert "not present in adjacency" in str(exc_info.value)


def test_multi_target_dijkstra_rejects_negative_edge_length():
    adjacency = GraphAdjacency(
        adjacency={
            "A": [
                AdjacentEdge(neighbor="B", length_m=-5.0),
            ],
            "B": [],
        },
        node_coordinates={},
        node_count=2,
        edge_count=1,
        directed=True,
        multigraph=False,
        build_time_ms=1.0,
    )

    with pytest.raises(ValueError) as exc_info:
        multi_target_dijkstra(
            adjacency=adjacency,
            source_node="A",
            target_nodes={"B"},
        )

    assert "Negative edge length" in str(exc_info.value)


def test_build_source_dijkstra_matrix_returns_valid_directed_matrix():
    result = build_source_dijkstra_matrix(
        adjacency=_sample_adjacency(),
        ordered_nodes=["A", "B", "C", "D"],
    )

    assert isinstance(result, SourceDijkstraMatrixResult)

    assert result.source_runs == 4
    assert result.nodes_expanded_total > 0
    assert result.total_time_ms >= 0

    assert result.matrix_distance_m == [
        [0.0, 2.0, 3.0, 4.0],
        [None, 0.0, 1.0, 2.0],
        [None, None, 0.0, 1.0],
        [None, None, None, 0.0],
    ]


def test_build_source_dijkstra_matrix_preserves_directionality():
    adjacency = GraphAdjacency(
        adjacency={
            "A": [
                AdjacentEdge(neighbor="B", length_m=10.0),
            ],
            "B": [
                AdjacentEdge(neighbor="A", length_m=30.0),
            ],
        },
        node_coordinates={},
        node_count=2,
        edge_count=2,
        directed=True,
        multigraph=False,
        build_time_ms=1.0,
    )

    result = build_source_dijkstra_matrix(
        adjacency=adjacency,
        ordered_nodes=["A", "B"],
    )

    assert result.matrix_distance_m == [
        [0.0, 10.0],
        [30.0, 0.0],
    ]


def test_build_source_dijkstra_matrix_handles_disconnected_components():
    result = build_source_dijkstra_matrix(
        adjacency=_disconnected_adjacency(),
        ordered_nodes=["A", "B", "X", "Y"],
    )

    assert result.matrix_distance_m == [
        [0.0, 10.0, None, None],
        [None, 0.0, None, None],
        [None, None, 0.0, 20.0],
        [None, None, None, 0.0],
    ]


def test_build_source_dijkstra_matrix_single_node():
    adjacency = GraphAdjacency(
        adjacency={
            "A": [],
        },
        node_coordinates={},
        node_count=1,
        edge_count=0,
        directed=True,
        multigraph=False,
        build_time_ms=1.0,
    )

    result = build_source_dijkstra_matrix(
        adjacency=adjacency,
        ordered_nodes=["A"],
    )

    assert result.matrix_distance_m == [[0.0]]
    assert result.source_runs == 1


def test_count_failed_pairs_ignores_diagonal_none():
    matrix = [
        [None, 10.0, None],
        [5.0, None, 2.0],
        [None, None, None],
    ]

    assert count_failed_pairs(matrix) == 3


def test_count_computed_pairs_counts_non_none_values_including_diagonal():
    matrix = [
        [0.0, 10.0, None],
        [5.0, 0.0, 2.0],
        [None, None, 0.0],
    ]

    assert count_computed_pairs(matrix) == 6


def test_source_dijkstra_matrix_counts_work_with_helper_functions():
    result = build_source_dijkstra_matrix(
        adjacency=_sample_adjacency(),
        ordered_nodes=["A", "B", "C", "D"],
    )

    assert count_computed_pairs(result.matrix_distance_m) == 10
    assert count_failed_pairs(result.matrix_distance_m) == 6