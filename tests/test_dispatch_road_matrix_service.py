# tests/test_dispatch_road_matrix_service.py

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from app.services.dispatch_road_matrix_service import (
    DispatchRoadMatrixDependencies,
    DispatchRoadMatrixServiceError,
    GeoCoordinate,
    build_dispatch_road_matrix,
)


@pytest.fixture
def anyio_backend() -> str:
    """
    Force pytest-anyio to use asyncio only.
    """

    return "asyncio"


class CountingSnapper:
    def __init__(
        self,
        mapping: dict[
            tuple[float, float],
            int,
        ],
    ) -> None:
        self.mapping = mapping

        self.calls: list[
            tuple[float, float]
        ] = []

    def __call__(
        self,
        lat: float,
        lon: float,
    ) -> int:
        key = (
            float(lat),
            float(lon),
        )

        self.calls.append(
            key
        )

        return self.mapping[
            key
        ]


class CountingSourceDistanceBuilder:
    def __init__(
        self,
        distances: dict[
            tuple[int, int],
            float | int | None,
        ],
    ) -> None:
        self.distances = distances

        self.calls: list[
            tuple[
                int,
                tuple[int, ...],
            ]
        ] = []

    def __call__(
        self,
        source_node: int,
        target_nodes: Sequence[int],
    ) -> dict[
        int,
        float | int | None,
    ]:
        normalized_targets = tuple(
            int(
                target_node
            )
            for target_node
            in target_nodes
        )

        self.calls.append(
            (
                int(
                    source_node
                ),
                normalized_targets,
            )
        )

        return {
            target_node: (
                self.distances.get(
                    (
                        int(
                            source_node
                        ),
                        int(
                            target_node
                        ),
                    )
                )
            )
            for target_node
            in normalized_targets
        }


class FakeTextCache:
    def __init__(
        self,
    ) -> None:
        self.store: dict[
            str,
            str,
        ] = {}

        self.get_calls: list[
            str
        ] = []

        self.set_calls: list[
            tuple[
                str,
                str,
                int,
            ]
        ] = []

        self.raise_on_get = False
        self.raise_on_set = False

    def get(
        self,
        key: str,
    ) -> str | None:
        self.get_calls.append(
            key
        )

        if self.raise_on_get:
            raise RuntimeError(
                "simulated cache get failure"
            )

        return self.store.get(
            key
        )

    def set(
        self,
        key: str,
        value: str,
        ttl_seconds: int,
    ) -> bool:
        self.set_calls.append(
            (
                key,
                value,
                ttl_seconds,
            )
        )

        if self.raise_on_set:
            raise RuntimeError(
                "simulated cache set failure"
            )

        self.store[
            key
        ] = value

        return True


class RecordingCacheKeyBuilder:
    def __init__(
        self,
        key: str = "phase10:test:road-matrix",
    ) -> None:
        self.key = key

        self.calls: list[
            tuple[
                tuple[int, ...],
                tuple[int, ...],
                float,
            ]
        ] = []

    def __call__(
        self,
        driver_nodes: Sequence[int],
        order_nodes: Sequence[int],
        unreachable_cost_m: float,
    ) -> str:
        self.calls.append(
            (
                tuple(
                    driver_nodes
                ),
                tuple(
                    order_nodes
                ),
                float(
                    unreachable_cost_m
                ),
            )
        )

        return self.key


def _drivers() -> tuple[
    GeoCoordinate,
    ...,
]:
    return (
        GeoCoordinate(
            lat=26.4500,
            lon=80.3500,
        ),
        GeoCoordinate(
            lat=26.4600,
            lon=80.3600,
        ),
    )


def _orders() -> tuple[
    GeoCoordinate,
    ...,
]:
    return (
        GeoCoordinate(
            lat=26.4700,
            lon=80.3700,
        ),
        GeoCoordinate(
            lat=26.4800,
            lon=80.3800,
        ),
    )


def _snap_mapping() -> dict[
    tuple[float, float],
    int,
]:
    return {
        (
            26.4500,
            80.3500,
        ): 101,
        (
            26.4600,
            80.3600,
        ): 102,
        (
            26.4700,
            80.3700,
        ): 201,
        (
            26.4800,
            80.3800,
        ): 202,
    }


