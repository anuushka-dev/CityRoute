# app/services/greedy_service.py

from __future__ import annotations

from time import perf_counter
from typing import Any

from fastapi import Request

from app.core.greedy_nearest_neighbor import (
    GreedyMatrixError,
    solve_nearest_neighbor_greedy,
)
from app.models.matrix_model import MatrixLocation, MatrixRequest
from app.schemas.vrp import (
    Coordinate,
    GreedyLegResponse,
    GreedyRouteRequest,
    GreedyRouteResponse,
)
from app.services.matrix_service import build_distance_matrix_response


class GreedyServiceError(ValueError):
    """Raised when the greedy service receives invalid input or invalid matrix output."""


class GreedyNoPathError(RuntimeError):
    """Raised when the matrix contains unreachable legs required by greedy ordering."""


def _coordinate_to_dict(coord: Coordinate) -> dict[str, float]:
    return {
        "lat": coord.lat,
        "lon": coord.lon,
    }


def _extract_cache_hit(cache_metadata: Any) -> bool | None:
    """
    Extract cache hit status from Phase 5 cache metadata.

    Expected Phase 5 cache shape:
    {
        "enabled": true,
        "hit": true/false,
        ...
    }
    """

    if cache_metadata is None:
        return None

    if isinstance(cache_metadata, dict):
        hit = cache_metadata.get("hit")
        if hit is None:
            return None
        return bool(hit)

    if hasattr(cache_metadata, "model_dump"):
        cache_dict = cache_metadata.model_dump()
        hit = cache_dict.get("hit")
        if hit is None:
            return None
        return bool(hit)

    hit = getattr(cache_metadata, "hit", None)
    if hit is None:
        return None

    return bool(hit)


def _extract_matrix(matrix_result: Any) -> tuple[list[list[float]], float, bool | None]:
    """
    Extract distance matrix, generation time, and cache status from Phase 5 MatrixResponse.

    Phase 5 wrapper response should contain:
    - matrix_distance_m
    - generation_time_ms
    - cache.hit
    """

    result_dict: dict[str, Any] | None = None

    if isinstance(matrix_result, dict):
        result_dict = matrix_result
    elif hasattr(matrix_result, "model_dump"):
        result_dict = matrix_result.model_dump()
    elif hasattr(matrix_result, "dict"):
        result_dict = matrix_result.dict()

    if result_dict is not None:
        matrix = (
            result_dict.get("matrix_distance_m")
            or result_dict.get("matrix")
            or result_dict.get("distances")
            or result_dict.get("distance_matrix")
        )

        matrix_generation_time_ms = float(
            result_dict.get("generation_time_ms")
            or result_dict.get("matrix_generation_time_ms")
            or result_dict.get("route_time_total_ms")
            or result_dict.get("compute_time_ms")
            or result_dict.get("total_time_ms")
            or 0.0
        )

        cache_used = _extract_cache_hit(result_dict.get("cache"))

    else:
        matrix = (
            getattr(matrix_result, "matrix_distance_m", None)
            or getattr(matrix_result, "matrix", None)
            or getattr(matrix_result, "distances", None)
            or getattr(matrix_result, "distance_matrix", None)
        )

        matrix_generation_time_ms = float(
            getattr(matrix_result, "generation_time_ms", None)
            or getattr(matrix_result, "matrix_generation_time_ms", None)
            or getattr(matrix_result, "route_time_total_ms", None)
            or getattr(matrix_result, "compute_time_ms", None)
            or getattr(matrix_result, "total_time_ms", None)
            or 0.0
        )

        cache_used = _extract_cache_hit(getattr(matrix_result, "cache", None))

    if matrix is None:
        available_fields = [
            name
            for name in dir(matrix_result)
            if not name.startswith("_")
        ]

        raise GreedyServiceError(
            "Phase 5 matrix response did not return matrix_distance_m. "
            f"Available fields: {available_fields}"
        )

    if not isinstance(matrix, list) or not matrix:
        raise GreedyServiceError(
            f"Phase 5 matrix output must be a non-empty list. Got type={type(matrix)}."
        )

    return matrix, round(matrix_generation_time_ms, 3), cache_used


