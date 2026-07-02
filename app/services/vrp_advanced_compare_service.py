from __future__ import annotations

from dataclasses import asdict, is_dataclass
from time import perf_counter
from typing import Any

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from app.core.lns import large_neighborhood_search
from app.core.two_opt import (
    assert_two_opt_non_regression,
    calculate_route_distance_m,
    two_optimize,
)
from app.models.matrix_model import MatrixRequest
from app.schemas.vrp_advanced_compare import (
    AdvancedCompareRequest,
    AdvancedCompareResponse,
    AdvancedComparisonSummary,
    AdvancedGreedyResult,
    AdvancedLNSResult,
    AdvancedLNSTraceItem,
    AdvancedRouteLeg,
    AdvancedTwoOptResult,
    AdvancedTwoOptTraceItem,
)
from app.services.matrix_service import build_distance_matrix_response


class AdvancedCompareServiceError(RuntimeError):
    """Raised when Phase 8 advanced VRP comparison cannot be computed."""


def _elapsed_ms(start: float) -> float:
    return round((perf_counter() - start) * 1000.0, 3)


def _get_attr_or_key(obj: Any, name: str, default: Any = None) -> Any:
    if hasattr(obj, name):
        return getattr(obj, name)

    if isinstance(obj, dict):
        return obj.get(name, default)

    return default


def _distance_value(cell: Any) -> float:
    if isinstance(cell, int | float):
        return float(cell)

    if cell is None:
        return -1.0

    if hasattr(cell, "distance_m"):
        return float(cell.distance_m)

    if hasattr(cell, "distance_meters"):
        return float(cell.distance_meters)

    if hasattr(cell, "route_distance_m"):
        return float(cell.route_distance_m)

    if hasattr(cell, "total_distance_m"):
        return float(cell.total_distance_m)

    if isinstance(cell, dict):
        for key in (
            "distance_m",
            "distance_meters",
            "route_distance_m",
            "total_distance_m",
            "value",
        ):
            value = cell.get(key)
            if value is not None:
                return float(value)

    raise AdvancedCompareServiceError(f"Unsupported matrix cell format: {type(cell).__name__}")


def _normalize_distance_matrix(raw_matrix: Any) -> list[list[float]]:
    if not isinstance(raw_matrix, list) or not raw_matrix:
        raise AdvancedCompareServiceError("matrix response must contain a non-empty matrix list")

    normalized: list[list[float]] = []

    for row in raw_matrix:
        if not isinstance(row, list):
            raise AdvancedCompareServiceError("matrix response rows must be lists")

        normalized.append([_distance_value(cell) for cell in row])

    size = len(normalized)
    if any(len(row) != size for row in normalized):
        raise AdvancedCompareServiceError("distance matrix must be square")

    return normalized


def _extract_matrix(matrix_response: Any) -> list[list[float]]:
    for field_name in (
        "matrix_distance_m",
        "matrix",
        "distance_matrix",
        "distances",
        "distances_m",
        "distance_matrix_m",
        "distance_matrix_meters",
    ):
        raw_matrix = _get_attr_or_key(matrix_response, field_name)

        if raw_matrix is not None:
            return _normalize_distance_matrix(raw_matrix)

    raise AdvancedCompareServiceError(
        "matrix response does not contain distance matrix; "
        f"available_type={type(matrix_response).__name__}"
    )


def _matrix_locations(payload: AdvancedCompareRequest) -> list[dict[str, Any]]:
    locations: list[dict[str, Any]] = [
        {
            "id": "start",
            "lat": payload.start.lat,
            "lon": payload.start.lon,
        }
    ]

    for index, stop in enumerate(payload.stops):
        locations.append(
            {
                "id": f"stop_{index}",
                "lat": stop.lat,
                "lon": stop.lon,
            }
        )

    return locations


async def _build_matrix_response(
    request: Request,
    payload: AdvancedCompareRequest,
) -> Any:
    graph = getattr(request.app.state, "graph", None)
    snap_index = getattr(request.app.state, "snap_index", None)

    if graph is None:
        raise AdvancedCompareServiceError("Graph is required for matrix generation")

    if snap_index is None:
        raise AdvancedCompareServiceError("Snap index is required for matrix generation")

    matrix_payload: dict[str, Any] = {
        "locations": _matrix_locations(payload),
        "algorithm": payload.matrix_algorithm,
        "use_cache": payload.use_cache,
    }

    ttl_seconds = getattr(payload, "ttl_seconds", None)
    if ttl_seconds is not None:
        matrix_payload["ttl_seconds"] = ttl_seconds

    matrix_request = MatrixRequest(**matrix_payload)

    return await run_in_threadpool(
        build_distance_matrix_response,
        matrix_request,
        graph,
        snap_index,
    )


