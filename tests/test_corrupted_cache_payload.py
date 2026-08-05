# tests/test_corrupted_cache_payload.py

from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from typing import Any

import pytest

from app.infrastructure.redis_resilience import (
    RedisAvailability,
    RedisFailureReason,
    RedisRecoveryController,
)
from app.infrastructure.resilience_state import ResilienceState
from app.services.dispatch_road_matrix_service import (
    DispatchRoadMatrixDependencies,
    DispatchRoadMatrixServiceError,
    GeoCoordinate,
    build_dispatch_road_matrix,
)


@pytest.fixture
def anyio_backend() -> str:
    """Run asynchronous cache tests with asyncio."""

    return "asyncio"


DRIVERS = (
    GeoCoordinate(lat=26.44, lon=80.30),
    GeoCoordinate(lat=26.45, lon=80.31),
)

ORDERS = (
    GeoCoordinate(lat=26.46, lon=80.32),
    GeoCoordinate(lat=26.47, lon=80.33),
)

NODE_LOOKUP = {
    (26.44, 80.30): 101,
    (26.45, 80.31): 102,
    (26.46, 80.32): 201,
    (26.47, 80.33): 202,
}

UNREACHABLE_COST_M = 1_000_000_000.0


class FakeCache:
    """Controllable raw cache used by the road-matrix service."""

    def __init__(
        self,
        value: Any = None,
    ) -> None:
        self.value = value

        self.get_calls = 0
        self.set_calls = 0

        self.last_get_key: str | None = None
        self.last_set_key: str | None = None
        self.last_set_value: str | None = None
        self.last_set_ttl_seconds: int | None = None

        self.get_error: BaseException | None = None
        self.set_error: BaseException | None = None

    async def get(
        self,
        key: str,
    ) -> Any:
        self.get_calls += 1
        self.last_get_key = key

        if self.get_error is not None:
            raise self.get_error

        return self.value

    async def set(
        self,
        key: str,
        value: str,
        ttl_seconds: int,
    ) -> bool:
        self.set_calls += 1

        self.last_set_key = key
        self.last_set_value = value
        self.last_set_ttl_seconds = ttl_seconds

        if self.set_error is not None:
            raise self.set_error

        self.value = value
        return True


