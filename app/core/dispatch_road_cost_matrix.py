# app/core/dispatch_road_cost_matrix.py

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import TypeAlias

NodeId: TypeAlias = int

DistanceValue: TypeAlias = float | int | None

SourceDistanceRow: TypeAlias = (
    Mapping[NodeId, DistanceValue]
    | Sequence[DistanceValue]
)

SourceDistanceBuilder: TypeAlias = Callable[
    [NodeId, Sequence[NodeId]],
    SourceDistanceRow,
]


class RoadDispatchMatrixError(ValueError):
    """Raised when a real-road dispatch matrix cannot be built safely."""


@dataclass(frozen=True)
class UnreachableRoadPair:
    """
    One driver-to-order pair for which no directed road path was found.
    """

    driver_index: int
    order_index: int
    driver_node: NodeId
    order_node: NodeId
    replacement_cost_m: float


@dataclass(frozen=True)
class RoadDispatchCostMatrixResult:

    cost_matrix_m: tuple[tuple[float, ...], ...]
    reachable_matrix: tuple[tuple[bool, ...], ...]

    driver_nodes: tuple[NodeId, ...]
    order_nodes: tuple[NodeId, ...]

    driver_count: int
    order_count: int

    unique_driver_node_count: int
    unique_order_node_count: int
    source_search_count: int

    reachable_pair_count: int
    unreachable_pair_count: int
    unreachable_pairs: tuple[UnreachableRoadPair, ...]

    unreachable_cost_m: float
    build_time_ms: float

    @property
    def pair_count(self) -> int:
        return self.driver_count * self.order_count

    @property
    def all_pairs_reachable(self) -> bool:
        return self.unreachable_pair_count == 0

    def cost_at(
        self,
        driver_index: int,
        order_index: int,
    ) -> float:
        return self.cost_matrix_m[driver_index][order_index]

    def is_reachable(
        self,
        driver_index: int,
        order_index: int,
    ) -> bool:
        return self.reachable_matrix[driver_index][order_index]


def build_dispatch_road_cost_matrix(
    *,
    driver_nodes: Sequence[NodeId],
    order_nodes: Sequence[NodeId],
    source_distance_builder: SourceDistanceBuilder,
    unreachable_cost_m: float = 1_000_000_000.0,
) -> RoadDispatchCostMatrixResult:

    started_at = perf_counter()

    normalized_driver_nodes = _validate_node_sequence(
        name="driver_nodes",
        nodes=driver_nodes,
    )
    normalized_order_nodes = _validate_node_sequence(
        name="order_nodes",
        nodes=order_nodes,
    )

    _validate_unreachable_cost(unreachable_cost_m)

    if not callable(source_distance_builder):
        raise TypeError("source_distance_builder must be callable.")

    unique_driver_nodes = _unique_preserving_order(normalized_driver_nodes)
    unique_order_nodes = _unique_preserving_order(normalized_order_nodes)

    distances_by_source: dict[NodeId, dict[NodeId, float | None]] = {}

    for source_node in unique_driver_nodes:
        try:
            raw_row = source_distance_builder(
                source_node,
                unique_order_nodes,
            )
        except Exception as exc:
            raise RoadDispatchMatrixError(
                "Road-distance builder failed for "
                f"source_node={source_node}: {exc}"
            ) from exc

        distances_by_source[source_node] = _normalize_source_distance_row(
            source_node=source_node,
            target_nodes=unique_order_nodes,
            raw_row=raw_row,
        )

    cost_matrix: list[tuple[float, ...]] = []
    reachable_matrix: list[tuple[bool, ...]] = []
    unreachable_pairs: list[UnreachableRoadPair] = []

    reachable_pair_count = 0

    for driver_index, driver_node in enumerate(normalized_driver_nodes):
        source_distances = distances_by_source[driver_node]

        cost_row: list[float] = []
        reachable_row: list[bool] = []

        for order_index, order_node in enumerate(normalized_order_nodes):
            distance_m = source_distances[order_node]

            if distance_m is None:
                cost_row.append(float(unreachable_cost_m))
                reachable_row.append(False)

                unreachable_pairs.append(
                    UnreachableRoadPair(
                        driver_index=driver_index,
                        order_index=order_index,
                        driver_node=driver_node,
                        order_node=order_node,
                        replacement_cost_m=float(unreachable_cost_m),
                    )
                )
                continue

            cost_row.append(distance_m)
            reachable_row.append(True)
            reachable_pair_count += 1

        cost_matrix.append(tuple(cost_row))
        reachable_matrix.append(tuple(reachable_row))

    unreachable_pair_count = len(unreachable_pairs)

    return RoadDispatchCostMatrixResult(
        cost_matrix_m=tuple(cost_matrix),
        reachable_matrix=tuple(reachable_matrix),
        driver_nodes=normalized_driver_nodes,
        order_nodes=normalized_order_nodes,
        driver_count=len(normalized_driver_nodes),
        order_count=len(normalized_order_nodes),
        unique_driver_node_count=len(unique_driver_nodes),
        unique_order_node_count=len(unique_order_nodes),
        source_search_count=len(unique_driver_nodes),
        reachable_pair_count=reachable_pair_count,
        unreachable_pair_count=unreachable_pair_count,
        unreachable_pairs=tuple(unreachable_pairs),
        unreachable_cost_m=float(unreachable_cost_m),
        build_time_ms=_elapsed_ms(started_at),
    )


