# tests/test_resilience_state.py

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError

import pytest

from app.infrastructure.resilience_state import ResilienceState


@pytest.fixture
def anyio_backend() -> str:
    """Run asynchronous state tests with asyncio."""

    return "asyncio"


@pytest.mark.anyio
async def test_initial_snapshot_has_safe_defaults() -> None:
    state = ResilienceState()

    snapshot = await state.snapshot()

    assert snapshot.uptime_s >= 0.0

    assert snapshot.startup_started is False
    assert snapshot.startup_complete is False
    assert snapshot.accepting_requests is False

    assert snapshot.shutdown_requested is False
    assert snapshot.shutdown_complete is False

    assert snapshot.startup_started_at_utc is None
    assert snapshot.startup_completed_at_utc is None
    assert snapshot.shutdown_requested_at_utc is None
    assert snapshot.shutdown_completed_at_utc is None

    assert snapshot.graph == "not_initialized"
    assert snapshot.snap_index == "not_initialized"
    assert snapshot.dispatch_adjacency == "not_initialized"
    assert snapshot.redis == "not_initialized"

    assert snapshot.active_requests == 0
    assert snapshot.waiting_requests == 0
    assert snapshot.completed_requests == 0
    assert snapshot.rejected_requests == 0
    assert snapshot.timed_out_requests == 0
    assert snapshot.overload_events == 0

    assert snapshot.last_failure_reason is None
    assert snapshot.last_rejection_reason is None
    assert snapshot.last_timeout_endpoint is None

    assert snapshot.last_redis_success_at_utc is None
    assert snapshot.last_redis_failure_at_utc is None
    assert snapshot.last_redis_failure_reason is None


@pytest.mark.anyio
async def test_startup_lifecycle_transitions() -> None:
    state = ResilienceState()

    await state.mark_startup_started()

    started_snapshot = await state.snapshot()

    assert started_snapshot.startup_started is True
    assert started_snapshot.startup_complete is False
    assert started_snapshot.accepting_requests is False
    assert started_snapshot.startup_started_at_utc is not None
    assert started_snapshot.startup_completed_at_utc is None

    await state.mark_startup_complete(
        accepting_requests=True
    )

    completed_snapshot = await state.snapshot()

    assert completed_snapshot.startup_started is True
    assert completed_snapshot.startup_complete is True
    assert completed_snapshot.accepting_requests is True
    assert completed_snapshot.startup_started_at_utc is not None
    assert completed_snapshot.startup_completed_at_utc is not None


@pytest.mark.anyio
async def test_startup_can_complete_without_accepting_requests() -> None:
    state = ResilienceState()

    await state.mark_startup_started()
    await state.mark_startup_complete(
        accepting_requests=False
    )

    snapshot = await state.snapshot()

    assert snapshot.startup_started is True
    assert snapshot.startup_complete is True
    assert snapshot.accepting_requests is False


@pytest.mark.anyio
async def test_component_helpers_update_runtime_states() -> None:
    state = ResilienceState()

    await state.set_graph_ready(True)
    await state.set_snap_index_ready(True)
    await state.set_dispatch_adjacency_ready(True)

    ready_snapshot = await state.snapshot()

    assert ready_snapshot.graph == "ready"
    assert ready_snapshot.snap_index == "ready"
    assert ready_snapshot.dispatch_adjacency == "ready"

    await state.set_graph_ready(False)
    await state.set_snap_index_ready(False)
    await state.set_dispatch_adjacency_ready(False)

    unavailable_snapshot = await state.snapshot()

    assert unavailable_snapshot.graph == "not_ready"
    assert unavailable_snapshot.snap_index == "not_ready"
    assert unavailable_snapshot.dispatch_adjacency == "not_ready"


@pytest.mark.anyio
async def test_set_component_state_supports_explicit_status() -> None:
    state = ResilienceState()

    await state.set_component_state(
        "graph",
        "unavailable",
    )
    await state.set_component_state(
        "snap_index",
        "not_ready",
    )
    await state.set_component_state(
        "dispatch_adjacency",
        "ready",
    )
    await state.set_component_state(
        "redis",
        "not_initialized",
    )

    snapshot = await state.snapshot()

    assert snapshot.graph == "unavailable"
    assert snapshot.snap_index == "not_ready"
    assert snapshot.dispatch_adjacency == "ready"
    assert snapshot.redis == "not_initialized"


