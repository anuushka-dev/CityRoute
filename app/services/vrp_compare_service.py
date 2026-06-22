# app/services/vrp_compare_service.py

from __future__ import annotations

import inspect
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from time import perf_counter
from typing import Any

from app.core.two_opt import (
    TwoOptResult,
    assert_two_opt_non_regression,
    calculate_route_distance_m,
    two_optimize,
)


CoordinatePayload = dict[str, Any]
DistanceMatrix = Sequence[Sequence[float]]


class VrpCompareServiceError(ValueError):
    """Raised when VRP compare input, matrix data, or optimization data is invalid."""


def _extract_lat_lon(location: Any) -> tuple[float, float]:
    if isinstance(location, Mapping):
        lat = location.get("lat")
        lon = location.get("lon")
    else:
        lat = getattr(location, "lat", None)
        lon = getattr(location, "lon", None)

    if lat is None or lon is None:
        raise VrpCompareServiceError("location must contain lat and lon")

    try:
        lat_float = float(lat)
        lon_float = float(lon)
    except (TypeError, ValueError) as exc:
        raise VrpCompareServiceError("location lat and lon must be numeric") from exc

    if not math.isfinite(lat_float) or not math.isfinite(lon_float):
        raise VrpCompareServiceError("location lat and lon must be finite numbers")

    if not -90.0 <= lat_float <= 90.0:
        raise VrpCompareServiceError(f"latitude out of range: {lat_float}")

    if not -180.0 <= lon_float <= 180.0:
        raise VrpCompareServiceError(f"longitude out of range: {lon_float}")

    return lat_float, lon_float


def _location_id(location: Any, fallback: str) -> str:
    if isinstance(location, Mapping):
        raw_id = location.get("id", fallback)
    else:
        raw_id = getattr(location, "id", fallback)

    if raw_id is None or str(raw_id).strip() == "":
        return fallback

    return str(raw_id)


def _build_matrix_locations(depot: Any, stops: Sequence[Any]) -> list[CoordinatePayload]:
    depot_lat, depot_lon = _extract_lat_lon(depot)

    locations: list[CoordinatePayload] = [
        {
            "id": _location_id(depot, "depot"),
            "lat": depot_lat,
            "lon": depot_lon,
        }
    ]

    for index, stop in enumerate(stops):
        lat, lon = _extract_lat_lon(stop)

        locations.append(
            {
                "id": _location_id(stop, f"stop_{index}"),
                "lat": lat,
                "lon": lon,
            }
        )

    return locations


def _validate_stops(stops: Sequence[Any]) -> None:
    if stops is None:
        raise VrpCompareServiceError("stops must not be null")

    if isinstance(stops, (str, bytes, bytearray)):
        raise VrpCompareServiceError("stops must be a sequence of locations")

    if not stops:
        raise VrpCompareServiceError("stops must contain at least one stop")

    if len(stops) > 24:
        raise VrpCompareServiceError(
            "Phase 7 supports maximum 24 stops because depot + stops must stay "
            "within the 25-location matrix limit"
        )


def _validate_optimizer_settings(
    *,
    two_opt_max_iterations: int,
    improvement_tolerance_m: float,
) -> None:
    if two_opt_max_iterations <= 0:
        raise VrpCompareServiceError("two_opt_max_iterations must be greater than 0")

    if improvement_tolerance_m < 0:
        raise VrpCompareServiceError("improvement_tolerance_m must be non-negative")


def _to_plain_data(value: Any) -> Any:
    """
    Convert Pydantic/dataclass/custom/Starlette response objects into plain data.

    This protects Phase 7.1 from exact Phase 5 response model naming and from
    responses wrapped as JSONResponse-like objects.
    """
    if isinstance(value, Mapping):
        return {str(key): _to_plain_data(item) for key, item in value.items()}

    if hasattr(value, "body"):
        try:
            body = value.body

            if isinstance(body, bytes):
                return _to_plain_data(json.loads(body.decode("utf-8")))

            if isinstance(body, str):
                return _to_plain_data(json.loads(body))

        except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return value

    if hasattr(value, "model_dump"):
        return _to_plain_data(value.model_dump())

    if hasattr(value, "dict"):
        return _to_plain_data(value.dict())

    if isinstance(value, tuple) and hasattr(value, "_asdict"):
        return _to_plain_data(value._asdict())

    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [_to_plain_data(item) for item in value]

    return value


