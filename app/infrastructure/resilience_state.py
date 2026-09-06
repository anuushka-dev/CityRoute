# app/infrastructure/resilience_state.py

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from time import perf_counter
from typing import Literal

ComponentName = Literal[
    "graph",
    "snap_index",
    "dispatch_adjacency",
    "redis",
]

RuntimeComponentStatus = Literal[
    "not_initialized",
    "ready",
    "not_ready",
    "unavailable",
]


def _utc_now_iso() -> str:
    """Return a timezone-aware UTC timestamp suitable for logs and JSON."""

    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _validate_timeout(timeout_s: float) -> None:
    if not isfinite(timeout_s) or timeout_s < 0:
        raise ValueError("timeout_s must be a finite value greater than or equal to 0")


@dataclass(frozen=True, slots=True)
class ResilienceSnapshot:
    """
    Immutable point-in-time view of CityRoute reliability state.

    A snapshot prevents API handlers and metrics collectors from reading a
    partially updated collection of mutable runtime fields.
    """

    uptime_s: float

    startup_started: bool
    startup_complete: bool
    accepting_requests: bool

    shutdown_requested: bool
    shutdown_complete: bool

    startup_started_at_utc: str | None
    startup_completed_at_utc: str | None
    shutdown_requested_at_utc: str | None
    shutdown_completed_at_utc: str | None

    graph: RuntimeComponentStatus
    snap_index: RuntimeComponentStatus
    dispatch_adjacency: RuntimeComponentStatus
    redis: RuntimeComponentStatus

    active_requests: int
    waiting_requests: int
    completed_requests: int
    rejected_requests: int
    timed_out_requests: int
    overload_events: int

    last_failure_reason: str | None
    last_rejection_reason: str | None
    last_timeout_endpoint: str | None

    last_redis_success_at_utc: str | None
    last_redis_failure_at_utc: str | None
    last_redis_failure_reason: str | None


