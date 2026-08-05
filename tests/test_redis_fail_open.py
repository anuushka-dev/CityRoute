# tests/test_redis_fail_open.py

from __future__ import annotations

from collections.abc import Callable

import pytest

from app.infrastructure.redis_resilience import (
    RedisAvailability,
    RedisFailureReason,
    RedisRecoveryController,
)
from app.infrastructure.resilience_state import ResilienceState
from app.services.readiness_service import (
    ReadinessPolicy,
    ReadinessService,
)


@pytest.fixture
def anyio_backend() -> str:
    """Run asynchronous Redis tests with asyncio."""

    return "asyncio"


class FakeRedis:
    """Controllable asynchronous Redis health-check test double."""

    def __init__(self) -> None:
        self.available = True
        self.failure_factory: Callable[[], BaseException] = (
            lambda: ConnectionError("Redis connection refused")
        )
        self.ping_calls = 0

    async def ping(self) -> bool:
        self.ping_calls += 1

        if not self.available:
            raise self.failure_factory()

        return True


async def _initialize_core_components(
    state: ResilienceState,
) -> None:
    """
    Initialize all required non-Redis CityRoute components.

    Redis is intentionally managed separately by RedisRecoveryController.
    """

    await state.mark_startup_started()
    await state.set_graph_ready(True)
    await state.set_snap_index_ready(True)
    await state.set_dispatch_adjacency_ready(True)
    await state.mark_startup_complete()


def _readiness_service(
    state: ResilienceState,
    *,
    require_redis: bool = False,
    redis_fail_open: bool = True,
) -> ReadinessService:
    return ReadinessService(
        resilience_state=state,
        phase="tier4_phase11",
        policy=ReadinessPolicy(
            require_graph=True,
            require_snap_index=True,
            require_dispatch_adjacency=True,
            require_redis=require_redis,
            redis_fail_open=redis_fail_open,
        ),
    )


def _controller(
    state: ResilienceState,
    fake_redis: FakeRedis,
    *,
    fail_open_enabled: bool = True,
    recovery_interval_s: float = 0.2,
    max_recovery_interval_s: float = 1.0,
) -> RedisRecoveryController:
    return RedisRecoveryController(
        resilience_state=state,
        health_check=fake_redis.ping,
        fail_open_enabled=fail_open_enabled,
        recovery_interval_s=recovery_interval_s,
        max_recovery_interval_s=max_recovery_interval_s,
        backoff_multiplier=2.0,
    )


@pytest.mark.anyio
async def test_optional_uninitialized_redis_does_not_block_readiness(
) -> None:
    state = ResilienceState()
    await _initialize_core_components(state)

    service = _readiness_service(
        state,
        require_redis=False,
        redis_fail_open=True,
    )

    readiness = await service.get_readiness()

    assert readiness.status == "ready"
    assert readiness.ready is True
    assert readiness.accepting_requests is True

    assert readiness.components.graph == "ready"
    assert readiness.components.snap_index == "ready"
    assert readiness.components.dispatch_adjacency == "ready"
    assert readiness.components.redis == "not_required"

    assert readiness.degraded_dependencies == []
    assert readiness.failure_reasons == []


@pytest.mark.anyio
async def test_redis_startup_outage_fails_open() -> None:
    state = ResilienceState()
    await _initialize_core_components(state)

    fake_redis = FakeRedis()
    fake_redis.available = False

    controller = _controller(
        state,
        fake_redis,
        fail_open_enabled=True,
    )

    startup_available = await controller.initialize()

    redis_snapshot = await controller.snapshot()
    state_snapshot = await state.snapshot()

    readiness = await _readiness_service(
        state,
        require_redis=False,
        redis_fail_open=True,
    ).get_readiness()

    assert startup_available is False

    assert redis_snapshot.availability == (
        RedisAvailability.UNAVAILABLE
    )
    assert redis_snapshot.available is False
    assert redis_snapshot.fail_open_enabled is True
    assert redis_snapshot.total_failures == 1
    assert redis_snapshot.consecutive_failures == 1
    assert redis_snapshot.last_failure_reason == (
        RedisFailureReason.UNAVAILABLE_AT_STARTUP
    )

    assert state_snapshot.redis == "unavailable"

    # The API remains production-ready because Redis is optional.
    assert readiness.status == "degraded"
    assert readiness.ready is True
    assert readiness.components.redis == "degraded"
    assert readiness.degraded_dependencies == ["redis"]
    assert readiness.failure_reasons == []