def _distance_mapping() -> dict[
    tuple[int, int],
    float | None,
]:
    return {
        (
            101,
            201,
        ): 1_000.0,
        (
            101,
            202,
        ): 2_000.0,
        (
            102,
            201,
        ): 3_000.0,
        (
            102,
            202,
        ): 4_000.0,
    }


def _matrix_as_lists(
    matrix: Sequence[
        Sequence[
            Any
        ]
    ],
) -> list[
    list[Any]
]:
    return [
        list(
            row
        )
        for row
        in matrix
    ]


@pytest.mark.anyio
async def test_build_dispatch_road_matrix_returns_computed_result_without_cache():
    snapper = CountingSnapper(
        _snap_mapping()
    )

    source_builder = (
        CountingSourceDistanceBuilder(
            _distance_mapping()
        )
    )

    dependencies = (
        DispatchRoadMatrixDependencies(
            snap_node=snapper,
            source_distance_builder=(
                source_builder
            ),
        )
    )

    result = await build_dispatch_road_matrix(
        drivers=_drivers(),
        orders=_orders(),
        dependencies=dependencies,
        use_cache=False,
    )

    assert (
        result.matrix_algorithm
        == "source_dijkstra"
    )

    assert (
        result.matrix_source
        == "computed"
    )

    assert result.cache_used is False

    assert (
        result.cache_status
        == "disabled"
    )

    assert result.cache_hits == 0
    assert result.cache_misses == 0
    assert result.cache_key is None
    assert result.cache_error is None

    assert result.driver_nodes == (
        101,
        102,
    )

    assert result.order_nodes == (
        201,
        202,
    )

    assert (
        result.snapped_driver_count
        == 2
    )

    assert (
        result.snapped_order_count
        == 2
    )

    assert _matrix_as_lists(
        result.matrix_result.cost_matrix_m
    ) == [
        [
            1_000.0,
            2_000.0,
        ],
        [
            3_000.0,
            4_000.0,
        ],
    ]

    assert _matrix_as_lists(
        result.matrix_result.reachable_matrix
    ) == [
        [
            True,
            True,
        ],
        [
            True,
            True,
        ],
    ]


@pytest.mark.anyio
async def test_build_dispatch_road_matrix_snaps_each_unique_coordinate_once():
    shared_coordinate = (
        26.4500,
        80.3500,
    )

    snapper = CountingSnapper(
        {
            shared_coordinate: 101,
            (
                26.4600,
                80.3600,
            ): 102,
        }
    )

    source_builder = (
        CountingSourceDistanceBuilder(
            {
                (
                    101,
                    101,
                ): 0.0,
                (
                    101,
                    102,
                ): 500.0,
            }
        )
    )

    result = await build_dispatch_road_matrix(
        drivers=(
            GeoCoordinate(
                lat=26.4500,
                lon=80.3500,
            ),
            GeoCoordinate(
                lat=26.4500,
                lon=80.3500,
            ),
        ),
        orders=(
            GeoCoordinate(
                lat=26.4500,
                lon=80.3500,
            ),
            GeoCoordinate(
                lat=26.4600,
                lon=80.3600,
            ),
        ),
        dependencies=(
            DispatchRoadMatrixDependencies(
                snap_node=snapper,
                source_distance_builder=(
                    source_builder
                ),
            )
        ),
        use_cache=False,
    )

    assert len(
        snapper.calls
    ) == 2

    assert snapper.calls == [
        (
            26.4500,
            80.3500,
        ),
        (
            26.4600,
            80.3600,
        ),
    ]

    assert result.driver_nodes == (
        101,
        101,
    )

    assert result.order_nodes == (
        101,
        102,
    )


@pytest.mark.anyio
async def test_build_dispatch_road_matrix_tracks_unreachable_pairs():
    snapper = CountingSnapper(
        _snap_mapping()
    )

    source_builder = (
        CountingSourceDistanceBuilder(
            {
                (
                    101,
                    201,
                ): 1_000.0,
                (
                    101,
                    202,
                ): None,
                (
                    102,
                    201,
                ): 3_000.0,
                (
                    102,
                    202,
                ): None,
            }
        )
    )

    unreachable_cost_m = (
        1_000_000_000.0
    )

    result = await build_dispatch_road_matrix(
        drivers=_drivers(),
        orders=_orders(),
        dependencies=(
            DispatchRoadMatrixDependencies(
                snap_node=snapper,
                source_distance_builder=(
                    source_builder
                ),
            )
        ),
        use_cache=False,
        unreachable_cost_m=(
            unreachable_cost_m
        ),
    )

    assert (
        result.unreachable_pair_count
        == 2
    )

    assert (
        result.all_pairs_reachable
        is False
    )

    assert _matrix_as_lists(
        result.matrix_result.reachable_matrix
    ) == [
        [
            True,
            False,
        ],
        [
            True,
            False,
        ],
    ]

    assert _matrix_as_lists(
        result.matrix_result.cost_matrix_m
    ) == [
        [
            1_000.0,
            unreachable_cost_m,
        ],
        [
            3_000.0,
            unreachable_cost_m,
        ],
    ]

    assert len(
        result.matrix_result.unreachable_pairs
    ) == 2


