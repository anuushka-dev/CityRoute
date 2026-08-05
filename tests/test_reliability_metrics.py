# tests/test_reliability_metrics.py

from __future__ import annotations

import asyncio
import math
from collections.abc import Iterator

import pytest
from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.parser import (
    text_string_to_metric_families,
)

from app.core.concurrency_limiter import ConcurrencyLimiter
from app.infrastructure.redis_resilience import (
    RedisRecoveryController,
)
from app.infrastructure.resilience_state import ResilienceState
from app.observability.reliability_metrics import (
    ReliabilityMetrics,
    get_reliability_metrics,
)


@pytest.fixture
def anyio_backend() -> str:
    """Run asynchronous metrics tests with asyncio."""

    return "asyncio"


@pytest.fixture
def registry() -> CollectorRegistry:
    """
    Give every test an isolated Prometheus registry.

    Using the global registry would make counter values and collector
    registration dependent on test execution order.
    """

    return CollectorRegistry(
        auto_describe=True,
    )


@pytest.fixture
def metrics(
    registry: CollectorRegistry,
) -> ReliabilityMetrics:
    return ReliabilityMetrics(
        registry=registry,
    )


def _metric_text(
    registry: CollectorRegistry,
) -> str:
    return generate_latest(registry).decode("utf-8")


def _samples(
    registry: CollectorRegistry,
) -> Iterator[object]:
    text = _metric_text(registry)

    for family in text_string_to_metric_families(text):
        yield from family.samples


def _sample_value(
    registry: CollectorRegistry,
    name: str,
    *,
    labels: dict[str, str] | None = None,
) -> float:
    expected_labels = labels or {}

    for sample in _samples(registry):
        if sample.name != name:
            continue

        if dict(sample.labels) != expected_labels:
            continue

        return float(sample.value)

    raise AssertionError(
        f"Metric sample not found: "
        f"name={name!r}, labels={expected_labels!r}\n\n"
        f"{_metric_text(registry)}"
    )


def _registered_names(
    registry: CollectorRegistry,
) -> set[str]:
    """
    Return collector names registered with this isolated registry.

    This intentionally checks the registry contract because labeled
    counters and histograms do not produce text samples until first use.
    """

    names_to_collectors = getattr(
        registry,
        "_names_to_collectors",
    )

    return {
        str(name)
        for name in names_to_collectors
    }


async def _initialize_ready_state(
    state: ResilienceState,
) -> None:
    await state.mark_startup_started()

    await state.set_graph_ready(True)
    await state.set_snap_index_ready(True)
    await state.set_dispatch_adjacency_ready(True)
    await state.mark_redis_success()

    await state.mark_startup_complete(
        accepting_requests=True,
    )


def _limiter(
    *,
    max_active_requests: int = 4,
    max_waiting_requests: int = 8,
) -> ConcurrencyLimiter:
    return ConcurrencyLimiter(
        max_active_requests=max_active_requests,
        max_waiting_requests=max_waiting_requests,
        default_wait_timeout_s=0.25,
    )


async def _healthy_redis_controller(
    state: ResilienceState,
) -> RedisRecoveryController:
    async def health_check() -> bool:
        return True

    controller = RedisRecoveryController(
        resilience_state=state,
        health_check=health_check,
        fail_open_enabled=True,
    )

    initialized = await controller.initialize()

    assert initialized is True

    return controller


def test_required_reliability_collectors_are_registered(
    metrics: ReliabilityMetrics,
    registry: CollectorRegistry,
) -> None:
    del metrics

    names = _registered_names(registry)

    required_names = {
        "cityroute_active_requests",
        "cityroute_waiting_requests",
        "cityroute_readiness",
        "cityroute_accepting_requests",
        "cityroute_redis_available",
        "cityroute_graceful_shutdown_inflight",
        "cityroute_admission_decisions_total",
        "cityroute_request_rejections_total",
        "cityroute_request_timeouts_total",
        "cityroute_overload_events_total",
        "cityroute_redis_failures_total",
        "cityroute_redis_recoveries_total",
        "cityroute_admission_wait_seconds",
        "cityroute_request_execution_seconds",
    }

    missing = required_names - names

    assert missing == set(), (
        "Required Phase 11 metrics are not registered: "
        f"{sorted(missing)}"
    )


