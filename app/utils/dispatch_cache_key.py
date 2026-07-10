# app/utils/dispatch_cache_key.py

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

CACHE_KEY_VERSION = "v1"
DISPATCH_DISTANCE_KEY_PREFIX = "dispatch:distance"
DISPATCH_RESPONSE_KEY_PREFIX = "dispatch:response"


class CacheKeyDriverLike(Protocol):
    driver_id: str
    lat: float
    lon: float
    capacity: int
    current_load: int


class CacheKeyOrderLike(Protocol):
    order_id: str
    lat: float
    lon: float


def build_dispatch_distance_cache_key(
    *,
    drivers: Sequence[CacheKeyDriverLike],
    orders: Sequence[CacheKeyOrderLike],
    matrix_algorithm: str,
    load_penalty_m: float = 0.0,
    slot_penalty_m: float = 0.0,
    graph_fingerprint: str | None = None,
) -> str:
    """Build stable cache key for driver-to-order dispatch distance matrix."""

    payload = {
        "version": CACHE_KEY_VERSION,
        "component": "dispatch_distance_matrix",
        "matrix_algorithm": matrix_algorithm,
        "load_penalty_m": _round_float(load_penalty_m),
        "slot_penalty_m": _round_float(slot_penalty_m),
        "graph_fingerprint": graph_fingerprint,
        "drivers": _normalize_drivers(drivers),
        "orders": _normalize_orders(orders),
    }

    return _build_key(
        prefix=DISPATCH_DISTANCE_KEY_PREFIX,
        matrix_algorithm=matrix_algorithm,
        payload=payload,
    )


def build_dispatch_response_cache_key(
    *,
    drivers: Sequence[CacheKeyDriverLike],
    orders: Sequence[CacheKeyOrderLike],
    matrix_algorithm: str,
    load_penalty_m: float = 0.0,
    slot_penalty_m: float = 0.0,
    return_cost_breakdown: bool = False,
    graph_fingerprint: str | None = None,
) -> str:
    """Build stable cache key for full dispatch response payload."""

    payload = {
        "version": CACHE_KEY_VERSION,
        "component": "dispatch_response",
        "matrix_algorithm": matrix_algorithm,
        "load_penalty_m": _round_float(load_penalty_m),
        "slot_penalty_m": _round_float(slot_penalty_m),
        "return_cost_breakdown": bool(return_cost_breakdown),
        "graph_fingerprint": graph_fingerprint,
        "drivers": _normalize_drivers(drivers),
        "orders": _normalize_orders(orders),
    }

    return _build_key(
        prefix=DISPATCH_RESPONSE_KEY_PREFIX,
        matrix_algorithm=matrix_algorithm,
        payload=payload,
    )


def build_dispatch_cache_fingerprint(payload: Mapping[str, Any]) -> str:
    """Build deterministic SHA256 fingerprint for already-normalized payloads."""

    raw_payload = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )

    return hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()


def _build_key(
    *,
    prefix: str,
    matrix_algorithm: str,
    payload: Mapping[str, Any],
) -> str:
    digest = build_dispatch_cache_fingerprint(payload)
    safe_algorithm = _sanitize_key_part(matrix_algorithm)

    return f"{prefix}:{CACHE_KEY_VERSION}:{safe_algorithm}:{digest}"


def _normalize_drivers(
    drivers: Sequence[CacheKeyDriverLike],
) -> list[dict[str, int | float | str]]:
    return [
        {
            "driver_id": str(driver.driver_id),
            "lat": _round_coordinate(driver.lat),
            "lon": _round_coordinate(driver.lon),
            "capacity": int(driver.capacity),
            "current_load": int(driver.current_load),
        }
        for driver in sorted(drivers, key=lambda item: str(item.driver_id))
    ]


def _normalize_orders(
    orders: Sequence[CacheKeyOrderLike],
) -> list[dict[str, float | str]]:
    return [
        {
            "order_id": str(order.order_id),
            "lat": _round_coordinate(order.lat),
            "lon": _round_coordinate(order.lon),
        }
        for order in sorted(orders, key=lambda item: str(item.order_id))
    ]


def _round_coordinate(value: float) -> float:
    return round(float(value), 7)


def _round_float(value: float) -> float:
    return round(float(value), 6)


def _sanitize_key_part(value: str) -> str:
    return (
        value.strip()
        .lower()
        .replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
    )