def _nearest_neighbor_order(
    distance_matrix: list[list[float]],
    *,
    stop_count: int,
) -> list[int]:
    """Return public stop indices: 0..stop_count-1."""

    unvisited = set(range(stop_count))
    order: list[int] = []
    current_matrix_index = 0

    while unvisited:
        best_stop: int | None = None
        best_distance = float("inf")

        for stop_index in unvisited:
            matrix_index = stop_index + 1
            distance = distance_matrix[current_matrix_index][matrix_index]

            if distance >= 0 and distance < best_distance:
                best_distance = distance
                best_stop = stop_index

        if best_stop is None:
            raise AdvancedCompareServiceError(
                "nearest-neighbor greedy cannot continue because remaining stops are unreachable"
            )

        order.append(best_stop)
        unvisited.remove(best_stop)
        current_matrix_index = best_stop + 1

    return order


def _build_legs(
    order: list[int],
    distance_matrix: list[list[float]],
    *,
    return_to_start: bool,
) -> list[AdvancedRouteLeg]:
    legs: list[AdvancedRouteLeg] = []

    current_matrix_index = 0
    current_type = "start"
    current_public_index: int | None = None

    for stop_index in order:
        next_matrix_index = stop_index + 1

        legs.append(
            AdvancedRouteLeg(
                from_type=current_type,
                from_index=current_public_index,
                to_type="stop",
                to_index=stop_index,
                distance_m=round(distance_matrix[current_matrix_index][next_matrix_index], 3),
            )
        )

        current_matrix_index = next_matrix_index
        current_type = "stop"
        current_public_index = stop_index

    if return_to_start and order:
        legs.append(
            AdvancedRouteLeg(
                from_type="stop",
                from_index=current_public_index,
                to_type="start",
                to_index=None,
                distance_m=round(distance_matrix[current_matrix_index][0], 3),
            )
        )

    return legs


def _public_to_matrix_order(order: list[int]) -> list[int]:
    return [stop_index + 1 for stop_index in order]


def _matrix_to_public_order(order: list[int]) -> list[int]:
    return [matrix_index - 1 for matrix_index in order]


def _distance_saved(before_m: float, after_m: float) -> float:
    return round(before_m - after_m, 3)


def _improvement_pct(before_m: float, after_m: float) -> float:
    if before_m <= 0:
        return 0.0

    return round(((before_m - after_m) / before_m) * 100.0, 3)


def _trace_to_dict(item: Any) -> dict[str, Any]:
    if is_dataclass(item):
        return asdict(item)

    if isinstance(item, dict):
        return item

    return {
        key: getattr(item, key)
        for key in dir(item)
        if not key.startswith("_") and not callable(getattr(item, key))
    }


def _two_opt_trace_items(two_opt_result: Any) -> list[AdvancedTwoOptTraceItem]:
    trace = getattr(two_opt_result, "convergence_trace", [])

    items: list[AdvancedTwoOptTraceItem] = []

    for item in trace:
        data = _trace_to_dict(item)

        best_distance = (
            data.get("best_distance_m")
            or data.get("distance_m")
            or data.get("route_distance_m")
            or data.get("optimized_distance_m")
            or getattr(two_opt_result, "optimized_distance_m")
        )

        items.append(
            AdvancedTwoOptTraceItem(
                iteration=int(data.get("iteration", len(items))),
                best_distance_m=round(float(best_distance), 3),
                improved=bool(data.get("improved", False)),
            )
        )

    return items


