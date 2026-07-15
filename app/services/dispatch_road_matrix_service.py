# app/services/dispatch_road_matrix_service.py

from __future__ import annotations

import asyncio
import inspect
import json
import math
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal, TypeAlias

from app.core.dispatch_road_cost_matrix import (
    NodeId,
    RoadDispatchCostMatrixResult,
    SourceDistanceBuilder,
    UnreachableRoadPair,
    build_dispatch_road_cost_matrix,
)
from app.utils.matrix_cache_key import (
    build_dispatch_road_matrix_cache_key,
)

CACHE_PAYLOAD_VERSION = 1


class DispatchRoadMatrixServiceError(RuntimeError):
    """Raised when the road-aware dispatch matrix service cannot proceed."""


@dataclass(frozen=True)
class GeoCoordinate:
    """Geographic coordinate used by the road-matrix service."""

    lat: float
    lon: float


@dataclass(frozen=True)
class SnappedDispatchLocation:
    """One input coordinate after nearest-node snapping."""

    original_index: int
    lat: float
    lon: float
    node_id: NodeId


CacheStatus: TypeAlias = Literal[
    "disabled",
    "hit",
    "miss",
]

MatrixSource: TypeAlias = Literal[
    "computed",
    "cache",
]


SnapNodeFn: TypeAlias = Callable[
    [float, float],
    NodeId | Awaitable[NodeId],
]

CacheGetFn: TypeAlias = Callable[
    [str],
    Any | Awaitable[Any],
]

CacheSetFn: TypeAlias = Callable[
    [str, str, int],
    Any | Awaitable[Any],
]

CacheKeyBuilder: TypeAlias = Callable[
    [Sequence[NodeId], Sequence[NodeId], float],
    str,
]


@dataclass(frozen=True)
class DispatchRoadMatrixDependencies:
    """
    External infrastructure dependencies used by the service.

    These are injected so this service does not directly depend on:
    - FastAPI app.state
    - a specific Redis client
    - a specific BallTree implementation
    - global graph state
    """

    snap_node: SnapNodeFn
    source_distance_builder: SourceDistanceBuilder

    cache_get: CacheGetFn | None = None
    cache_set: CacheSetFn | None = None

    cache_key_builder: CacheKeyBuilder | None = None


@dataclass(frozen=True)
class DispatchRoadMatrixServiceResult:
    """Complete real-road dispatch matrix result and telemetry."""

    matrix_result: RoadDispatchCostMatrixResult

    snapped_drivers: tuple[SnappedDispatchLocation, ...]
    snapped_orders: tuple[SnappedDispatchLocation, ...]

    matrix_algorithm: str
    matrix_source: MatrixSource

    cache_used: bool
    cache_status: CacheStatus
    cache_hits: int
    cache_misses: int
    cache_key: str | None
    cache_error: str | None

    snap_time_ms: float
    cache_lookup_time_ms: float
    cache_write_time_ms: float
    matrix_generation_time_ms: float
    total_time_ms: float

    @property
    def driver_nodes(self) -> tuple[NodeId, ...]:
        return tuple(
            item.node_id
            for item in self.snapped_drivers
        )

    @property
    def order_nodes(self) -> tuple[NodeId, ...]:
        return tuple(
            item.node_id
            for item in self.snapped_orders
        )

    @property
    def snapped_driver_count(self) -> int:
        return len(self.snapped_drivers)

    @property
    def snapped_order_count(self) -> int:
        return len(self.snapped_orders)

    @property
    def unreachable_pair_count(self) -> int:
        return self.matrix_result.unreachable_pair_count

    @property
    def all_pairs_reachable(self) -> bool:
        return self.matrix_result.all_pairs_reachable


