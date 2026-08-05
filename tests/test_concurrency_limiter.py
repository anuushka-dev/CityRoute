# tests/test_concurrency_limiter.py

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError

import pytest

from app.core.concurrency_limiter import (
    ConcurrencyLimiter,
)


@pytest.fixture
def anyio_backend() -> str:
    """Run asynchronous limiter tests with asyncio."""

    return "asyncio"


async def _wait_for_counts(
    limiter: ConcurrencyLimiter,
    *,
    active: int | None = None,
    waiting: int | None = None,
    timeout_s: float = 1.0,
) -> None:
    """
    Wait until the limiter reaches the requested counter values.

    This avoids unreliable fixed sleeps in concurrency tests.
    """

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s

    while True:
        snapshot = await limiter.snapshot()

        active_matches = (
            active is None
            or snapshot.active_requests == active
        )
        waiting_matches = (
            waiting is None
            or snapshot.waiting_requests == waiting
        )

        if active_matches and waiting_matches:
            return

        if loop.time() >= deadline:
            raise AssertionError(
                "Limiter did not reach expected state: "
                f"expected active={active}, waiting={waiting}; "
                f"actual active={snapshot.active_requests}, "
                f"waiting={snapshot.waiting_requests}"
            )

        await asyncio.sleep(0.001)


def test_constructor_rejects_invalid_active_capacity() -> None:
    with pytest.raises(
        ValueError,
        match="max_active_requests",
    ):
        ConcurrencyLimiter(
            max_active_requests=0,
            max_waiting_requests=1,
            default_wait_timeout_s=1.0,
        )

    with pytest.raises(
        ValueError,
        match="max_active_requests",
    ):
        ConcurrencyLimiter(
            max_active_requests=-1,
            max_waiting_requests=1,
            default_wait_timeout_s=1.0,
        )

    with pytest.raises(
        ValueError,
        match="max_active_requests",
    ):
        ConcurrencyLimiter(
            max_active_requests=True,
            max_waiting_requests=1,
            default_wait_timeout_s=1.0,
        )


def test_constructor_rejects_invalid_waiting_capacity() -> None:
    with pytest.raises(
        ValueError,
        match="max_waiting_requests",
    ):
        ConcurrencyLimiter(
            max_active_requests=1,
            max_waiting_requests=-1,
            default_wait_timeout_s=1.0,
        )

    with pytest.raises(
        ValueError,
        match="max_waiting_requests",
    ):
        ConcurrencyLimiter(
            max_active_requests=1,
            max_waiting_requests=True,
            default_wait_timeout_s=1.0,
        )


def test_constructor_rejects_invalid_default_timeout() -> None:
    with pytest.raises(
        ValueError,
        match="default_wait_timeout_s",
    ):
        ConcurrencyLimiter(
            max_active_requests=1,
            max_waiting_requests=1,
            default_wait_timeout_s=-0.1,
        )

    with pytest.raises(
        ValueError,
        match="default_wait_timeout_s",
    ):
        ConcurrencyLimiter(
            max_active_requests=1,
            max_waiting_requests=1,
            default_wait_timeout_s=float("inf"),
        )


@pytest.mark.anyio
async def test_initial_snapshot_has_safe_defaults() -> None:
    limiter = ConcurrencyLimiter(
        max_active_requests=4,
        max_waiting_requests=8,
        default_wait_timeout_s=0.5,
    )

    snapshot = await limiter.snapshot()

    assert snapshot.max_active_requests == 4
    assert snapshot.max_waiting_requests == 8
    assert snapshot.default_wait_timeout_s == 0.5

    assert snapshot.accepting_requests is True
    assert snapshot.close_reason is None

    assert snapshot.active_requests == 0
    assert snapshot.waiting_requests == 0

    assert snapshot.max_observed_active_requests == 0
    assert snapshot.max_observed_waiting_requests == 0

    assert snapshot.total_admitted_requests == 0
    assert snapshot.total_released_requests == 0
    assert snapshot.total_rejected_requests == 0

    assert snapshot.queue_full_rejections == 0
    assert snapshot.wait_timeout_rejections == 0
    assert snapshot.limiter_closed_rejections == 0