@pytest.mark.anyio
async def test_redis_success_and_failure_are_recorded() -> None:
    state = ResilienceState()

    await state.mark_redis_success()

    healthy_snapshot = await state.snapshot()

    assert healthy_snapshot.redis == "ready"
    assert healthy_snapshot.last_redis_success_at_utc is not None
    assert healthy_snapshot.last_redis_failure_at_utc is None
    assert healthy_snapshot.last_redis_failure_reason is None

    await state.mark_redis_failure(
        "connection_error:connection refused",
        unavailable=True,
    )

    failed_snapshot = await state.snapshot()

    assert failed_snapshot.redis == "unavailable"
    assert failed_snapshot.last_redis_failure_at_utc is not None
    assert (
        failed_snapshot.last_redis_failure_reason
        == "connection_error:connection refused"
    )

    await state.mark_redis_failure(
        "corrupted_payload",
        unavailable=False,
    )

    degraded_snapshot = await state.snapshot()

    assert degraded_snapshot.redis == "not_ready"
    assert degraded_snapshot.last_redis_failure_reason == (
        "corrupted_payload"
    )

    await state.mark_redis_success()

    recovered_snapshot = await state.snapshot()

    assert recovered_snapshot.redis == "ready"
    assert recovered_snapshot.last_redis_success_at_utc is not None


@pytest.mark.anyio
async def test_waiting_request_counters_do_not_underflow() -> None:
    state = ResilienceState()

    first_count = await state.waiting_started()
    second_count = await state.waiting_started()

    assert first_count == 1
    assert second_count == 2

    snapshot = await state.snapshot()
    assert snapshot.waiting_requests == 2

    first_finished = await state.waiting_finished()
    second_finished = await state.waiting_finished()
    extra_finished = await state.waiting_finished()

    assert first_finished is True
    assert second_finished is True
    assert extra_finished is False

    final_snapshot = await state.snapshot()
    assert final_snapshot.waiting_requests == 0


@pytest.mark.anyio
async def test_request_counters_track_active_and_completed_work() -> None:
    state = ResilienceState()

    first_active = await state.request_started()
    second_active = await state.request_started()

    assert first_active == 1
    assert second_active == 2

    active_snapshot = await state.snapshot()

    assert active_snapshot.active_requests == 2
    assert active_snapshot.completed_requests == 0

    first_finished = await state.request_finished()

    middle_snapshot = await state.snapshot()

    assert first_finished is True
    assert middle_snapshot.active_requests == 1
    assert middle_snapshot.completed_requests == 1

    second_finished = await state.request_finished()
    extra_finished = await state.request_finished()

    assert second_finished is True
    assert extra_finished is False

    final_snapshot = await state.snapshot()

    assert final_snapshot.active_requests == 0
    assert final_snapshot.completed_requests == 2


@pytest.mark.anyio
async def test_reliability_events_and_last_reasons_are_recorded() -> None:
    state = ResilienceState()

    await state.request_rejected("queue_full")
    await state.request_rejected("service_shutting_down")

    rejection_snapshot = await state.snapshot()

    assert rejection_snapshot.rejected_requests == 2
    assert (
        rejection_snapshot.last_rejection_reason
        == "service_shutting_down"
    )

    await state.request_timed_out(
        "/vrp/compare/advanced"
    )

    await state.overload_event("queue_full")
    await state.overload_event("wait_timeout")

    await state.record_failure(
        "dispatch_adjacency_build_failed"
    )

    snapshot = await state.snapshot()

    assert snapshot.rejected_requests == 2

    # The latest overload reason becomes the latest operational
    # rejection reason.
    assert snapshot.last_rejection_reason == "wait_timeout"

    assert snapshot.timed_out_requests == 1
    assert snapshot.last_timeout_endpoint == (
        "/vrp/compare/advanced"
    )

    assert snapshot.overload_events == 2
    assert snapshot.last_failure_reason == (
        "dispatch_adjacency_build_failed"
    )