async def build_dispatch_road_matrix(
    *,
    drivers: Sequence[GeoCoordinate],
    orders: Sequence[GeoCoordinate],
    dependencies: DispatchRoadMatrixDependencies,
    use_cache: bool = True,
    cache_ttl_seconds: int = 86_400,
    unreachable_cost_m: float = 1_000_000_000.0,
    fail_open_on_cache_error: bool = True,
) -> DispatchRoadMatrixServiceResult:
    """
    Build or retrieve a real-road driver x order dispatch matrix.

    Pipeline:

        GPS coordinates
            ->
        coordinate validation
            ->
        graph-node snapping
            ->
        deterministic cache key
            ->
        cache lookup
            ->
        source-wise road-distance computation on cache miss
            ->
        cache write
            ->
        matrix result + telemetry
    """

    total_started_at = perf_counter()

    normalized_drivers = _validate_coordinates(
        name="drivers",
        coordinates=drivers,
    )

    normalized_orders = _validate_coordinates(
        name="orders",
        coordinates=orders,
    )

    _validate_dependencies(
        dependencies
    )

    _validate_cache_ttl(
        cache_ttl_seconds
    )

    _validate_unreachable_cost(
        unreachable_cost_m
    )

    # ------------------------------------------------------------------
    # 1. Snap GPS coordinates to graph nodes.
    # ------------------------------------------------------------------

    snap_started_at = perf_counter()

    request_snap_cache: dict[
        tuple[float, float],
        NodeId,
    ] = {}

    snapped_drivers = await _snap_locations(
        coordinates=normalized_drivers,
        snap_node=dependencies.snap_node,
        request_snap_cache=request_snap_cache,
    )

    snapped_orders = await _snap_locations(
        coordinates=normalized_orders,
        snap_node=dependencies.snap_node,
        request_snap_cache=request_snap_cache,
    )

    snap_time_ms = _elapsed_ms(
        snap_started_at
    )

    driver_nodes = tuple(
        item.node_id
        for item in snapped_drivers
    )

    order_nodes = tuple(
        item.node_id
        for item in snapped_orders
    )

    # ------------------------------------------------------------------
    # 2. Configure cache behavior.
    # ------------------------------------------------------------------

    cache_available = (
        dependencies.cache_get is not None
        and dependencies.cache_set is not None
    )

    if use_cache and not cache_available:
        raise DispatchRoadMatrixServiceError(
            "use_cache=True requires both cache_get "
            "and cache_set dependencies."
        )

    cache_used = bool(
        use_cache
        and cache_available
    )

    cache_status: CacheStatus = "disabled"

    cache_hits = 0
    cache_misses = 0

    cache_error: str | None = None
    cache_key: str | None = None

    cache_lookup_time_ms = 0.0
    cache_write_time_ms = 0.0

    # ------------------------------------------------------------------
    # 3. Cache lookup.
    # ------------------------------------------------------------------

    if cache_used:
        cache_key_builder = (
            dependencies.cache_key_builder
            or build_dispatch_road_matrix_cache_key
        )

        cache_key = cache_key_builder(
            driver_nodes,
            order_nodes,
            float(unreachable_cost_m),
        )

        lookup_started_at = perf_counter()

        try:
            cached_value = await _maybe_await(
                dependencies.cache_get(  # type: ignore[misc]
                    cache_key
                )
            )

        except Exception as exc:
            cache_lookup_time_ms = _elapsed_ms(
                lookup_started_at
            )

            if not fail_open_on_cache_error:
                raise DispatchRoadMatrixServiceError(
                    "Dispatch road-matrix cache lookup failed: "
                    f"{exc}"
                ) from exc

            cache_error = (
                f"cache_get_failed: {exc}"
            )

            cached_value = None

        else:
            cache_lookup_time_ms = _elapsed_ms(
                lookup_started_at
            )

        if cached_value is not None:
            try:
                cached_matrix = (
                    _deserialize_matrix_result(
                        cached_value,
                        expected_driver_nodes=driver_nodes,
                        expected_order_nodes=order_nodes,
                        expected_unreachable_cost_m=(
                            float(unreachable_cost_m)
                        ),
                    )
                )

            except Exception as exc:
                if not fail_open_on_cache_error:
                    raise DispatchRoadMatrixServiceError(
                        "Invalid cached road-matrix payload: "
                        f"{exc}"
                    ) from exc

                cache_error = _merge_cache_error(
                    cache_error,
                    f"invalid_cache_payload: {exc}",
                )

            else:
                cache_status = "hit"
                cache_hits = 1

                return DispatchRoadMatrixServiceResult(
                    matrix_result=cached_matrix,
                    snapped_drivers=snapped_drivers,
                    snapped_orders=snapped_orders,
                    matrix_algorithm="source_dijkstra",
                    matrix_source="cache",
                    cache_used=True,
                    cache_status=cache_status,
                    cache_hits=cache_hits,
                    cache_misses=cache_misses,
                    cache_key=cache_key,
                    cache_error=cache_error,
                    snap_time_ms=snap_time_ms,
                    cache_lookup_time_ms=(
                        cache_lookup_time_ms
                    ),
                    cache_write_time_ms=0.0,
                    matrix_generation_time_ms=0.0,
                    total_time_ms=_elapsed_ms(
                        total_started_at
                    ),
                )

        cache_status = "miss"
        cache_misses = 1

    # ------------------------------------------------------------------
    # 4. Compute real-road matrix.
    # ------------------------------------------------------------------

    matrix_started_at = perf_counter()

    try:
        matrix_result = await asyncio.to_thread(
            build_dispatch_road_cost_matrix,
            driver_nodes=driver_nodes,
            order_nodes=order_nodes,
            source_distance_builder=(
                dependencies.source_distance_builder
            ),
            unreachable_cost_m=(
                float(unreachable_cost_m)
            ),
        )

    except Exception as exc:
        raise DispatchRoadMatrixServiceError(
            "Real-road dispatch matrix generation failed: "
            f"{exc}"
        ) from exc

    matrix_generation_time_ms = _elapsed_ms(
        matrix_started_at
    )

    # ------------------------------------------------------------------
    # 5. Write computed result to cache.
    # ------------------------------------------------------------------

    if (
        cache_used
        and cache_key is not None
    ):
        cache_payload = _serialize_matrix_result(
            matrix_result
        )

        write_started_at = perf_counter()

        try:
            await _maybe_await(
                dependencies.cache_set(  # type: ignore[misc]
                    cache_key,
                    cache_payload,
                    cache_ttl_seconds,
                )
            )

        except Exception as exc:
            cache_write_time_ms = _elapsed_ms(
                write_started_at
            )

            if not fail_open_on_cache_error:
                raise DispatchRoadMatrixServiceError(
                    "Dispatch road-matrix cache write failed: "
                    f"{exc}"
                ) from exc

            cache_error = _merge_cache_error(
                cache_error,
                f"cache_set_failed: {exc}",
            )

        else:
            cache_write_time_ms = _elapsed_ms(
                write_started_at
            )

    return DispatchRoadMatrixServiceResult(
        matrix_result=matrix_result,
        snapped_drivers=snapped_drivers,
        snapped_orders=snapped_orders,
        matrix_algorithm="source_dijkstra",
        matrix_source="computed",
        cache_used=cache_used,
        cache_status=cache_status,
        cache_hits=cache_hits,
        cache_misses=cache_misses,
        cache_key=cache_key,
        cache_error=cache_error,
        snap_time_ms=snap_time_ms,
        cache_lookup_time_ms=(
            cache_lookup_time_ms
        ),
        cache_write_time_ms=(
            cache_write_time_ms
        ),
        matrix_generation_time_ms=(
            matrix_generation_time_ms
        ),
        total_time_ms=_elapsed_ms(
            total_started_at
        ),
    )