@pytest.mark.anyio
async def test_cache_miss_computes_and_writes_matrix():
    snapper = CountingSnapper(
        _snap_mapping()
    )

    source_builder = (
        CountingSourceDistanceBuilder(
            _distance_mapping()
        )
    )

    cache = FakeTextCache()

    key_builder = (
        RecordingCacheKeyBuilder()
    )

    result = await build_dispatch_road_matrix(
        drivers=_drivers(),
        orders=_orders(),
        dependencies=(
            DispatchRoadMatrixDependencies(
                snap_node=snapper,
                source_distance_builder=(
                    source_builder
                ),
                cache_get=cache.get,
                cache_set=cache.set,
                cache_key_builder=(
                    key_builder
                ),
            )
        ),
        use_cache=True,
        cache_ttl_seconds=600,
    )

    assert result.cache_used is True
    assert result.cache_status == "miss"
    assert result.cache_hits == 0
    assert result.cache_misses == 1

    assert (
        result.matrix_source
        == "computed"
    )

    assert (
        result.cache_key
        == "phase10:test:road-matrix"
    )

    assert cache.get_calls == [
        "phase10:test:road-matrix"
    ]

    assert len(
        cache.set_calls
    ) == 1

    assert (
        cache.set_calls[
            0
        ][
            0
        ]
        == "phase10:test:road-matrix"
    )

    assert (
        cache.set_calls[
            0
        ][
            2
        ]
        == 600
    )

    assert (
        "phase10:test:road-matrix"
        in cache.store
    )


@pytest.mark.anyio
async def test_cache_miss_then_warm_hit_returns_identical_matrix():
    snapper = CountingSnapper(
        _snap_mapping()
    )

    source_builder = (
        CountingSourceDistanceBuilder(
            _distance_mapping()
        )
    )

    cache = FakeTextCache()

    dependencies = (
        DispatchRoadMatrixDependencies(
            snap_node=snapper,
            source_distance_builder=(
                source_builder
            ),
            cache_get=cache.get,
            cache_set=cache.set,
            cache_key_builder=(
                RecordingCacheKeyBuilder()
            ),
        )
    )

    first = await build_dispatch_road_matrix(
        drivers=_drivers(),
        orders=_orders(),
        dependencies=dependencies,
        use_cache=True,
        cache_ttl_seconds=600,
    )

    source_call_count_after_first = len(
        source_builder.calls
    )

    second = await build_dispatch_road_matrix(
        drivers=_drivers(),
        orders=_orders(),
        dependencies=dependencies,
        use_cache=True,
        cache_ttl_seconds=600,
    )

    assert first.cache_status == "miss"

    assert (
        first.matrix_source
        == "computed"
    )

    assert second.cache_status == "hit"
    assert second.cache_hits == 1
    assert second.cache_misses == 0

    assert (
        second.matrix_source
        == "cache"
    )

    assert (
        second.matrix_generation_time_ms
        == 0.0
    )

    assert (
        len(
            source_builder.calls
        )
        == source_call_count_after_first
    )

    assert _matrix_as_lists(
        first.matrix_result.cost_matrix_m
    ) == _matrix_as_lists(
        second.matrix_result.cost_matrix_m
    )

    assert _matrix_as_lists(
        first.matrix_result.reachable_matrix
    ) == _matrix_as_lists(
        second.matrix_result.reachable_matrix
    )