@pytest.mark.anyio
async def test_runtime_redis_outage_keeps_core_service_ready() -> None:
    state = ResilienceState()
    await _initialize_core_components(state)

    fake_redis = FakeRedis()
    controller = _controller(state, fake_redis)

    assert await controller.initialize() is True

    fake_redis.available = False

    redis_healthy = await controller.check_health()

    redis_snapshot = await controller.snapshot()
    state_snapshot = await state.snapshot()

    readiness = await _readiness_service(
        state,
        require_redis=False,
        redis_fail_open=True,
    ).get_readiness()

    assert redis_healthy is False
    assert redis_snapshot.availability == (
        RedisAvailability.UNAVAILABLE
    )
    assert redis_snapshot.last_failure_reason == (
        RedisFailureReason.CONNECTION_ERROR
    )
    assert redis_snapshot.total_failures == 1

    assert state_snapshot.redis == "unavailable"

    assert readiness.status == "degraded"
    assert readiness.ready is True
    assert readiness.accepting_requests is True
    assert readiness.components.redis == "degraded"
    assert readiness.degraded_dependencies == ["redis"]

    assert readiness.components.graph == "ready"
    assert readiness.components.snap_index == "ready"
    assert readiness.components.dispatch_adjacency == "ready"


@pytest.mark.anyio
async def test_redis_outage_blocks_readiness_when_required() -> None:
    state = ResilienceState()
    await _initialize_core_components(state)

    fake_redis = FakeRedis()
    controller = _controller(state, fake_redis)

    assert await controller.initialize() is True

    fake_redis.available = False
    assert await controller.check_health() is False

    readiness = await _readiness_service(
        state,
        require_redis=True,
        redis_fail_open=False,
    ).get_readiness()

    assert readiness.status == "not_ready"
    assert readiness.ready is False
    assert readiness.components.redis == "unavailable"
    assert readiness.degraded_dependencies == []

    assert readiness.failure_reasons == [
        "redis_not_ready:unavailable"
    ]


@pytest.mark.anyio
async def test_corrupted_payload_is_degraded_not_unavailable() -> None:
    state = ResilienceState()
    await _initialize_core_components(state)

    fake_redis = FakeRedis()
    controller = _controller(state, fake_redis)

    assert await controller.initialize() is True

    await controller.mark_corrupted_payload(
        detail="Invalid JSON in cached dispatch matrix",
    )

    redis_snapshot = await controller.snapshot()
    state_snapshot = await state.snapshot()

    readiness = await _readiness_service(
        state,
        require_redis=False,
        redis_fail_open=True,
    ).get_readiness()

    assert redis_snapshot.availability == (
        RedisAvailability.DEGRADED
    )
    assert redis_snapshot.available is False
    assert redis_snapshot.degraded is True
    assert redis_snapshot.last_failure_reason == (
        RedisFailureReason.CORRUPTED_PAYLOAD
    )
    assert redis_snapshot.last_failure_detail == (
        "Invalid JSON in cached dispatch matrix"
    )

    # ResilienceState uses not_ready for reachable-but-degraded Redis.
    assert state_snapshot.redis == "not_ready"

    assert readiness.status == "degraded"
    assert readiness.ready is True
    assert readiness.components.redis == "degraded"
    assert readiness.degraded_dependencies == ["redis"]


@pytest.mark.anyio
async def test_invalid_payload_type_fails_open() -> None:
    state = ResilienceState()
    await _initialize_core_components(state)

    fake_redis = FakeRedis()
    controller = _controller(state, fake_redis)

    assert await controller.initialize() is True

    await controller.mark_invalid_payload_type(
        detail="Expected dictionary but received list",
    )

    redis_snapshot = await controller.snapshot()

    readiness = await _readiness_service(
        state,
        require_redis=False,
        redis_fail_open=True,
    ).get_readiness()

    assert redis_snapshot.availability == (
        RedisAvailability.DEGRADED
    )
    assert redis_snapshot.last_failure_reason == (
        RedisFailureReason.INVALID_PAYLOAD_TYPE
    )

    assert readiness.status == "degraded"
    assert readiness.ready is True
    assert readiness.components.redis == "degraded"


@pytest.mark.anyio
async def test_redis_recovers_without_application_restart() -> None:
    state = ResilienceState()
    await _initialize_core_components(state)

    fake_redis = FakeRedis()
    controller = _controller(state, fake_redis)

    assert await controller.initialize() is True

    fake_redis.available = False
    assert await controller.check_health() is False

    degraded_readiness = await _readiness_service(
        state,
        require_redis=False,
        redis_fail_open=True,
    ).get_readiness()

    assert degraded_readiness.status == "degraded"
    assert degraded_readiness.ready is True

    fake_redis.available = True

    recovered = await controller.attempt_recovery(
        force=True
    )

    redis_snapshot = await controller.snapshot()
    state_snapshot = await state.snapshot()

    recovered_readiness = await _readiness_service(
        state,
        require_redis=False,
        redis_fail_open=True,
    ).get_readiness()

    assert recovered is True

    assert redis_snapshot.availability == (
        RedisAvailability.AVAILABLE
    )
    assert redis_snapshot.available is True
    assert redis_snapshot.consecutive_failures == 0
    assert redis_snapshot.total_failures == 1
    assert redis_snapshot.total_recovery_attempts == 1
    assert redis_snapshot.total_recoveries == 1
    assert redis_snapshot.last_failure_reason is None
    assert redis_snapshot.last_recovered_at_utc is not None

    assert state_snapshot.redis == "ready"

    assert recovered_readiness.status == "ready"
    assert recovered_readiness.ready is True
    assert recovered_readiness.components.redis == "ready"
    assert recovered_readiness.degraded_dependencies == []