async def build_advanced_compare_response(
    request: Request,
    payload: AdvancedCompareRequest,
) -> AdvancedCompareResponse:
    total_start = perf_counter()

    matrix_response = await _build_matrix_response(request, payload)
    distance_matrix = _extract_matrix(matrix_response)

    stop_count = len(payload.stops)

    matrix_generation_time_ms = float(
        _get_attr_or_key(matrix_response, "generation_time_ms", 0.0)
        or _get_attr_or_key(matrix_response, "matrix_generation_time_ms", 0.0)
        or _get_attr_or_key(matrix_response, "total_time_ms", 0.0)
        or 0.0
    )

    cache_payload = _get_attr_or_key(matrix_response, "cache", {}) or {}

    cache_used = bool(
        _get_attr_or_key(matrix_response, "cache_used", None)
        if _get_attr_or_key(matrix_response, "cache_used", None) is not None
        else _get_attr_or_key(cache_payload, "enabled", False)
    )

    cache_hit = bool(_get_attr_or_key(cache_payload, "hit", False))
    cache_status = _get_attr_or_key(matrix_response, "cache_status", None)

    if cache_status is None:
        cache_status = "hit" if cache_hit else "miss"

    cache_hits = int(_get_attr_or_key(matrix_response, "cache_hits", 0) or int(cache_hit))
    cache_misses = int(
    _get_attr_or_key(matrix_response, "cache_misses", 0) or int(not cache_hit)
    )

    greedy_start = perf_counter()
    greedy_order = _nearest_neighbor_order(distance_matrix, stop_count=stop_count)
    greedy_distance_m = calculate_route_distance_m(
        greedy_order,
        distance_matrix,
        return_to_start=payload.return_to_start,
    )
    greedy_time_ms = _elapsed_ms(greedy_start)

    two_opt_start = perf_counter()
    two_opt_result = two_optimize(
        greedy_order,
        distance_matrix,
        return_to_start=payload.return_to_start,
        max_iterations=payload.two_opt_max_iterations,
        improvement_tolerance_m=payload.two_opt_improvement_tolerance_m,
        keep_trace=payload.keep_trace,
    )
    two_opt_time_ms = _elapsed_ms(two_opt_start)

    try:
        assert_two_opt_non_regression(two_opt_result)
    except AssertionError as exc:
        raise AdvancedCompareServiceError(str(exc)) from exc

    two_opt_order = list(two_opt_result.optimized_order)
    two_opt_distance_m = float(two_opt_result.optimized_distance_m)

    lns_start = perf_counter()
    lns_result = large_neighborhood_search(
        initial_order=_public_to_matrix_order(two_opt_order),
        distance_matrix=distance_matrix,
        depot_index=0,
        return_to_start=payload.return_to_start,
        max_iterations=payload.lns_max_iterations,
        destroy_fraction=payload.lns_destroy_fraction,
        random_seed=payload.lns_random_seed,
        no_improvement_limit=payload.lns_no_improvement_limit,
        keep_trace=payload.keep_trace,
    )
    lns_time_ms = _elapsed_ms(lns_start)

    lns_order = _matrix_to_public_order(lns_result.optimized_order)
    lns_distance_m = float(lns_result.total_distance_m)

    return AdvancedCompareResponse(
        status="ok",
        phase="tier3_phase8",
        matrix_algorithm=payload.matrix_algorithm,
        stop_count=stop_count,
        return_to_start=payload.return_to_start,
        greedy=AdvancedGreedyResult(
            algorithm="nearest_neighbor_greedy",
            optimized_order=greedy_order,
            total_distance_m=round(float(greedy_distance_m), 3),
            legs=_build_legs(
                greedy_order,
                distance_matrix,
                return_to_start=payload.return_to_start,
            ),
            optimization_time_ms=greedy_time_ms,
        ),
        two_opt=AdvancedTwoOptResult(
            algorithm="two_opt",
            optimized_order=two_opt_order,
            total_distance_m=round(two_opt_distance_m, 3),
            initial_distance_m=round(float(two_opt_result.initial_distance_m), 3),
            distance_saved_m=round(float(two_opt_result.improvement_m), 3),
            improvement_pct=round(float(two_opt_result.improvement_pct), 3),
            iterations_run=int(two_opt_result.iterations),
            swaps_applied=int(two_opt_result.swaps_applied),
            converged=bool(two_opt_result.converged),
            legs=_build_legs(
                two_opt_order,
                distance_matrix,
                return_to_start=payload.return_to_start,
            ),
            optimization_time_ms=two_opt_time_ms,
            trace=_two_opt_trace_items(two_opt_result),
        ),
        lns=AdvancedLNSResult(
            algorithm="large_neighborhood_search",
            optimized_order=lns_order,
            total_distance_m=round(lns_distance_m, 3),
            initial_distance_m=round(float(lns_result.initial_distance_m), 3),
            distance_saved_m=round(float(lns_result.distance_saved_m), 3),
            improvement_pct=round(float(lns_result.improvement_pct), 3),
            iterations_run=int(lns_result.iterations_run),
            improvements_applied=int(lns_result.improvements_applied),
            converged=bool(lns_result.converged),
            random_seed=lns_result.random_seed,
            legs=_build_legs(
                lns_order,
                distance_matrix,
                return_to_start=payload.return_to_start,
            ),
            optimization_time_ms=lns_time_ms,
            trace=[
                AdvancedLNSTraceItem(
                    iteration=int(item.iteration),
                    best_distance_m=round(float(item.best_distance_m), 3),
                    candidate_distance_m=round(float(item.candidate_distance_m), 3),
                    improved=bool(item.improved),
                    removed_count=int(item.removed_count),
                )
                for item in lns_result.trace
            ],
        ),
        comparison=AdvancedComparisonSummary(
            two_opt_vs_greedy_distance_saved_m=_distance_saved(
                float(greedy_distance_m),
                two_opt_distance_m,
            ),
            two_opt_vs_greedy_improvement_pct=_improvement_pct(
                float(greedy_distance_m),
                two_opt_distance_m,
            ),
            lns_vs_two_opt_distance_saved_m=_distance_saved(
                two_opt_distance_m,
                lns_distance_m,
            ),
            lns_vs_two_opt_improvement_pct=_improvement_pct(
                two_opt_distance_m,
                lns_distance_m,
            ),
            lns_vs_greedy_distance_saved_m=_distance_saved(
                float(greedy_distance_m),
                lns_distance_m,
            ),
            lns_vs_greedy_improvement_pct=_improvement_pct(
                float(greedy_distance_m),
                lns_distance_m,
            ),
            two_opt_non_regression=two_opt_distance_m <= float(greedy_distance_m),
            lns_non_regression=lns_distance_m <= two_opt_distance_m,
        ),
        matrix_generation_time_ms=round(matrix_generation_time_ms, 3),
        cache_used=cache_used,
        cache_status=cache_status,
        cache_hits=cache_hits,
        cache_misses=cache_misses,
        total_time_ms=_elapsed_ms(total_start),
    )