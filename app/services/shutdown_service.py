# app/services/shutdown_service.py

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite
from time import perf_counter
from typing import Protocol, TypeAlias

from app.core.concurrency_limiter import (
    ConcurrencyLimiter,
)
from app.infrastructure.resilience_state import ResilienceState

logger = logging.getLogger(__name__)

ShutdownHookReturn: TypeAlias = object | Awaitable[object]
ShutdownHookCallback: TypeAlias = Callable[[], ShutdownHookReturn]


class ShutdownPhase(StrEnum):
    """Internal lifecycle phases of the graceful-shutdown service."""

    NOT_STARTED = "not_started"
    DRAINING = "draining"
    CLEANING_UP = "cleaning_up"
    COMPLETE = "complete"
    FORCED = "forced"
    FAILED = "failed"


class ShutdownMetrics(Protocol):
    """
    Minimal metrics interface required by ShutdownService.

    `ReliabilityMetrics` already provides these methods.
    """

    def set_accepting_requests(self, accepting: bool) -> None: ...

    def set_shutdown_inflight(self, value: int) -> None: ...

    def record_forced_shutdown(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ShutdownPolicy:
    """
    Bounded graceful-shutdown timing policy.

    drain_timeout_s:
        Maximum time allowed for accepted protected requests to finish.

    cleanup_timeout_s:
        Total time budget shared by all cleanup hooks.

    default_hook_timeout_s:
        Maximum time for one hook unless that hook defines its own timeout.

    run_sync_hooks_in_thread:
        Prevent blocking synchronous cleanup callbacks from blocking the event
        loop.
    """

    drain_timeout_s: float = 30.0
    cleanup_timeout_s: float = 15.0
    default_hook_timeout_s: float = 5.0
    run_sync_hooks_in_thread: bool = True

    def __post_init__(self) -> None:
        _validate_non_negative_finite(
            self.drain_timeout_s,
            field_name="drain_timeout_s",
        )
        _validate_non_negative_finite(
            self.cleanup_timeout_s,
            field_name="cleanup_timeout_s",
        )
        _validate_non_negative_finite(
            self.default_hook_timeout_s,
            field_name="default_hook_timeout_s",
        )

        if not isinstance(self.run_sync_hooks_in_thread, bool):
            raise TypeError(
                "run_sync_hooks_in_thread must be a boolean"
            )


@dataclass(frozen=True, slots=True)
class ShutdownHook:
    """
    One ordered resource-cleanup operation.

    Suitable hooks include:

        Redis client close
        HTTP client close
        executor shutdown
        telemetry flush
        temporary resource cleanup
    """

    name: str
    callback: ShutdownHookCallback
    timeout_s: float | None = None

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()

        if not normalized_name:
            raise ValueError("Shutdown hook name must not be empty")

        if not callable(self.callback):
            raise TypeError("Shutdown hook callback must be callable")

        if self.timeout_s is not None:
            _validate_non_negative_finite(
                self.timeout_s,
                field_name=f"shutdown hook {normalized_name!r} timeout_s",
            )

        object.__setattr__(self, "name", normalized_name)


@dataclass(frozen=True, slots=True)
class ShutdownHookResult:
    """Result of one bounded cleanup hook."""

    name: str
    success: bool
    timed_out: bool
    elapsed_ms: float
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ShutdownResult:
    """
    Complete outcome of one process-local shutdown operation.

    `graceful` is true only when request draining and all cleanup hooks
    completed successfully within their configured limits.
    """

    phase: ShutdownPhase

    graceful: bool
    forced: bool
    drained: bool
    cleanup_success: bool

    active_requests_at_start: int
    waiting_requests_at_start: int

    active_requests_remaining: int
    waiting_requests_remaining: int

    drain_elapsed_ms: float
    cleanup_elapsed_ms: float
    total_elapsed_ms: float

    started_at_utc: str
    completed_at_utc: str

    hook_results: tuple[ShutdownHookResult, ...]


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _validate_non_negative_finite(
    value: float,
    *,
    field_name: str,
) -> None:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a number")

    if not isfinite(value) or value < 0:
        raise ValueError(
            f"{field_name} must be finite and greater than or equal to 0"
        )


def _remaining_seconds(deadline: float) -> float:
    return max(
        0.0,
        deadline - asyncio.get_running_loop().time(),
    )


class ShutdownService:
    """
    Coordinate bounded graceful shutdown for one CityRoute worker process.

    Shutdown sequence:

        mark lifecycle as shutting down
            ↓
        disable new protected requests
            ↓
        close concurrency admission
            ↓
        wake and reject queued requests
            ↓
        wait for active protected requests to drain
            ↓
        execute ordered resource-cleanup hooks
            ↓
        mark shutdown complete

    The operation is idempotent and single-flight. Concurrent calls await the
    same shutdown task rather than running duplicate cleanup operations.

    Multi-worker boundary:

    Every Uvicorn worker has its own ResilienceState, ConcurrencyLimiter, and
    ShutdownService. The process manager must signal and wait for every worker.
    """

    def __init__(
        self,
        *,
        resilience_state: ResilienceState,
        concurrency_limiter: ConcurrencyLimiter,
        policy: ShutdownPolicy | None = None,
        cleanup_hooks: Sequence[ShutdownHook] = (),
        metrics: ShutdownMetrics | None = None,
    ) -> None:
        hook_names: set[str] = set()
        normalized_hooks: list[ShutdownHook] = []

        for hook in cleanup_hooks:
            if hook.name in hook_names:
                raise ValueError(
                    f"Duplicate shutdown hook name: {hook.name!r}"
                )

            hook_names.add(hook.name)
            normalized_hooks.append(hook)

        self._resilience_state = resilience_state
        self._concurrency_limiter = concurrency_limiter
        self._policy = policy or ShutdownPolicy()
        self._cleanup_hooks = normalized_hooks
        self._metrics = metrics

        self._task_lock = asyncio.Lock()
        self._shutdown_task: asyncio.Task[ShutdownResult] | None = None

        self._phase = ShutdownPhase.NOT_STARTED
        self._result: ShutdownResult | None = None

    @property
    def phase(self) -> ShutdownPhase:
        return self._phase

    @property
    def result(self) -> ShutdownResult | None:
        return self._result

    @property
    def shutdown_started(self) -> bool:
        return self._shutdown_task is not None

    async def add_cleanup_hook(
        self,
        hook: ShutdownHook,
    ) -> None:
        """
        Add a cleanup hook before shutdown begins.

        Hooks cannot be registered after the shutdown task has been created.
        """

        async with self._task_lock:
            if self._shutdown_task is not None:
                raise RuntimeError(
                    "Cannot add a cleanup hook after shutdown has started"
                )

            if any(
                existing.name == hook.name
                for existing in self._cleanup_hooks
            ):
                raise ValueError(
                    f"Duplicate shutdown hook name: {hook.name!r}"
                )

            self._cleanup_hooks.append(hook)

    async def shutdown(self) -> ShutdownResult:
        """
        Start or join the process-local graceful shutdown.

        Shielding prevents cancellation of one waiting caller from cancelling
        the shared shutdown operation.
        """

        async with self._task_lock:
            if self._shutdown_task is None:
                self._shutdown_task = asyncio.create_task(
                    self._run_shutdown(),
                    name="cityroute-graceful-shutdown",
                )

            task = self._shutdown_task

        return await asyncio.shield(task)

    async def _run_shutdown(self) -> ShutdownResult:
        total_started_at = perf_counter()
        started_at_utc = _utc_now_iso()

        self._phase = ShutdownPhase.DRAINING

        await self._resilience_state.begin_shutdown()
        await self._concurrency_limiter.close(
            reason="service_shutdown",
        )

        limiter_at_start = (
            await self._concurrency_limiter.snapshot()
        )

        self._safe_set_accepting_requests(False)
        self._safe_set_shutdown_inflight(
            limiter_at_start.active_requests
        )

        logger.info(
            "Graceful shutdown started | active=%d | waiting=%d | "
            "drain_timeout_s=%.3f",
            limiter_at_start.active_requests,
            limiter_at_start.waiting_requests,
            self._policy.drain_timeout_s,
        )

        drain_started_at = perf_counter()
        drained = await self._drain_requests()
        drain_elapsed_ms = _elapsed_ms(drain_started_at)

        limiter_after_drain = (
            await self._concurrency_limiter.snapshot()
        )

        self._safe_set_shutdown_inflight(
            limiter_after_drain.active_requests
        )

        forced = not drained

        if forced:
            self._safe_record_forced_shutdown()

            logger.error(
                "Graceful shutdown drain deadline exceeded | "
                "active_remaining=%d | waiting_remaining=%d",
                limiter_after_drain.active_requests,
                limiter_after_drain.waiting_requests,
            )
        else:
            logger.info(
                "Protected request drain completed | elapsed_ms=%.3f",
                drain_elapsed_ms,
            )

        self._phase = ShutdownPhase.CLEANING_UP

        cleanup_started_at = perf_counter()
        hook_results = await self._run_cleanup_hooks()
        cleanup_elapsed_ms = _elapsed_ms(cleanup_started_at)

        cleanup_success = all(
            result.success
            for result in hook_results
        )

        await self._resilience_state.mark_shutdown_complete()

        final_limiter_snapshot = (
            await self._concurrency_limiter.snapshot()
        )

        self._safe_set_shutdown_inflight(
            final_limiter_snapshot.active_requests
        )

        if forced:
            final_phase = ShutdownPhase.FORCED
        elif not cleanup_success:
            final_phase = ShutdownPhase.FAILED
        else:
            final_phase = ShutdownPhase.COMPLETE

        self._phase = final_phase

        result = ShutdownResult(
            phase=final_phase,
            graceful=drained and cleanup_success,
            forced=forced,
            drained=drained,
            cleanup_success=cleanup_success,
            active_requests_at_start=(
                limiter_at_start.active_requests
            ),
            waiting_requests_at_start=(
                limiter_at_start.waiting_requests
            ),
            active_requests_remaining=(
                final_limiter_snapshot.active_requests
            ),
            waiting_requests_remaining=(
                final_limiter_snapshot.waiting_requests
            ),
            drain_elapsed_ms=drain_elapsed_ms,
            cleanup_elapsed_ms=cleanup_elapsed_ms,
            total_elapsed_ms=_elapsed_ms(total_started_at),
            started_at_utc=started_at_utc,
            completed_at_utc=_utc_now_iso(),
            hook_results=hook_results,
        )

        self._result = result

        logger.info(
            "Graceful shutdown finished | phase=%s | graceful=%s | "
            "drained=%s | cleanup_success=%s | total_elapsed_ms=%.3f",
            result.phase,
            result.graceful,
            result.drained,
            result.cleanup_success,
            result.total_elapsed_ms,
        )

        return result

    async def _drain_requests(self) -> bool:
        """
        Drain both limiter-owned and resilience-state request counters.

        The limiter is the authoritative source for admission state. The
        resilience-state check also detects integration counter leaks.
        """

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._policy.drain_timeout_s

        limiter_drained = (
            await self._concurrency_limiter.wait_until_idle(
                timeout_s=_remaining_seconds(deadline),
            )
        )

        state_drained = (
            await self._resilience_state.wait_for_active_requests_to_drain(
                timeout_s=_remaining_seconds(deadline),
            )
        )

        limiter_snapshot = (
            await self._concurrency_limiter.snapshot()
        )
        state_snapshot = await self._resilience_state.snapshot()

        counters_empty = (
            limiter_snapshot.active_requests == 0
            and limiter_snapshot.waiting_requests == 0
            and state_snapshot.active_requests == 0
        )

        return limiter_drained and state_drained and counters_empty

    async def _run_cleanup_hooks(
        self,
    ) -> tuple[ShutdownHookResult, ...]:
        if not self._cleanup_hooks:
            return ()

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._policy.cleanup_timeout_s

        results: list[ShutdownHookResult] = []

        for hook in self._cleanup_hooks:
            remaining_s = _remaining_seconds(deadline)

            if remaining_s <= 0:
                results.append(
                    ShutdownHookResult(
                        name=hook.name,
                        success=False,
                        timed_out=True,
                        elapsed_ms=0.0,
                        error="total_cleanup_timeout_exceeded",
                    )
                )
                continue

            hook_timeout_s = (
                self._policy.default_hook_timeout_s
                if hook.timeout_s is None
                else hook.timeout_s
            )
            effective_timeout_s = min(
                hook_timeout_s,
                remaining_s,
            )

            result = await self._run_cleanup_hook(
                hook=hook,
                timeout_s=effective_timeout_s,
            )
            results.append(result)

        return tuple(results)

    async def _run_cleanup_hook(
        self,
        *,
        hook: ShutdownHook,
        timeout_s: float,
    ) -> ShutdownHookResult:
        started_at = perf_counter()

        try:
            await asyncio.wait_for(
                self._invoke_hook(hook.callback),
                timeout=timeout_s,
            )
        except TimeoutError:
            elapsed_ms = _elapsed_ms(started_at)

            logger.error(
                "Shutdown hook timed out | hook=%s | "
                "timeout_s=%.3f | elapsed_ms=%.3f",
                hook.name,
                timeout_s,
                elapsed_ms,
            )

            return ShutdownHookResult(
                name=hook.name,
                success=False,
                timed_out=True,
                elapsed_ms=elapsed_ms,
                error="hook_timeout",
            )
        except Exception as exc:
            elapsed_ms = _elapsed_ms(started_at)
            error = (
                f"{type(exc).__name__}: {str(exc).strip()}"
            )[:500]

            logger.exception(
                "Shutdown hook failed | hook=%s",
                hook.name,
            )

            await self._resilience_state.record_failure(
                f"shutdown_hook_failed:{hook.name}:{error}"
            )

            return ShutdownHookResult(
                name=hook.name,
                success=False,
                timed_out=False,
                elapsed_ms=elapsed_ms,
                error=error,
            )

        return ShutdownHookResult(
            name=hook.name,
            success=True,
            timed_out=False,
            elapsed_ms=_elapsed_ms(started_at),
            error=None,
        )

    async def _invoke_hook(
        self,
        callback: ShutdownHookCallback,
    ) -> None:
        if inspect.iscoroutinefunction(callback):
            result = callback()
        elif self._policy.run_sync_hooks_in_thread:
            result = await asyncio.to_thread(callback)
        else:
            result = callback()

        if inspect.isawaitable(result):
            await result

    def _safe_set_accepting_requests(
        self,
        accepting: bool,
    ) -> None:
        if self._metrics is None:
            return

        try:
            self._metrics.set_accepting_requests(accepting)
        except Exception:
            logger.exception(
                "Unable to update shutdown admission metric"
            )

    def _safe_set_shutdown_inflight(
        self,
        value: int,
    ) -> None:
        if self._metrics is None:
            return

        try:
            self._metrics.set_shutdown_inflight(value)
        except Exception:
            logger.exception(
                "Unable to update shutdown inflight metric"
            )

    def _safe_record_forced_shutdown(self) -> None:
        if self._metrics is None:
            return

        try:
            self._metrics.record_forced_shutdown()
        except Exception:
            logger.exception(
                "Unable to record forced-shutdown metric"
            )


def _elapsed_ms(started_at: float) -> float:
    return round(
        max(
            0.0,
            (perf_counter() - started_at) * 1000.0,
        ),
        3,
    )


__all__ = [
    "ShutdownHook",
    "ShutdownHookCallback",
    "ShutdownHookResult",
    "ShutdownMetrics",
    "ShutdownPhase",
    "ShutdownPolicy",
    "ShutdownResult",
    "ShutdownService",
]