@pytest.mark.anyio
async def test_refresh_gauges_reports_ready_idle_service(
    metrics: ReliabilityMetrics,
    registry: CollectorRegistry,
) -> None:
    state = ResilienceState()
    limiter = _limiter()

    await _initialize_ready_state(state)

    redis_controller = await _healthy_redis_controller(
        state
    )

    metrics.refresh_gauges(
        resilience_snapshot=await state.snapshot(),
        limiter_snapshot=await limiter.snapshot(),
        redis_snapshot=await redis_controller.snapshot(),
        ready=True,
    )

    assert _sample_value(
        registry,
        "cityroute_active_requests",
    ) == 0.0

    assert _sample_value(
        registry,
        "cityroute_waiting_requests",
    ) == 0.0

    assert _sample_value(
        registry,
        "cityroute_readiness",
    ) == 1.0

    assert _sample_value(
        registry,
        "cityroute_accepting_requests",
    ) == 1.0

    assert _sample_value(
        registry,
        "cityroute_redis_available",
    ) == 1.0

    assert _sample_value(
        registry,
        "cityroute_graceful_shutdown_inflight",
    ) == 0.0

@pytest.mark.anyio
async def test_refresh_gauges_reports_active_and_waiting_work(
    metrics: ReliabilityMetrics,
    registry: CollectorRegistry,
) -> None:
    state = ResilienceState()

    await _initialize_ready_state(state)

    limiter = _limiter(
        max_active_requests=1,
        max_waiting_requests=1,
    )

    redis_controller = await _healthy_redis_controller(
        state
    )

    active_outcome = await limiter.acquire()

    queued_task = asyncio.create_task(
        limiter.acquire(
            wait_timeout_s=1.0,
        )
    )

    loop = asyncio.get_running_loop()
    deadline = loop.time() + 1.0

    while True:
        limiter_snapshot = await limiter.snapshot()

        if (
            limiter_snapshot.active_requests == 1
            and limiter_snapshot.waiting_requests == 1
        ):
            break

        if loop.time() >= deadline:
            queued_task.cancel()

            with pytest.raises(asyncio.CancelledError):
                await queued_task

            raise AssertionError(
                "Limiter did not reach active=1, waiting=1"
            )

        await asyncio.sleep(0.001)

    metrics.refresh_gauges(
        resilience_snapshot=await state.snapshot(),
        limiter_snapshot=limiter_snapshot,
        redis_snapshot=await redis_controller.snapshot(),
        ready=True,
    )

    assert _sample_value(
        registry,
        "cityroute_active_requests",
    ) == 1.0

    assert _sample_value(
        registry,
        "cityroute_waiting_requests",
    ) == 1.0

    await active_outcome.require_lease().release()

    queued_outcome = await asyncio.wait_for(
        queued_task,
        timeout=1.0,
    )

    await queued_outcome.require_lease().release()


@pytest.mark.anyio
async def test_refresh_gauges_reports_degraded_redis(
    metrics: ReliabilityMetrics,
    registry: CollectorRegistry,
) -> None:
    state = ResilienceState()
    limiter = _limiter()

    await _initialize_ready_state(state)

    async def failing_healthcheck() -> bool:
        raise ConnectionError(
            "Redis connection refused"
        )

    redis_controller = RedisRecoveryController(
        resilience_state=state,
        health_check=failing_healthcheck,
        fail_open_enabled=True,
    )

    initialized = await redis_controller.initialize()

    assert initialized is False

    metrics.refresh_gauges(
        resilience_snapshot=await state.snapshot(),
        limiter_snapshot=await limiter.snapshot(),
        redis_snapshot=await redis_controller.snapshot(),
        ready=True,
    )

    # CityRoute stays ready under the configured Redis fail-open mode.
    assert _sample_value(
        registry,
        "cityroute_readiness",
    ) == 1.0

    assert _sample_value(
        registry,
        "cityroute_accepting_requests",
    ) == 1.0

    assert _sample_value(
        registry,
        "cityroute_redis_available",
    ) == 0.0


@pytest.mark.anyio
async def test_refresh_gauges_reports_shutdown_state(
    metrics: ReliabilityMetrics,
    registry: CollectorRegistry,
) -> None:
    state = ResilienceState()
    limiter = _limiter()

    await _initialize_ready_state(state)

    redis_controller = await _healthy_redis_controller(
        state
    )

    active_outcome = await limiter.acquire()
    await state.request_started()

    await state.begin_shutdown()
    await limiter.close(
        reason="service_shutdown",
    )

    metrics.refresh_gauges(
        resilience_snapshot=await state.snapshot(),
        limiter_snapshot=await limiter.snapshot(),
        redis_snapshot=await redis_controller.snapshot(),
        ready=False,
    )

    assert _sample_value(
        registry,
        "cityroute_readiness",
    ) == 0.0

    assert _sample_value(
        registry,
        "cityroute_accepting_requests",
    ) == 0.0

    assert _sample_value(
        registry,
        "cityroute_graceful_shutdown_inflight",
    ) == 1.0

    await state.request_finished()
    await active_outcome.require_lease().release()