async def _snap_locations(
    *,
    coordinates: Sequence[GeoCoordinate],
    snap_node: SnapNodeFn,
    request_snap_cache: dict[
        tuple[float, float],
        NodeId,
    ],
) -> tuple[SnappedDispatchLocation, ...]:
    """
    Snap coordinates to graph nodes.

    Duplicate coordinates in the same request reuse their already-snapped
    node ID.
    """

    snapped: list[
        SnappedDispatchLocation
    ] = []

    for index, coordinate in enumerate(
        coordinates
    ):
        coordinate_key = (
            coordinate.lat,
            coordinate.lon,
        )

        if coordinate_key in request_snap_cache:
            node_id = request_snap_cache[
                coordinate_key
            ]

        else:
            try:
                raw_node_id = await _maybe_await(
                    snap_node(
                        coordinate.lat,
                        coordinate.lon,
                    )
                )

            except Exception as exc:
                raise DispatchRoadMatrixServiceError(
                    "Failed to snap dispatch coordinate "
                    f"index={index}, "
                    f"lat={coordinate.lat}, "
                    f"lon={coordinate.lon}: "
                    f"{exc}"
                ) from exc

            node_id = _validate_snapped_node_id(
                raw_node_id
            )

            request_snap_cache[
                coordinate_key
            ] = node_id

        snapped.append(
            SnappedDispatchLocation(
                original_index=index,
                lat=coordinate.lat,
                lon=coordinate.lon,
                node_id=node_id,
            )
        )

    return tuple(snapped)


