# tests/test_redis_failure_recovery.py

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from app.infrastructure.redis_resilience import (
    RedisAvailability,
    RedisFailureReason,
    RedisRecoveryController,
)
from app.infrastructure.resilience_state import ResilienceState


@pytest.fixture
def anyio_backend() -> str:
    """Run asynchronous Redis recovery tests with asyncio."""

    return "asyncio"


class RecoverableRedis:
    """Controllable Redis health-check double."""

    def __init__(self) -> None:
        self.available = True
        self.delay_s = 0.0
        self.ping_calls = 0
        self.failure_factory: Callable[[], BaseException] = (
            lambda: ConnectionError("Redis connection refused")
        )

    async def ping(self) -> bool:
        self.ping_calls += 1

        if self.delay_s > 0:
            await asyncio.sleep(self.delay_s)

        if not self.available:
            raise self.failure_factory()

        return True


def _controller(
    state: ResilienceState,
    redis: RecoverableRedis,
    *,
    recovery_interval_s: float = 0.02,
    max_recovery_interval_s: float = 0.10,
    backoff_multiplier: float = 2.0,
) -> RedisRecoveryController:
    return RedisRecoveryController(
        resilience_state=state,
        health_check=redis.ping,
        fail_open_enabled=True,
        recovery_interval_s=recovery_interval_s,
        max_recovery_interval_s=max_recovery_interval_s,
        backoff_multiplier=backoff_multiplier,
    )


def test_constructor_validates_recovery_configuration() -> None:
    state = ResilienceState()
    redis = RecoverableRedis()

    with pytest.raises(
        ValueError,
        match="recovery_interval_s",
    ):
        RedisRecoveryController(
            resilience_state=state,
            health_check=redis.ping,
            recovery_interval_s=0.0,
        )

    with pytest.raises(
        ValueError,
        match="max_recovery_interval_s",
    ):
        RedisRecoveryController(
            resilience_state=state,
            health_check=redis.ping,
            recovery_interval_s=2.0,
            max_recovery_interval_s=1.0,
        )

    with pytest.raises(
        ValueError,
        match="backoff_multiplier",
    ):
        RedisRecoveryController(
            resilience_state=state,
            health_check=redis.ping,
            backoff_multiplier=0.5,
        )

    with pytest.raises(
        TypeError,
        match="fail_open_enabled",
    ):
        RedisRecoveryController(
            resilience_state=state,
            health_check=redis.ping,
            fail_open_enabled=1,  # type: ignore[arg-type]
        )


@pytest.mark.anyio
async def test_startup_failure_can_recover_without_restart() -> None:
    state = ResilienceState()
    redis = RecoverableRedis()
    redis.available = False

    controller = _controller(state, redis)

    initialized = await controller.initialize()

    failed_snapshot = await controller.snapshot()
    failed_state = await state.snapshot()

    assert initialized is False
    assert failed_snapshot.availability == (
        RedisAvailability.UNAVAILABLE
    )
    assert failed_snapshot.available is False
    assert failed_snapshot.total_failures == 1
    assert failed_snapshot.consecutive_failures == 1
    assert failed_snapshot.total_recovery_attempts == 0
    assert failed_snapshot.total_recoveries == 0
    assert failed_snapshot.last_failure_reason == (
        RedisFailureReason.UNAVAILABLE_AT_STARTUP
    )
    assert failed_snapshot.last_failure_detail is not None
    assert "ConnectionError" in failed_snapshot.last_failure_detail
    assert failed_state.redis == "unavailable"

    redis.available = True

    recovered = await controller.attempt_recovery(
        force=True
    )

    recovered_snapshot = await controller.snapshot()
    recovered_state = await state.snapshot()

    assert recovered is True
    assert recovered_snapshot.availability == (
        RedisAvailability.AVAILABLE
    )
    assert recovered_snapshot.available is True
    assert recovered_snapshot.consecutive_failures == 0
    assert recovered_snapshot.total_failures == 1
    assert recovered_snapshot.total_recovery_attempts == 1
    assert recovered_snapshot.total_recoveries == 1
    assert recovered_snapshot.last_failure_reason is None
    assert recovered_snapshot.last_failure_detail is None
    assert recovered_snapshot.last_recovered_at_utc is not None
    assert recovered_snapshot.next_recovery_in_s == 0.0
    assert recovered_state.redis == "ready"


@pytest.mark.anyio
async def test_runtime_success_recovers_without_recovery_attempt() -> None:
    state = ResilienceState()
    redis = RecoverableRedis()
    controller = _controller(state, redis)

    assert await controller.initialize() is True

    redis.available = False
    assert await controller.check_health() is False

    redis.available = True
    assert await controller.check_health() is True

    snapshot = await controller.snapshot()

    assert snapshot.availability == RedisAvailability.AVAILABLE
    assert snapshot.total_failures == 1
    assert snapshot.total_recovery_attempts == 0
    assert snapshot.total_recoveries == 1
    assert snapshot.consecutive_failures == 0
    assert snapshot.last_failure_reason is None