@pytest.mark.anyio
async def test_cache_key_builder_receives_snapped_node_order_and_policy():
    snapper = CountingSnapper(
        _snap_mapping()
    )

    source_builder = (
        CountingSourceDistanceBuilder(
            _distance_mapping()
        )
    )

    cache = FakeTextCache()

    key_builder = (
        RecordingCacheKeyBuilder(
            key="custom-key"
        )
    )

    unreachable_cost_m = (
        123_456_789.0
    )

    result = await build_dispatch_road_matrix(
        drivers=_drivers(),
        orders=_orders(),
        dependencies=(
            DispatchRoadMatrixDependencies(
                snap_node=snapper,
                source_distance_builder=(
                    source_builder
                ),
                cache_get=cache.get,
                cache_set=cache.set,
                cache_key_builder=(
                    key_builder
                ),
            )
        ),
        use_cache=True,
        unreachable_cost_m=(
            unreachable_cost_m
        ),
    )

    assert key_builder.calls == [
        (
            (
                101,
                102,
            ),
            (
                201,
                202,
            ),
            unreachable_cost_m,
        )
    ]

    assert result.cache_key == "custom-key"


@pytest.mark.anyio
async def test_cache_disabled_skips_cache_get_set_and_key_builder():
    snapper = CountingSnapper(
        _snap_mapping()
    )

    source_builder = (
        CountingSourceDistanceBuilder(
            _distance_mapping()
        )
    )

    cache = FakeTextCache()

    key_builder = (
        RecordingCacheKeyBuilder()
    )

    result = await build_dispatch_road_matrix(
        drivers=_drivers(),
        orders=_orders(),
        dependencies=(
            DispatchRoadMatrixDependencies(
                snap_node=snapper,
                source_distance_builder=(
                    source_builder
                ),
                cache_get=cache.get,
                cache_set=cache.set,
                cache_key_builder=(
                    key_builder
                ),
            )
        ),
        use_cache=False,
    )

    assert result.cache_used is False
    assert result.cache_status == "disabled"
    assert result.cache_key is None

    assert cache.get_calls == []
    assert cache.set_calls == []
    assert key_builder.calls == []


@pytest.mark.anyio
async def test_use_cache_requires_both_cache_dependencies():
    snapper = CountingSnapper(
        _snap_mapping()
    )

    source_builder = (
        CountingSourceDistanceBuilder(
            _distance_mapping()
        )
    )

    with pytest.raises(
        DispatchRoadMatrixServiceError,
        match=(
            "requires both cache_get "
            "and cache_set"
        ),
    ):
        await build_dispatch_road_matrix(
            drivers=_drivers(),
            orders=_orders(),
            dependencies=(
                DispatchRoadMatrixDependencies(
                    snap_node=snapper,
                    source_distance_builder=(
                        source_builder
                    ),
                    cache_get=lambda key: None,
                    cache_set=None,
                )
            ),
            use_cache=True,
        )


@pytest.mark.anyio
async def test_corrupt_cached_payload_fails_open_and_rebuilds():
    snapper = CountingSnapper(
        _snap_mapping()
    )

    source_builder = (
        CountingSourceDistanceBuilder(
            _distance_mapping()
        )
    )

    cache = FakeTextCache()

    key_builder = (
        RecordingCacheKeyBuilder(
            key="corrupt-key"
        )
    )

    cache.store[
        "corrupt-key"
    ] = "not-valid-json"

    result = await build_dispatch_road_matrix(
        drivers=_drivers(),
        orders=_orders(),
        dependencies=(
            DispatchRoadMatrixDependencies(
                snap_node=snapper,
                source_distance_builder=(
                    source_builder
                ),
                cache_get=cache.get,
                cache_set=cache.set,
                cache_key_builder=(
                    key_builder
                ),
            )
        ),
        use_cache=True,
        fail_open_on_cache_error=True,
    )

    assert result.cache_status == "miss"

    assert (
        result.matrix_source
        == "computed"
    )

    assert result.cache_error is not None

    assert (
        "invalid_cache_payload"
        in result.cache_error
    )

    assert len(
        source_builder.calls
    ) > 0

    assert (
        cache.store[
            "corrupt-key"
        ]
        != "not-valid-json"
    )


