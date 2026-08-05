# app/core/concurrency_limiter.py

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from math import isfinite
from time import perf_counter
from typing import Literal

AdmissionRejectionReason = Literal[
    "queue_full",
    "wait_timeout",
    "limiter_closed",
]


def _validate_non_negative_finite(
    value: float,
    *,
    field_name: str,
) -> None:
    if not isfinite(value) or value < 0:
        raise ValueError(
            f"{field_name} must be a finite value greater than or equal to 0"
        )


@dataclass(frozen=True, slots=True)
class ConcurrencyLimiterSnapshot:
    """
    Immutable point-in-time view of limiter state.

    This snapshot is suitable for readiness reporting, metrics, probes, and
    graceful-shutdown diagnostics.
    """

    max_active_requests: int
    max_waiting_requests: int
    default_wait_timeout_s: float

    accepting_requests: bool
    close_reason: str | None

    active_requests: int
    waiting_requests: int

    max_observed_active_requests: int
    max_observed_waiting_requests: int

    total_admitted_requests: int
    total_released_requests: int
    total_rejected_requests: int

    queue_full_rejections: int
    wait_timeout_rejections: int
    limiter_closed_rejections: int


@dataclass(frozen=True, slots=True)
class AdmissionOutcome:
    """
    Result of one concurrency-admission attempt.

    When `accepted` is true, `lease` is guaranteed to be present. The caller
    must release that lease, preferably through:

        async with outcome.require_lease():
            ...

    Rejected requests do not receive a lease.
    """

    accepted: bool
    queued: bool
    waited_ms: float

    rejection_reason: AdmissionRejectionReason | None

    active_requests_at_decision: int
    waiting_requests_at_decision: int

    lease: AdmissionLease | None = None

    def require_lease(self) -> AdmissionLease:
        """Return the admission lease or raise for a rejected request."""

        if not self.accepted or self.lease is None:
            reason = self.rejection_reason or "unknown"
            raise RuntimeError(
                f"Admission was rejected; no lease is available: {reason}"
            )

        return self.lease


class AdmissionLease:
    """
    Idempotent permit representing one active request.

    Releasing the lease returns capacity to the limiter and wakes one queued
    request. Calling `release()` more than once is safe and returns False after
    the first successful release.
    """

    __slots__ = (
        "_limiter",
        "_release_lock",
        "_released",
    )

    def __init__(self, limiter: ConcurrencyLimiter) -> None:
        self._limiter = limiter
        self._release_lock = asyncio.Lock()
        self._released = False

    @property
    def released(self) -> bool:
        return self._released

    async def release(self) -> bool:
        """
        Release this permit exactly once.

        Returns:
            True when this call released the permit.
            False when the permit had already been released.
        """

        async with self._release_lock:
            if self._released:
                return False

            await self._limiter._release()
            self._released = True
            return True

    async def __aenter__(self) -> AdmissionLease:
        if self._released:
            raise RuntimeError("Cannot enter an already released admission lease")

        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        await self.release()