@pytest.mark.anyio
async def test_repeated_failures_apply_bounded_backoff() -> None:
    state = ResilienceState()
    redis = RecoverableRedis()

    controller = _controller(
        state,
        redis,
        recovery_interval_s=0.01,
        max_recovery_interval_s=0.025,
        backoff_multiplier=2.0,
    )

    assert await controller.initialize() is True

    redis.available = False

    assert await controller.check_health() is False
    first = await controller.snapshot()

    assert first.consecutive_failures == 1
    assert first.current_backoff_s == pytest.approx(0.01)

    assert await controller.check_health() is False
    second = await controller.snapshot()

    assert second.consecutive_failures == 2
    assert second.current_backoff_s == pytest.approx(0.02)

    assert await controller.check_health() is False
    third = await controller.snapshot()

    assert third.consecutive_failures == 3
    assert third.total_failures == 3
    assert third.current_backoff_s == pytest.approx(0.025)
    assert third.next_recovery_in_s > 0.0


@pytest.mark.anyio
async def test_recovery_is_skipped_before_backoff_deadline() -> None:
    state = ResilienceState()
    redis = RecoverableRedis()

    controller = _controller(
        state,
        redis,
        recovery_interval_s=5.0,
        max_recovery_interval_s=10.0,
    )

    assert await controller.initialize() is True

    redis.available = False
    assert await controller.check_health() is False

    ping_calls_before = redis.ping_calls

    recovered = await controller.attempt_recovery()
    snapshot = await controller.snapshot()

    assert recovered is False
    assert redis.ping_calls == ping_calls_before
    assert snapshot.total_recovery_attempts == 0
    assert snapshot.availability == (
        RedisAvailability.UNAVAILABLE
    )
    assert snapshot.next_recovery_in_s > 0.0


@pytest.mark.anyio
async def test_should_attempt_recovery_tracks_deadline() -> None:
    state = ResilienceState()
    redis = RecoverableRedis()

    controller = _controller(
        state,
        redis,
        recovery_interval_s=0.02,
        max_recovery_interval_s=0.10,
    )

    assert await controller.initialize() is True

    redis.available = False
    assert await controller.check_health() is False

    assert await controller.should_attempt_recovery() is False

    await asyncio.sleep(0.04)

    assert await controller.should_attempt_recovery() is True


@pytest.mark.anyio
async def test_recovery_runs_after_backoff_deadline() -> None:
    state = ResilienceState()
    redis = RecoverableRedis()

    controller = _controller(
        state,
        redis,
        recovery_interval_s=0.02,
        max_recovery_interval_s=0.10,
    )

    assert await controller.initialize() is True

    redis.available = False
    assert await controller.check_health() is False

    redis.available = True

    await asyncio.sleep(0.04)

    recovered = await controller.attempt_recovery()
    snapshot = await controller.snapshot()

    assert recovered is True
    assert snapshot.availability == RedisAvailability.AVAILABLE
    assert snapshot.total_recovery_attempts == 1
    assert snapshot.total_recoveries == 1
    assert snapshot.consecutive_failures == 0
    assert snapshot.next_recovery_in_s == 0.0


@pytest.mark.anyio
async def test_failed_recovery_increases_failure_backoff() -> None:
    state = ResilienceState()
    redis = RecoverableRedis()

    controller = _controller(
        state,
        redis,
        recovery_interval_s=0.01,
        max_recovery_interval_s=0.10,
    )

    assert await controller.initialize() is True

    redis.available = False
    assert await controller.check_health() is False

    first_failure = await controller.snapshot()

    assert first_failure.total_failures == 1
    assert first_failure.current_backoff_s == pytest.approx(0.01)

    await asyncio.sleep(0.03)

    recovered = await controller.attempt_recovery()
    second_failure = await controller.snapshot()

    assert recovered is False
    assert second_failure.availability == (
        RedisAvailability.UNAVAILABLE
    )
    assert second_failure.total_recovery_attempts == 1
    assert second_failure.total_recoveries == 0
    assert second_failure.total_failures == 2
    assert second_failure.consecutive_failures == 2
    assert second_failure.current_backoff_s == pytest.approx(0.02)


