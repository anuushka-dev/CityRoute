from __future__ import annotations

from dataclasses import dataclass, field
from random import Random

UNREACHABLE_DISTANCE = -1.0


@dataclass(frozen=True)
class LNSIterationTrace:
    iteration: int
    best_distance_m: float
    candidate_distance_m: float
    improved: bool
    removed_count: int


@dataclass(frozen=True)
class LNSResult:
    optimized_order: list[int]
    total_distance_m: float
    initial_distance_m: float
    distance_saved_m: float
    improvement_pct: float
    iterations_run: int
    improvements_applied: int
    converged: bool
    random_seed: int | None
    trace: list[LNSIterationTrace] = field(default_factory=list)


def route_distance_m(
    order: list[int],
    distance_matrix: list[list[float]],
    *,
    depot_index: int = 0,
    return_to_start: bool = False,
) -> float:
    """Compute depot -> ordered stops -> optional depot distance."""

    if not order:
        return 0.0

    total = 0.0
    current = depot_index

    for stop in order:
        distance = distance_matrix[current][stop]
        if distance == UNREACHABLE_DISTANCE:
            return UNREACHABLE_DISTANCE

        total += distance
        current = stop

    if return_to_start:
        distance = distance_matrix[current][depot_index]
        if distance == UNREACHABLE_DISTANCE:
            return UNREACHABLE_DISTANCE

        total += distance

    return round(total, 3)


def cheapest_insertion_repair(
    partial_order: list[int],
    removed_stops: list[int],
    distance_matrix: list[list[float]],
    *,
    depot_index: int = 0,
    return_to_start: bool = False,
) -> list[int]:
    """Repair route by inserting removed stops at cheapest available positions."""

    repaired = partial_order.copy()

    for stop in removed_stops:
        best_position = 0
        best_distance = float("inf")

        for position in range(len(repaired) + 1):
            candidate = repaired[:position] + [stop] + repaired[position:]
            candidate_distance = route_distance_m(
                candidate,
                distance_matrix,
                depot_index=depot_index,
                return_to_start=return_to_start,
            )

            if candidate_distance != UNREACHABLE_DISTANCE and candidate_distance < best_distance:
                best_distance = candidate_distance
                best_position = position

        repaired.insert(best_position, stop)

    return repaired


def large_neighborhood_search(
    initial_order: list[int],
    distance_matrix: list[list[float]],
    *,
    depot_index: int = 0,
    return_to_start: bool = False,
    max_iterations: int = 500,
    destroy_fraction: float = 0.30,
    random_seed: int | None = None,
    no_improvement_limit: int = 100,
    keep_trace: bool = False,
) -> LNSResult:
    """
    Improve a stop order using destroy-and-repair Large Neighborhood Search.

    Matrix convention:
    - depot/start is index 0 by default
    - stops are matrix indices, usually 1..N
    - unreachable distance is represented by -1.0
    """

    if not initial_order:
        return LNSResult(
            optimized_order=[],
            total_distance_m=0.0,
            initial_distance_m=0.0,
            distance_saved_m=0.0,
            improvement_pct=0.0,
            iterations_run=0,
            improvements_applied=0,
            converged=True,
            random_seed=random_seed,
            trace=[],
        )

    if max_iterations < 1:
        raise ValueError("max_iterations must be >= 1")

    if not 0.0 < destroy_fraction <= 1.0:
        raise ValueError("destroy_fraction must be > 0 and <= 1")

    if no_improvement_limit < 1:
        raise ValueError("no_improvement_limit must be >= 1")

    rng = Random(random_seed)

    best_order = initial_order.copy()
    initial_distance = route_distance_m(
        best_order,
        distance_matrix,
        depot_index=depot_index,
        return_to_start=return_to_start,
    )

    if initial_distance == UNREACHABLE_DISTANCE:
        raise ValueError("initial_order contains unreachable route legs")

    best_distance = initial_distance
    trace: list[LNSIterationTrace] = []
    improvements_applied = 0
    no_improvement_count = 0
    iterations_run = 0

    remove_count = max(1, int(len(best_order) * destroy_fraction))

    for iteration in range(1, max_iterations + 1):
        iterations_run = iteration

        removed_positions = sorted(rng.sample(range(len(best_order)), remove_count), reverse=True)

        candidate_partial = best_order.copy()
        removed_stops: list[int] = []

        for position in removed_positions:
            removed_stops.append(candidate_partial.pop(position))

        rng.shuffle(removed_stops)

        candidate_order = cheapest_insertion_repair(
            candidate_partial,
            removed_stops,
            distance_matrix,
            depot_index=depot_index,
            return_to_start=return_to_start,
        )

        candidate_distance = route_distance_m(
            candidate_order,
            distance_matrix,
            depot_index=depot_index,
            return_to_start=return_to_start,
        )

        improved = candidate_distance != UNREACHABLE_DISTANCE and candidate_distance < best_distance

        if improved:
            best_order = candidate_order
            best_distance = candidate_distance
            improvements_applied += 1
            no_improvement_count = 0
        else:
            no_improvement_count += 1

        if keep_trace:
            trace.append(
                LNSIterationTrace(
                    iteration=iteration,
                    best_distance_m=round(best_distance, 3),
                    candidate_distance_m=round(candidate_distance, 3),
                    improved=improved,
                    removed_count=remove_count,
                )
            )

        if no_improvement_count >= no_improvement_limit:
            break

    distance_saved = round(initial_distance - best_distance, 3)
    improvement_pct = round((distance_saved / initial_distance) * 100, 3) if initial_distance else 0.0

    return LNSResult(
        optimized_order=best_order,
        total_distance_m=round(best_distance, 3),
        initial_distance_m=round(initial_distance, 3),
        distance_saved_m=distance_saved,
        improvement_pct=improvement_pct,
        iterations_run=iterations_run,
        improvements_applied=improvements_applied,
        converged=no_improvement_count >= no_improvement_limit,
        random_seed=random_seed,
        trace=trace,
    )