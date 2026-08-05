# tests/test_graceful_shutdown.py

from __future__ import annotations

import asyncio
from threading import Event as ThreadEvent

import pytest

from app.core.concurrency_limiter import ConcurrencyLimiter
from app.infrastructure.resilience_state import ResilienceState
from app.services.shutdown_service import (
    ShutdownHook,
    ShutdownPolicy,
    ShutdownService,
)


@pytest.fixture
def anyio_backend() -> str:
    """Run asynchronous shutdown tests with asyncio."""

    return "asyncio"


async def _initialize_running_state(
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


def _limiter() -> ConcurrencyLimiter:
    return ConcurrencyLimiter(
        max_active_requests=2,
        max_waiting_requests=2,
        default_wait_timeout_s=0.25,
    )


def _policy(
    *,
    drain_timeout_s: float = 0.25,
    cleanup_timeout_s: float = 0.25,
    default_hook_timeout_s: float = 0.10,
    run_sync_hooks_in_thread: bool = True,
) -> ShutdownPolicy:
    return ShutdownPolicy(
        drain_timeout_s=drain_timeout_s,
        cleanup_timeout_s=cleanup_timeout_s,
        default_hook_timeout_s=default_hook_timeout_s,
        run_sync_hooks_in_thread=run_sync_hooks_in_thread,
    )


def _phase_value(result: object) -> str:
    phase = getattr(result, "phase")
    value = getattr(phase, "value", phase)
    return str(value)


async def _wait_for_shutdown_request(
    state: ResilienceState,
    *,
    timeout_s: float = 1.0,
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s

    while True:
        snapshot = await state.snapshot()

        if snapshot.shutdown_requested:
            return

        if loop.time() >= deadline:
            raise AssertionError(
                "Shutdown did not enter draining state"
            )

        await asyncio.sleep(0.001)


def test_shutdown_policy_rejects_invalid_drain_timeout() -> None:
    with pytest.raises((TypeError, ValueError)):
        _policy(drain_timeout_s=-1.0)


def test_shutdown_policy_rejects_invalid_cleanup_timeout() -> None:
    with pytest.raises((TypeError, ValueError)):
        _policy(cleanup_timeout_s=-1.0)


def test_shutdown_policy_rejects_invalid_hook_timeout() -> None:
    with pytest.raises((TypeError, ValueError)):
        _policy(default_hook_timeout_s=-1.0)


@pytest.mark.anyio
async def test_idle_service_shuts_down_gracefully() -> None:
    state = ResilienceState()
    limiter = _limiter()

    await _initialize_running_state(state)

    service = ShutdownService(
        resilience_state=state,
        concurrency_limiter=limiter,
        policy=_policy(),
    )

    result = await service.shutdown()

    state_snapshot = await state.snapshot()
    limiter_snapshot = await limiter.snapshot()

    assert _phase_value(result) == "complete"
    assert result.graceful is True
    assert result.forced is False
    assert result.drained is True
    assert result.cleanup_success is True

    assert state_snapshot.shutdown_requested is True
    assert state_snapshot.shutdown_complete is True
    assert state_snapshot.accepting_requests is False

    assert limiter_snapshot.accepting_requests is False
    assert limiter_snapshot.close_reason == "service_shutdown"
    assert limiter_snapshot.active_requests == 0
    assert limiter_snapshot.waiting_requests == 0


@pytest.mark.anyio
async def test_shutdown_waits_for_inflight_request() -> None:
    state = ResilienceState()
    limiter = _limiter()

    await _initialize_running_state(state)

    admission = await limiter.acquire()
    lease = admission.require_lease()

    await state.request_started()

    service = ShutdownService(
        resilience_state=state,
        concurrency_limiter=limiter,
        policy=_policy(
            drain_timeout_s=0.5,
        ),
    )

    shutdown_task = asyncio.create_task(
        service.shutdown()
    )

    await _wait_for_shutdown_request(state)

    limiter_during_shutdown = await limiter.snapshot()
    state_during_shutdown = await state.snapshot()

    assert limiter_during_shutdown.accepting_requests is False
    assert limiter_during_shutdown.active_requests == 1

    assert state_during_shutdown.shutdown_requested is True
    assert state_during_shutdown.accepting_requests is False
    assert state_during_shutdown.active_requests == 1

    await state.request_finished()
    await lease.release()

    result = await asyncio.wait_for(
        shutdown_task,
        timeout=1.0,
    )

    state_snapshot = await state.snapshot()
    limiter_snapshot = await limiter.snapshot()

    assert result.drained is True
    assert result.forced is False
    assert result.graceful is True

    assert state_snapshot.active_requests == 0
    assert state_snapshot.completed_requests == 1
    assert state_snapshot.shutdown_complete is True

    assert limiter_snapshot.active_requests == 0
    assert limiter_snapshot.total_released_requests == 1


@pytest.mark.anyio
async def test_new_requests_are_rejected_after_shutdown_begins(
) -> None:
    state = ResilienceState()
    limiter = _limiter()

    await _initialize_running_state(state)

    active = await limiter.acquire()
    await state.request_started()

    service = ShutdownService(
        resilience_state=state,
        concurrency_limiter=limiter,
        policy=_policy(
            drain_timeout_s=0.5,
        ),
    )

    shutdown_task = asyncio.create_task(
        service.shutdown()
    )

    await _wait_for_shutdown_request(state)

    rejected = await limiter.acquire()

    assert rejected.accepted is False
    assert rejected.rejection_reason == "limiter_closed"
    assert rejected.lease is None

    with pytest.raises(RuntimeError):
        await state.set_accepting_requests(True)

    await state.request_finished()
    await active.require_lease().release()

    result = await shutdown_task

    assert result.drained is True
    assert result.forced is False


@pytest.mark.anyio
async def test_shutdown_executes_async_cleanup_hook() -> None:
    state = ResilienceState()
    limiter = _limiter()
    hook_executed = asyncio.Event()

    await _initialize_running_state(state)

    async def cleanup() -> None:
        hook_executed.set()

    service = ShutdownService(
        resilience_state=state,
        concurrency_limiter=limiter,
        policy=_policy(),
        cleanup_hooks=(
            ShutdownHook(
                name="async_cleanup",
                callback=cleanup,
            ),
        ),
    )

    result = await service.shutdown()

    assert hook_executed.is_set()
    assert result.cleanup_success is True
    assert result.graceful is True
    assert _phase_value(result) == "complete"


@pytest.mark.anyio
async def test_shutdown_executes_synchronous_cleanup_hook() -> None:
    state = ResilienceState()
    limiter = _limiter()
    hook_executed = ThreadEvent()

    await _initialize_running_state(state)

    def cleanup() -> None:
        hook_executed.set()

    service = ShutdownService(
        resilience_state=state,
        concurrency_limiter=limiter,
        policy=_policy(
            run_sync_hooks_in_thread=True,
        ),
        cleanup_hooks=(
            ShutdownHook(
                name="sync_cleanup",
                callback=cleanup,
            ),
        ),
    )

    result = await service.shutdown()

    assert hook_executed.is_set()
    assert result.cleanup_success is True

    snapshot = await state.snapshot()

    assert snapshot.shutdown_complete is True


@pytest.mark.anyio
async def test_cleanup_exception_is_controlled() -> None:
    state = ResilienceState()
    limiter = _limiter()

    await _initialize_running_state(state)

    async def failing_cleanup() -> None:
        raise RuntimeError("cleanup failure")

    service = ShutdownService(
        resilience_state=state,
        concurrency_limiter=limiter,
        policy=_policy(),
        cleanup_hooks=(
            ShutdownHook(
                name="failing_cleanup",
                callback=failing_cleanup,
            ),
        ),
    )

    result = await service.shutdown()
    snapshot = await state.snapshot()

    assert _phase_value(result) == "failed"
    assert result.drained is True
    assert result.cleanup_success is False
    assert result.graceful is False
    assert result.forced is False

    # A failed cleanup hook must not leave lifecycle shutdown incomplete.
    assert snapshot.shutdown_requested is True
    assert snapshot.shutdown_complete is True
    assert snapshot.accepting_requests is False


@pytest.mark.anyio
async def test_cleanup_hook_timeout_is_controlled() -> None:
    state = ResilienceState()
    limiter = _limiter()

    hook_started = asyncio.Event()
    hook_finished = asyncio.Event()

    await _initialize_running_state(state)

    async def slow_cleanup() -> None:
        hook_started.set()

        try:
            await asyncio.sleep(5.0)
        finally:
            hook_finished.set()

    service = ShutdownService(
        resilience_state=state,
        concurrency_limiter=limiter,
        policy=_policy(
            cleanup_timeout_s=0.10,
            default_hook_timeout_s=0.01,
        ),
        cleanup_hooks=(
            ShutdownHook(
                name="slow_cleanup",
                callback=slow_cleanup,
            ),
        ),
    )

    result = await service.shutdown()

    assert hook_started.is_set()
    assert hook_finished.is_set()

    assert _phase_value(result) == "failed"
    assert result.drained is True
    assert result.cleanup_success is False
    assert result.graceful is False
    assert result.forced is False

    snapshot = await state.snapshot()

    assert snapshot.shutdown_complete is True


@pytest.mark.anyio
async def test_drain_timeout_forces_shutdown() -> None:
    state = ResilienceState()
    limiter = _limiter()

    await _initialize_running_state(state)

    admission = await limiter.acquire()
    lease = admission.require_lease()

    await state.request_started()

    service = ShutdownService(
        resilience_state=state,
        concurrency_limiter=limiter,
        policy=_policy(
            drain_timeout_s=0.01,
        ),
    )

    result = await service.shutdown()

    state_snapshot = await state.snapshot()
    limiter_snapshot = await limiter.snapshot()

    assert _phase_value(result) == "forced"
    assert result.drained is False
    assert result.forced is True
    assert result.graceful is False
    assert result.cleanup_success is True

    assert state_snapshot.shutdown_complete is True
    assert state_snapshot.active_requests == 1

    assert limiter_snapshot.accepting_requests is False
    assert limiter_snapshot.active_requests == 1

    # Release the intentionally stuck request after the assertion.
    await state.request_finished()
    await lease.release()


@pytest.mark.anyio
async def test_shutdown_is_idempotent() -> None:
    state = ResilienceState()
    limiter = _limiter()
    cleanup_calls = 0

    await _initialize_running_state(state)

    async def cleanup() -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1

    service = ShutdownService(
        resilience_state=state,
        concurrency_limiter=limiter,
        policy=_policy(),
        cleanup_hooks=(
            ShutdownHook(
                name="cleanup",
                callback=cleanup,
            ),
        ),
    )

    first_result = await service.shutdown()
    second_result = await service.shutdown()

    assert cleanup_calls == 1
    assert first_result == second_result
    assert _phase_value(first_result) == "complete"

    snapshot = await state.snapshot()

    assert snapshot.shutdown_complete is True


@pytest.mark.anyio
async def test_concurrent_shutdown_calls_are_single_flight() -> None:
    state = ResilienceState()
    limiter = _limiter()

    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    cleanup_calls = 0

    await _initialize_running_state(state)

    async def cleanup() -> None:
        nonlocal cleanup_calls

        cleanup_calls += 1
        cleanup_started.set()

        await release_cleanup.wait()

    service = ShutdownService(
        resilience_state=state,
        concurrency_limiter=limiter,
        policy=_policy(
            cleanup_timeout_s=1.0,
            default_hook_timeout_s=1.0,
        ),
        cleanup_hooks=(
            ShutdownHook(
                name="single_flight_cleanup",
                callback=cleanup,
            ),
        ),
    )

    tasks = [
        asyncio.create_task(service.shutdown())
        for _ in range(5)
    ]

    await asyncio.wait_for(
        cleanup_started.wait(),
        timeout=1.0,
    )

    release_cleanup.set()

    results = await asyncio.gather(*tasks)

    assert cleanup_calls == 1
    assert all(
        result == results[0]
        for result in results
    )

    assert results[0].drained is True
    assert results[0].cleanup_success is True
    assert _phase_value(results[0]) == "complete"


@pytest.mark.anyio
async def test_cleanup_hooks_run_after_requests_drain() -> None:
    state = ResilienceState()
    limiter = _limiter()

    await _initialize_running_state(state)

    admission = await limiter.acquire()
    lease = admission.require_lease()
    await state.request_started()

    hook_observation: dict[str, int] = {}

    async def inspect_counts() -> None:
        limiter_snapshot = await limiter.snapshot()
        state_snapshot = await state.snapshot()

        hook_observation["limiter_active"] = (
            limiter_snapshot.active_requests
        )
        hook_observation["state_active"] = (
            state_snapshot.active_requests
        )

    service = ShutdownService(
        resilience_state=state,
        concurrency_limiter=limiter,
        policy=_policy(
            drain_timeout_s=0.5,
        ),
        cleanup_hooks=(
            ShutdownHook(
                name="inspect_drained_state",
                callback=inspect_counts,
            ),
        ),
    )

    shutdown_task = asyncio.create_task(
        service.shutdown()
    )

    await _wait_for_shutdown_request(state)

    await state.request_finished()
    await lease.release()

    result = await shutdown_task

    assert result.drained is True
    assert result.cleanup_success is True

    assert hook_observation == {
        "limiter_active": 0,
        "state_active": 0,
    }


@pytest.mark.anyio
async def test_shutdown_timestamps_are_recorded() -> None:
    state = ResilienceState()
    limiter = _limiter()

    await _initialize_running_state(state)

    before = await state.snapshot()

    service = ShutdownService(
        resilience_state=state,
        concurrency_limiter=limiter,
        policy=_policy(),
    )

    await service.shutdown()

    after = await state.snapshot()

    assert before.shutdown_requested_at_utc is None
    assert before.shutdown_completed_at_utc is None

    assert after.shutdown_requested_at_utc is not None
    assert after.shutdown_completed_at_utc is not None
    assert (
        after.shutdown_completed_at_utc
        >= after.shutdown_requested_at_utc
    )