@pytest.mark.anyio
async def test_forced_recovery_bypasses_backoff() -> None:
    state = ResilienceState()
    redis = RecoverableRedis()

    controller = _controller(
        state,
        redis,
        recovery_interval_s=30.0,
        max_recovery_interval_s=60.0,
    )

    assert await controller.initialize() is True

    redis.available = False
    assert await controller.check_health() is False

    redis.available = True

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
async def test_healthy_dependency_skips_unnecessary_recovery_ping() -> None:
    state = ResilienceState()
    redis = RecoverableRedis()
    controller = _controller(state, redis)

    assert await controller.initialize() is True

    ping_calls_before = redis.ping_calls

    available = await controller.attempt_recovery()
    snapshot = await controller.snapshot()

    assert available is True
    assert redis.ping_calls == ping_calls_before
    assert snapshot.total_recovery_attempts == 0
    assert snapshot.total_recoveries == 0


@pytest.mark.anyio
async def test_concurrent_recovery_attempts_are_single_flight() -> None:
    state = ResilienceState()
    redis = RecoverableRedis()

    controller = _controller(
        state,
        redis,
        recovery_interval_s=0.01,
        max_recovery_interval_s=0.10,
    )

    assert await controller.initialize() is True

    redis.available = False
    assert await controller.check_health() is False

    redis.available = True
    redis.delay_s = 0.03

    await asyncio.sleep(0.03)

    ping_calls_before = redis.ping_calls

    results = await asyncio.gather(
        *(
            controller.attempt_recovery()
            for _ in range(5)
        )
    )

    snapshot = await controller.snapshot()

    assert results == [True, True, True, True, True]

    # Only the first coroutine performs the Redis probe. The remaining
    # callers observe the recovered available state.
    assert redis.ping_calls == ping_calls_before + 1
    assert snapshot.total_recovery_attempts == 1
    assert snapshot.total_recoveries == 1
    assert snapshot.availability == RedisAvailability.AVAILABLE


@pytest.mark.anyio
async def test_failure_detail_is_bounded() -> None:
    state = ResilienceState()
    redis = RecoverableRedis()
    controller = _controller(state, redis)

    await controller.mark_failure(
        RedisFailureReason.OPERATION_ERROR,
        detail="x" * 1_000,
        unavailable=False,
    )

    snapshot = await controller.snapshot()
    state_snapshot = await state.snapshot()

    assert snapshot.availability == RedisAvailability.DEGRADED
    assert snapshot.last_failure_reason == (
        RedisFailureReason.OPERATION_ERROR
    )
    assert snapshot.last_failure_detail is not None
    assert len(snapshot.last_failure_detail) == 500
    assert state_snapshot.redis == "not_ready"


@pytest.mark.anyio
async def test_mark_success_clears_failure_state() -> None:
    state = ResilienceState()
    redis = RecoverableRedis()
    controller = _controller(state, redis)

    await controller.mark_failure(
        RedisFailureReason.READ_ERROR,
        detail="temporary Redis read failure",
        unavailable=True,
    )

    failed = await controller.snapshot()

    assert failed.total_failures == 1
    assert failed.consecutive_failures == 1
    assert failed.last_failure_reason == (
        RedisFailureReason.READ_ERROR
    )

    await controller.mark_success()

    recovered = await controller.snapshot()
    state_snapshot = await state.snapshot()

    assert recovered.availability == RedisAvailability.AVAILABLE
    assert recovered.available is True
    assert recovered.consecutive_failures == 0
    assert recovered.total_failures == 1
    assert recovered.total_recoveries == 1
    assert recovered.last_failure_reason is None
    assert recovered.last_failure_detail is None
    assert recovered.current_backoff_s == pytest.approx(0.02)
    assert recovered.next_recovery_in_s == 0.0
    assert state_snapshot.redis == "ready"


@pytest.mark.anyio
async def test_unknown_exception_becomes_healthcheck_failure() -> None:
    state = ResilienceState()
    redis = RecoverableRedis()
    controller = _controller(state, redis)

    assert await controller.initialize() is True

    redis.available = False
    redis.failure_factory = lambda: RuntimeError(
        "unexpected Redis client failure"
    )

    healthy = await controller.check_health()
    snapshot = await controller.snapshot()

    assert healthy is False
    assert snapshot.availability == (
        RedisAvailability.UNAVAILABLE
    )
    assert snapshot.last_failure_reason == (
        RedisFailureReason.HEALTHCHECK_FAILED
    )
    assert snapshot.last_failure_detail is not None
    assert "RuntimeError" in snapshot.last_failure_detail


@pytest.mark.anyio
async def test_attempt_recovery_validates_force_argument() -> None:
    state = ResilienceState()
    redis = RecoverableRedis()
    controller = _controller(state, redis)

    with pytest.raises(
        TypeError,
        match="force must be a boolean",
    ):
        await controller.attempt_recovery(
            force=1  # type: ignore[arg-type]
        )