class ConcurrencyLimiter:
    """
    Bounded asynchronous admission controller.

    The limiter enforces two independent limits:

    1. `max_active_requests`
       Maximum number of protected requests executing simultaneously.

    2. `max_waiting_requests`
       Maximum number of requests allowed to wait for execution capacity.

    Requests are handled as follows:

        available active capacity
            -> admitted immediately

        active capacity full, waiting capacity available
            -> wait for a bounded duration

        active and waiting capacity full
            -> reject with queue_full

        waiting deadline expires
            -> reject with wait_timeout

        limiter closed
            -> reject with limiter_closed

    The limiter is process-local. Each Uvicorn worker receives its own limiter.
    Multi-worker global concurrency is therefore approximately:

        worker_count * max_active_requests

    Phase 11 multi-worker evidence must account for that behavior.
    """

    def __init__(
        self,
        *,
        max_active_requests: int,
        max_waiting_requests: int,
        default_wait_timeout_s: float,
    ) -> None:
        if isinstance(max_active_requests, bool) or max_active_requests < 1:
            raise ValueError("max_active_requests must be an integer of at least 1")

        if isinstance(max_waiting_requests, bool) or max_waiting_requests < 0:
            raise ValueError(
                "max_waiting_requests must be an integer greater than or equal to 0"
            )

        _validate_non_negative_finite(
            default_wait_timeout_s,
            field_name="default_wait_timeout_s",
        )

        self._max_active_requests = max_active_requests
        self._max_waiting_requests = max_waiting_requests
        self._default_wait_timeout_s = default_wait_timeout_s

        self._condition = asyncio.Condition()

        self._accepting_requests = True
        self._close_reason: str | None = None

        self._active_requests = 0
        self._waiting_requests = 0

        self._max_observed_active_requests = 0
        self._max_observed_waiting_requests = 0

        self._total_admitted_requests = 0
        self._total_released_requests = 0
        self._total_rejected_requests = 0

        self._queue_full_rejections = 0
        self._wait_timeout_rejections = 0
        self._limiter_closed_rejections = 0

    @property
    def max_active_requests(self) -> int:
        return self._max_active_requests

    @property
    def max_waiting_requests(self) -> int:
        return self._max_waiting_requests

    @property
    def default_wait_timeout_s(self) -> float:
        return self._default_wait_timeout_s

    async def acquire(
        self,
        *,
        wait_timeout_s: float | None = None,
    ) -> AdmissionOutcome:
        """
        Attempt to obtain execution capacity.

        The returned lease must be released for every accepted outcome.
        Cancellation while queued removes the request from the waiting count
        and does not leak capacity.
        """

        timeout_s = (
            self._default_wait_timeout_s
            if wait_timeout_s is None
            else wait_timeout_s
        )

        _validate_non_negative_finite(
            timeout_s,
            field_name="wait_timeout_s",
        )

        started_at = perf_counter()
        queued = False
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s

        async with self._condition:
            if not self._accepting_requests:
                return self._rejected_outcome_locked(
                    reason="limiter_closed",
                    queued=False,
                    started_at=started_at,
                )

            # Do not allow a new arrival to skip requests already waiting.
            if (
                self._active_requests < self._max_active_requests
                and self._waiting_requests == 0
            ):
                return self._accepted_outcome_locked(
                    queued=False,
                    started_at=started_at,
                )

            if self._waiting_requests >= self._max_waiting_requests:
                return self._rejected_outcome_locked(
                    reason="queue_full",
                    queued=False,
                    started_at=started_at,
                )

            self._waiting_requests += 1
            queued = True

            self._max_observed_waiting_requests = max(
                self._max_observed_waiting_requests,
                self._waiting_requests,
            )

            try:
                while True:
                    if not self._accepting_requests:
                        self._remove_waiter_locked()

                        return self._rejected_outcome_locked(
                            reason="limiter_closed",
                            queued=True,
                            started_at=started_at,
                        )

                    if self._active_requests < self._max_active_requests:
                        self._remove_waiter_locked()

                        return self._accepted_outcome_locked(
                            queued=True,
                            started_at=started_at,
                        )

                    remaining_s = deadline - loop.time()

                    if remaining_s <= 0:
                        self._remove_waiter_locked()

                        return self._rejected_outcome_locked(
                            reason="wait_timeout",
                            queued=True,
                            started_at=started_at,
                        )

                    try:
                        await asyncio.wait_for(
                            self._condition.wait(),
                            timeout=remaining_s,
                        )
                    except TimeoutError:
                        self._remove_waiter_locked()

                        return self._rejected_outcome_locked(
                            reason="wait_timeout",
                            queued=True,
                            started_at=started_at,
                        )

            except asyncio.CancelledError:
                if queued:
                    self._remove_waiter_locked()

                raise

    async def close(
        self,
        *,
        reason: str = "service_shutdown",
    ) -> None:
        """
        Stop accepting new work and wake all queued requests.

        Active leases remain valid and can finish normally. Queued requests
        wake and receive a `limiter_closed` rejection.
        """

        normalized_reason = reason.strip() or "service_shutdown"

        async with self._condition:
            self._accepting_requests = False

            if self._close_reason is None:
                self._close_reason = normalized_reason

            self._condition.notify_all()

    async def wait_until_idle(
        self,
        *,
        timeout_s: float,
    ) -> bool:
        """
        Wait until both active and queued request counts reach zero.

        The limiter should normally be closed before this method is called so
        no new requests can enter while shutdown is draining.

        Returns:
            True when the limiter became idle before the timeout.
            False when the timeout expired.
        """

        _validate_non_negative_finite(
            timeout_s,
            field_name="timeout_s",
        )

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s

        async with self._condition:
            while self._active_requests > 0 or self._waiting_requests > 0:
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

    async def snapshot(self) -> ConcurrencyLimiterSnapshot:
        """Return an internally consistent immutable limiter snapshot."""

        async with self._condition:
            return ConcurrencyLimiterSnapshot(
                max_active_requests=self._max_active_requests,
                max_waiting_requests=self._max_waiting_requests,
                default_wait_timeout_s=self._default_wait_timeout_s,
                accepting_requests=self._accepting_requests,
                close_reason=self._close_reason,
                active_requests=self._active_requests,
                waiting_requests=self._waiting_requests,
                max_observed_active_requests=(
                    self._max_observed_active_requests
                ),
                max_observed_waiting_requests=(
                    self._max_observed_waiting_requests
                ),
                total_admitted_requests=self._total_admitted_requests,
                total_released_requests=self._total_released_requests,
                total_rejected_requests=self._total_rejected_requests,
                queue_full_rejections=self._queue_full_rejections,
                wait_timeout_rejections=self._wait_timeout_rejections,
                limiter_closed_rejections=(
                    self._limiter_closed_rejections
                ),
            )

    async def _release(self) -> None:
        """Return one active permit to the limiter."""

        async with self._condition:
            if self._active_requests <= 0:
                raise RuntimeError(
                    "Concurrency limiter active-request counter underflow"
                )

            self._active_requests -= 1
            self._total_released_requests += 1

            # Wake the oldest condition waiter.
            self._condition.notify(1)

            # Also wake shutdown drain waiters when the limiter becomes idle.
            if self._active_requests == 0 and self._waiting_requests == 0:
                self._condition.notify_all()

    def _accepted_outcome_locked(
        self,
        *,
        queued: bool,
        started_at: float,
    ) -> AdmissionOutcome:
        self._active_requests += 1
        self._total_admitted_requests += 1

        self._max_observed_active_requests = max(
            self._max_observed_active_requests,
            self._active_requests,
        )

        return AdmissionOutcome(
            accepted=True,
            queued=queued,
            waited_ms=self._elapsed_ms(started_at),
            rejection_reason=None,
            active_requests_at_decision=self._active_requests,
            waiting_requests_at_decision=self._waiting_requests,
            lease=AdmissionLease(self),
        )

    def _rejected_outcome_locked(
        self,
        *,
        reason: AdmissionRejectionReason,
        queued: bool,
        started_at: float,
    ) -> AdmissionOutcome:
        self._total_rejected_requests += 1

        if reason == "queue_full":
            self._queue_full_rejections += 1
        elif reason == "wait_timeout":
            self._wait_timeout_rejections += 1
        elif reason == "limiter_closed":
            self._limiter_closed_rejections += 1

        return AdmissionOutcome(
            accepted=False,
            queued=queued,
            waited_ms=self._elapsed_ms(started_at),
            rejection_reason=reason,
            active_requests_at_decision=self._active_requests,
            waiting_requests_at_decision=self._waiting_requests,
            lease=None,
        )

    def _remove_waiter_locked(self) -> None:
        if self._waiting_requests <= 0:
            raise RuntimeError(
                "Concurrency limiter waiting-request counter underflow"
            )

        self._waiting_requests -= 1

        # Another waiter may now fit within the bounded queue or may need to
        # observe newly available execution capacity.
        self._condition.notify(1)

        if self._active_requests == 0 and self._waiting_requests == 0:
            self._condition.notify_all()

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        return round(
            max(0.0, (perf_counter() - started_at) * 1000.0),
            3,
        )
    async def reset_for_startup(self) -> None:
        """
        Reopen the process-local limiter for a new application lifespan.

        Configuration limits are preserved. Runtime counters and the permanent
        close state from the previous lifespan are cleared.
        """

        async with self._condition:
            if self._active_requests != 0:
                raise RuntimeError(
                    "Cannot reset concurrency limiter while requests are active"
                )

            if self._waiting_requests != 0:
                raise RuntimeError(
                    "Cannot reset concurrency limiter while requests are waiting"
                )

            self._accepting_requests = True
            self._close_reason = None

            self._active_requests = 0
            self._waiting_requests = 0

            self._max_observed_active_requests = 0
            self._max_observed_waiting_requests = 0

            self._total_admitted_requests = 0
            self._total_released_requests = 0
            self._total_rejected_requests = 0

            self._queue_full_rejections = 0
            self._wait_timeout_rejections = 0
            self._limiter_closed_rejections = 0

            self._condition.notify_all()
    

__all__ = [
    "AdmissionLease",
    "AdmissionOutcome",
    "AdmissionRejectionReason",
    "ConcurrencyLimiter",
    "ConcurrencyLimiterSnapshot",
]