@pytest.mark.anyio
async def test_corrupt_cached_payload_fails_closed_when_requested():
    snapper = CountingSnapper(
        _snap_mapping()
    )

    source_builder = (
        CountingSourceDistanceBuilder(
            _distance_mapping()
        )
    )

    cache = FakeTextCache()

    cache.store[
        "corrupt-key"
    ] = "not-valid-json"

    with pytest.raises(
        DispatchRoadMatrixServiceError,
        match=(
            "Invalid cached "
            "road-matrix payload"
        ),
    ):
        await build_dispatch_road_matrix(
            drivers=_drivers(),
            orders=_orders(),
            dependencies=(
                DispatchRoadMatrixDependencies(
                    snap_node=snapper,
                    source_distance_builder=(
                        source_builder
                    ),
                    cache_get=cache.get,
                    cache_set=cache.set,
                    cache_key_builder=(
                        RecordingCacheKeyBuilder(
                            key="corrupt-key"
                        )
                    ),
                )
            ),
            use_cache=True,
            fail_open_on_cache_error=False,
        )


@pytest.mark.anyio
async def test_cache_get_failure_fails_open_and_computes():
    snapper = CountingSnapper(
        _snap_mapping()
    )

    source_builder = (
        CountingSourceDistanceBuilder(
            _distance_mapping()
        )
    )

    cache = FakeTextCache()

    cache.raise_on_get = True

    result = await build_dispatch_road_matrix(
        drivers=_drivers(),
        orders=_orders(),
        dependencies=(
            DispatchRoadMatrixDependencies(
                snap_node=snapper,
                source_distance_builder=(
                    source_builder
                ),
                cache_get=cache.get,
                cache_set=cache.set,
                cache_key_builder=(
                    RecordingCacheKeyBuilder()
                ),
            )
        ),
        use_cache=True,
        fail_open_on_cache_error=True,
    )

    assert result.cache_status == "miss"

    assert (
        result.matrix_source
        == "computed"
    )

    assert result.cache_error is not None

    assert (
        "cache_get_failed"
        in result.cache_error
    )


@pytest.mark.anyio
async def test_cache_get_failure_fails_closed_when_requested():
    snapper = CountingSnapper(
        _snap_mapping()
    )

    source_builder = (
        CountingSourceDistanceBuilder(
            _distance_mapping()
        )
    )

    cache = FakeTextCache()

    cache.raise_on_get = True

    with pytest.raises(
        DispatchRoadMatrixServiceError,
        match=(
            "cache lookup failed"
        ),
    ):
        await build_dispatch_road_matrix(
            drivers=_drivers(),
            orders=_orders(),
            dependencies=(
                DispatchRoadMatrixDependencies(
                    snap_node=snapper,
                    source_distance_builder=(
                        source_builder
                    ),
                    cache_get=cache.get,
                    cache_set=cache.set,
                    cache_key_builder=(
                        RecordingCacheKeyBuilder()
                    ),
                )
            ),
            use_cache=True,
            fail_open_on_cache_error=False,
        )


@pytest.mark.anyio
async def test_cache_set_failure_fails_open_and_returns_computed_result():
    snapper = CountingSnapper(
        _snap_mapping()
    )

    source_builder = (
        CountingSourceDistanceBuilder(
            _distance_mapping()
        )
    )

    cache = FakeTextCache()

    cache.raise_on_set = True

    result = await build_dispatch_road_matrix(
        drivers=_drivers(),
        orders=_orders(),
        dependencies=(
            DispatchRoadMatrixDependencies(
                snap_node=snapper,
                source_distance_builder=(
                    source_builder
                ),
                cache_get=cache.get,
                cache_set=cache.set,
                cache_key_builder=(
                    RecordingCacheKeyBuilder()
                ),
            )
        ),
        use_cache=True,
        fail_open_on_cache_error=True,
    )

    assert result.cache_status == "miss"

    assert (
        result.matrix_source
        == "computed"
    )

    assert result.cache_error is not None

    assert (
        "cache_set_failed"
        in result.cache_error
    )


@pytest.mark.anyio
async def test_cache_set_failure_fails_closed_when_requested():
    snapper = CountingSnapper(
        _snap_mapping()
    )

    source_builder = (
        CountingSourceDistanceBuilder(
            _distance_mapping()
        )
    )

    cache = FakeTextCache()

    cache.raise_on_set = True

    with pytest.raises(
        DispatchRoadMatrixServiceError,
        match=(
            "cache write failed"
        ),
    ):
        await build_dispatch_road_matrix(
            drivers=_drivers(),
            orders=_orders(),
            dependencies=(
                DispatchRoadMatrixDependencies(
                    snap_node=snapper,
                    source_distance_builder=(
                        source_builder
                    ),
                    cache_get=cache.get,
                    cache_set=cache.set,
                    cache_key_builder=(
                        RecordingCacheKeyBuilder()
                    ),
                )
            ),
            use_cache=True,
            fail_open_on_cache_error=False,
        )