@pytest.mark.anyio
async def test_request_is_admitted_immediately() -> None:
    limiter = ConcurrencyLimiter(
        max_active_requests=2,
        max_waiting_requests=2,
        default_wait_timeout_s=1.0,
    )

    outcome = await limiter.acquire()

    assert outcome.accepted is True
    assert outcome.queued is False
    assert outcome.rejection_reason is None
    assert outcome.waited_ms >= 0.0
    assert outcome.active_requests_at_decision == 1
    assert outcome.waiting_requests_at_decision == 0

    snapshot = await limiter.snapshot()

    assert snapshot.active_requests == 1
    assert snapshot.waiting_requests == 0
    assert snapshot.total_admitted_requests == 1
    assert snapshot.max_observed_active_requests == 1

    released = await outcome.require_lease().release()

    assert released is True

    final_snapshot = await limiter.snapshot()

    assert final_snapshot.active_requests == 0
    assert final_snapshot.total_released_requests == 1


@pytest.mark.anyio
async def test_lease_release_is_idempotent() -> None:
    limiter = ConcurrencyLimiter(
        max_active_requests=1,
        max_waiting_requests=0,
        default_wait_timeout_s=1.0,
    )

    outcome = await limiter.acquire()
    lease = outcome.require_lease()

    first_release = await lease.release()
    second_release = await lease.release()

    assert first_release is True
    assert second_release is False
    assert lease.released is True

    snapshot = await limiter.snapshot()

    assert snapshot.active_requests == 0
    assert snapshot.total_admitted_requests == 1
    assert snapshot.total_released_requests == 1


@pytest.mark.anyio
async def test_lease_async_context_manager_releases_capacity() -> None:
    limiter = ConcurrencyLimiter(
        max_active_requests=1,
        max_waiting_requests=0,
        default_wait_timeout_s=1.0,
    )

    outcome = await limiter.acquire()

    async with outcome.require_lease():
        active_snapshot = await limiter.snapshot()
        assert active_snapshot.active_requests == 1

    final_snapshot = await limiter.snapshot()

    assert final_snapshot.active_requests == 0
    assert final_snapshot.total_released_requests == 1


@pytest.mark.anyio
async def test_released_lease_cannot_be_entered_again() -> None:
    limiter = ConcurrencyLimiter(
        max_active_requests=1,
        max_waiting_requests=0,
        default_wait_timeout_s=1.0,
    )

    outcome = await limiter.acquire()
    lease = outcome.require_lease()

    await lease.release()

    with pytest.raises(
        RuntimeError,
        match="already released",
    ):
        async with lease:
            pass


@pytest.mark.anyio
async def test_request_waits_and_is_admitted_after_release() -> None:
    limiter = ConcurrencyLimiter(
        max_active_requests=1,
        max_waiting_requests=1,
        default_wait_timeout_s=1.0,
    )

    first = await limiter.acquire()

    second_task = asyncio.create_task(
        limiter.acquire()
    )

    await _wait_for_counts(
        limiter,
        active=1,
        waiting=1,
    )

    queued_snapshot = await limiter.snapshot()

    assert queued_snapshot.max_observed_waiting_requests == 1

    await first.require_lease().release()

    second = await asyncio.wait_for(
        second_task,
        timeout=1.0,
    )

    assert second.accepted is True
    assert second.queued is True
    assert second.rejection_reason is None
    assert second.waited_ms >= 0.0

    await second.require_lease().release()

    final_snapshot = await limiter.snapshot()

    assert final_snapshot.active_requests == 0
    assert final_snapshot.waiting_requests == 0
    assert final_snapshot.total_admitted_requests == 2
    assert final_snapshot.total_released_requests == 2
    assert final_snapshot.total_rejected_requests == 0