class CountingDistanceBuilder:
    """Deterministic source-distance builder with call telemetry."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(
        self,
        source_node: int,
        target_nodes: tuple[int, ...] | list[int],
    ) -> dict[int, float]:
        self.calls += 1

        return {
            int(target_node): float(
                abs(source_node - int(target_node)) * 10
                + 5
            )
            for target_node in target_nodes
        }


def _snap_node(
    lat: float,
    lon: float,
) -> int:
    return NODE_LOOKUP[(lat, lon)]


def _cache_key_builder(
    driver_nodes: tuple[int, ...] | list[int],
    order_nodes: tuple[int, ...] | list[int],
    unreachable_cost_m: float,
) -> str:
    assert tuple(driver_nodes) == (101, 102)
    assert tuple(order_nodes) == (201, 202)
    assert unreachable_cost_m == UNREACHABLE_COST_M

    return "cityroute:test:corrupted-cache-payload"


def _dependencies(
    cache: FakeCache,
    distance_builder: CountingDistanceBuilder,
) -> DispatchRoadMatrixDependencies:
    return DispatchRoadMatrixDependencies(
        snap_node=_snap_node,
        source_distance_builder=distance_builder,
        cache_get=cache.get,
        cache_set=cache.set,
        cache_key_builder=_cache_key_builder,
    )


def _valid_payload() -> dict[str, Any]:
    return {
        "version": 1,
        "matrix_algorithm": "source_dijkstra",
        "cost_matrix_m": [
            [1005.0, 1015.0],
            [995.0, 1005.0],
        ],
        "reachable_matrix": [
            [True, True],
            [True, True],
        ],
        "driver_nodes": [101, 102],
        "order_nodes": [201, 202],
        "driver_count": 2,
        "order_count": 2,
        "unique_driver_node_count": 2,
        "unique_order_node_count": 2,
        "source_search_count": 2,
        "reachable_pair_count": 4,
        "unreachable_pair_count": 0,
        "unreachable_pairs": [],
        "unreachable_cost_m": UNREACHABLE_COST_M,
        "build_time_ms": 1.25,
    }


async def _build(
    *,
    cache: FakeCache,
    distance_builder: CountingDistanceBuilder,
    fail_open_on_cache_error: bool = True,
):
    return await build_dispatch_road_matrix(
        drivers=DRIVERS,
        orders=ORDERS,
        dependencies=_dependencies(
            cache,
            distance_builder,
        ),
        use_cache=True,
        cache_ttl_seconds=600,
        unreachable_cost_m=UNREACHABLE_COST_M,
        fail_open_on_cache_error=(
            fail_open_on_cache_error
        ),
    )


@pytest.mark.anyio
async def test_invalid_json_fails_open_rebuilds_and_repairs_cache(
) -> None:
    cache = FakeCache(
        value="{this-is-not-valid-json"
    )
    distance_builder = CountingDistanceBuilder()

    result = await _build(
        cache=cache,
        distance_builder=distance_builder,
    )

    assert result.matrix_source == "computed"
    assert result.cache_used is True
    assert result.cache_status == "miss"
    assert result.cache_hits == 0
    assert result.cache_misses == 1

    assert result.cache_error is not None
    assert "invalid_cache_payload" in result.cache_error

    assert distance_builder.calls == 2

    assert cache.get_calls == 1
    assert cache.set_calls == 1
    assert cache.last_set_ttl_seconds == 600
    assert cache.last_set_key == (
        "cityroute:test:corrupted-cache-payload"
    )

    assert cache.last_set_value is not None

    repaired_payload = json.loads(
        cache.last_set_value
    )

    assert repaired_payload["version"] == 1
    assert (
        repaired_payload["matrix_algorithm"]
        == "source_dijkstra"
    )
    assert repaired_payload["driver_nodes"] == [101, 102]
    assert repaired_payload["order_nodes"] == [201, 202]

    calls_after_repair = distance_builder.calls

    cached_result = await _build(
        cache=cache,
        distance_builder=distance_builder,
    )

    assert cached_result.matrix_source == "cache"
    assert cached_result.cache_status == "hit"
    assert cached_result.cache_hits == 1
    assert cached_result.cache_misses == 0
    assert cached_result.cache_error is None

    # The repaired cache prevents another Dijkstra matrix build.
    assert distance_builder.calls == calls_after_repair


def _json_array_payload() -> str:
    return json.dumps(
        [
            "not",
            "a",
            "matrix-object",
        ]
    )


def _unsupported_type_payload() -> object:
    return object()


def _unsupported_version_payload() -> dict[str, Any]:
    payload = _valid_payload()
    payload["version"] = 999
    return payload


def _wrong_algorithm_payload() -> dict[str, Any]:
    payload = _valid_payload()
    payload["matrix_algorithm"] = "haversine"
    return payload


def _wrong_driver_order_payload() -> dict[str, Any]:
    payload = _valid_payload()
    payload["driver_nodes"] = [102, 101]
    return payload


def _negative_cost_payload() -> dict[str, Any]:
    payload = _valid_payload()
    payload["cost_matrix_m"][0][0] = -1.0
    return payload


def _invalid_row_count_payload() -> dict[str, Any]:
    payload = _valid_payload()
    payload["cost_matrix_m"] = [
        [1005.0, 1015.0],
    ]
    return payload


def _inconsistent_unreachable_metadata_payload(
) -> dict[str, Any]:
    payload = _valid_payload()

    payload["cost_matrix_m"][0][0] = (
        UNREACHABLE_COST_M
    )
    payload["reachable_matrix"][0][0] = False

    # Deliberately leave unreachable_pairs empty.
    payload["unreachable_pairs"] = []

    return payload


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload_factory",
    [
        pytest.param(
            _json_array_payload,
            id="json-array",
        ),
        pytest.param(
            _unsupported_type_payload,
            id="unsupported-python-type",
        ),
        pytest.param(
            _unsupported_version_payload,
            id="unsupported-version",
        ),
        pytest.param(
            _wrong_algorithm_payload,
            id="wrong-algorithm",
        ),
        pytest.param(
            _wrong_driver_order_payload,
            id="wrong-driver-order",
        ),
        pytest.param(
            _negative_cost_payload,
            id="negative-cost",
        ),
        pytest.param(
            _invalid_row_count_payload,
            id="invalid-row-count",
        ),
        pytest.param(
            _inconsistent_unreachable_metadata_payload,
            id="inconsistent-unreachable-metadata",
        ),
    ],
)
async def test_corrupted_payload_variants_are_treated_as_misses(
    payload_factory: Callable[[], Any],
) -> None:
    cache = FakeCache(
        value=payload_factory()
    )
    distance_builder = CountingDistanceBuilder()

    result = await _build(
        cache=cache,
        distance_builder=distance_builder,
    )

    assert result.matrix_source == "computed"
    assert result.cache_status == "miss"
    assert result.cache_hits == 0
    assert result.cache_misses == 1

    assert result.cache_error is not None
    assert "invalid_cache_payload" in result.cache_error

    assert distance_builder.calls == 2
    assert cache.get_calls == 1
    assert cache.set_calls == 1

    assert isinstance(cache.value, str)

    repaired_payload = json.loads(cache.value)

    assert repaired_payload["version"] == 1
    assert (
        repaired_payload["matrix_algorithm"]
        == "source_dijkstra"
    )


@pytest.mark.anyio
async def test_corrupted_payload_fails_closed_when_configured(
) -> None:
    cache = FakeCache(
        value="{invalid-json"
    )
    distance_builder = CountingDistanceBuilder()

    with pytest.raises(
        DispatchRoadMatrixServiceError,
        match="Invalid cached road-matrix payload",
    ):
        await _build(
            cache=cache,
            distance_builder=distance_builder,
            fail_open_on_cache_error=False,
        )

    assert cache.get_calls == 1
    assert cache.set_calls == 0
    assert distance_builder.calls == 0


@pytest.mark.anyio
async def test_valid_dictionary_payload_is_a_cache_hit() -> None:
    cache = FakeCache(
        value=deepcopy(_valid_payload())
    )
    distance_builder = CountingDistanceBuilder()

    result = await _build(
        cache=cache,
        distance_builder=distance_builder,
    )

    assert result.matrix_source == "cache"
    assert result.cache_status == "hit"
    assert result.cache_hits == 1
    assert result.cache_misses == 0
    assert result.cache_error is None

    assert result.matrix_result.driver_nodes == (101, 102)
    assert result.matrix_result.order_nodes == (201, 202)
    assert result.matrix_result.cost_matrix_m == (
        (1005.0, 1015.0),
        (995.0, 1005.0),
    )

    assert cache.get_calls == 1
    assert cache.set_calls == 0
    assert distance_builder.calls == 0


@pytest.mark.anyio
async def test_valid_utf8_bytes_payload_is_a_cache_hit() -> None:
    cache = FakeCache(
        value=json.dumps(
            _valid_payload()
        ).encode("utf-8")
    )
    distance_builder = CountingDistanceBuilder()

    result = await _build(
        cache=cache,
        distance_builder=distance_builder,
    )

    assert result.matrix_source == "cache"
    assert result.cache_status == "hit"
    assert result.cache_error is None

    assert cache.set_calls == 0
    assert distance_builder.calls == 0


@pytest.mark.anyio
async def test_corrupt_payload_and_write_failure_are_both_reported(
) -> None:
    cache = FakeCache(
        value="{invalid-json"
    )
    cache.set_error = ConnectionError(
        "Redis write unavailable"
    )

    distance_builder = CountingDistanceBuilder()

    result = await _build(
        cache=cache,
        distance_builder=distance_builder,
    )

    assert result.matrix_source == "computed"
    assert result.cache_status == "miss"

    assert result.cache_error is not None
    assert "invalid_cache_payload" in result.cache_error
    assert "cache_set_failed" in result.cache_error
    assert "Redis write unavailable" in result.cache_error

    assert distance_builder.calls == 2
    assert cache.get_calls == 1
    assert cache.set_calls == 1


@pytest.mark.anyio
async def test_redis_controller_records_corrupted_payload_and_recovers(
) -> None:
    state = ResilienceState()

    async def healthy_redis() -> bool:
        return True

    controller = RedisRecoveryController(
        resilience_state=state,
        health_check=healthy_redis,
        fail_open_enabled=True,
    )

    assert await controller.initialize() is True

    await controller.mark_corrupted_payload(
        detail=(
            "Dispatch road-matrix cache contained "
            "malformed JSON"
        ),
    )

    degraded = await controller.snapshot()
    degraded_state = await state.snapshot()

    assert degraded.availability == (
        RedisAvailability.DEGRADED
    )
    assert degraded.available is False
    assert degraded.degraded is True
    assert degraded.last_failure_reason == (
        RedisFailureReason.CORRUPTED_PAYLOAD
    )
    assert degraded.last_failure_detail == (
        "Dispatch road-matrix cache contained "
        "malformed JSON"
    )

    assert degraded_state.redis == "not_ready"
    assert degraded_state.last_redis_failure_reason is not None

    await controller.mark_success()

    recovered = await controller.snapshot()
    recovered_state = await state.snapshot()

    assert recovered.availability == (
        RedisAvailability.AVAILABLE
    )
    assert recovered.available is True
    assert recovered.degraded is False
    assert recovered.last_failure_reason is None
    assert recovered.last_failure_detail is None
    assert recovered.total_recoveries == 1

    assert recovered_state.redis == "ready"