def _normalize_source_distance_row(
    *,
    source_node: NodeId,
    target_nodes: Sequence[NodeId],
    raw_row: SourceDistanceRow,
) -> dict[NodeId, float | None]:

    normalized: dict[NodeId, float | None] = {}

    if isinstance(raw_row, Mapping):
        for target_node in target_nodes:
            if source_node == target_node:
                normalized[target_node] = 0.0
                continue

            normalized[target_node] = _normalize_distance_value(
                value=raw_row.get(target_node),
                source_node=source_node,
                target_node=target_node,
            )

        return normalized

    if isinstance(raw_row, (str, bytes, bytearray)):
        raise RoadDispatchMatrixError(
            "source_distance_builder returned an invalid sequence type."
        )

    if not isinstance(raw_row, Sequence):
        raise RoadDispatchMatrixError(
            "source_distance_builder must return either a mapping "
            "or a sequence of distances."
        )

    if len(raw_row) != len(target_nodes):
        raise RoadDispatchMatrixError(
            "source_distance_builder returned the wrong number of distances: "
            f"expected={len(target_nodes)}, actual={len(raw_row)}, "
            f"source_node={source_node}."
        )

    for target_node, raw_distance in zip(
        target_nodes,
        raw_row,
        strict=True,
    ):
        if source_node == target_node:
            normalized[target_node] = 0.0
            continue

        normalized[target_node] = _normalize_distance_value(
            value=raw_distance,
            source_node=source_node,
            target_node=target_node,
        )

    return normalized


def _normalize_distance_value(
    *,
    value: DistanceValue,
    source_node: NodeId,
    target_node: NodeId,
) -> float | None:

    if value is None:
        return None

    if isinstance(value, bool):
        raise RoadDispatchMatrixError(
            "Road distance must be numeric, not bool: "
            f"source_node={source_node}, target_node={target_node}."
        )

    try:
        distance_m = float(value)
    except (TypeError, ValueError) as exc:
        raise RoadDispatchMatrixError(
            "Road distance is not numeric: "
            f"source_node={source_node}, "
            f"target_node={target_node}, "
            f"value={value!r}."
        ) from exc

    if math.isnan(distance_m):
        raise RoadDispatchMatrixError(
            "Road distance cannot be NaN: "
            f"source_node={source_node}, target_node={target_node}."
        )

    if math.isinf(distance_m):
        if distance_m > 0:
            return None

        raise RoadDispatchMatrixError(
            "Road distance cannot be negative infinity: "
            f"source_node={source_node}, target_node={target_node}."
        )

    if distance_m < 0:
        raise RoadDispatchMatrixError(
            "Road distance cannot be negative: "
            f"source_node={source_node}, "
            f"target_node={target_node}, "
            f"distance_m={distance_m}."
        )

    return distance_m


def _validate_node_sequence(
    *,
    name: str,
    nodes: Sequence[NodeId],
) -> tuple[NodeId, ...]:
    if isinstance(nodes, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be a sequence of graph node IDs.")

    normalized = tuple(nodes)

    if not normalized:
        raise ValueError(f"{name} must contain at least one graph node.")

    for index, node in enumerate(normalized):
        if isinstance(node, bool) or not isinstance(node, int):
            raise TypeError(
                f"{name}[{index}] must be an int graph node ID; "
                f"received {type(node).__name__}."
            )

    return normalized


def _validate_unreachable_cost(unreachable_cost_m: float) -> None:
    if isinstance(unreachable_cost_m, bool):
        raise TypeError("unreachable_cost_m must be numeric.")

    try:
        normalized = float(unreachable_cost_m)
    except (TypeError, ValueError) as exc:
        raise TypeError("unreachable_cost_m must be numeric.") from exc

    if not math.isfinite(normalized):
        raise ValueError("unreachable_cost_m must be finite.")

    if normalized <= 0:
        raise ValueError("unreachable_cost_m must be greater than zero.")


def _unique_preserving_order(
    nodes: Sequence[NodeId],
) -> tuple[NodeId, ...]:
    return tuple(dict.fromkeys(nodes))


def _elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000.0, 6)