def _is_numeric_distance(value: Any) -> bool:
    if isinstance(value, bool):
        return False

    try:
        distance = float(value)
    except (TypeError, ValueError):
        return False

    return math.isfinite(distance) and distance >= -1.0


def _extract_distance_from_cell(cell: Any) -> float | None:
    if _is_numeric_distance(cell):
        return float(cell)

    if not isinstance(cell, Mapping):
        return None

    candidate_keys = (
        "distance_m",
        "distance",
        "distanceMeters",
        "distance_meters",
        "route_distance_m",
        "total_distance_m",
        "value",
    )

    for key in candidate_keys:
        if key in cell and _is_numeric_distance(cell[key]):
            return float(cell[key])

    return None


def _looks_like_numeric_matrix(value: Any) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return False

    if len(value) < 2:
        return False

    matrix_size = len(value)

    for row in value:
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes, bytearray)):
            return False

        if len(row) != matrix_size:
            return False

        for item in row:
            if not _is_numeric_distance(item):
                return False

    return True


def _looks_like_cell_matrix(value: Any) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return False

    if len(value) < 2:
        return False

    matrix_size = len(value)

    for row in value:
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes, bytearray)):
            return False

        if len(row) != matrix_size:
            return False

        for cell in row:
            if _extract_distance_from_cell(cell) is None:
                return False

    return True


def _cell_matrix_to_numeric_matrix(value: Sequence[Sequence[Any]]) -> list[list[float]]:
    matrix: list[list[float]] = []

    for row_index, row in enumerate(value):
        matrix_row: list[float] = []

        for col_index, cell in enumerate(row):
            distance = _extract_distance_from_cell(cell)

            if distance is None:
                raise VrpCompareServiceError(
                    f"matrix cell [{row_index}][{col_index}] does not contain distance"
                )

            matrix_row.append(distance)

        matrix.append(matrix_row)

    return matrix


def _find_distance_matrix_candidate(value: Any) -> Any:
    plain_value = _to_plain_data(value)

    if _looks_like_numeric_matrix(plain_value):
        return plain_value

    if _looks_like_cell_matrix(plain_value):
        return _cell_matrix_to_numeric_matrix(plain_value)

    if isinstance(plain_value, Mapping):
        preferred_keys = (
            "matrix",
            "distance_matrix",
            "matrix_distance_m",
            "distances",
            "distances_m",
            "distance_m",
            "distance_matrix_m",
            "distance_matrix_meters",
            "matrix_m",
            "matrix_meters",
            "rows",
            "values",
            "data",
            "result",
            "payload",
            "response",
        )

        for key in preferred_keys:
            if key in plain_value:
                candidate = _find_distance_matrix_candidate(plain_value[key])
                if candidate is not None:
                    return candidate

        for item in plain_value.values():
            candidate = _find_distance_matrix_candidate(item)
            if candidate is not None:
                return candidate

    if isinstance(plain_value, Sequence) and not isinstance(
        plain_value,
        (str, bytes, bytearray),
    ):
        for item in plain_value:
            candidate = _find_distance_matrix_candidate(item)
            if candidate is not None:
                return candidate

    return None


def _available_response_fields(response: Any) -> list[str]:
    plain_response = _to_plain_data(response)

    if isinstance(plain_response, Mapping):
        return sorted(str(key) for key in plain_response.keys())

    return []


