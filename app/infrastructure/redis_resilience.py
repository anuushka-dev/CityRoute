# app/infrastructure/redis_resilience.py

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite
from time import perf_counter
from typing import TypeAlias

from app.infrastructure.resilience_state import ResilienceState

RedisHealthCheckResult: TypeAlias = bool | Awaitable[bool]
RedisHealthCheck: TypeAlias = Callable[[], RedisHealthCheckResult]


class RedisAvailability(StrEnum):
    """Operational availability states for the Redis dependency."""

    NOT_INITIALIZED = "not_initialized"
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    RECOVERING = "recovering"


class RedisFailureReason(StrEnum):
    """Controlled failure categories used by cache and recovery code."""

    CONNECTION_ERROR = "connection_error"
    TIMEOUT = "timeout"
    AUTHENTICATION_ERROR = "authentication_error"
    HEALTHCHECK_FAILED = "healthcheck_failed"
    UNAVAILABLE_AT_STARTUP = "unavailable_at_startup"

    CORRUPTED_PAYLOAD = "corrupted_payload"
    INVALID_PAYLOAD_TYPE = "invalid_payload_type"
    SERIALIZATION_ERROR = "serialization_error"

    READ_ERROR = "read_error"
    WRITE_ERROR = "write_error"
    DELETE_ERROR = "delete_error"
    OPERATION_ERROR = "operation_error"

    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class RedisHealthSnapshot:
    """
    Immutable point-in-time view of Redis reliability state.

    This snapshot can be used by readiness, metrics, failure-injection probes,
    and the Phase 11 evidence collector.
    """

    availability: RedisAvailability
    available: bool
    degraded: bool
    recovery_in_progress: bool

    consecutive_failures: int
    total_failures: int
    total_recovery_attempts: int
    total_recoveries: int

    last_success_at_utc: str | None
    last_failure_at_utc: str | None
    last_recovery_attempt_at_utc: str | None
    last_recovered_at_utc: str | None

    last_failure_reason: RedisFailureReason | None
    last_failure_detail: str | None

    recovery_interval_s: float
    current_backoff_s: float
    next_recovery_in_s: float

    fail_open_enabled: bool


def _utc_now_iso() -> str:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _validate_positive_finite(
    value: float,
    *,
    field_name: str,
) -> None:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a number")

    if not isfinite(value) or value <= 0:
        raise ValueError(
            f"{field_name} must be finite and greater than 0"
        )


def _normalize_detail(
    detail: str | None,
) -> str | None:
    if detail is None:
        return None

    normalized = detail.strip()

    if not normalized:
        return None

    # Prevent unexpectedly large exception or payload text from remaining in
    # long-lived process state.
    return normalized[:500]


def _callable_is_async(callback: RedisHealthCheck) -> bool:
    if inspect.iscoroutinefunction(callback):
        return True

    call_method = getattr(callback, "__call__", None)
    return inspect.iscoroutinefunction(call_method)


def _classify_exception(
    exc: BaseException,
) -> RedisFailureReason:
    """
    Classify dependency exceptions without importing redis-py here.

    Keeping the recovery controller independent of redis-py allows focused
    unit tests and avoids coupling this module to one Redis client.
    """

    exception_name = type(exc).__name__.lower()
    message = str(exc).lower()
    combined = f"{exception_name} {message}"

    if "timeout" in combined:
        return RedisFailureReason.TIMEOUT

    if (
        "authentication" in combined
        or "autherror" in combined
        or "invalid password" in combined
    ):
        return RedisFailureReason.AUTHENTICATION_ERROR

    if (
        "connection" in combined
        or "refused" in combined
        or "network" in combined
        or "socket" in combined
    ):
        return RedisFailureReason.CONNECTION_ERROR

    return RedisFailureReason.HEALTHCHECK_FAILED