class ResilienceState:
    """
    Process-local, async-safe runtime reliability state for CityRoute.

    This component stores lifecycle state, dependency availability, and request
    counters. All mutation and snapshot operations are protected by one
    asyncio.Condition so shutdown code can also wait efficiently for active
    requests to drain.

    Important:
        This state is process-local. When Uvicorn runs multiple workers, each
        worker owns an independent ResilienceState instance. Cross-worker
        aggregation belongs in Prometheus or another external metrics system.
    """

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._started_at = perf_counter()

        self._startup_started = False
        self._startup_complete = False
        self._accepting_requests = False

        self._shutdown_requested = False
        self._shutdown_complete = False

        self._startup_started_at_utc: str | None = None
        self._startup_completed_at_utc: str | None = None
        self._shutdown_requested_at_utc: str | None = None
        self._shutdown_completed_at_utc: str | None = None

        self._components: dict[ComponentName, RuntimeComponentStatus] = {
            "graph": "not_initialized",
            "snap_index": "not_initialized",
            "dispatch_adjacency": "not_initialized",
            "redis": "not_initialized",
        }

        self._active_requests = 0
        self._waiting_requests = 0
        self._completed_requests = 0
        self._rejected_requests = 0
        self._timed_out_requests = 0
        self._overload_events = 0

        self._last_failure_reason: str | None = None
        self._last_rejection_reason: str | None = None
        self._last_timeout_endpoint: str | None = None

        self._last_redis_success_at_utc: str | None = None
        self._last_redis_failure_at_utc: str | None = None
        self._last_redis_failure_reason: str | None = None

    # ------------------------------------------------------------------
    # Application lifecycle
    # ------------------------------------------------------------------

    async def mark_startup_started(self) -> None:
        """Mark application initialization as started."""

        async with self._condition:
            if not self._startup_started:
                self._startup_started = True
                self._startup_started_at_utc = _utc_now_iso()

            self._condition.notify_all()

    async def mark_startup_complete(
        self,
        *,
        accepting_requests: bool = True,
    ) -> None:
        """
        Mark startup as complete.

        Startup completion is idempotent. The service cannot be made accepting
        after shutdown has already started.
        """

        async with self._condition:
            if not self._startup_started:
                self._startup_started = True
                self._startup_started_at_utc = _utc_now_iso()

            self._startup_complete = True

            if self._startup_completed_at_utc is None:
                self._startup_completed_at_utc = _utc_now_iso()

            self._accepting_requests = (
                accepting_requests and not self._shutdown_requested and not self._shutdown_complete
            )

            self._condition.notify_all()

    async def set_accepting_requests(self, accepting: bool) -> None:
        """
        Enable or disable admission of new protected requests.

        Enabling admission before startup completion or after shutdown begins
        is rejected because it would violate the lifecycle model.
        """

        async with self._condition:
            if accepting and not self._startup_complete:
                raise RuntimeError("Cannot accept requests before startup is complete")

            if accepting and (self._shutdown_requested or self._shutdown_complete):
                raise RuntimeError("Cannot accept requests after shutdown has started")

            self._accepting_requests = accepting
            self._condition.notify_all()

    async def begin_shutdown(self) -> None:
        """
        Begin graceful shutdown.

        New protected work should be rejected after this method returns.
        Existing active work remains tracked until it finishes or the shutdown
        drain timeout expires.
        """

        async with self._condition:
            self._accepting_requests = False
            self._shutdown_requested = True

            if self._shutdown_requested_at_utc is None:
                self._shutdown_requested_at_utc = _utc_now_iso()

            self._condition.notify_all()

    async def mark_shutdown_complete(self) -> None:
        """Mark the process lifecycle as fully shut down."""

        async with self._condition:
            self._accepting_requests = False
            self._shutdown_requested = True
            self._shutdown_complete = True

            if self._shutdown_requested_at_utc is None:
                self._shutdown_requested_at_utc = _utc_now_iso()

            if self._shutdown_completed_at_utc is None:
                self._shutdown_completed_at_utc = _utc_now_iso()

            self._condition.notify_all()

    # ------------------------------------------------------------------
    # Component state
    # ------------------------------------------------------------------

    async def set_component_state(
        self,
        component: ComponentName,
        status: RuntimeComponentStatus,
    ) -> None:
        """Set the current state of one runtime component."""

        allowed_statuses: set[str] = {
            "not_initialized",
            "ready",
            "not_ready",
            "unavailable",
        }

        if status not in allowed_statuses:
            raise ValueError(f"Unsupported component status: {status!r}")

        async with self._condition:
            if component not in self._components:
                raise ValueError(f"Unsupported component name: {component!r}")

            self._components[component] = status
            self._condition.notify_all()

    async def set_graph_ready(self, ready: bool) -> None:
        await self.set_component_state(
            "graph",
            "ready" if ready else "not_ready",
        )

    async def set_snap_index_ready(self, ready: bool) -> None:
        await self.set_component_state(
            "snap_index",
            "ready" if ready else "not_ready",
        )

    async def set_dispatch_adjacency_ready(self, ready: bool) -> None:
        await self.set_component_state(
            "dispatch_adjacency",
            "ready" if ready else "not_ready",
        )

    async def mark_redis_success(self) -> None:
        """Mark Redis as available after a successful operation or ping."""

        async with self._condition:
            self._components["redis"] = "ready"
            self._last_redis_success_at_utc = _utc_now_iso()
            self._last_redis_failure_reason = None
            self._condition.notify_all()

    async def mark_redis_failure(
        self,
        reason: str,
        *,
        unavailable: bool = True,
    ) -> None:
        """
        Record a Redis failure.

        `unavailable=True` is appropriate for connection and timeout failures.
        Use `unavailable=False` for a degraded but still reachable Redis state,
        such as a malformed cached payload.
        """

        normalized_reason = reason.strip() or "unknown_redis_failure"

        async with self._condition:
            self._components["redis"] = "unavailable" if unavailable else "not_ready"
            self._last_redis_failure_at_utc = _utc_now_iso()
            self._last_redis_failure_reason = normalized_reason
            self._last_failure_reason = normalized_reason
            self._condition.notify_all()

    # ------------------------------------------------------------------
    # Request counters
    # ------------------------------------------------------------------

    async def waiting_started(self) -> int:
        """
        Record one request entering the bounded admission queue.

        Returns the current waiting-request count.
        """

        async with self._condition:
            self._waiting_requests += 1
            current = self._waiting_requests
            self._condition.notify_all()
            return current

    async def waiting_finished(self) -> bool:
        """
        Record one request leaving the admission queue.

        Returns False if an underflow was prevented. Underflow is recorded as
        an internal reliability failure rather than producing a negative count.
        """

        async with self._condition:
            if self._waiting_requests <= 0:
                self._waiting_requests = 0
                self._last_failure_reason = "waiting_requests_underflow"
                self._condition.notify_all()
                return False

            self._waiting_requests -= 1
            self._condition.notify_all()
            return True

    async def request_started(self) -> int:
        """
        Record one admitted request beginning execution.

        Returns the current active-request count.
        """

        async with self._condition:
            self._active_requests += 1
            current = self._active_requests
            self._condition.notify_all()
            return current

    async def request_finished(self) -> bool:
        """
        Record one active request finishing.

        A completed request is counted regardless of whether the endpoint
        returned success or an application error. Returns False when an
        underflow was prevented.
        """

        async with self._condition:
            if self._active_requests <= 0:
                self._active_requests = 0
                self._last_failure_reason = "active_requests_underflow"
                self._condition.notify_all()
                return False

            self._active_requests -= 1
            self._completed_requests += 1
            self._condition.notify_all()
            return True

    async def request_rejected(self, reason: str) -> None:
        """Record a controlled admission or lifecycle rejection."""

        normalized_reason = reason.strip() or "unspecified_rejection"

        async with self._condition:
            self._rejected_requests += 1
            self._last_rejection_reason = normalized_reason
            self._condition.notify_all()

    async def request_timed_out(self, endpoint: str) -> None:
        """Record an endpoint timeout."""

        normalized_endpoint = endpoint.strip() or "unknown_endpoint"

        async with self._condition:
            self._timed_out_requests += 1
            self._last_timeout_endpoint = normalized_endpoint
            self._condition.notify_all()

    async def overload_event(self, reason: str) -> None:
        """Record an overload event separately from individual rejections."""

        normalized_reason = reason.strip() or "unspecified_overload"

        async with self._condition:
            self._overload_events += 1
            self._last_rejection_reason = normalized_reason
            self._condition.notify_all()

    async def record_failure(self, reason: str) -> None:
        """Record the latest internal or dependency failure reason."""

        normalized_reason = reason.strip() or "unspecified_failure"

        async with self._condition:
            self._last_failure_reason = normalized_reason
            self._condition.notify_all()

    # ------------------------------------------------------------------
    # Graceful-drain support
    # ------------------------------------------------------------------

    async def wait_for_active_requests_to_drain(
        self,
        timeout_s: float,
    ) -> bool:
        """
        Wait until active request count reaches zero.

        Returns:
            True: all active requests completed before the timeout.
            False: the drain timeout expired with work still active.
        """

        _validate_timeout(timeout_s)

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s

        async with self._condition:
            while self._active_requests > 0:
                remaining_s = deadline - loop.time()

                if remaining_s <= 0:
                    return False

                try:
                    await asyncio.wait_for(
                        self._condition.wait(),
                        timeout=remaining_s,
                    )
                except TimeoutError:
                    return False

            return True

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    async def snapshot(self) -> ResilienceSnapshot:
        """Return an immutable, internally consistent state snapshot."""

        async with self._condition:
            return ResilienceSnapshot(
                uptime_s=round(
                    max(0.0, perf_counter() - self._started_at),
                    3,
                ),
                startup_started=self._startup_started,
                startup_complete=self._startup_complete,
                accepting_requests=self._accepting_requests,
                shutdown_requested=self._shutdown_requested,
                shutdown_complete=self._shutdown_complete,
                startup_started_at_utc=self._startup_started_at_utc,
                startup_completed_at_utc=self._startup_completed_at_utc,
                shutdown_requested_at_utc=self._shutdown_requested_at_utc,
                shutdown_completed_at_utc=self._shutdown_completed_at_utc,
                graph=self._components["graph"],
                snap_index=self._components["snap_index"],
                dispatch_adjacency=self._components["dispatch_adjacency"],
                redis=self._components["redis"],
                active_requests=self._active_requests,
                waiting_requests=self._waiting_requests,
                completed_requests=self._completed_requests,
                rejected_requests=self._rejected_requests,
                timed_out_requests=self._timed_out_requests,
                overload_events=self._overload_events,
                last_failure_reason=self._last_failure_reason,
                last_rejection_reason=self._last_rejection_reason,
                last_timeout_endpoint=self._last_timeout_endpoint,
                last_redis_success_at_utc=self._last_redis_success_at_utc,
                last_redis_failure_at_utc=self._last_redis_failure_at_utc,
                last_redis_failure_reason=self._last_redis_failure_reason,
            )

    async def reset_for_startup(self) -> None:
        """
        Reset process-local lifecycle state for a new application lifespan.

        Production workers normally execute one lifespan. This reset also
        supports repeated FastAPI TestClient lifespans and embedded server
        restarts within the same Python process.

        Resetting while requests are active is forbidden.
        """

        async with self._condition:
            if self._active_requests != 0:
                raise RuntimeError("Cannot reset resilience state while requests are active")

            if self._waiting_requests != 0:
                raise RuntimeError("Cannot reset resilience state while requests are waiting")

            self._started_at = perf_counter()

            self._startup_started = False
            self._startup_complete = False
            self._accepting_requests = False

            self._shutdown_requested = False
            self._shutdown_complete = False

            self._startup_started_at_utc = None
            self._startup_completed_at_utc = None
            self._shutdown_requested_at_utc = None
            self._shutdown_completed_at_utc = None

            self._graph = "not_initialized"
            self._snap_index = "not_initialized"
            self._dispatch_adjacency = "not_initialized"
            self._redis = "not_initialized"

            self._active_requests = 0
            self._waiting_requests = 0
            self._completed_requests = 0
            self._rejected_requests = 0
            self._timed_out_requests = 0
            self._overload_events = 0

            self._last_failure_reason = None
            self._last_rejection_reason = None
            self._last_timeout_endpoint = None

            self._last_redis_success_at_utc = None
            self._last_redis_failure_at_utc = None
            self._last_redis_failure_reason = None

            self._condition.notify_all()


__all__ = [
    "ComponentName",
    "ResilienceSnapshot",
    "ResilienceState",
    "RuntimeComponentStatus",
]