def _validate_distance_matrix(
    distance_matrix: Any,
    *,
    expected_size: int | None = None,
) -> list[list[float]]:
    if distance_matrix is None:
        raise VrpCompareServiceError("distance matrix must not be null")

    if isinstance(distance_matrix, (str, bytes, bytearray)):
        raise VrpCompareServiceError("distance matrix must be a 2D numeric sequence")

    if not isinstance(distance_matrix, Sequence):
        raise VrpCompareServiceError("distance matrix must be a sequence")

    if len(distance_matrix) < 2:
        raise VrpCompareServiceError(
            "distance matrix must contain depot plus at least one stop"
        )

    if expected_size is not None and len(distance_matrix) != expected_size:
        raise VrpCompareServiceError(
            f"distance matrix size mismatch: expected {expected_size}, "
            f"got {len(distance_matrix)}"
        )

    normalized: list[list[float]] = []
    matrix_size = len(distance_matrix)

    for row_index, row in enumerate(distance_matrix):
        if isinstance(row, (str, bytes, bytearray)) or not isinstance(row, Sequence):
            raise VrpCompareServiceError(
                f"distance matrix row {row_index} must be a numeric sequence"
            )

        if len(row) != matrix_size:
            raise VrpCompareServiceError(
                "distance matrix must be square: "
                f"row {row_index} has length {len(row)}, expected {matrix_size}"
            )

        normalized_row: list[float] = []

        for col_index, value in enumerate(row):
            if isinstance(value, bool):
                raise VrpCompareServiceError(
                    f"distance matrix value [{row_index}][{col_index}] must be numeric"
                )

            try:
                distance = float(value)
            except (TypeError, ValueError) as exc:
                raise VrpCompareServiceError(
                    f"distance matrix value [{row_index}][{col_index}] must be numeric"
                ) from exc

            if not math.isfinite(distance):
                raise VrpCompareServiceError(
                    f"distance matrix value [{row_index}][{col_index}] must be finite"
                )

            if distance < -1.0:
                raise VrpCompareServiceError(
                    f"distance matrix value [{row_index}][{col_index}] is invalid: "
                    f"{distance}"
                )

            if row_index == col_index and distance < 0:
                raise VrpCompareServiceError(
                    f"distance matrix diagonal [{row_index}][{col_index}] "
                    "cannot be unreachable"
                )

            normalized_row.append(distance)

        normalized.append(normalized_row)

    return normalized


def _edge_distance_or_none(
    distance_matrix: Sequence[Sequence[float]],
    from_matrix_index: int,
    to_matrix_index: int,
) -> float | None:
    distance = float(distance_matrix[from_matrix_index][to_matrix_index])

    if distance < 0:
        return None

    return distance


def _edge_distance_required(
    distance_matrix: Sequence[Sequence[float]],
    from_matrix_index: int,
    to_matrix_index: int,
    *,
    context: str,
) -> float:
    distance = _edge_distance_or_none(
        distance_matrix,
        from_matrix_index,
        to_matrix_index,
    )

    if distance is None:
        raise VrpCompareServiceError(
            f"unreachable {context} from matrix index "
            f"{from_matrix_index} to {to_matrix_index}"
        )

    return distance


def _validate_stop_order(order: Sequence[int], *, stop_count: int, label: str) -> None:
    if sorted(order) != list(range(stop_count)):
        raise VrpCompareServiceError(
            f"{label} order is invalid: expected each stop index 0..{stop_count - 1} "
            "exactly once"
        )


def _nearest_neighbor_order(
    distance_matrix: DistanceMatrix,
    *,
    stop_count: int,
    depot_index: int = 0,
) -> list[int]:
    if stop_count <= 0:
        raise VrpCompareServiceError("stop_count must be greater than 0")

    unvisited = set(range(stop_count))
    order: list[int] = []

    current_matrix_index = depot_index

    while unvisited:
        reachable_candidates: list[tuple[float, int]] = []

        for stop_index in unvisited:
            stop_matrix_index = stop_index + 1
            distance = _edge_distance_or_none(
                distance_matrix,
                current_matrix_index,
                stop_matrix_index,
            )

            if distance is not None:
                reachable_candidates.append((distance, stop_index))

        if not reachable_candidates:
            raise VrpCompareServiceError(
                "nearest-neighbor greedy cannot continue because all remaining "
                f"stops are unreachable from matrix index {current_matrix_index}"
            )

        _, best_stop = min(reachable_candidates, key=lambda item: (item[0], item[1]))

        order.append(best_stop)
        unvisited.remove(best_stop)
        current_matrix_index = best_stop + 1

    _validate_stop_order(order, stop_count=stop_count, label="greedy")

    return order


def _build_legs(
    order: Sequence[int],
    distance_matrix: DistanceMatrix,
    *,
    return_to_start: bool,
) -> list[dict[str, Any]]:
    stop_count = len(distance_matrix) - 1
    _validate_stop_order(order, stop_count=stop_count, label="route")

    legs: list[dict[str, Any]] = []

    previous_type = "start"
    previous_stop_index: int | None = None
    previous_matrix_index = 0

    for stop_index in order:
        stop_matrix_index = stop_index + 1

        distance_m = _edge_distance_required(
            distance_matrix,
            previous_matrix_index,
            stop_matrix_index,
            context="leg",
        )

        legs.append(
            {
                "from_type": previous_type,
                "from_index": previous_stop_index,
                "to_type": "stop",
                "to_index": stop_index,
                "distance_m": round(distance_m, 3),
            }
        )

        previous_type = "stop"
        previous_stop_index = stop_index
        previous_matrix_index = stop_matrix_index

    if return_to_start:
        return_distance_m = _edge_distance_required(
            distance_matrix,
            previous_matrix_index,
            0,
            context="return leg",
        )

        legs.append(
            {
                "from_type": "stop",
                "from_index": previous_stop_index,
                "to_type": "start",
                "to_index": None,
                "distance_m": round(return_distance_m, 3),
            }
        )

    return legs