class RedisRecoveryController:
    """
    Async-safe Redis availability and automatic-recovery controller.

    The controller provides:

        startup availability detection
        runtime failure recording
        fail-open dependency state
        bounded exponential recovery backoff
        single-flight recovery attempts
        recovery without restarting CityRoute
        consistent snapshots for readiness and metrics

    The health-check callback may be either synchronous or asynchronous.
    Synchronous callbacks run in a worker thread by default so a network-level
    Redis ping does not block the event loop.

    This class does not read or write cache values. Serialization and cache
    operations remain the responsibility of `RedisCache`.
    """

    def __init__(
        self,
        *,
        resilience_state: ResilienceState,
        health_check: RedisHealthCheck,
        fail_open_enabled: bool = True,
        recovery_interval_s: float = 5.0,
        max_recovery_interval_s: float = 60.0,
        backoff_multiplier: float = 2.0,
        run_sync_healthcheck_in_thread: bool = True,
    ) -> None:
        _validate_positive_finite(
            recovery_interval_s,
            field_name="recovery_interval_s",
        )
        _validate_positive_finite(
            max_recovery_interval_s,
            field_name="max_recovery_interval_s",
        )
        _validate_positive_finite(
            backoff_multiplier,
            field_name="backoff_multiplier",
        )

        if max_recovery_interval_s < recovery_interval_s:
            raise ValueError(
                "max_recovery_interval_s must be greater than or equal to "
                "recovery_interval_s"
            )

        if backoff_multiplier < 1:
            raise ValueError(
                "backoff_multiplier must be greater than or equal to 1"
            )

        if not isinstance(fail_open_enabled, bool):
            raise TypeError("fail_open_enabled must be a boolean")

        if not isinstance(run_sync_healthcheck_in_thread, bool):
            raise TypeError(
                "run_sync_healthcheck_in_thread must be a boolean"
            )

        self._resilience_state = resilience_state
        self._health_check = health_check

        self._fail_open_enabled = fail_open_enabled
        self._recovery_interval_s = recovery_interval_s
        self._max_recovery_interval_s = max_recovery_interval_s
        self._backoff_multiplier = backoff_multiplier
        self._run_sync_healthcheck_in_thread = (
            run_sync_healthcheck_in_thread
        )

        self._state_lock = asyncio.Lock()
        self._recovery_lock = asyncio.Lock()

        self._availability = RedisAvailability.NOT_INITIALIZED

        self._consecutive_failures = 0
        self._total_failures = 0
        self._total_recovery_attempts = 0
        self._total_recoveries = 0

        self._last_success_at_utc: str | None = None
        self._last_failure_at_utc: str | None = None
        self._last_recovery_attempt_at_utc: str | None = None
        self._last_recovered_at_utc: str | None = None

        self._last_failure_reason: RedisFailureReason | None = None
        self._last_failure_detail: str | None = None

        self._current_backoff_s = recovery_interval_s
        self._next_recovery_at_monotonic = 0.0

    @property
    def fail_open_enabled(self) -> bool:
        return self._fail_open_enabled

    async def initialize(self) -> bool:
        """
        Probe Redis during application startup.

        Redis startup failure is recorded but does not raise. The caller can
        decide whether startup should continue according to readiness policy.
        """

        success, failure_reason, failure_detail = await self._probe_health()

        if success:
            await self.mark_success()
            return True

        await self.mark_failure(
            RedisFailureReason.UNAVAILABLE_AT_STARTUP,
            detail=(
                failure_detail
                or (
                    failure_reason.value
                    if failure_reason is not None
                    else "Redis startup health check returned false"
                )
            ),
            unavailable=True,
        )
        return False

    async def check_health(self) -> bool:
        """
        Perform an immediate Redis health check.

        Unlike `attempt_recovery`, this method does not respect recovery
        backoff. It is intended for explicit health checks and controlled
        probes, not tight background loops.
        """

        success, failure_reason, failure_detail = await self._probe_health()

        if success:
            await self.mark_success()
            return True

        await self.mark_failure(
            failure_reason or RedisFailureReason.HEALTHCHECK_FAILED,
            detail=(
                failure_detail
                or "Redis health check returned false"
            ),
            unavailable=True,
        )
        return False

    async def attempt_recovery(
        self,
        *,
        force: bool = False,
    ) -> bool:
        """
        Attempt to recover Redis availability.

        Recovery is single-flight: only one coroutine runs the Redis probe at
        a time. Normal attempts respect exponential backoff. `force=True`
        bypasses the current backoff deadline for tests and operator actions.

        Returns:
            True when Redis is available after this method.
            False when recovery is skipped or unsuccessful.
        """

        if not isinstance(force, bool):
            raise TypeError("force must be a boolean")

        async with self._recovery_lock:
            now = perf_counter()

            async with self._state_lock:
                if (
                    self._availability == RedisAvailability.AVAILABLE
                    and not force
                ):
                    return True

                if (
                    not force
                    and now < self._next_recovery_at_monotonic
                ):
                    return False

                self._availability = RedisAvailability.RECOVERING
                self._total_recovery_attempts += 1
                self._last_recovery_attempt_at_utc = _utc_now_iso()

            success, failure_reason, failure_detail = (
                await self._probe_health()
            )

            if success:
                await self.mark_success(
                    recovered=True,
                )
                return True

            await self.mark_failure(
                failure_reason
                or RedisFailureReason.HEALTHCHECK_FAILED,
                detail=(
                    failure_detail
                    or "Redis recovery health check returned false"
                ),
                unavailable=True,
            )
            return False

    async def should_attempt_recovery(self) -> bool:
        """
        Return whether the recovery deadline has arrived.

        This method does not reserve the recovery attempt. The single-flight
        recovery lock still provides the final concurrency protection.
        """

        now = perf_counter()

        async with self._state_lock:
            return (
                self._availability
                != RedisAvailability.AVAILABLE
                and now >= self._next_recovery_at_monotonic
            )

    async def mark_success(
        self,
        *,
        recovered: bool = False,
    ) -> None:
        """
        Record a successful Redis operation or ping.

        A transition from degraded, unavailable, or recovering to available
        counts as a recovery. Repeated successful operations while already
        available do not increment the recovery counter.
        """

        if not isinstance(recovered, bool):
            raise TypeError("recovered must be a boolean")

        now_utc = _utc_now_iso()

        async with self._state_lock:
            previous_availability = self._availability

            transitioned_from_failure = previous_availability in {
                RedisAvailability.DEGRADED,
                RedisAvailability.UNAVAILABLE,
                RedisAvailability.RECOVERING,
            }

            self._availability = RedisAvailability.AVAILABLE
            self._consecutive_failures = 0
            self._last_success_at_utc = now_utc

            self._last_failure_reason = None
            self._last_failure_detail = None

            self._current_backoff_s = self._recovery_interval_s
            self._next_recovery_at_monotonic = 0.0

            if recovered or transitioned_from_failure:
                self._total_recoveries += 1
                self._last_recovered_at_utc = now_utc

        await self._resilience_state.mark_redis_success()

    async def mark_failure(
        self,
        reason: RedisFailureReason,
        *,
        detail: str | None = None,
        unavailable: bool = True,
    ) -> None:
        """
        Record a Redis failure and schedule the next recovery opportunity.

        Use `unavailable=True` for connection, timeout, authentication, and
        health-check failures.

        Use `unavailable=False` for reachable-but-degraded conditions such as
        corrupted JSON or an invalid cached payload type.
        """

        if not isinstance(reason, RedisFailureReason):
            raise TypeError(
                "reason must be a RedisFailureReason value"
            )

        if not isinstance(unavailable, bool):
            raise TypeError("unavailable must be a boolean")

        now = perf_counter()
        now_utc = _utc_now_iso()
        normalized_detail = _normalize_detail(detail)

        async with self._state_lock:
            self._availability = (
                RedisAvailability.UNAVAILABLE
                if unavailable
                else RedisAvailability.DEGRADED
            )

            self._consecutive_failures += 1
            self._total_failures += 1

            self._last_failure_at_utc = now_utc
            self._last_failure_reason = reason
            self._last_failure_detail = normalized_detail

            backoff_exponent = max(
                0,
                self._consecutive_failures - 1,
            )
            calculated_backoff = (
                self._recovery_interval_s
                * (self._backoff_multiplier**backoff_exponent)
            )

            self._current_backoff_s = min(
                calculated_backoff,
                self._max_recovery_interval_s,
            )
            self._next_recovery_at_monotonic = (
                now + self._current_backoff_s
            )

        state_reason = reason.value

        if normalized_detail is not None:
            state_reason = f"{state_reason}:{normalized_detail}"

        await self._resilience_state.mark_redis_failure(
            state_reason,
            unavailable=unavailable,
        )

    async def mark_corrupted_payload(
        self,
        *,
        detail: str | None = None,
    ) -> None:
        """
        Record a corrupted cache payload without treating Redis connectivity as
        unavailable.
        """

        await self.mark_failure(
            RedisFailureReason.CORRUPTED_PAYLOAD,
            detail=detail,
            unavailable=False,
        )

    async def mark_invalid_payload_type(
        self,
        *,
        detail: str | None = None,
    ) -> None:
        """Record a cache payload with an unexpected decoded type."""

        await self.mark_failure(
            RedisFailureReason.INVALID_PAYLOAD_TYPE,
            detail=detail,
            unavailable=False,
        )

    async def snapshot(self) -> RedisHealthSnapshot:
        """Return an immutable and internally consistent Redis snapshot."""

        now = perf_counter()

        async with self._state_lock:
            next_recovery_in_s = max(
                0.0,
                self._next_recovery_at_monotonic - now,
            )

            return RedisHealthSnapshot(
                availability=self._availability,
                available=(
                    self._availability
                    == RedisAvailability.AVAILABLE
                ),
                degraded=(
                    self._availability
                    == RedisAvailability.DEGRADED
                ),
                recovery_in_progress=(
                    self._availability
                    == RedisAvailability.RECOVERING
                ),
                consecutive_failures=self._consecutive_failures,
                total_failures=self._total_failures,
                total_recovery_attempts=(
                    self._total_recovery_attempts
                ),
                total_recoveries=self._total_recoveries,
                last_success_at_utc=self._last_success_at_utc,
                last_failure_at_utc=self._last_failure_at_utc,
                last_recovery_attempt_at_utc=(
                    self._last_recovery_attempt_at_utc
                ),
                last_recovered_at_utc=self._last_recovered_at_utc,
                last_failure_reason=self._last_failure_reason,
                last_failure_detail=self._last_failure_detail,
                recovery_interval_s=self._recovery_interval_s,
                current_backoff_s=self._current_backoff_s,
                next_recovery_in_s=round(
                    next_recovery_in_s,
                    3,
                ),
                fail_open_enabled=self._fail_open_enabled,
            )

    async def _probe_health(
        self,
    ) -> tuple[
        bool,
        RedisFailureReason | None,
        str | None,
    ]:
        try:
            result = await self._invoke_health_check()
        except Exception as exc:
            return (
                False,
                _classify_exception(exc),
                f"{type(exc).__name__}: {exc}",
            )

        if result:
            return True, None, None

        return (
            False,
            RedisFailureReason.HEALTHCHECK_FAILED,
            "Redis health check returned false",
        )

    async def _invoke_health_check(self) -> bool:
        if _callable_is_async(self._health_check):
            result = self._health_check()
        elif self._run_sync_healthcheck_in_thread:
            result = await asyncio.to_thread(
                self._health_check
            )
        else:
            result = self._health_check()

        if inspect.isawaitable(result):
            result = await result

        if not isinstance(result, bool):
            raise TypeError(
                "Redis health-check callback must return bool"
            )

        return result


__all__ = [
    "RedisAvailability",
    "RedisFailureReason",
    "RedisHealthCheck",
    "RedisHealthSnapshot",
    "RedisRecoveryController",
]