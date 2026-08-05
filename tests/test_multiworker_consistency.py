# tests/test_multiworker_consistency.py

from __future__ import annotations

import asyncio
import multiprocessing
import os
import queue
import traceback
from collections.abc import Sequence
from typing import Protocol, cast

WORKER_TIMEOUT_S = 30.0


class _QueueLike(Protocol):
    def put(self, item: object) -> None:
        """Place an item in the multiprocessing queue."""

    def get(
        self,
        block: bool = True,
        timeout: float | None = None,
    ) -> object:
        """Retrieve an item from the multiprocessing queue."""


class _EventLike(Protocol):
    def set(self) -> None:
        """Set the multiprocessing event."""

    def wait(
        self,
        timeout: float | None = None,
    ) -> bool:
        """Wait until the multiprocessing event is set."""


def _limiter_snapshot_payload(
    snapshot: object,
) -> dict[str, object]:
    return {
        "max_active_requests": getattr(
            snapshot,
            "max_active_requests",
        ),
        "max_waiting_requests": getattr(
            snapshot,
            "max_waiting_requests",
        ),
        "default_wait_timeout_s": getattr(
            snapshot,
            "default_wait_timeout_s",
        ),
        "accepting_requests": getattr(
            snapshot,
            "accepting_requests",
        ),
        "close_reason": getattr(
            snapshot,
            "close_reason",
        ),
        "active_requests": getattr(
            snapshot,
            "active_requests",
        ),
        "waiting_requests": getattr(
            snapshot,
            "waiting_requests",
        ),
        "total_admitted_requests": getattr(
            snapshot,
            "total_admitted_requests",
        ),
        "total_released_requests": getattr(
            snapshot,
            "total_released_requests",
        ),
        "total_rejected_requests": getattr(
            snapshot,
            "total_rejected_requests",
        ),
        "queue_full_rejections": getattr(
            snapshot,
            "queue_full_rejections",
        ),
        "wait_timeout_rejections": getattr(
            snapshot,
            "wait_timeout_rejections",
        ),
        "limiter_closed_rejections": getattr(
            snapshot,
            "limiter_closed_rejections",
        ),
    }


def _state_snapshot_payload(
    snapshot: object,
) -> dict[str, object]:
    return {
        "startup_started": getattr(
            snapshot,
            "startup_started",
        ),
        "startup_complete": getattr(
            snapshot,
            "startup_complete",
        ),
        "accepting_requests": getattr(
            snapshot,
            "accepting_requests",
        ),
        "shutdown_requested": getattr(
            snapshot,
            "shutdown_requested",
        ),
        "shutdown_complete": getattr(
            snapshot,
            "shutdown_complete",
        ),
        "graph": getattr(
            snapshot,
            "graph",
        ),
        "snap_index": getattr(
            snapshot,
            "snap_index",
        ),
        "dispatch_adjacency": getattr(
            snapshot,
            "dispatch_adjacency",
        ),
        "redis": getattr(
            snapshot,
            "redis",
        ),
        "active_requests": getattr(
            snapshot,
            "active_requests",
        ),
        "waiting_requests": getattr(
            snapshot,
            "waiting_requests",
        ),
        "completed_requests": getattr(
            snapshot,
            "completed_requests",
        ),
        "rejected_requests": getattr(
            snapshot,
            "rejected_requests",
        ),
        "timed_out_requests": getattr(
            snapshot,
            "timed_out_requests",
        ),
        "overload_events": getattr(
            snapshot,
            "overload_events",
        ),
        "last_rejection_reason": getattr(
            snapshot,
            "last_rejection_reason",
        ),
    }


