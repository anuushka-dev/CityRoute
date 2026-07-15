# app/core/multi_target_dijkstra.py

from __future__ import annotations

import heapq
import math
from collections.abc import Sequence
from dataclasses import dataclass
from math import inf
from time import perf_counter
from typing import Any

from app.core.graph_adjacency import (
    AdjacentEdge,
    GraphAdjacency,
)


@dataclass(frozen=True)
class MultiTargetDijkstraResult:

    source_node: Any

    # target node -> road distance in meters
    #
    # None means that the target exists in the graph but is unreachable from
    # the source under the graph's directed traversal rules.
    target_distances_m: dict[
        Any,
        float | None,
    ]

    nodes_expanded: int
    route_time_ms: float

    reached_target_count: int
    unreachable_target_count: int

    @property
    def requested_target_count(
        self,
    ) -> int:
        return len(
            self.target_distances_m
        )

    @property
    def all_targets_reached(
        self,
    ) -> bool:
        return (
            self.unreachable_target_count
            == 0
        )


@dataclass(frozen=True)
class SourceDijkstraMatrixResult:

    matrix_distance_m: list[
        list[
            float | None
        ]
    ]

    nodes_expanded_total: int
    source_runs: int
    total_time_ms: float

    @property
    def matrix_size(
        self,
    ) -> int:
        return len(
            self.matrix_distance_m
        )


def multi_target_dijkstra(
    *,
    adjacency: GraphAdjacency,
    source_node: Any,
    target_nodes: set[Any],
) -> MultiTargetDijkstraResult:

    started_at = perf_counter()

    _validate_adjacency(
        adjacency
    )

    _validate_node_exists(
        adjacency=adjacency,
        node=source_node,
        role="Source",
    )

    clean_targets = set(
        target_nodes
    )

    if not clean_targets:
        return MultiTargetDijkstraResult(
            source_node=source_node,
            target_distances_m={},
            nodes_expanded=0,
            route_time_ms=_elapsed_ms(
                started_at
            ),
            reached_target_count=0,
            unreachable_target_count=0,
        )

    for target_node in clean_targets:
        _validate_node_exists(
            adjacency=adjacency,
            node=target_node,
            role="Target",
        )

    # Best currently known distance for discovered nodes.
    distances: dict[
        Any,
        float,
    ] = {
        source_node: 0.0,
    }

    # Nodes whose globally shortest distance has already been finalized.
    finalized: set[
        Any
    ] = set()

    # Preserve every requested target in the final response.
    #
    # Targets that remain None after the heap is exhausted are unreachable.
    target_distances: dict[
        Any,
        float | None,
    ] = {
        target_node: None
        for target_node
        in clean_targets
    }

    remaining_targets = set(
        clean_targets
    )

    # Counter prevents Python from comparing graph node objects when two
    # heap entries have identical distance values.
    heap: list[
        tuple[
            float,
            int,
            Any,
        ]
    ] = []

    counter = 0

    heapq.heappush(
        heap,
        (
            0.0,
            counter,
            source_node,
        ),
    )

    counter += 1

    nodes_expanded = 0

    while (
        heap
        and remaining_targets
    ):
        (
            current_distance,
            _,
            current_node,
        ) = heapq.heappop(
            heap
        )

        if (
            current_node
            in finalized
        ):
            continue

        # Defensive stale-entry check.
        #
        # Usually the finalized set already protects this, but this also
        # guards against an obsolete heap entry before finalization.
        best_known_distance = (
            distances.get(
                current_node,
                inf,
            )
        )

        if (
            current_distance
            > best_known_distance
        ):
            continue

        finalized.add(
            current_node
        )

        nodes_expanded += 1

        # Dijkstra guarantees that the first finalized distance for this
        # target is globally optimal.
        if (
            current_node
            in remaining_targets
        ):
            target_distances[
                current_node
            ] = round(
                current_distance,
                3,
            )

            remaining_targets.remove(
                current_node
            )

            if not remaining_targets:
                break

        for edge in adjacency.neighbors(
            current_node
        ):
            edge_length_m = (
                _validate_edge(
                    edge=edge,
                    current_node=current_node,
                )
            )

            neighbor = (
                edge.neighbor
            )

            if (
                neighbor
                in finalized
            ):
                continue

            candidate_distance = (
                current_distance
                + edge_length_m
            )

            if not math.isfinite(
                candidate_distance
            ):
                raise ValueError(
                    "Non-finite candidate distance produced for "
                    f"{current_node!r} -> {neighbor!r}."
                )

            if (
                candidate_distance
                < distances.get(
                    neighbor,
                    inf,
                )
            ):
                distances[
                    neighbor
                ] = (
                    candidate_distance
                )

                heapq.heappush(
                    heap,
                    (
                        candidate_distance,
                        counter,
                        neighbor,
                    ),
                )

                counter += 1

    reached_target_count = sum(
        value is not None
        for value
        in target_distances.values()
    )

    unreachable_target_count = (
        len(
            target_distances
        )
        - reached_target_count
    )

    return MultiTargetDijkstraResult(
        source_node=source_node,
        target_distances_m=target_distances,
        nodes_expanded=nodes_expanded,
        route_time_ms=_elapsed_ms(
            started_at
        ),
        reached_target_count=(
            reached_target_count
        ),
        unreachable_target_count=(
            unreachable_target_count
        ),
    )