@pytest.mark.anyio
async def test_request_is_rejected_when_queue_is_full() -> None:
    limiter = ConcurrencyLimiter(
        max_active_requests=1,
        max_waiting_requests=1,
        default_wait_timeout_s=1.0,
    )

    active = await limiter.acquire()

    queued_task = asyncio.create_task(
        limiter.acquire()
    )

    await _wait_for_counts(
        limiter,
        active=1,
        waiting=1,
    )

    rejected = await limiter.acquire()

    assert rejected.accepted is False
    assert rejected.queued is False
    assert rejected.rejection_reason == "queue_full"
    assert rejected.lease is None
    assert rejected.active_requests_at_decision == 1
    assert rejected.waiting_requests_at_decision == 1

    with pytest.raises(
        RuntimeError,
        match="queue_full",
    ):
        rejected.require_lease()

    await active.require_lease().release()

    queued = await asyncio.wait_for(
        queued_task,
        timeout=1.0,
    )
    await queued.require_lease().release()

    snapshot = await limiter.snapshot()

    assert snapshot.total_rejected_requests == 1
    assert snapshot.queue_full_rejections == 1
    assert snapshot.wait_timeout_rejections == 0
    assert snapshot.limiter_closed_rejections == 0


@pytest.mark.anyio
async def test_zero_length_queue_rejects_when_active_is_full() -> None:
    limiter = ConcurrencyLimiter(
        max_active_requests=1,
        max_waiting_requests=0,
        default_wait_timeout_s=1.0,
    )

    active = await limiter.acquire()
    rejected = await limiter.acquire()

    assert rejected.accepted is False
    assert rejected.rejection_reason == "queue_full"

    await active.require_lease().release()

    snapshot = await limiter.snapshot()

    assert snapshot.total_admitted_requests == 1
    assert snapshot.total_rejected_requests == 1
    assert snapshot.queue_full_rejections == 1


@pytest.mark.anyio
async def test_queued_request_times_out() -> None:
    limiter = ConcurrencyLimiter(
        max_active_requests=1,
        max_waiting_requests=1,
        default_wait_timeout_s=0.02,
    )

    active = await limiter.acquire()

    timed_out = await limiter.acquire()

    assert timed_out.accepted is False
    assert timed_out.queued is True
    assert timed_out.rejection_reason == "wait_timeout"
    assert timed_out.waited_ms >= 0.0

    snapshot = await limiter.snapshot()

    assert snapshot.active_requests == 1
    assert snapshot.waiting_requests == 0
    assert snapshot.total_rejected_requests == 1
    assert snapshot.wait_timeout_rejections == 1

    await active.require_lease().release()


@pytest.mark.anyio
async def test_acquire_supports_timeout_override() -> None:
    limiter = ConcurrencyLimiter(
        max_active_requests=1,
        max_waiting_requests=1,
        default_wait_timeout_s=10.0,
    )

    active = await limiter.acquire()

    timed_out = await limiter.acquire(
        wait_timeout_s=0.01
    )

    assert timed_out.accepted is False
    assert timed_out.rejection_reason == "wait_timeout"

    await active.require_lease().release()


@pytest.mark.anyio
async def test_acquire_rejects_invalid_timeout_override() -> None:
    limiter = ConcurrencyLimiter(
        max_active_requests=1,
        max_waiting_requests=1,
        default_wait_timeout_s=1.0,
    )

    with pytest.raises(
        ValueError,
        match="wait_timeout_s",
    ):
        await limiter.acquire(
            wait_timeout_s=-1.0
        )

    with pytest.raises(
        ValueError,
        match="wait_timeout_s",
    ):
        await limiter.acquire(
            wait_timeout_s=float("inf")
        )


@pytest.mark.anyio
async def test_close_rejects_new_requests() -> None:
    limiter = ConcurrencyLimiter(
        max_active_requests=1,
        max_waiting_requests=1,
        default_wait_timeout_s=1.0,
    )

    await limiter.close(
        reason="service_shutdown"
    )

    rejected = await limiter.acquire()

    assert rejected.accepted is False
    assert rejected.queued is False
    assert rejected.rejection_reason == "limiter_closed"

    snapshot = await limiter.snapshot()

    assert snapshot.accepting_requests is False
    assert snapshot.close_reason == "service_shutdown"
    assert snapshot.total_rejected_requests == 1
    assert snapshot.limiter_closed_rejections == 1


@pytest.mark.anyio
async def test_close_preserves_first_close_reason() -> None:
    limiter = ConcurrencyLimiter(
        max_active_requests=1,
        max_waiting_requests=1,
        default_wait_timeout_s=1.0,
    )

    await limiter.close(reason="first_reason")
    await limiter.close(reason="second_reason")

    snapshot = await limiter.snapshot()

    assert snapshot.accepting_requests is False
    assert snapshot.close_reason == "first_reason"