def _worker_probe(
    worker_id: int,
    mode: str,
    result_queue: _QueueLike,
) -> None:
    """
    Inspect or mutate the process-local Phase 11 runtime.

    Each spawned process imports app.main independently, matching the
    isolation model used by multiworker ASGI servers.
    """

    try:
        from app.config import get_settings
        from app.main import (
            APP_VERSION,
            PROJECT_PHASE_CODE,
            PROJECT_PHASE_NAME,
            app,
        )

        async def run_probe() -> dict[str, object]:
            limiter = app.state.concurrency_limiter
            state = app.state.resilience_state
            settings = get_settings()

            limiter_before = await limiter.snapshot()
            state_before = await state.snapshot()

            result: dict[str, object] = {
                "ok": True,
                "worker_id": worker_id,
                "mode": mode,
                "pid": os.getpid(),
                "version": APP_VERSION,
                "phase_code": PROJECT_PHASE_CODE,
                "phase_name": PROJECT_PHASE_NAME,
                "settings_max_active": (
                    settings.concurrency_max_active_requests
                ),
                "settings_max_waiting": (
                    settings.concurrency_max_waiting_requests
                ),
                "limiter_before": _limiter_snapshot_payload(
                    limiter_before
                ),
                "state_before": _state_snapshot_payload(
                    state_before
                ),
            }

            if mode == "observe":
                return result

            if mode == "normal_request":
                outcome = await limiter.acquire()

                result["request_accepted"] = outcome.accepted
                result["request_rejection_reason"] = (
                    outcome.rejection_reason
                )

                if outcome.accepted:
                    during = await limiter.snapshot()

                    result["limiter_during"] = (
                        _limiter_snapshot_payload(during)
                    )

                    await outcome.require_lease().release()

                result["limiter_after"] = (
                    _limiter_snapshot_payload(
                        await limiter.snapshot()
                    )
                )

                return result

            if mode == "mutate":
                await state.mark_startup_started()

                await state.set_graph_ready(True)
                await state.set_snap_index_ready(True)
                await state.set_dispatch_adjacency_ready(True)
                await state.mark_redis_success()

                await state.mark_startup_complete(
                    accepting_requests=True,
                )

                outcome = await limiter.acquire()

                if not outcome.accepted:
                    raise AssertionError(
                        "Fresh worker failed to acquire capacity"
                    )

                await state.request_started()
                await state.request_rejected(
                    "worker_rejection",
                )
                await state.overload_event(
                    "worker_overload",
                )

                result["limiter_during"] = (
                    _limiter_snapshot_payload(
                        await limiter.snapshot()
                    )
                )
                result["state_during"] = (
                    _state_snapshot_payload(
                        await state.snapshot()
                    )
                )

                await state.request_finished()
                await outcome.require_lease().release()

                result["limiter_after"] = (
                    _limiter_snapshot_payload(
                        await limiter.snapshot()
                    )
                )
                result["state_after"] = (
                    _state_snapshot_payload(
                        await state.snapshot()
                    )
                )

                return result

            if mode == "close":
                await limiter.close(
                    reason=f"worker_{worker_id}_shutdown",
                )

                rejected = await limiter.acquire()

                result["request_accepted"] = rejected.accepted
                result["request_rejection_reason"] = (
                    rejected.rejection_reason
                )
                result["limiter_after"] = (
                    _limiter_snapshot_payload(
                        await limiter.snapshot()
                    )
                )

                return result

            raise ValueError(
                f"Unsupported worker probe mode: {mode}"
            )

        result_queue.put(
            asyncio.run(run_probe())
        )
    except BaseException as exc:
        result_queue.put(
            {
                "ok": False,
                "worker_id": worker_id,
                "mode": mode,
                "pid": os.getpid(),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        raise


def _capacity_worker(
    worker_id: int,
    ready_queue: _QueueLike,
    result_queue: _QueueLike,
    release_event: _EventLike,
) -> None:
    """
    Saturate one process-local limiter and wait for coordinated release.

    The parent waits until every worker reaches its own maximum capacity,
    proving that the configured limit applies independently per process.
    """

    try:
        from app.main import app

        async def run_capacity_probe() -> dict[str, object]:
            limiter = app.state.concurrency_limiter
            initial = await limiter.snapshot()

            leases = []

            for _ in range(initial.max_active_requests):
                outcome = await limiter.acquire()

                if not outcome.accepted:
                    raise AssertionError(
                        "Worker could not reach configured "
                        "active-request capacity"
                    )

                leases.append(
                    outcome.require_lease()
                )

            saturated = await limiter.snapshot()

            ready_queue.put(
                {
                    "ok": True,
                    "worker_id": worker_id,
                    "pid": os.getpid(),
                    "max_active_requests": (
                        saturated.max_active_requests
                    ),
                    "active_requests": (
                        saturated.active_requests
                    ),
                    "waiting_requests": (
                        saturated.waiting_requests
                    ),
                }
            )

            released_by_parent = await asyncio.to_thread(
                release_event.wait,
                WORKER_TIMEOUT_S,
            )

            if not released_by_parent:
                raise TimeoutError(
                    "Parent did not release capacity workers"
                )

            for lease in leases:
                await lease.release()

            final = await limiter.snapshot()

            return {
                "ok": True,
                "worker_id": worker_id,
                "pid": os.getpid(),
                "max_active_requests": (
                    final.max_active_requests
                ),
                "active_requests": final.active_requests,
                "waiting_requests": final.waiting_requests,
                "total_admitted_requests": (
                    final.total_admitted_requests
                ),
                "total_released_requests": (
                    final.total_released_requests
                ),
            }

        result_queue.put(
            asyncio.run(run_capacity_probe())
        )
    except BaseException as exc:
        result_queue.put(
            {
                "ok": False,
                "worker_id": worker_id,
                "pid": os.getpid(),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        raise


def _assert_worker_result_success(
    result: dict[str, object],
) -> None:
    assert result["ok"] is True, (
        "Spawned worker failed:\n"
        f"{result.get('traceback', result)}"
    )


def _collect_worker_results(
    modes: Sequence[str],
) -> list[dict[str, object]]:
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()

    processes = [
        context.Process(
            target=_worker_probe,
            args=(
                worker_id,
                mode,
                result_queue,
            ),
        )
        for worker_id, mode in enumerate(modes)
    ]

    try:
        for process in processes:
            process.start()

        results: list[dict[str, object]] = []

        for _ in processes:
            try:
                raw_result = result_queue.get(
                    timeout=WORKER_TIMEOUT_S,
                )
            except queue.Empty as exc:
                raise AssertionError(
                    "Timed out waiting for spawned worker result"
                ) from exc

            result = cast(
                dict[str, object],
                raw_result,
            )

            results.append(result)

        for process in processes:
            process.join(
                timeout=WORKER_TIMEOUT_S,
            )

            assert process.is_alive() is False, (
                "Spawned worker did not terminate"
            )

            assert process.exitcode == 0, (
                "Spawned worker exited unsuccessfully: "
                f"exitcode={process.exitcode}"
            )

        for result in results:
            _assert_worker_result_success(result)

        return sorted(
            results,
            key=lambda item: int(item["worker_id"]),
        )
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5.0)

        result_queue.close()
        result_queue.join_thread()


def test_main_attaches_process_local_reliability_runtime() -> None:
    from app.config import get_settings
    from app.core.concurrency_limiter import (
        ConcurrencyLimiter,
    )
    from app.infrastructure.resilience_state import (
        ResilienceState,
    )
    from app.main import app

    settings = get_settings()

    limiter = app.state.concurrency_limiter
    state = app.state.resilience_state

    assert isinstance(
        limiter,
        ConcurrencyLimiter,
    )
    assert isinstance(
        state,
        ResilienceState,
    )

    snapshot = asyncio.run(
        limiter.snapshot()
    )

    assert snapshot.max_active_requests == (
        settings.concurrency_max_active_requests
    )
    assert snapshot.max_waiting_requests == (
        settings.concurrency_max_waiting_requests
    )


def test_spawned_workers_share_metadata_and_configuration() -> None:
    results = _collect_worker_results(
        (
            "observe",
            "observe",
            "observe",
        )
    )

    assert len(
        {
            int(result["pid"])
            for result in results
        }
    ) == 3

    assert {
        str(result["phase_code"])
        for result in results
    } == {
        "tier4_phase11",
    }

    assert len(
        {
            str(result["phase_name"])
            for result in results
        }
    ) == 1

    assert len(
        {
            str(result["version"])
            for result in results
        }
    ) == 1

    active_limits = {
        int(result["settings_max_active"])
        for result in results
    }
    waiting_limits = {
        int(result["settings_max_waiting"])
        for result in results
    }

    assert len(active_limits) == 1
    assert len(waiting_limits) == 1

    for result in results:
        limiter_before = cast(
            dict[str, object],
            result["limiter_before"],
        )

        assert limiter_before[
            "max_active_requests"
        ] == result["settings_max_active"]

        assert limiter_before[
            "max_waiting_requests"
        ] == result["settings_max_waiting"]


def test_each_spawned_worker_starts_with_fresh_runtime_state(
) -> None:
    results = _collect_worker_results(
        (
            "observe",
            "observe",
        )
    )

    for result in results:
        limiter = cast(
            dict[str, object],
            result["limiter_before"],
        )
        state = cast(
            dict[str, object],
            result["state_before"],
        )

        assert limiter["accepting_requests"] is True
        assert limiter["close_reason"] is None
        assert limiter["active_requests"] == 0
        assert limiter["waiting_requests"] == 0
        assert limiter["total_admitted_requests"] == 0
        assert limiter["total_released_requests"] == 0
        assert limiter["total_rejected_requests"] == 0

        assert state["startup_started"] is False
        assert state["startup_complete"] is False
        assert state["accepting_requests"] is False
        assert state["shutdown_requested"] is False
        assert state["shutdown_complete"] is False

        assert state["active_requests"] == 0
        assert state["waiting_requests"] == 0
        assert state["completed_requests"] == 0
        assert state["rejected_requests"] == 0
        assert state["timed_out_requests"] == 0
        assert state["overload_events"] == 0


def test_worker_runtime_mutation_is_isolated() -> None:
    mutated, untouched = _collect_worker_results(
        (
            "mutate",
            "observe",
        )
    )

    mutated_state = cast(
        dict[str, object],
        mutated["state_during"],
    )
    mutated_limiter = cast(
        dict[str, object],
        mutated["limiter_during"],
    )

    untouched_state = cast(
        dict[str, object],
        untouched["state_before"],
    )
    untouched_limiter = cast(
        dict[str, object],
        untouched["limiter_before"],
    )

    assert mutated_state["startup_complete"] is True
    assert mutated_state["accepting_requests"] is True
    assert mutated_state["active_requests"] == 1
    assert mutated_state["rejected_requests"] == 1
    assert mutated_state["overload_events"] == 1
    assert (
        mutated_state["last_rejection_reason"]
        == "worker_overload"
    )

    assert mutated_limiter["active_requests"] == 1
    assert mutated_limiter["total_admitted_requests"] == 1

    assert untouched_state["startup_complete"] is False
    assert untouched_state["active_requests"] == 0
    assert untouched_state["rejected_requests"] == 0
    assert untouched_state["overload_events"] == 0

    assert untouched_limiter["active_requests"] == 0
    assert untouched_limiter["total_admitted_requests"] == 0


def test_limiter_closure_is_process_local() -> None:
    closed, normal = _collect_worker_results(
        (
            "close",
            "normal_request",
        )
    )

    closed_limiter = cast(
        dict[str, object],
        closed["limiter_after"],
    )
    normal_limiter = cast(
        dict[str, object],
        normal["limiter_after"],
    )

    assert closed["request_accepted"] is False
    assert (
        closed["request_rejection_reason"]
        == "limiter_closed"
    )

    assert closed_limiter["accepting_requests"] is False
    assert (
        closed_limiter["close_reason"]
        == "worker_0_shutdown"
    )
    assert closed_limiter["limiter_closed_rejections"] == 1

    assert normal["request_accepted"] is True
    assert normal["request_rejection_reason"] is None

    assert normal_limiter["accepting_requests"] is True
    assert normal_limiter["close_reason"] is None
    assert normal_limiter["total_admitted_requests"] == 1
    assert normal_limiter["total_released_requests"] == 1
    assert normal_limiter["total_rejected_requests"] == 0


def test_child_mutation_does_not_change_parent_runtime() -> None:
    from app.main import app

    parent_limiter_before = asyncio.run(
        app.state.concurrency_limiter.snapshot()
    )
    parent_state_before = asyncio.run(
        app.state.resilience_state.snapshot()
    )

    result = _collect_worker_results(
        ("mutate",)
    )[0]

    _assert_worker_result_success(result)

    parent_limiter_after = asyncio.run(
        app.state.concurrency_limiter.snapshot()
    )
    parent_state_after = asyncio.run(
        app.state.resilience_state.snapshot()
    )

    assert (
        parent_limiter_after.active_requests
        == parent_limiter_before.active_requests
    )
    assert (
        parent_limiter_after.waiting_requests
        == parent_limiter_before.waiting_requests
    )
    assert (
        parent_limiter_after.total_admitted_requests
        == parent_limiter_before.total_admitted_requests
    )
    assert (
        parent_limiter_after.total_released_requests
        == parent_limiter_before.total_released_requests
    )
    assert (
        parent_limiter_after.total_rejected_requests
        == parent_limiter_before.total_rejected_requests
    )

    assert (
        parent_state_after.active_requests
        == parent_state_before.active_requests
    )
    assert (
        parent_state_after.completed_requests
        == parent_state_before.completed_requests
    )
    assert (
        parent_state_after.rejected_requests
        == parent_state_before.rejected_requests
    )
    assert (
        parent_state_after.overload_events
        == parent_state_before.overload_events
    )


def test_multiworker_capacity_scales_per_process() -> None:
    worker_count = 2

    context = multiprocessing.get_context("spawn")

    ready_queue = context.Queue()
    result_queue = context.Queue()
    release_event = context.Event()

    processes = [
        context.Process(
            target=_capacity_worker,
            args=(
                worker_id,
                ready_queue,
                result_queue,
                release_event,
            ),
        )
        for worker_id in range(worker_count)
    ]

    try:
        for process in processes:
            process.start()

        ready_results: list[dict[str, object]] = []

        for _ in processes:
            try:
                raw_ready = ready_queue.get(
                    timeout=WORKER_TIMEOUT_S,
                )
            except queue.Empty as exc:
                raise AssertionError(
                    "Timed out waiting for workers to "
                    "reach local capacity"
                ) from exc

            ready = cast(
                dict[str, object],
                raw_ready,
            )

            _assert_worker_result_success(ready)
            ready_results.append(ready)

        assert len(
            {
                int(result["pid"])
                for result in ready_results
            }
        ) == worker_count

        capacities = {
            int(result["max_active_requests"])
            for result in ready_results
        }

        assert len(capacities) == 1

        per_worker_capacity = capacities.pop()

        for result in ready_results:
            assert (
                int(result["active_requests"])
                == per_worker_capacity
            )
            assert result["waiting_requests"] == 0

        total_active_across_workers = sum(
            int(result["active_requests"])
            for result in ready_results
        )

        assert total_active_across_workers == (
            worker_count * per_worker_capacity
        )

        release_event.set()

        final_results: list[dict[str, object]] = []

        for _ in processes:
            try:
                raw_result = result_queue.get(
                    timeout=WORKER_TIMEOUT_S,
                )
            except queue.Empty as exc:
                raise AssertionError(
                    "Timed out waiting for capacity workers "
                    "to release their leases"
                ) from exc

            result = cast(
                dict[str, object],
                raw_result,
            )

            _assert_worker_result_success(result)
            final_results.append(result)

        for result in final_results:
            assert result["active_requests"] == 0
            assert result["waiting_requests"] == 0

            assert (
                result["total_admitted_requests"]
                == per_worker_capacity
            )
            assert (
                result["total_released_requests"]
                == per_worker_capacity
            )

        for process in processes:
            process.join(
                timeout=WORKER_TIMEOUT_S,
            )

            assert process.is_alive() is False
            assert process.exitcode == 0
    finally:
        release_event.set()

        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5.0)

        ready_queue.close()
        ready_queue.join_thread()

        result_queue.close()
        result_queue.join_thread()