def _serialize_matrix_result(
    result: RoadDispatchCostMatrixResult,
) -> str:
    """Serialize a road matrix into a Redis-safe JSON payload."""

    payload = {
        "version": CACHE_PAYLOAD_VERSION,
        "matrix_algorithm": "source_dijkstra",
        "cost_matrix_m": [
            list(row)
            for row in result.cost_matrix_m
        ],
        "reachable_matrix": [
            list(row)
            for row in result.reachable_matrix
        ],
        "driver_nodes": list(
            result.driver_nodes
        ),
        "order_nodes": list(
            result.order_nodes
        ),
        "driver_count": result.driver_count,
        "order_count": result.order_count,
        "unique_driver_node_count": (
            result.unique_driver_node_count
        ),
        "unique_order_node_count": (
            result.unique_order_node_count
        ),
        "source_search_count": (
            result.source_search_count
        ),
        "reachable_pair_count": (
            result.reachable_pair_count
        ),
        "unreachable_pair_count": (
            result.unreachable_pair_count
        ),
        "unreachable_pairs": [
            {
                "driver_index": (
                    pair.driver_index
                ),
                "order_index": (
                    pair.order_index
                ),
                "driver_node": (
                    pair.driver_node
                ),
                "order_node": (
                    pair.order_node
                ),
                "replacement_cost_m": (
                    pair.replacement_cost_m
                ),
            }
            for pair
            in result.unreachable_pairs
        ],
        "unreachable_cost_m": (
            result.unreachable_cost_m
        ),
        "build_time_ms": (
            result.build_time_ms
        ),
    }

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _deserialize_matrix_result(
    cached_value: Any,
    *,
    expected_driver_nodes: Sequence[NodeId],
    expected_order_nodes: Sequence[NodeId],
    expected_unreachable_cost_m: float,
) -> RoadDispatchCostMatrixResult:
    """Restore and validate one cached road-matrix payload."""

    payload = _decode_cache_payload(
        cached_value
    )

    version = payload.get(
        "version"
    )

    if version != CACHE_PAYLOAD_VERSION:
        raise ValueError(
            "Unsupported cache payload version: "
            f"expected={CACHE_PAYLOAD_VERSION}, "
            f"actual={version!r}."
        )

    if (
        payload.get("matrix_algorithm")
        != "source_dijkstra"
    ):
        raise ValueError(
            "Cached payload is not a "
            "source_dijkstra road matrix."
        )

    driver_nodes = tuple(
        _validate_cached_node_id(node)
        for node in payload[
            "driver_nodes"
        ]
    )

    order_nodes = tuple(
        _validate_cached_node_id(node)
        for node in payload[
            "order_nodes"
        ]
    )

    if driver_nodes != tuple(
        expected_driver_nodes
    ):
        raise ValueError(
            "Cached driver-node ordering does not "
            "match the current request."
        )

    if order_nodes != tuple(
        expected_order_nodes
    ):
        raise ValueError(
            "Cached order-node ordering does not "
            "match the current request."
        )

    unreachable_cost_m = float(
        payload[
            "unreachable_cost_m"
        ]
    )

    if not math.isclose(
        unreachable_cost_m,
        expected_unreachable_cost_m,
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        raise ValueError(
            "Cached unreachable-cost policy does not "
            "match the current request."
        )

    cost_matrix = tuple(
        tuple(
            float(value)
            for value in row
        )
        for row in payload[
            "cost_matrix_m"
        ]
    )

    reachable_matrix = tuple(
        tuple(
            bool(value)
            for value in row
        )
        for row in payload[
            "reachable_matrix"
        ]
    )

    driver_count = len(
        driver_nodes
    )

    order_count = len(
        order_nodes
    )

    _validate_cached_matrix_shape(
        cost_matrix=cost_matrix,
        reachable_matrix=reachable_matrix,
        driver_count=driver_count,
        order_count=order_count,
    )

    unreachable_pairs = tuple(
        UnreachableRoadPair(
            driver_index=int(
                item[
                    "driver_index"
                ]
            ),
            order_index=int(
                item[
                    "order_index"
                ]
            ),
            driver_node=(
                _validate_cached_node_id(
                    item[
                        "driver_node"
                    ]
                )
            ),
            order_node=(
                _validate_cached_node_id(
                    item[
                        "order_node"
                    ]
                )
            ),
            replacement_cost_m=float(
                item[
                    "replacement_cost_m"
                ]
            ),
        )
        for item in payload.get(
            "unreachable_pairs",
            [],
        )
    )

    reachable_pair_count = sum(
        1
        for row in reachable_matrix
        for reachable in row
        if reachable
    )

    unreachable_pair_count = (
        driver_count
        * order_count
        - reachable_pair_count
    )

    if (
        unreachable_pair_count
        != len(unreachable_pairs)
    ):
        raise ValueError(
            "Cached unreachable-pair metadata is "
            "inconsistent with reachable_matrix."
        )

    return RoadDispatchCostMatrixResult(
        cost_matrix_m=cost_matrix,
        reachable_matrix=reachable_matrix,
        driver_nodes=driver_nodes,
        order_nodes=order_nodes,
        driver_count=driver_count,
        order_count=order_count,
        unique_driver_node_count=len(
            dict.fromkeys(
                driver_nodes
            )
        ),
        unique_order_node_count=len(
            dict.fromkeys(
                order_nodes
            )
        ),
        source_search_count=int(
            payload.get(
                "source_search_count",
                len(
                    dict.fromkeys(
                        driver_nodes
                    )
                ),
            )
        ),
        reachable_pair_count=(
            reachable_pair_count
        ),
        unreachable_pair_count=(
            unreachable_pair_count
        ),
        unreachable_pairs=(
            unreachable_pairs
        ),
        unreachable_cost_m=(
            unreachable_cost_m
        ),
        build_time_ms=float(
            payload.get(
                "build_time_ms",
                0.0,
            )
        ),
    )


def _decode_cache_payload(
    cached_value: Any,
) -> dict[str, Any]:
    """Decode a Redis cache payload into a dictionary."""

    if isinstance(
        cached_value,
        dict,
    ):
        return cached_value

    if isinstance(
        cached_value,
        bytes,
    ):
        cached_value = (
            cached_value.decode(
                "utf-8"
            )
        )

    if isinstance(
        cached_value,
        str,
    ):
        decoded = json.loads(
            cached_value
        )

        if not isinstance(
            decoded,
            dict,
        ):
            raise ValueError(
                "Decoded cache payload must be "
                "a JSON object."
            )

        return decoded

    raise TypeError(
        "Cache payload must be dict, str, or bytes; "
        f"received "
        f"{type(cached_value).__name__}."
    )


def _validate_cached_matrix_shape(
    *,
    cost_matrix: tuple[
        tuple[float, ...],
        ...,
    ],
    reachable_matrix: tuple[
        tuple[bool, ...],
        ...,
    ],
    driver_count: int,
    order_count: int,
) -> None:
    """Validate cached matrix dimensions and numeric values."""

    if len(
        cost_matrix
    ) != driver_count:
        raise ValueError(
            "Cached cost matrix has an "
            "invalid row count."
        )

    if len(
        reachable_matrix
    ) != driver_count:
        raise ValueError(
            "Cached reachability matrix has an "
            "invalid row count."
        )

    for row_index, row in enumerate(
        cost_matrix
    ):
        if len(
            row
        ) != order_count:
            raise ValueError(
                "Cached cost matrix has an invalid "
                "column count at row "
                f"{row_index}."
            )

        for value in row:
            if (
                not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(
                    "Cached cost matrix contains "
                    "an invalid cost."
                )

    for row_index, row in enumerate(
        reachable_matrix
    ):
        if len(
            row
        ) != order_count:
            raise ValueError(
                "Cached reachability matrix has an "
                "invalid column count at row "
                f"{row_index}."
            )


def _validate_coordinates(
    *,
    name: str,
    coordinates: Sequence[
        GeoCoordinate
    ],
) -> tuple[
    GeoCoordinate,
    ...,
]:
    """Validate one coordinate collection."""

    if isinstance(
        coordinates,
        (
            str,
            bytes,
            bytearray,
        ),
    ):
        raise TypeError(
            f"{name} must be a sequence of "
            "GeoCoordinate objects."
        )

    normalized = tuple(
        coordinates
    )

    if not normalized:
        raise ValueError(
            f"{name} must contain at least "
            "one coordinate."
        )

    for index, coordinate in enumerate(
        normalized
    ):
        if not isinstance(
            coordinate,
            GeoCoordinate,
        ):
            raise TypeError(
                f"{name}[{index}] must be "
                "GeoCoordinate; received "
                f"{type(coordinate).__name__}."
            )

        _validate_lat_lon(
            name=(
                f"{name}[{index}]"
            ),
            lat=coordinate.lat,
            lon=coordinate.lon,
        )

    return normalized


def _validate_lat_lon(
    *,
    name: str,
    lat: float,
    lon: float,
) -> None:
    """Validate latitude and longitude values."""

    if (
        isinstance(lat, bool)
        or isinstance(lon, bool)
    ):
        raise TypeError(
            f"{name} latitude and longitude "
            "must be numeric."
        )

    try:
        normalized_lat = float(
            lat
        )

        normalized_lon = float(
            lon
        )

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise TypeError(
            f"{name} latitude and longitude "
            "must be numeric."
        ) from exc

    if not math.isfinite(
        normalized_lat
    ):
        raise ValueError(
            f"{name}.lat must be finite."
        )

    if not math.isfinite(
        normalized_lon
    ):
        raise ValueError(
            f"{name}.lon must be finite."
        )

    if not (
        -90.0
        <= normalized_lat
        <= 90.0
    ):
        raise ValueError(
            f"{name}.lat must be between "
            "-90 and 90."
        )

    if not (
        -180.0
        <= normalized_lon
        <= 180.0
    ):
        raise ValueError(
            f"{name}.lon must be between "
            "-180 and 180."
        )


def _validate_dependencies(
    dependencies: DispatchRoadMatrixDependencies,
) -> None:
    """Validate injected service dependencies."""

    if not callable(
        dependencies.snap_node
    ):
        raise TypeError(
            "dependencies.snap_node must "
            "be callable."
        )

    if not callable(
        dependencies.source_distance_builder
    ):
        raise TypeError(
            "dependencies.source_distance_builder "
            "must be callable."
        )

    if (
        dependencies.cache_get is not None
        and not callable(
            dependencies.cache_get
        )
    ):
        raise TypeError(
            "dependencies.cache_get must be "
            "callable or None."
        )

    if (
        dependencies.cache_set is not None
        and not callable(
            dependencies.cache_set
        )
    ):
        raise TypeError(
            "dependencies.cache_set must be "
            "callable or None."
        )

    if (
        dependencies.cache_key_builder
        is not None
        and not callable(
            dependencies.cache_key_builder
        )
    ):
        raise TypeError(
            "dependencies.cache_key_builder must "
            "be callable or None."
        )


def _validate_cache_ttl(
    cache_ttl_seconds: int,
) -> None:
    """Validate cache TTL."""

    if (
        isinstance(
            cache_ttl_seconds,
            bool,
        )
        or not isinstance(
            cache_ttl_seconds,
            int,
        )
    ):
        raise TypeError(
            "cache_ttl_seconds must be "
            "an integer."
        )

    if cache_ttl_seconds <= 0:
        raise ValueError(
            "cache_ttl_seconds must be "
            "greater than zero."
        )


def _validate_unreachable_cost(
    unreachable_cost_m: float,
) -> None:
    """Validate the finite unreachable-pair replacement cost."""

    if isinstance(
        unreachable_cost_m,
        bool,
    ):
        raise TypeError(
            "unreachable_cost_m must "
            "be numeric."
        )

    try:
        normalized = float(
            unreachable_cost_m
        )

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise TypeError(
            "unreachable_cost_m must "
            "be numeric."
        ) from exc

    if not math.isfinite(
        normalized
    ):
        raise ValueError(
            "unreachable_cost_m must "
            "be finite."
        )

    if normalized <= 0:
        raise ValueError(
            "unreachable_cost_m must be "
            "greater than zero."
        )


def _validate_snapped_node_id(
    node_id: Any,
) -> NodeId:
    """Validate a graph node ID returned by the snapping adapter."""

    if (
        isinstance(
            node_id,
            bool,
        )
        or not isinstance(
            node_id,
            int,
        )
    ):
        raise DispatchRoadMatrixServiceError(
            "snap_node must return an integer "
            "graph node ID; received "
            f"{type(node_id).__name__}."
        )

    return node_id


def _validate_cached_node_id(
    node_id: Any,
) -> NodeId:
    """Validate one cached graph node ID."""

    if (
        isinstance(
            node_id,
            bool,
        )
        or not isinstance(
            node_id,
            int,
        )
    ):
        raise ValueError(
            "Cached graph node IDs must "
            "be integers."
        )

    return node_id


async def _maybe_await(
    value: Any,
) -> Any:
    """
    Support both synchronous and asynchronous infrastructure adapters.
    """

    if inspect.isawaitable(
        value
    ):
        return await value

    return value


def _merge_cache_error(
    existing: str | None,
    new_error: str,
) -> str:
    """Combine multiple cache errors without losing earlier evidence."""

    if existing is None:
        return new_error

    return (
        f"{existing}; "
        f"{new_error}"
    )


def _elapsed_ms(
    started_at: float,
) -> float:
    """Return elapsed milliseconds rounded for stable telemetry."""

    return round(
        (
            perf_counter()
            - started_at
        )
        * 1000.0,
        6,
    )


__all__ = [
    "DispatchRoadMatrixDependencies",
    "DispatchRoadMatrixServiceError",
    "DispatchRoadMatrixServiceResult",
    "GeoCoordinate",
    "SnappedDispatchLocation",
    "build_dispatch_road_matrix",
]