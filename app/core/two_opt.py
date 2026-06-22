# app/core/two_opt.py

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Sequence


DistanceMatrix = Sequence[Sequence[float]]


@dataclass(frozen=True)
class TwoOptIteration:
    iteration: int
    distance_m: float
    improved: bool
    swap_i: int | None = None
    swap_j: int | None = None


@dataclass(frozen=True)
class TwoOptResult:
    initial_order: list[int]
    optimized_order: list[int]

    initial_distance_m: float
    optimized_distance_m: float

    improvement_m: float
    improvement_pct: float
    improved: bool

    iterations: int
    swaps_applied: int
    converged: bool
    return_to_start: bool

    convergence_trace: list[TwoOptIteration] = field(default_factory=list)


def _validate_distance_matrix(distance_matrix: DistanceMatrix) -> None:
    if not distance_matrix:
        raise ValueError("distance_matrix must not be empty")

    size = len(distance_matrix)

    for row_index, row in enumerate(distance_matrix):
        if len(row) != size:
            raise ValueError(
                f"distance_matrix must be square: row {row_index} has "
                f"length {len(row)}, expected {size}"
            )

        for col_index, value in enumerate(row):
            if not isinstance(value, (int, float)):
                raise ValueError(
                    f"distance_matrix[{row_index}][{col_index}] must be numeric"
                )

            if not isfinite(float(value)):
                raise ValueError(
                    f"distance_matrix[{row_index}][{col_index}] must be finite"
                )


def _validate_order(
    order: Sequence[int],
    distance_matrix: DistanceMatrix,
    depot_index: int,
) -> None:
    matrix_size = len(distance_matrix)
    stop_count = matrix_size - 1

    if depot_index != 0:
        raise ValueError("Phase 7 expects depot_index=0")

    if not order:
        raise ValueError("order must contain at least one stop")

    if len(order) != len(set(order)):
        raise ValueError("order must not contain duplicate stops")

    for stop_index in order:
        if not isinstance(stop_index, int):
            raise ValueError("all stop indices must be integers")

        if stop_index < 0 or stop_index >= stop_count:
            raise ValueError(
                f"stop index {stop_index} is out of range for {stop_count} stops"
            )


def _stop_to_matrix_index(stop_index: int) -> int:

    return stop_index + 1


def _edge_distance(
    distance_matrix: DistanceMatrix,
    from_matrix_index: int,
    to_matrix_index: int,
) -> float:
    distance = float(distance_matrix[from_matrix_index][to_matrix_index])

    if distance < 0:
        raise ValueError(
            "distance_matrix contains unreachable edge "
            f"{from_matrix_index}->{to_matrix_index}: {distance}"
        )

    return distance


def calculate_route_distance_m(
    order: Sequence[int],
    distance_matrix: DistanceMatrix,
    *,
    return_to_start: bool = False,
    depot_index: int = 0,
) -> float:

    _validate_distance_matrix(distance_matrix)
    _validate_order(order, distance_matrix, depot_index)

    total_distance = 0.0

    first_stop_matrix_index = _stop_to_matrix_index(order[0])
    total_distance += _edge_distance(
        distance_matrix,
        depot_index,
        first_stop_matrix_index,
    )

    for previous_stop, current_stop in zip(order, order[1:]):
        previous_matrix_index = _stop_to_matrix_index(previous_stop)
        current_matrix_index = _stop_to_matrix_index(current_stop)

        total_distance += _edge_distance(
            distance_matrix,
            previous_matrix_index,
            current_matrix_index,
        )

    if return_to_start:
        last_stop_matrix_index = _stop_to_matrix_index(order[-1])
        total_distance += _edge_distance(
            distance_matrix,
            last_stop_matrix_index,
            depot_index,
        )

    return round(total_distance, 3)


def _two_opt_swap(order: Sequence[int], i: int, j: int) -> list[int]:
    return list(order[:i]) + list(reversed(order[i : j + 1])) + list(order[j + 1 :])