def _algorithm_payload(
    *,
    algorithm: str,
    order: Sequence[int],
    distance_m: float,
    legs: list[dict[str, Any]],
    optimization_time_ms: float,
    iterations: int = 0,
    swaps_applied: int = 0,
    converged: bool = True,
) -> dict[str, Any]:
    return {
        "algorithm": algorithm,
        "optimized_order": list(order),
        "total_distance_m": round(float(distance_m), 3),
        "legs": legs,
        "optimization_time_ms": round(float(optimization_time_ms), 3),
        "iterations": int(iterations),
        "swaps_applied": int(swaps_applied),
        "converged": bool(converged),
    }


def _improvement_payload(two_opt_result: TwoOptResult) -> dict[str, Any]:
    non_regression = (
        two_opt_result.optimized_distance_m <= two_opt_result.initial_distance_m
    )

    return {
        "baseline_distance_m": round(float(two_opt_result.initial_distance_m), 3),
        "optimized_distance_m": round(float(two_opt_result.optimized_distance_m), 3),
        "distance_saved_m": round(float(two_opt_result.improvement_m), 3),
        "improvement_pct": round(float(two_opt_result.improvement_pct), 3),
        "improved": bool(two_opt_result.improved),
        "non_regression": bool(non_regression),
    }


def _response_get(response: Any, names: Sequence[str], default: Any = None) -> Any:
    plain_response = _to_plain_data(response)

    if isinstance(plain_response, Mapping):
        for name in names:
            if name in plain_response:
                return plain_response[name]

    return default


def _deep_response_get(
    response: Any,
    names: Sequence[str],
    default: Any = None,
) -> Any:
    plain_response = _to_plain_data(response)

    def walk(value: Any) -> Any:
        if isinstance(value, Mapping):
            for name in names:
                if name in value:
                    return value[name]

            for item in value.values():
                found = walk(item)

                if found is not None:
                    return found

        if isinstance(value, Sequence) and not isinstance(
            value,
            (str, bytes, bytearray),
        ):
            for item in value:
                found = walk(item)

                if found is not None:
                    return found

        return None

    found_value = walk(plain_response)

    if found_value is None:
        return default

    return found_value


def _safe_int(value: Any, *, default: int = 0) -> int:
    if value is None:
        return default

    if isinstance(value, bool):
        return int(value)

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default

    if parsed < 0:
        return default

    return parsed


def _safe_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        lowered = value.strip().lower()

        if lowered in {"true", "1", "yes", "y", "enabled", "hit"}:
            return True

        if lowered in {"false", "0", "no", "n", "disabled", "miss"}:
            return False

    return bool(value)


def _derive_cache_status(
    *,
    cache_used: bool,
    cache_hits: int,
    cache_misses: int,
    explicit_status: Any = None,
) -> str:
    if isinstance(explicit_status, str):
        normalized = explicit_status.strip().lower()

        if normalized in {"hit", "miss", "partial", "disabled", "unknown"}:
            return normalized

    if not cache_used:
        return "disabled"

    if cache_hits > 0 and cache_misses == 0:
        return "hit"

    if cache_hits == 0 and cache_misses > 0:
        return "miss"

    if cache_hits > 0 and cache_misses > 0:
        return "partial"

    return "unknown"