@pytest.mark.anyio
async def test_refresh_gauges_replaces_previous_values(
    metrics: ReliabilityMetrics,
    registry: CollectorRegistry,
) -> None:
    state = ResilienceState()
    limiter = _limiter()

    await _initialize_ready_state(state)

    redis_controller = await _healthy_redis_controller(
        state
    )

    metrics.refresh_gauges(
        resilience_snapshot=await state.snapshot(),
        limiter_snapshot=await limiter.snapshot(),
        redis_snapshot=await redis_controller.snapshot(),
        ready=True,
    )

    assert _sample_value(
        registry,
        "cityroute_readiness",
    ) == 1.0

    assert _sample_value(
        registry,
        "cityroute_graceful_shutdown_inflight",
    ) == 0.0

    active_outcome = await limiter.acquire()
    await state.request_started()

    await state.begin_shutdown()
    await limiter.close(
        reason="service_shutdown",
    )

    metrics.refresh_gauges(
        resilience_snapshot=await state.snapshot(),
        limiter_snapshot=await limiter.snapshot(),
        redis_snapshot=await redis_controller.snapshot(),
        ready=False,
    )

    assert _sample_value(
        registry,
        "cityroute_readiness",
    ) == 0.0

    assert _sample_value(
        registry,
        "cityroute_accepting_requests",
    ) == 0.0

    assert _sample_value(
        registry,
        "cityroute_graceful_shutdown_inflight",
    ) == 1.0

    await state.request_finished()
    await active_outcome.require_lease().release()

    metrics.refresh_gauges(
        resilience_snapshot=await state.snapshot(),
        limiter_snapshot=await limiter.snapshot(),
        redis_snapshot=await redis_controller.snapshot(),
        ready=False,
    )

    assert _sample_value(
        registry,
        "cityroute_graceful_shutdown_inflight",
    ) == 0.0


@pytest.mark.anyio
async def test_missing_redis_snapshot_uses_resilience_state(
    metrics: ReliabilityMetrics,
    registry: CollectorRegistry,
) -> None:
    state = ResilienceState()
    limiter = _limiter()

    await _initialize_ready_state(state)

    metrics.refresh_gauges(
        resilience_snapshot=await state.snapshot(),
        limiter_snapshot=await limiter.snapshot(),
        redis_snapshot=None,
        ready=True,
    )

    assert _sample_value(
        registry,
        "cityroute_redis_available",
    ) == 1.0

    await state.mark_redis_failure(
        "connection refused",
        unavailable=True,
    )

    metrics.refresh_gauges(
        resilience_snapshot=await state.snapshot(),
        limiter_snapshot=await limiter.snapshot(),
        redis_snapshot=None,
        ready=True,
    )

    assert _sample_value(
        registry,
        "cityroute_redis_available",
    ) == 0.0


def test_metric_labels_avoid_unbounded_cardinality(
    metrics: ReliabilityMetrics,
    registry: CollectorRegistry,
) -> None:
    del metrics

    forbidden_labels = {
        "path",
        "url",
        "detail",
        "message",
        "exception",
        "traceback",
        "driver_id",
        "order_id",
        "request_id",
        "cache_key",
    }

    collectors = {
        id(collector): collector
        for collector in getattr(
            registry,
            "_names_to_collectors",
        ).values()
    }.values()

    for collector in collectors:
        label_names = {
            str(label_name)
            for label_name in getattr(
                collector,
                "_labelnames",
                (),
            )
        }

        invalid = label_names & forbidden_labels

        assert invalid == set(), (
            f"Collector {collector!r} uses "
            f"high-cardinality labels: {sorted(invalid)}"
        )


def test_exported_metric_values_are_finite(
    metrics: ReliabilityMetrics,
    registry: CollectorRegistry,
) -> None:
    del metrics

    for sample in _samples(registry):
        value = float(sample.value)

        assert math.isfinite(value), (
            f"Metric {sample.name!r} exported "
            f"non-finite value {value!r}"
        )


def test_custom_registries_are_isolated() -> None:
    first_registry = CollectorRegistry(
        auto_describe=True,
    )
    second_registry = CollectorRegistry(
        auto_describe=True,
    )

    ReliabilityMetrics(
        registry=first_registry,
    )
    ReliabilityMetrics(
        registry=second_registry,
    )

    assert first_registry is not second_registry

    assert _registered_names(first_registry) == (
        _registered_names(second_registry)
    )


def test_global_metrics_accessor_is_singleton() -> None:
    first = get_reliability_metrics()
    second = get_reliability_metrics()

    assert first is second