def two_optimize(
    initial_order: Sequence[int],
    distance_matrix: DistanceMatrix,
    *,
    return_to_start: bool = False,
    max_iterations: int = 100,
    improvement_tolerance_m: float = 0.001,
    depot_index: int = 0,
    keep_trace: bool = True,
) -> TwoOptResult:

    if max_iterations <= 0:
        raise ValueError("max_iterations must be greater than 0")

    if improvement_tolerance_m < 0:
        raise ValueError("improvement_tolerance_m must be non-negative")

    _validate_distance_matrix(distance_matrix)
    _validate_order(initial_order, distance_matrix, depot_index)

    current_order = list(initial_order)
    best_distance = calculate_route_distance_m(
        current_order,
        distance_matrix,
        return_to_start=return_to_start,
        depot_index=depot_index,
    )

    initial_distance = best_distance
    swaps_applied = 0
    convergence_trace: list[TwoOptIteration] = []

    if keep_trace:
        convergence_trace.append(
            TwoOptIteration(
                iteration=0,
                distance_m=best_distance,
                improved=False,
            )
        )

    stop_count = len(current_order)
    converged = False

    for iteration in range(1, max_iterations + 1):
        best_candidate_order = current_order
        best_candidate_distance = best_distance
        best_swap_i: int | None = None
        best_swap_j: int | None = None

        # Keep the depot fixed. The depot is not inside order.
        # For open routes, the final stop may change.
        # For return-to-start routes, the final depot leg is included in distance.
        for i in range(0, stop_count - 1):
            for j in range(i + 1, stop_count):
                candidate_order = _two_opt_swap(current_order, i, j)

                candidate_distance = calculate_route_distance_m(
                    candidate_order,
                    distance_matrix,
                    return_to_start=return_to_start,
                    depot_index=depot_index,
                )

                improvement = best_candidate_distance - candidate_distance

                if improvement > improvement_tolerance_m:
                    best_candidate_order = candidate_order
                    best_candidate_distance = candidate_distance
                    best_swap_i = i
                    best_swap_j = j

        if best_swap_i is None or best_swap_j is None:
            converged = True

            if keep_trace:
                convergence_trace.append(
                    TwoOptIteration(
                        iteration=iteration,
                        distance_m=best_distance,
                        improved=False,
                    )
                )

            break

        current_order = best_candidate_order
        best_distance = best_candidate_distance
        swaps_applied += 1

        if keep_trace:
            convergence_trace.append(
                TwoOptIteration(
                    iteration=iteration,
                    distance_m=best_distance,
                    improved=True,
                    swap_i=best_swap_i,
                    swap_j=best_swap_j,
                )
            )

    optimized_distance = best_distance
    improvement_m = round(initial_distance - optimized_distance, 3)

    if improvement_m < improvement_tolerance_m:
        improvement_m = 0.0

    improvement_pct = (
        round((improvement_m / initial_distance) * 100.0, 3)
        if initial_distance > 0
        else 0.0
    )

    return TwoOptResult(
        initial_order=list(initial_order),
        optimized_order=current_order,
        initial_distance_m=round(initial_distance, 3),
        optimized_distance_m=round(optimized_distance, 3),
        improvement_m=improvement_m,
        improvement_pct=improvement_pct,
        improved=improvement_m > 0,
        iterations=len(convergence_trace) - 1 if keep_trace else swaps_applied,
        swaps_applied=swaps_applied,
        converged=converged,
        return_to_start=return_to_start,
        convergence_trace=convergence_trace,
    )


def assert_two_opt_non_regression(result: TwoOptResult) -> None:

    if result.optimized_distance_m > result.initial_distance_m:
        raise AssertionError(
            "2-Opt regression detected: "
            f"initial={result.initial_distance_m}, "
            f"optimized={result.optimized_distance_m}"
        )