@pytest.mark.anyio
async def test_shutdown_lifecycle_disables_admission() -> None:
    state = ResilienceState()

    await state.mark_startup_started()
    await state.mark_startup_complete()

    await state.begin_shutdown()

    draining_snapshot = await state.snapshot()

    assert draining_snapshot.shutdown_requested is True
    assert draining_snapshot.shutdown_complete is False
    assert draining_snapshot.accepting_requests is False
    assert draining_snapshot.shutdown_requested_at_utc is not None
    assert draining_snapshot.shutdown_completed_at_utc is None

    await state.mark_shutdown_complete()

    completed_snapshot = await state.snapshot()

    assert completed_snapshot.shutdown_requested is True
    assert completed_snapshot.shutdown_complete is True
    assert completed_snapshot.accepting_requests is False
    assert completed_snapshot.shutdown_requested_at_utc is not None
    assert completed_snapshot.shutdown_completed_at_utc is not None


@pytest.mark.anyio
async def test_set_accepting_requests_changes_admission_state() -> None:
    state = ResilienceState()

    # Admission cannot be enabled before startup completes.
    with pytest.raises(
        RuntimeError,
        match="Cannot accept requests before startup is complete",
    ):
        await state.set_accepting_requests(True)

    await state.mark_startup_started()
    await state.mark_startup_complete(
        accepting_requests=False
    )

    startup_snapshot = await state.snapshot()

    assert startup_snapshot.startup_complete is True
    assert startup_snapshot.accepting_requests is False

    await state.set_accepting_requests(True)

    accepting_snapshot = await state.snapshot()

    assert accepting_snapshot.accepting_requests is True

    await state.set_accepting_requests(False)

    rejecting_snapshot = await state.snapshot()

    assert rejecting_snapshot.accepting_requests is False

@pytest.mark.anyio
async def test_wait_for_active_requests_to_drain_succeeds() -> None:
    state = ResilienceState()

    await state.request_started()

    async def finish_request() -> None:
        await asyncio.sleep(0.03)
        await state.request_finished()

    finish_task = asyncio.create_task(
        finish_request()
    )

    drained = await state.wait_for_active_requests_to_drain(
        timeout_s=0.5
    )

    await finish_task

    snapshot = await state.snapshot()

    assert drained is True
    assert snapshot.active_requests == 0
    assert snapshot.completed_requests == 1


@pytest.mark.anyio
async def test_wait_for_active_requests_to_drain_times_out() -> None:
    state = ResilienceState()

    await state.request_started()

    drained = await state.wait_for_active_requests_to_drain(
        timeout_s=0.01
    )

    snapshot = await state.snapshot()

    assert drained is False
    assert snapshot.active_requests == 1

    await state.request_finished()


@pytest.mark.anyio
async def test_zero_timeout_succeeds_when_already_idle() -> None:
    state = ResilienceState()

    drained = await state.wait_for_active_requests_to_drain(
        timeout_s=0.0
    )

    assert drained is True


@pytest.mark.anyio
async def test_concurrent_request_updates_are_atomic() -> None:
    state = ResilienceState()

    worker_count = 50

    all_started = asyncio.Event()
    release_workers = asyncio.Event()
    start_lock = asyncio.Lock()
    started_count = 0

    async def worker() -> None:
        nonlocal started_count

        await state.request_started()

        async with start_lock:
            started_count += 1

            if started_count == worker_count:
                all_started.set()

        await release_workers.wait()
        await state.request_finished()

    tasks = [
        asyncio.create_task(worker())
        for _ in range(worker_count)
    ]

    await asyncio.wait_for(
        all_started.wait(),
        timeout=1.0,
    )

    active_snapshot = await state.snapshot()

    assert active_snapshot.active_requests == worker_count
    assert active_snapshot.completed_requests == 0

    release_workers.set()

    await asyncio.gather(*tasks)

    completed_snapshot = await state.snapshot()

    assert completed_snapshot.active_requests == 0
    assert completed_snapshot.completed_requests == worker_count


@pytest.mark.anyio
async def test_snapshot_is_immutable() -> None:
    state = ResilienceState()
    snapshot = await state.snapshot()

    with pytest.raises(FrozenInstanceError):
        snapshot.active_requests = 10  # type: ignore[misc]