def _extract_cache_telemetry(
    matrix_response: Any,
    *,
    requested_use_cache: bool,
) -> tuple[bool, str, int, int]:
    plain_response = _to_plain_data(matrix_response)

    cache_metadata: Any = None

    if isinstance(plain_response, Mapping):
        raw_cache = plain_response.get("cache")

        if isinstance(raw_cache, Mapping):
            cache_metadata = raw_cache

    if isinstance(cache_metadata, Mapping):
        cache_enabled = _safe_bool(
            cache_metadata.get("enabled"),
            default=bool(requested_use_cache),
        )

        raw_hit = cache_metadata.get("hit")

        if not cache_enabled:
            return False, "disabled", 0, 0

        if isinstance(raw_hit, bool):
            if raw_hit:
                return True, "hit", 1, 0

            return True, "miss", 0, 1

        explicit_status = (
            cache_metadata.get("cache_status")
            or cache_metadata.get("status")
            or cache_metadata.get("result")
            or cache_metadata.get("source")
        )

        cache_status = _derive_cache_status(
            cache_used=cache_enabled,
            cache_hits=0,
            cache_misses=0,
            explicit_status=explicit_status,
        )

        return cache_enabled, cache_status, 0, 0

    cache_hits = _safe_int(
        _deep_response_get(
            matrix_response,
            (
                "cache_hits",
                "matrix_cache_hits",
                "redis_cache_hits",
                "hit_count",
                "hits",
            ),
            0,
        )
    )

    cache_misses = _safe_int(
        _deep_response_get(
            matrix_response,
            (
                "cache_misses",
                "matrix_cache_misses",
                "redis_cache_misses",
                "miss_count",
                "misses",
            ),
            0,
        )
    )

    cache_used = _safe_bool(
        _deep_response_get(
            matrix_response,
            (
                "cache_used",
                "use_cache",
                "matrix_cache_used",
                "redis_cache_used",
                "enabled",
            ),
            requested_use_cache,
        ),
        default=bool(requested_use_cache),
    )

    explicit_cache_status = _deep_response_get(
        matrix_response,
        (
            "cache_status",
            "matrix_cache_status",
            "redis_cache_status",
            "cache_result",
            "source",
        ),
        None,
    )

    cache_status = _derive_cache_status(
        cache_used=cache_used,
        cache_hits=cache_hits,
        cache_misses=cache_misses,
        explicit_status=explicit_cache_status,
    )

    return cache_used, cache_status, cache_hits, cache_misses


async def compute_vrp_compare_from_matrix(
    *,
    distance_matrix: DistanceMatrix,
    expected_stop_count: int | None = None,
    return_to_start: bool = False,
    two_opt_max_iterations: int = 100,
    improvement_tolerance_m: float = 0.001,
    keep_trace: bool = True,
) -> dict[str, Any]:
    _validate_optimizer_settings(
        two_opt_max_iterations=two_opt_max_iterations,
        improvement_tolerance_m=improvement_tolerance_m,
    )

    normalized_matrix = _validate_distance_matrix(distance_matrix)

    stop_count = len(normalized_matrix) - 1

    if expected_stop_count is not None and stop_count != expected_stop_count:
        raise VrpCompareServiceError(
            f"stop count mismatch: expected {expected_stop_count}, got {stop_count}"
        )

    total_start = perf_counter()

    greedy_start = perf_counter()
    greedy_order = _nearest_neighbor_order(
        normalized_matrix,
        stop_count=stop_count,
    )
    greedy_distance_m = calculate_route_distance_m(
        greedy_order,
        normalized_matrix,
        return_to_start=return_to_start,
    )
    greedy_time_ms = (perf_counter() - greedy_start) * 1000.0

    two_opt_start = perf_counter()
    two_opt_result = two_optimize(
        greedy_order,
        normalized_matrix,
        return_to_start=return_to_start,
        max_iterations=two_opt_max_iterations,
        improvement_tolerance_m=improvement_tolerance_m,
        keep_trace=keep_trace,
    )
    two_opt_time_ms = (perf_counter() - two_opt_start) * 1000.0

    try:
        assert_two_opt_non_regression(two_opt_result)
    except AssertionError as exc:
        raise VrpCompareServiceError(str(exc)) from exc

    _validate_stop_order(
        two_opt_result.optimized_order,
        stop_count=stop_count,
        label="two_opt",
    )

    greedy_legs = _build_legs(
        greedy_order,
        normalized_matrix,
        return_to_start=return_to_start,
    )

    two_opt_legs = _build_legs(
        two_opt_result.optimized_order,
        normalized_matrix,
        return_to_start=return_to_start,
    )

    total_time_ms = (perf_counter() - total_start) * 1000.0

    return {
        "status": "ok",
        "phase": "tier2_phase7",
        "comparison": "greedy_vs_two_opt",
        "stop_count": stop_count,
        "return_to_start": bool(return_to_start),
        "greedy": _algorithm_payload(
            algorithm="nearest_neighbor_greedy",
            order=greedy_order,
            distance_m=greedy_distance_m,
            legs=greedy_legs,
            optimization_time_ms=greedy_time_ms,
        ),
        "two_opt": _algorithm_payload(
            algorithm="two_opt",
            order=two_opt_result.optimized_order,
            distance_m=two_opt_result.optimized_distance_m,
            legs=two_opt_legs,
            optimization_time_ms=two_opt_time_ms,
            iterations=two_opt_result.iterations,
            swaps_applied=two_opt_result.swaps_applied,
            converged=two_opt_result.converged,
        ),
        "improvement": _improvement_payload(two_opt_result),
        "convergence_trace": [
            asdict(item) for item in two_opt_result.convergence_trace
        ],
        "total_time_ms": round(total_time_ms, 3),
    }