@pytest.mark.anyio
async def test_service_supports_async_snap_and_cache_callbacks():
    snap_mapping = (
        _snap_mapping()
    )

    cache_store: dict[
        str,
        str,
    ] = {}

    async def async_snap_node(
        lat: float,
        lon: float,
    ) -> int:
        return snap_mapping[
            (
                float(lat),
                float(lon),
            )
        ]

    async def async_cache_get(
        key: str,
    ) -> str | None:
        return cache_store.get(
            key
        )

    async def async_cache_set(
        key: str,
        value: str,
        ttl_seconds: int,
    ) -> bool:
        assert ttl_seconds == 300

        cache_store[
            key
        ] = value

        return True

    source_builder = (
        CountingSourceDistanceBuilder(
            _distance_mapping()
        )
    )

    result = await build_dispatch_road_matrix(
        drivers=_drivers(),
        orders=_orders(),
        dependencies=(
            DispatchRoadMatrixDependencies(
                snap_node=(
                    async_snap_node
                ),
                source_distance_builder=(
                    source_builder
                ),
                cache_get=(
                    async_cache_get
                ),
                cache_set=(
                    async_cache_set
                ),
                cache_key_builder=(
                    RecordingCacheKeyBuilder(
                        key="async-key"
                    )
                ),
            )
        ),
        use_cache=True,
        cache_ttl_seconds=300,
    )

    assert result.cache_status == "miss"

    assert (
        result.matrix_source
        == "computed"
    )

    assert "async-key" in cache_store


@pytest.mark.anyio
async def test_snap_failure_is_wrapped_as_service_error():
    def failing_snap_node(
        lat: float,
        lon: float,
    ) -> int:
        del lat
        del lon

        raise RuntimeError(
            "snap failed"
        )

    source_builder = (
        CountingSourceDistanceBuilder(
            {}
        )
    )

    with pytest.raises(
        DispatchRoadMatrixServiceError,
        match=(
            "Failed to snap "
            "dispatch coordinate"
        ),
    ):
        await build_dispatch_road_matrix(
            drivers=_drivers(),
            orders=_orders(),
            dependencies=(
                DispatchRoadMatrixDependencies(
                    snap_node=(
                        failing_snap_node
                    ),
                    source_distance_builder=(
                        source_builder
                    ),
                )
            ),
            use_cache=False,
        )


@pytest.mark.anyio
async def test_invalid_snap_node_id_is_rejected():
    def invalid_snap_node(
        lat: float,
        lon: float,
    ) -> str:
        del lat
        del lon

        return "not-an-integer-node"

    source_builder = (
        CountingSourceDistanceBuilder(
            {}
        )
    )

    with pytest.raises(
        DispatchRoadMatrixServiceError,
        match=(
            "snap_node must return "
            "an integer graph node ID"
        ),
    ):
        await build_dispatch_road_matrix(
            drivers=_drivers(),
            orders=_orders(),
            dependencies=(
                DispatchRoadMatrixDependencies(
                    snap_node=(
                        invalid_snap_node
                    ),
                    source_distance_builder=(
                        source_builder
                    ),
                )
            ),
            use_cache=False,
        )


@pytest.mark.anyio
async def test_source_distance_builder_failure_is_wrapped():
    snapper = CountingSnapper(
        _snap_mapping()
    )

    def failing_source_builder(
        source_node: int,
        target_nodes: Sequence[int],
    ) -> dict[
        int,
        float,
    ]:
        del source_node
        del target_nodes

        raise RuntimeError(
            "dijkstra failed"
        )

    with pytest.raises(
        DispatchRoadMatrixServiceError,
        match=(
            "Real-road dispatch "
            "matrix generation failed"
        ),
    ):
        await build_dispatch_road_matrix(
            drivers=_drivers(),
            orders=_orders(),
            dependencies=(
                DispatchRoadMatrixDependencies(
                    snap_node=snapper,
                    source_distance_builder=(
                        failing_source_builder
                    ),
                )
            ),
            use_cache=False,
        )