@pytest.mark.anyio
async def test_close_wakes_and_rejects_queued_request() -> None:
    limiter = ConcurrencyLimiter(
        max_active_requests=1,
        max_waiting_requests=1,
        default_wait_timeout_s=5.0,
    )

    active = await limiter.acquire()

    queued_task = asyncio.create_task(
        limiter.acquire()
    )

    await _wait_for_counts(
        limiter,
        active=1,
        waiting=1,
    )

    await limiter.close(
        reason="service_shutdown"
    )

    queued = await asyncio.wait_for(
        queued_task,
        timeout=1.0,
    )

    assert queued.accepted is False
    assert queued.queued is True
    assert queued.rejection_reason == "limiter_closed"

    snapshot = await limiter.snapshot()

    assert snapshot.active_requests == 1
    assert snapshot.waiting_requests == 0
    assert snapshot.limiter_closed_rejections == 1

    await active.require_lease().release()


@pytest.mark.anyio
async def test_cancelling_queued_acquire_removes_waiter() -> None:
    limiter = ConcurrencyLimiter(
        max_active_requests=1,
        max_waiting_requests=1,
        default_wait_timeout_s=5.0,
    )

    active = await limiter.acquire()

    queued_task = asyncio.create_task(
        limiter.acquire()
    )

    await _wait_for_counts(
        limiter,
        active=1,
        waiting=1,
    )

    queued_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await queued_task

    snapshot = await limiter.snapshot()

    assert snapshot.active_requests == 1
    assert snapshot.waiting_requests == 0
    assert snapshot.total_rejected_requests == 0

    await active.require_lease().release()


@pytest.mark.anyio
async def test_wait_until_idle_succeeds_after_release() -> None:
    limiter = ConcurrencyLimiter(
        max_active_requests=1,
        max_waiting_requests=0,
        default_wait_timeout_s=1.0,
    )

    outcome = await limiter.acquire()

    async def release_later() -> None:
        await asyncio.sleep(0.02)
        await outcome.require_lease().release()

    release_task = asyncio.create_task(
        release_later()
    )

    idle = await limiter.wait_until_idle(
        timeout_s=0.5
    )

    await release_task

    assert idle is True

    snapshot = await limiter.snapshot()

    assert snapshot.active_requests == 0
    assert snapshot.waiting_requests == 0


@pytest.mark.anyio
async def test_wait_until_idle_times_out_with_active_request() -> None:
    limiter = ConcurrencyLimiter(
        max_active_requests=1,
        max_waiting_requests=0,
        default_wait_timeout_s=1.0,
    )

    outcome = await limiter.acquire()

    idle = await limiter.wait_until_idle(
        timeout_s=0.01
    )

    assert idle is False

    await outcome.require_lease().release()


@pytest.mark.anyio
async def test_zero_idle_timeout_succeeds_when_already_idle() -> None:
    limiter = ConcurrencyLimiter(
        max_active_requests=1,
        max_waiting_requests=1,
        default_wait_timeout_s=1.0,
    )

    idle = await limiter.wait_until_idle(
        timeout_s=0.0
    )

    assert idle is True


@pytest.mark.anyio
async def test_max_observed_active_requests_are_recorded() -> None:
    limiter = ConcurrencyLimiter(
        max_active_requests=3,
        max_waiting_requests=0,
        default_wait_timeout_s=1.0,
    )

    outcomes = [
        await limiter.acquire()
        for _ in range(3)
    ]

    snapshot = await limiter.snapshot()

    assert snapshot.active_requests == 3
    assert snapshot.max_observed_active_requests == 3
    assert snapshot.total_admitted_requests == 3

    for outcome in outcomes:
        await outcome.require_lease().release()

    final_snapshot = await limiter.snapshot()

    assert final_snapshot.active_requests == 0
    assert final_snapshot.max_observed_active_requests == 3
    assert final_snapshot.total_released_requests == 3


@pytest.mark.anyio
async def test_snapshot_is_immutable() -> None:
    limiter = ConcurrencyLimiter(
        max_active_requests=1,
        max_waiting_requests=1,
        default_wait_timeout_s=1.0,
    )

    snapshot = await limiter.snapshot()

    with pytest.raises(FrozenInstanceError):
        snapshot.active_requests = 10  # type: ignore[misc]