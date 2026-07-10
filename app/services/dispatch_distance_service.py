# app/services/dispatch_distance_service.py

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from app.core.dispatch_cost_matrix import (
    DispatchDriver,
    DispatchOrder,
    haversine_distance_lookup,
)

DispatchMatrixAlgorithm = Literal["haversine", "source_dijkstra"]
SourceDijkstraMatrixBuilder = Callable[
    [Sequence[DispatchDriver], Sequence[DispatchOrder]],
    list[list[float]],
]

UNREACHABLE_DISPATCH_COST_M = 1_000_000_000_000.0


class DispatchDistanceError(ValueError):
    """Raised when dispatch distance generation cannot be completed."""


class DispatchDistanceCacheBackend(Protocol):
    """Small protocol so this service does not depend on one Redis implementation."""

    def get(self, key: str) -> Any: ...

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> Any: ...


@dataclass(frozen=True)
class DispatchDistanceMatrixResult:
    matrix_algorithm: DispatchMatrixAlgorithm
    driver_ids: list[str]
    order_ids: list[str]
    driver_order_distance_matrix: list[list[float]]
    cache_used: bool
    cache_hit: bool
    cache_key: str | None

    def distance_lookup(self, driver: DispatchDriver, order: DispatchOrder) -> float:
        driver_index = self._driver_index_by_id()
        order_index = self._order_index_by_id()

        if driver.driver_id not in driver_index:
            raise DispatchDistanceError(f"Unknown driver_id in distance lookup: {driver.driver_id}")

        if order.order_id not in order_index:
            raise DispatchDistanceError(f"Unknown order_id in distance lookup: {order.order_id}")

        return self.driver_order_distance_matrix[
            driver_index[driver.driver_id]
        ][
            order_index[order.order_id]
        ]

    def _driver_index_by_id(self) -> dict[str, int]:
        return {driver_id: index for index, driver_id in enumerate(self.driver_ids)}

    def _order_index_by_id(self) -> dict[str, int]:
        return {order_id: index for index, order_id in enumerate(self.order_ids)}


def build_dispatch_distance_matrix(
    *,
    drivers: Sequence[DispatchDriver],
    orders: Sequence[DispatchOrder],
    matrix_algorithm: DispatchMatrixAlgorithm,
    source_dijkstra_matrix_builder: SourceDijkstraMatrixBuilder | None = None,
    use_cache: bool = True,
    cache_backend: DispatchDistanceCacheBackend | None = None,
    cache_ttl_seconds: int | None = 86_400,
) -> DispatchDistanceMatrixResult:
    """Build driver-to-order distance matrix for dispatch.

    This service intentionally does not call the /matrix HTTP endpoint.
    Phase 9.1 should inject an internal source_dijkstra matrix builder from the
    existing Phase 5 matrix/routing layer.
    """

    _validate_drivers_and_orders(drivers=drivers, orders=orders)
    _validate_matrix_algorithm(matrix_algorithm)

    cache_key = _build_dispatch_distance_cache_key(
        drivers=drivers,
        orders=orders,
        matrix_algorithm=matrix_algorithm,
    )

    if use_cache and cache_backend is not None:
        cached_matrix = _read_cached_matrix(cache_backend, cache_key)
        if cached_matrix is not None:
            validated_cached_matrix = _validate_and_normalize_distance_matrix(
                matrix=cached_matrix,
                expected_rows=len(drivers),
                expected_cols=len(orders),
            )
            return DispatchDistanceMatrixResult(
                matrix_algorithm=matrix_algorithm,
                driver_ids=[driver.driver_id for driver in drivers],
                order_ids=[order.order_id for order in orders],
                driver_order_distance_matrix=validated_cached_matrix,
                cache_used=True,
                cache_hit=True,
                cache_key=cache_key,
            )

    if matrix_algorithm == "haversine":
        matrix = _build_haversine_matrix(drivers=drivers, orders=orders)
    else:
        if source_dijkstra_matrix_builder is None:
            raise DispatchDistanceError(
                'matrix_algorithm="source_dijkstra" requires an internal '
                "source_dijkstra_matrix_builder. Do not call /matrix over HTTP."
            )

        matrix = source_dijkstra_matrix_builder(drivers, orders)

    validated_matrix = _validate_and_normalize_distance_matrix(
        matrix=matrix,
        expected_rows=len(drivers),
        expected_cols=len(orders),
    )

    if use_cache and cache_backend is not None:
        _write_cached_matrix(
            cache_backend=cache_backend,
            cache_key=cache_key,
            matrix=validated_matrix,
            ttl_seconds=cache_ttl_seconds,
        )

    return DispatchDistanceMatrixResult(
        matrix_algorithm=matrix_algorithm,
        driver_ids=[driver.driver_id for driver in drivers],
        order_ids=[order.order_id for order in orders],
        driver_order_distance_matrix=validated_matrix,
        cache_used=use_cache and cache_backend is not None,
        cache_hit=False,
        cache_key=cache_key if use_cache and cache_backend is not None else None,
    )


