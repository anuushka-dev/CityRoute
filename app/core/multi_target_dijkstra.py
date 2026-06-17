# app/core/multi_target_dijkstra.py

from __future__ import annotations

import heapq
from dataclasses import dataclass
from math import inf
from time import perf_counter
from typing import Any

from app.core.graph_adjacency import GraphAdjacency


@dataclass(frozen=True)
class MultiTargetDijkstraResult:

    source_node: Any
    target_distances_m: dict[Any, float | None]
    nodes_expanded: int
    route_time_ms: float
    reached_target_count: int
    unreachable_target_count: int


@dataclass(frozen=True)
class SourceDijkstraMatrixResult:

    matrix_distance_m: list[list[float | None]]
    nodes_expanded_total: int
    source_runs: int
    total_time_ms: float


def multi_target_dijkstra(
    *,
    adjacency: GraphAdjacency,
    source_node: Any,
    target_nodes: set[Any],
) -> MultiTargetDijkstraResult:

    started_at = perf_counter()

    if source_node not in adjacency.adjacency:
        raise ValueError(f"Source node {source_node!r} is not present in adjacency.")

    clean_targets = set(target_nodes)

    if not clean_targets:
        return MultiTargetDijkstraResult(
            source_node=source_node,
            target_distances_m={},
            nodes_expanded=0,
            route_time_ms=round((perf_counter() - started_at) * 1000, 3),
            reached_target_count=0,
            unreachable_target_count=0,
        )

    for target_node in clean_targets:
        if target_node not in adjacency.adjacency:
            raise ValueError(f"Target node {target_node!r} is not present in adjacency.")

    distances: dict[Any, float] = {source_node: 0.0}
    finalized: set[Any] = set()

    target_distances: dict[Any, float | None] = {
        target_node: None for target_node in clean_targets
    }

    remaining_targets = set(clean_targets)

    heap: list[tuple[float, int, Any]] = []
    counter = 0

    heapq.heappush(heap, (0.0, counter, source_node))
    counter += 1

    nodes_expanded = 0

    while heap and remaining_targets:
        current_distance, _, current_node = heapq.heappop(heap)

        if current_node in finalized:
            continue

        finalized.add(current_node)
        nodes_expanded += 1

        if current_node in remaining_targets:
            target_distances[current_node] = round(current_distance, 3)
            remaining_targets.remove(current_node)

            if not remaining_targets:
                break

        for edge in adjacency.neighbors(current_node):
            if edge.length_m < 0:
                raise ValueError(
                    f"Negative edge length found: {current_node!r} -> "
                    f"{edge.neighbor!r} = {edge.length_m}"
                )

            neighbor = edge.neighbor

            if neighbor in finalized:
                continue

            candidate_distance = current_distance + edge.length_m

            if candidate_distance < distances.get(neighbor, inf):
                distances[neighbor] = candidate_distance
                heapq.heappush(heap, (candidate_distance, counter, neighbor))
                counter += 1

    reached_target_count = sum(
        value is not None for value in target_distances.values()
    )
    unreachable_target_count = len(target_distances) - reached_target_count

    route_time_ms = round((perf_counter() - started_at) * 1000, 3)

    return MultiTargetDijkstraResult(
        source_node=source_node,
        target_distances_m=target_distances,
        nodes_expanded=nodes_expanded,
        route_time_ms=route_time_ms,
        reached_target_count=reached_target_count,
        unreachable_target_count=unreachable_target_count,
    )


def build_source_dijkstra_matrix(
    *,
    adjacency: GraphAdjacency,
    ordered_nodes: list[Any],
) -> SourceDijkstraMatrixResult:

    started_at = perf_counter()

    n = len(ordered_nodes)

    matrix_distance_m: list[list[float | None]] = [
        [None for _ in range(n)] for _ in range(n)
    ]

    nodes_expanded_total = 0

    node_to_index = {
        node_id: index for index, node_id in enumerate(ordered_nodes)
    }

    for source_index, source_node in enumerate(ordered_nodes):
        matrix_distance_m[source_index][source_index] = 0.0

        target_nodes = set(ordered_nodes)
        target_nodes.discard(source_node)

        if not target_nodes:
            continue

        result = multi_target_dijkstra(
            adjacency=adjacency,
            source_node=source_node,
            target_nodes=target_nodes,
        )

        nodes_expanded_total += result.nodes_expanded

        for target_node, distance_m in result.target_distances_m.items():
            target_index = node_to_index[target_node]
            matrix_distance_m[source_index][target_index] = distance_m

    total_time_ms = round((perf_counter() - started_at) * 1000, 3)

    return SourceDijkstraMatrixResult(
        matrix_distance_m=matrix_distance_m,
        nodes_expanded_total=nodes_expanded_total,
        source_runs=n,
        total_time_ms=total_time_ms,
    )


def count_failed_pairs(matrix_distance_m: list[list[float | None]]) -> int:
    failed_pairs = 0

    for row_index, row in enumerate(matrix_distance_m):
        for col_index, value in enumerate(row):
            if row_index == col_index:
                continue

            if value is None:
                failed_pairs += 1

    return failed_pairs


def count_computed_pairs(matrix_distance_m: list[list[float | None]]) -> int:

    computed_pairs = 0

    for row in matrix_distance_m:
        for value in row:
            if value is not None:
                computed_pairs += 1

    return computed_pairs