@pytest.mark.anyio
async def test_invalid_driver_coordinate_is_rejected_before_snapping():
    snapper = CountingSnapper(
        _snap_mapping()
    )

    source_builder = (
        CountingSourceDistanceBuilder(
            _distance_mapping()
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "drivers\\[0\\].lat "
            "must be between -90 and 90"
        ),
    ):
        await build_dispatch_road_matrix(
            drivers=(
                GeoCoordinate(
                    lat=91.0,
                    lon=80.35,
                ),
            ),
            orders=_orders(),
            dependencies=(
                DispatchRoadMatrixDependencies(
                    snap_node=snapper,
                    source_distance_builder=(
                        source_builder
                    ),
                )
            ),
            use_cache=False,
        )

    assert snapper.calls == []


@pytest.mark.anyio
async def test_empty_driver_coordinates_are_rejected():
    snapper = CountingSnapper(
        _snap_mapping()
    )

    source_builder = (
        CountingSourceDistanceBuilder(
            _distance_mapping()
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "drivers must contain "
            "at least one coordinate"
        ),
    ):
        await build_dispatch_road_matrix(
            drivers=(),
            orders=_orders(),
            dependencies=(
                DispatchRoadMatrixDependencies(
                    snap_node=snapper,
                    source_distance_builder=(
                        source_builder
                    ),
                )
            ),
            use_cache=False,
        )


@pytest.mark.anyio
async def test_empty_order_coordinates_are_rejected():
    snapper = CountingSnapper(
        _snap_mapping()
    )

    source_builder = (
        CountingSourceDistanceBuilder(
            _distance_mapping()
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "orders must contain "
            "at least one coordinate"
        ),
    ):
        await build_dispatch_road_matrix(
            drivers=_drivers(),
            orders=(),
            dependencies=(
                DispatchRoadMatrixDependencies(
                    snap_node=snapper,
                    source_distance_builder=(
                        source_builder
                    ),
                )
            ),
            use_cache=False,
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "cache_ttl_seconds",
    [
        0,
        -1,
    ],
)
async def test_invalid_cache_ttl_is_rejected(
    cache_ttl_seconds: int,
):
    snapper = CountingSnapper(
        _snap_mapping()
    )

    source_builder = (
        CountingSourceDistanceBuilder(
            _distance_mapping()
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "cache_ttl_seconds must "
            "be greater than zero"
        ),
    ):
        await build_dispatch_road_matrix(
            drivers=_drivers(),
            orders=_orders(),
            dependencies=(
                DispatchRoadMatrixDependencies(
                    snap_node=snapper,
                    source_distance_builder=(
                        source_builder
                    ),
                )
            ),
            use_cache=False,
            cache_ttl_seconds=(
                cache_ttl_seconds
            ),
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "unreachable_cost_m",
    [
        0.0,
        -1.0,
        float(
            "nan"
        ),
        float(
            "inf"
        ),
    ],
)
async def test_invalid_unreachable_cost_is_rejected(
    unreachable_cost_m: float,
):
    snapper = CountingSnapper(
        _snap_mapping()
    )

    source_builder = (
        CountingSourceDistanceBuilder(
            _distance_mapping()
        )
    )

    with pytest.raises(
        ValueError
    ):
        await build_dispatch_road_matrix(
            drivers=_drivers(),
            orders=_orders(),
            dependencies=(
                DispatchRoadMatrixDependencies(
                    snap_node=snapper,
                    source_distance_builder=(
                        source_builder
                    ),
                )
            ),
            use_cache=False,
            unreachable_cost_m=(
                unreachable_cost_m
            ),
        )


@pytest.mark.anyio
async def test_result_timing_fields_are_non_negative():
    snapper = CountingSnapper(
        _snap_mapping()
    )

    source_builder = (
        CountingSourceDistanceBuilder(
            _distance_mapping()
        )
    )

    result = await build_dispatch_road_matrix(
        drivers=_drivers(),
        orders=_orders(),
        dependencies=(
            DispatchRoadMatrixDependencies(
                snap_node=snapper,
                source_distance_builder=(
                    source_builder
                ),
            )
        ),
        use_cache=False,
    )

    assert result.snap_time_ms >= 0.0

    assert (
        result.cache_lookup_time_ms
        >= 0.0
    )

    assert (
        result.cache_write_time_ms
        >= 0.0
    )

    assert (
        result.matrix_generation_time_ms
        >= 0.0
    )

    assert result.total_time_ms >= 0.0