def build_dispatch_distance_lookup(
    *,
    drivers: Sequence[DispatchDriver],
    orders: Sequence[DispatchOrder],
    matrix_algorithm: DispatchMatrixAlgorithm,
    source_dijkstra_matrix_builder: SourceDijkstraMatrixBuilder | None = None,
    use_cache: bool = True,
    cache_backend: DispatchDistanceCacheBackend | None = None,
    cache_ttl_seconds: int | None = 86_400,
) -> DispatchDistanceMatrixResult:
    """Build a reusable distance lookup result for dispatch cost matrix construction."""

    return build_dispatch_distance_matrix(
        drivers=drivers,
        orders=orders,
        matrix_algorithm=matrix_algorithm,
        source_dijkstra_matrix_builder=source_dijkstra_matrix_builder,
        use_cache=use_cache,
        cache_backend=cache_backend,
        cache_ttl_seconds=cache_ttl_seconds,
    )


def _build_haversine_matrix(
    *,
    drivers: Sequence[DispatchDriver],
    orders: Sequence[DispatchOrder],
) -> list[list[float]]:
    return [
        [
            haversine_distance_lookup(driver, order)
            for order in orders
        ]
        for driver in drivers
    ]


def _validate_drivers_and_orders(
    *,
    drivers: Sequence[DispatchDriver],
    orders: Sequence[DispatchOrder],
) -> None:
    if not drivers:
        raise DispatchDistanceError("At least one driver is required.")

    if not orders:
        raise DispatchDistanceError("At least one order is required.")

    driver_ids = [driver.driver_id for driver in drivers]
    order_ids = [order.order_id for order in orders]

    if any(not driver_id for driver_id in driver_ids):
        raise DispatchDistanceError("Driver IDs must be non-empty.")

    if any(not order_id for order_id in order_ids):
        raise DispatchDistanceError("Order IDs must be non-empty.")

    if len(set(driver_ids)) != len(driver_ids):
        raise DispatchDistanceError("Driver IDs must be unique.")

    if len(set(order_ids)) != len(order_ids):
        raise DispatchDistanceError("Order IDs must be unique.")


def _validate_matrix_algorithm(matrix_algorithm: str) -> None:
    if matrix_algorithm not in {"haversine", "source_dijkstra"}:
        raise DispatchDistanceError(
            f"Unsupported dispatch matrix_algorithm: {matrix_algorithm}"
        )


def _validate_and_normalize_distance_matrix(
    *,
    matrix: Sequence[Sequence[float]],
    expected_rows: int,
    expected_cols: int,
) -> list[list[float]]:
    if len(matrix) != expected_rows:
        raise DispatchDistanceError(
            f"Distance matrix row count mismatch: expected {expected_rows}, got {len(matrix)}"
        )

    normalized_matrix: list[list[float]] = []

    for row_index, row in enumerate(matrix):
        if len(row) != expected_cols:
            raise DispatchDistanceError(
                "Distance matrix column count mismatch at row "
                f"{row_index}: expected {expected_cols}, got {len(row)}"
            )

        normalized_row = [
            _normalize_distance_value(value)
            for value in row
        ]
        normalized_matrix.append(normalized_row)

    return normalized_matrix


def _normalize_distance_value(value: float | int | None) -> float:
    if value is None:
        return UNREACHABLE_DISPATCH_COST_M

    distance = float(value)

    if math.isnan(distance):
        return UNREACHABLE_DISPATCH_COST_M

    if math.isinf(distance):
        return UNREACHABLE_DISPATCH_COST_M

    if distance < 0:
        return UNREACHABLE_DISPATCH_COST_M

    return round(distance, 6)


def _build_dispatch_distance_cache_key(
    *,
    drivers: Sequence[DispatchDriver],
    orders: Sequence[DispatchOrder],
    matrix_algorithm: DispatchMatrixAlgorithm,
) -> str:
    payload = {
        "phase": "tier3_phase9_1",
        "component": "dispatch_distance_matrix",
        "matrix_algorithm": matrix_algorithm,
        "drivers": [
            {
                "driver_id": driver.driver_id,
                "lat": round(float(driver.lat), 7),
                "lon": round(float(driver.lon), 7),
                "capacity": int(driver.capacity),
                "current_load": int(driver.current_load),
            }
            for driver in drivers
        ],
        "orders": [
            {
                "order_id": order.order_id,
                "lat": round(float(order.lat), 7),
                "lon": round(float(order.lon), 7),
            }
            for order in orders
        ],
    }

    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    return f"dispatch:distance:{matrix_algorithm}:{digest}"


def _read_cached_matrix(
    cache_backend: DispatchDistanceCacheBackend,
    cache_key: str,
) -> list[list[float]] | None:
    try:
        cached_value = cache_backend.get(cache_key)
    except Exception:
        return None

    if cached_value is None:
        return None

    if isinstance(cached_value, bytes):
        cached_value = cached_value.decode("utf-8")

    if isinstance(cached_value, str):
        try:
            parsed_value = json.loads(cached_value)
        except json.JSONDecodeError:
            return None
    else:
        parsed_value = cached_value

    if not isinstance(parsed_value, list):
        return None

    return parsed_value


def _write_cached_matrix(
    *,
    cache_backend: DispatchDistanceCacheBackend,
    cache_key: str,
    matrix: list[list[float]],
    ttl_seconds: int | None,
) -> None:
    serialized_matrix = json.dumps(matrix, separators=(",", ":"))

    try:
        cache_backend.set(cache_key, serialized_matrix, ttl_seconds=ttl_seconds)
    except TypeError:
        cache_backend.set(cache_key, serialized_matrix)
    except Exception:
        return