async def compute_vrp_compare(
    *,
    depot: Any,
    stops: Sequence[Any],
    matrix_service: Any,
    matrix_algorithm: str = "source_dijkstra",
    use_cache: bool = True,
    ttl_seconds: int | None = None,
    return_to_start: bool = False,
    two_opt_max_iterations: int = 100,
    improvement_tolerance_m: float = 0.001,
    keep_trace: bool = True,
) -> dict[str, Any]:
    if not callable(matrix_service):
        raise VrpCompareServiceError("matrix_service must be callable")

    _validate_stops(stops)
    _validate_optimizer_settings(
        two_opt_max_iterations=two_opt_max_iterations,
        improvement_tolerance_m=improvement_tolerance_m,
    )

    locations = _build_matrix_locations(depot, stops)
    expected_matrix_size = len(locations)
    expected_stop_count = len(stops)

    matrix_payload: dict[str, Any] = {
        "locations": locations,
        "algorithm": matrix_algorithm,
        "use_cache": bool(use_cache),
    }

    if ttl_seconds is not None:
        if ttl_seconds <= 0:
            raise VrpCompareServiceError("ttl_seconds must be greater than 0")

        matrix_payload["ttl_seconds"] = ttl_seconds

    matrix_start = perf_counter()

    matrix_response = matrix_service(matrix_payload)

    if inspect.isawaitable(matrix_response):
        matrix_response = await matrix_response

    matrix_time_ms = (perf_counter() - matrix_start) * 1000.0

    distance_matrix = _response_get(
        matrix_response,
        names=(
            "matrix",
            "distance_matrix",
            "matrix_distance_m",
            "distances",
            "distances_m",
            "distance_m",
            "distance_matrix_m",
            "distance_matrix_meters",
            "matrix_m",
            "matrix_meters",
        ),
    )

    if distance_matrix is None:
        distance_matrix = _find_distance_matrix_candidate(matrix_response)

    if distance_matrix is None:
        raise VrpCompareServiceError(
            "matrix_service response must contain a distance matrix. "
            f"response_type={type(matrix_response).__name__}; "
            f"available_fields={_available_response_fields(matrix_response)}"
        )

    normalized_matrix = _validate_distance_matrix(
        distance_matrix,
        expected_size=expected_matrix_size,
    )

    cache_used, cache_status, cache_hits, cache_misses = _extract_cache_telemetry(
        matrix_response,
        requested_use_cache=use_cache,
    )

    matrix_generation_time_ms = _response_get(
        matrix_response,
        (
            "matrix_generation_time_ms",
            "generation_time_ms",
            "route_time_total_ms",
            "total_time_ms",
            "api_elapsed_ms",
        ),
        matrix_time_ms,
    )

    compare_result = await compute_vrp_compare_from_matrix(
        distance_matrix=normalized_matrix,
        expected_stop_count=expected_stop_count,
        return_to_start=return_to_start,
        two_opt_max_iterations=two_opt_max_iterations,
        improvement_tolerance_m=improvement_tolerance_m,
        keep_trace=keep_trace,
    )

    compare_result["matrix_algorithm"] = matrix_algorithm
    compare_result["matrix_generation_time_ms"] = round(
        float(matrix_generation_time_ms),
        3,
    )
    compare_result["cache_used"] = bool(cache_used)
    compare_result["cache_status"] = cache_status
    compare_result["cache_hits"] = cache_hits
    compare_result["cache_misses"] = cache_misses

    return compare_result