def _build_phase5_matrix(
    *,
    request: Request,
    locations: list[dict[str, float]],
    matrix_algorithm: str,
    use_cache: bool,
) -> tuple[list[list[float]], float, bool | None]:
    """
    Calls Phase 5 matrix service wrapper, not the raw core builder.

    This preserves:
    - generation_time_ms
    - Redis cache behavior
    - cache hit/miss metadata
    """

    graph = getattr(request.app.state, "graph", None)
    snap_index = getattr(request.app.state, "snap_index", None)

    if graph is None:
        raise GreedyServiceError("Graph not loaded.")

    if snap_index is None:
        raise GreedyServiceError("Snap index not loaded.")

    matrix_locations = [
        MatrixLocation(
            id=f"loc_{index}",
            lat=coord["lat"],
            lon=coord["lon"],
        )
        for index, coord in enumerate(locations)
    ]

    matrix_request = MatrixRequest(
        locations=matrix_locations,
        algorithm=matrix_algorithm,
        use_cache=use_cache,
    )

    matrix_response = build_distance_matrix_response(
        payload=matrix_request,
        graph=graph,
        snap_index=snap_index,
    )

    return _extract_matrix(matrix_response)


def _convert_leg(
    *,
    from_matrix_index: int,
    to_matrix_index: int,
    distance_m: float,
) -> GreedyLegResponse:
    if from_matrix_index == 0:
        from_type = "start"
        from_index = None
    else:
        from_type = "stop"
        from_index = from_matrix_index - 1

    if to_matrix_index == 0:
        to_type = "start"
        to_index = None
    else:
        to_type = "stop"
        to_index = to_matrix_index - 1

    return GreedyLegResponse(
        from_type=from_type,
        from_index=from_index,
        to_type=to_type,
        to_index=to_index,
        distance_m=round(distance_m, 3),
    )


def _validate_greedy_order(
    *,
    optimized_order: list[int],
    stop_count: int,
) -> None:
    expected = list(range(stop_count))

    if sorted(optimized_order) != expected:
        raise GreedyServiceError(
            "Greedy algorithm returned an invalid stop order. "
            "Every stop must appear exactly once."
        )


def solve_greedy_baseline(
    *,
    payload: GreedyRouteRequest,
    request: Request,
) -> GreedyRouteResponse:
    total_start = perf_counter()

    locations: list[dict[str, float]] = [_coordinate_to_dict(payload.start)]
    locations.extend(_coordinate_to_dict(stop) for stop in payload.stops)

    try:
        distance_matrix, matrix_generation_time_ms, cache_used = _build_phase5_matrix(
            request=request,
            locations=locations,
            matrix_algorithm=payload.matrix_algorithm,
            use_cache=payload.use_cache,
        )

        greedy_result = solve_nearest_neighbor_greedy(
            distance_matrix=distance_matrix,
            return_to_start=payload.return_to_start,
        )

    except GreedyMatrixError as exc:
        raise GreedyNoPathError(str(exc)) from exc

    except GreedyServiceError:
        raise

    except Exception as exc:
        raise GreedyServiceError(str(exc)) from exc

    stop_count = len(payload.stops)

    _validate_greedy_order(
        optimized_order=greedy_result.optimized_order,
        stop_count=stop_count,
    )

    total_time_ms = (perf_counter() - total_start) * 1000

    return GreedyRouteResponse(
        status="ok",
        phase="tier2_phase6",
        algorithm="nearest_neighbor_greedy",
        matrix_algorithm=payload.matrix_algorithm,
        stop_count=stop_count,
        optimized_order=greedy_result.optimized_order,
        total_distance_m=greedy_result.total_distance_m,
        return_to_start=payload.return_to_start,
        legs=[
            _convert_leg(
                from_matrix_index=leg.from_matrix_index,
                to_matrix_index=leg.to_matrix_index,
                distance_m=leg.distance_m,
            )
            for leg in greedy_result.legs
        ],
        matrix_generation_time_ms=matrix_generation_time_ms,
        optimization_time_ms=greedy_result.optimization_time_ms,
        total_time_ms=round(total_time_ms, 3),
        cache_used=cache_used,
    )