def build_source_dijkstra_matrix(
    *,
    adjacency: GraphAdjacency,
    ordered_nodes: list[Any],
) -> SourceDijkstraMatrixResult:

    started_at = perf_counter()

    _validate_adjacency(
        adjacency
    )

    normalized_nodes = list(
        ordered_nodes
    )

    node_count = len(
        normalized_nodes
    )

    matrix_distance_m: list[
        list[
            float | None
        ]
    ] = [
        [
            None
            for _ in range(
                node_count
            )
        ]
        for _ in range(
            node_count
        )
    ]

    if not normalized_nodes:
        return SourceDijkstraMatrixResult(
            matrix_distance_m=[],
            nodes_expanded_total=0,
            source_runs=0,
            total_time_ms=_elapsed_ms(
                started_at
            ),
        )

    # Validate every requested node once before starting expensive searches.
    for node_id in set(
        normalized_nodes
    ):
        _validate_node_exists(
            adjacency=adjacency,
            node=node_id,
            role="Matrix",
        )

    # One graph node may appear in multiple matrix positions.
    node_to_indices: dict[
        Any,
        list[int],
    ] = {}

    for (
        index,
        node_id,
    ) in enumerate(
        normalized_nodes
    ):
        node_to_indices.setdefault(
            node_id,
            [],
        ).append(
            index
        )

    unique_nodes = set(
        normalized_nodes
    )

    nodes_expanded_total = 0

    # Preserve the existing CityRoute contract:
    #
    # source_runs == number of matrix rows
    #
    # even when duplicate graph node IDs appear.
    source_runs = node_count

    for (
        source_index,
        source_node,
    ) in enumerate(
        normalized_nodes
    ):
        # Distance from one graph node to every duplicate occurrence of the
        # same node is exactly zero.
        for same_node_index in (
            node_to_indices[
                source_node
            ]
        ):
            matrix_distance_m[
                source_index
            ][
                same_node_index
            ] = 0.0

        target_nodes = set(
            unique_nodes
        )

        target_nodes.discard(
            source_node
        )

        if not target_nodes:
            continue

        result = (
            multi_target_dijkstra(
                adjacency=adjacency,
                source_node=source_node,
                target_nodes=target_nodes,
            )
        )

        nodes_expanded_total += (
            result.nodes_expanded
        )

        for (
            target_node,
            distance_m,
        ) in (
            result
            .target_distances_m
            .items()
        ):
            # Fill every matrix column representing this same graph node.
            for target_index in (
                node_to_indices[
                    target_node
                ]
            ):
                matrix_distance_m[
                    source_index
                ][
                    target_index
                ] = distance_m

    return SourceDijkstraMatrixResult(
        matrix_distance_m=(
            matrix_distance_m
        ),
        nodes_expanded_total=(
            nodes_expanded_total
        ),
        source_runs=source_runs,
        total_time_ms=_elapsed_ms(
            started_at
        ),
    )


def count_failed_pairs(
    matrix_distance_m: Sequence[
        Sequence[
            float | None
        ]
    ],
) -> int:

    failed_pairs = 0

    for (
        row_index,
        row,
    ) in enumerate(
        matrix_distance_m
    ):
        for (
            col_index,
            value,
        ) in enumerate(
            row
        ):
            if (
                row_index
                == col_index
            ):
                continue

            if value is None:
                failed_pairs += 1

    return failed_pairs


def count_computed_pairs(
    matrix_distance_m: Sequence[
        Sequence[
            float | None
        ]
    ],
) -> int:

    return sum(
        1
        for row
        in matrix_distance_m
        for value
        in row
        if value is not None
    )


def _validate_adjacency(
    adjacency: GraphAdjacency,
) -> None:

    if adjacency is None:
        raise ValueError(
            "adjacency must not be None."
        )

    if not hasattr(
        adjacency,
        "adjacency",
    ):
        raise TypeError(
            "adjacency must expose an adjacency mapping."
        )

    if not hasattr(
        adjacency,
        "neighbors",
    ):
        raise TypeError(
            "adjacency must expose neighbors(node)."
        )


def _validate_node_exists(
    *,
    adjacency: GraphAdjacency,
    node: Any,
    role: str,
) -> None:
    if (
        node
        not in adjacency.adjacency
    ):
        raise ValueError(
            f"{role} node {node!r} "
            "is not present in adjacency."
        )


def _validate_edge(
    *,
    edge: AdjacentEdge,
    current_node: Any,
) -> float:
    try:
        edge_length_m = float(
            edge.length_m
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as exc:
        raise ValueError(
            "Invalid edge length found: "
            f"{current_node!r} -> "
            f"{edge.neighbor!r} = "
            f"{edge.length_m!r}"
        ) from exc

    if not math.isfinite(
        edge_length_m
    ):
        raise ValueError(
            "Non-finite edge length found: "
            f"{current_node!r} -> "
            f"{edge.neighbor!r} = "
            f"{edge_length_m}"
        )

    if edge_length_m < 0:
        raise ValueError(
            "Negative edge length found: "
            f"{current_node!r} -> "
            f"{edge.neighbor!r} = "
            f"{edge_length_m}"
        )

    return edge_length_m


def _elapsed_ms(
    started_at: float,
) -> float:
    return round(
        (
            perf_counter()
            - started_at
        )
        * 1000.0,
        3,
    )


__all__ = [
    "MultiTargetDijkstraResult",
    "SourceDijkstraMatrixResult",
    "build_source_dijkstra_matrix",
    "count_computed_pairs",
    "count_failed_pairs",
    "multi_target_dijkstra",
]