@pytest.mark.anyio
async def test_immediate_recovery_respects_backoff() -> None:
    state = ResilienceState()
    fake_redis = FakeRedis()

    controller = _controller(
        state,
        fake_redis,
        recovery_interval_s=5.0,
        max_recovery_interval_s=10.0,
    )

    assert await controller.initialize() is True

    fake_redis.available = False
    assert await controller.check_health() is False

    calls_before_recovery = fake_redis.ping_calls

    recovered = await controller.attempt_recovery()

    redis_snapshot = await controller.snapshot()

    assert recovered is False

    # Backoff prevented another ping.
    assert fake_redis.ping_calls == calls_before_recovery

    assert redis_snapshot.total_recovery_attempts == 0
    assert redis_snapshot.next_recovery_in_s > 0.0
    assert redis_snapshot.current_backoff_s == 5.0


@pytest.mark.anyio
async def test_forced_recovery_bypasses_backoff() -> None:
    state = ResilienceState()
    fake_redis = FakeRedis()

    controller = _controller(
        state,
        fake_redis,
        recovery_interval_s=10.0,
        max_recovery_interval_s=20.0,
    )

    assert await controller.initialize() is True

    fake_redis.available = False
    assert await controller.check_health() is False

    fake_redis.available = True

    recovered = await controller.attempt_recovery(
        force=True
    )

    snapshot = await controller.snapshot()

    assert recovered is True
    assert snapshot.available is True
    assert snapshot.total_recovery_attempts == 1
    assert snapshot.total_recoveries == 1
    assert snapshot.next_recovery_in_s == 0.0


@pytest.mark.anyio
async def test_timeout_failure_is_classified() -> None:
    state = ResilienceState()
    fake_redis = FakeRedis()

    controller = _controller(state, fake_redis)

    assert await controller.initialize() is True

    fake_redis.available = False
    fake_redis.failure_factory = lambda: TimeoutError(
        "Redis operation timed out"
    )

    healthy = await controller.check_health()
    snapshot = await controller.snapshot()

    assert healthy is False
    assert snapshot.availability == (
        RedisAvailability.UNAVAILABLE
    )
    assert snapshot.last_failure_reason == (
        RedisFailureReason.TIMEOUT
    )


@pytest.mark.anyio
async def test_authentication_failure_is_classified() -> None:
    state = ResilienceState()
    fake_redis = FakeRedis()

    controller = _controller(state, fake_redis)

    assert await controller.initialize() is True

    fake_redis.available = False
    fake_redis.failure_factory = lambda: RuntimeError(
        "Redis authentication failed: invalid password"
    )

    healthy = await controller.check_health()
    snapshot = await controller.snapshot()

    assert healthy is False
    assert snapshot.last_failure_reason == (
        RedisFailureReason.AUTHENTICATION_ERROR
    )


@pytest.mark.anyio
async def test_invalid_healthcheck_return_is_controlled_failure() -> None:
    state = ResilienceState()

    async def invalid_ping() -> str:
        return "PONG"

    controller = RedisRecoveryController(
        resilience_state=state,
        health_check=invalid_ping,
        fail_open_enabled=True,
    )

    startup_available = await controller.initialize()

    redis_snapshot = await controller.snapshot()
    state_snapshot = await state.snapshot()

    assert startup_available is False
    assert redis_snapshot.availability == (
        RedisAvailability.UNAVAILABLE
    )
    assert redis_snapshot.last_failure_reason == (
        RedisFailureReason.UNAVAILABLE_AT_STARTUP
    )
    assert redis_snapshot.last_failure_detail is not None
    assert "TypeError" in redis_snapshot.last_failure_detail

    assert state_snapshot.redis == "unavailable"


@pytest.mark.anyio
async def test_synchronous_healthcheck_is_supported() -> None:
    state = ResilienceState()
    ping_calls = 0

    def synchronous_ping() -> bool:
        nonlocal ping_calls

        ping_calls += 1
        return True

    controller = RedisRecoveryController(
        resilience_state=state,
        health_check=synchronous_ping,
        fail_open_enabled=True,
        run_sync_healthcheck_in_thread=True,
    )

    initialized = await controller.initialize()

    snapshot = await controller.snapshot()
    state_snapshot = await state.snapshot()

    assert initialized is True
    assert ping_calls == 1

    assert snapshot.availability == (
        RedisAvailability.AVAILABLE
    )
    assert snapshot.available is True
    assert snapshot.fail_open_enabled is True

    assert state_snapshot.redis == "ready"