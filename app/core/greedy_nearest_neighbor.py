# app/core/greedy_nearest_neighbor.py

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from time import perf_counter


class GreedyMatrixError(ValueError):
    """Raised when the input distance matrix is invalid."""


@dataclass(frozen=True)
class GreedyLeg:

    from_matrix_index: int
    to_matrix_index: int
    distance_m: float


@dataclass(frozen=True)
class GreedyRouteResult:

    optimized_order: list[int]
    legs: list[GreedyLeg]
    total_distance_m: float
    optimization_time_ms: float


def _validate_square_matrix(distance_matrix: list[list[float | int | None]]) -> None:

    if not isinstance(distance_matrix, list):
        raise GreedyMatrixError("Distance matrix must be a list of rows.")

    if not distance_matrix:
        raise GreedyMatrixError("Distance matrix is empty.")

    matrix_size = len(distance_matrix)

    if matrix_size < 2:
        raise GreedyMatrixError(
            "At least one delivery stop is required. "
            "Matrix must contain start + at least one stop."
        )

    for row_index, row in enumerate(distance_matrix):
        if not isinstance(row, list):
            raise GreedyMatrixError(
                f"Distance matrix row {row_index} must be a list."
            )

        if len(row) != matrix_size:
            raise GreedyMatrixError(
                "Distance matrix must be square. "
                f"Expected row length {matrix_size}, got {len(row)} at row {row_index}."
            )

    for index in range(matrix_size):
        diagonal_value = distance_matrix[index][index]

        if diagonal_value is None:
            raise GreedyMatrixError(
                f"Distance matrix diagonal at index {index} cannot be None."
            )

        diagonal_distance = float(diagonal_value)

        if not isfinite(diagonal_distance):
            raise GreedyMatrixError(
                f"Distance matrix diagonal at index {index} must be finite."
            )

        if abs(diagonal_distance) > 0.01:
            raise GreedyMatrixError(
                "Distance matrix diagonal must be zero. "
                f"Found {diagonal_distance} at index {index}."
            )


def _read_distance(
    distance_matrix: list[list[float | int | None]],
    from_index: int,
    to_index: int,
) -> float:

    value = distance_matrix[from_index][to_index]

    if value is None:
        raise GreedyMatrixError(
            f"No path found from matrix index {from_index} to {to_index}."
        )

    distance = float(value)

    if not isfinite(distance):
        raise GreedyMatrixError(
            f"Non-finite distance from matrix index {from_index} to {to_index}."
        )

    if distance < 0:
        raise GreedyMatrixError(
            f"Negative distance from matrix index {from_index} to {to_index}."
        )

    return distance


def _select_nearest_unvisited(
    *,
    distance_matrix: list[list[float | int | None]],
    current_index: int,
    unvisited: set[int],
) -> tuple[int, float]:

    best_index: int | None = None
    best_distance: float | None = None

    for candidate_index in sorted(unvisited):
        candidate_distance = _read_distance(
            distance_matrix=distance_matrix,
            from_index=current_index,
            to_index=candidate_index,
        )

        if best_distance is None:
            best_distance = candidate_distance
            best_index = candidate_index
            continue

        if candidate_distance < best_distance:
            best_distance = candidate_distance
            best_index = candidate_index
            continue

        if candidate_distance == best_distance and best_index is not None:
            if candidate_index < best_index:
                best_index = candidate_index

    if best_index is None or best_distance is None:
        raise GreedyMatrixError(
            f"No reachable unvisited stop from matrix index {current_index}."
        )

    return best_index, best_distance


def solve_nearest_neighbor_greedy(
    *,
    distance_matrix: list[list[float | int | None]],
    return_to_start: bool = False,
) -> GreedyRouteResult:

    started_at = perf_counter()

    _validate_square_matrix(distance_matrix)

    matrix_size = len(distance_matrix)

    current_index = 0
    unvisited: set[int] = set(range(1, matrix_size))

    optimized_order: list[int] = []
    legs: list[GreedyLeg] = []
    total_distance_m = 0.0

    while unvisited:
        next_index, leg_distance_m = _select_nearest_unvisited(
            distance_matrix=distance_matrix,
            current_index=current_index,
            unvisited=unvisited,
        )

        legs.append(
            GreedyLeg(
                from_matrix_index=current_index,
                to_matrix_index=next_index,
                distance_m=round(leg_distance_m, 3),
            )
        )

        total_distance_m += leg_distance_m

        # Convert matrix index to user-facing stop index.
        optimized_order.append(next_index - 1)

        current_index = next_index
        unvisited.remove(next_index)

    if return_to_start:
        return_distance_m = _read_distance(
            distance_matrix=distance_matrix,
            from_index=current_index,
            to_index=0,
        )

        legs.append(
            GreedyLeg(
                from_matrix_index=current_index,
                to_matrix_index=0,
                distance_m=round(return_distance_m, 3),
            )
        )

        total_distance_m += return_distance_m

    optimization_time_ms = (perf_counter() - started_at) * 1000

    return GreedyRouteResult(
        optimized_order=optimized_order,
        legs=legs,
        total_distance_m=round(total_distance_m, 3),
        optimization_time_ms=round(optimization_time_ms, 3),
    )