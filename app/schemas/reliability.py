# app/schemas/reliability.py

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.timeout_policy import TimeoutCategory


class ReliabilityMode(StrEnum):
    """High-level operational mode reported by CityRoute."""

    STARTING = "starting"
    NORMAL = "normal"
    DEGRADED = "degraded"
    BUSY = "busy"
    OVERLOADED = "overloaded"
    SHUTTING_DOWN = "shutting_down"
    STOPPED = "stopped"


class AdmissionDecision(StrEnum):
    """Possible bounded-concurrency admission outcomes."""

    IMMEDIATE = "immediate"
    QUEUED = "queued"
    REJECTED = "rejected"


class OverloadReason(StrEnum):
    """Controlled reasons for rejecting protected requests."""

    QUEUE_FULL = "queue_full"
    WAIT_TIMEOUT = "wait_timeout"
    LIMITER_CLOSED = "limiter_closed"

    STARTUP_INCOMPLETE = "startup_incomplete"
    NOT_ACCEPTING_REQUESTS = "not_accepting_requests"
    SERVICE_SHUTTING_DOWN = "service_shutting_down"
    REQUIRED_COMPONENT_NOT_READY = "required_component_not_ready"

    OTHER = "other"


class DependencyState(StrEnum):
    """
    Public reliability state for application components and dependencies.

    `ready` is normally used for graph-related components.
    `available` is normally used for Redis.
    """

    NOT_INITIALIZED = "not_initialized"
    READY = "ready"
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    RECOVERING = "recovering"
    NOT_REQUIRED = "not_required"


class ShutdownState(StrEnum):
    """Graceful-shutdown lifecycle state."""

    RUNNING = "running"
    DRAINING = "draining"
    COMPLETE = "complete"
    FORCED = "forced"


class RequestOutcome(StrEnum):
    """Controlled endpoint execution outcomes used by reliability metrics."""

    SUCCESS = "success"
    CLIENT_ERROR = "client_error"
    SERVER_ERROR = "server_error"
    TIMEOUT = "timeout"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    ERROR = "error"
    OTHER = "other"


class ReliabilityComponents(BaseModel):
    """Current state of the major CityRoute runtime components."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        from_attributes=True,
    )

    graph: DependencyState = DependencyState.NOT_INITIALIZED
    snap_index: DependencyState = DependencyState.NOT_INITIALIZED
    dispatch_adjacency: DependencyState = (
        DependencyState.NOT_INITIALIZED
    )
    redis: DependencyState = DependencyState.NOT_INITIALIZED


class LifecycleReliabilitySnapshot(BaseModel):
    """
    Public lifecycle and process-level reliability snapshot.

    Most fields map directly to
    `app.infrastructure.resilience_state.ResilienceSnapshot`.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        from_attributes=True,
    )

    uptime_s: float = Field(ge=0.0)

    startup_started: bool
    startup_complete: bool
    accepting_requests: bool

    shutdown_requested: bool
    shutdown_complete: bool
    shutdown_state: ShutdownState

    startup_started_at_utc: datetime | None = None
    startup_completed_at_utc: datetime | None = None
    shutdown_requested_at_utc: datetime | None = None
    shutdown_completed_at_utc: datetime | None = None

    active_requests: int = Field(ge=0)
    waiting_requests: int = Field(ge=0)

    completed_requests: int = Field(ge=0)
    rejected_requests: int = Field(ge=0)
    timed_out_requests: int = Field(ge=0)
    overload_events: int = Field(ge=0)

    last_failure_reason: str | None = None
    last_rejection_reason: str | None = None
    last_timeout_endpoint: str | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> LifecycleReliabilitySnapshot:
        if self.startup_complete and not self.startup_started:
            raise ValueError(
                "startup_complete requires startup_started=true"
            )

        if self.shutdown_complete and not self.shutdown_requested:
            raise ValueError(
                "shutdown_complete requires shutdown_requested=true"
            )

        if self.shutdown_requested and self.accepting_requests:
            raise ValueError(
                "accepting_requests must be false after shutdown starts"
            )

        if (
            self.shutdown_state == ShutdownState.RUNNING
            and self.shutdown_requested
        ):
            raise ValueError(
                "shutdown_state cannot be running after shutdown starts"
            )

        if (
            self.shutdown_state
            in {
                ShutdownState.COMPLETE,
                ShutdownState.FORCED,
            }
            and not self.shutdown_complete
        ):
            raise ValueError(
                "complete or forced shutdown state requires "
                "shutdown_complete=true"
            )

        return self


class AdmissionReliabilitySnapshot(BaseModel):
    """
    Public snapshot of bounded concurrency and admission-control state.

    This model mirrors `ConcurrencyLimiterSnapshot`.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        from_attributes=True,
    )

    max_active_requests: int = Field(ge=1)
    max_waiting_requests: int = Field(ge=0)
    default_wait_timeout_s: float = Field(ge=0.0)

    accepting_requests: bool
    close_reason: str | None = None

    active_requests: int = Field(ge=0)
    waiting_requests: int = Field(ge=0)

    max_observed_active_requests: int = Field(ge=0)
    max_observed_waiting_requests: int = Field(ge=0)

    total_admitted_requests: int = Field(ge=0)
    total_released_requests: int = Field(ge=0)
    total_rejected_requests: int = Field(ge=0)

    queue_full_rejections: int = Field(ge=0)
    wait_timeout_rejections: int = Field(ge=0)
    limiter_closed_rejections: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_admission_state(
        self,
    ) -> AdmissionReliabilitySnapshot:
        if self.active_requests > self.max_active_requests:
            raise ValueError(
                "active_requests exceeds max_active_requests"
            )

        if self.waiting_requests > self.max_waiting_requests:
            raise ValueError(
                "waiting_requests exceeds max_waiting_requests"
            )

        if (
            self.max_observed_active_requests
            < self.active_requests
        ):
            raise ValueError(
                "max_observed_active_requests cannot be below "
                "active_requests"
            )

        if (
            self.max_observed_waiting_requests
            < self.waiting_requests
        ):
            raise ValueError(
                "max_observed_waiting_requests cannot be below "
                "waiting_requests"
            )

        if (
            self.total_released_requests
            > self.total_admitted_requests
        ):
            raise ValueError(
                "total_released_requests cannot exceed "
                "total_admitted_requests"
            )

        expected_active = (
            self.total_admitted_requests
            - self.total_released_requests
        )

        if expected_active != self.active_requests:
            raise ValueError(
                "active_requests must equal admitted minus released"
            )

        rejection_sum = (
            self.queue_full_rejections
            + self.wait_timeout_rejections
            + self.limiter_closed_rejections
        )

        if rejection_sum != self.total_rejected_requests:
            raise ValueError(
                "total_rejected_requests must equal the sum of "
                "specific rejection counters"
            )

        return self


class RedisReliabilitySnapshot(BaseModel):
    """
    Public Redis failure, recovery, and backoff snapshot.

    This model mirrors `RedisHealthSnapshot`.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        from_attributes=True,
    )

    availability: DependencyState
    available: bool
    degraded: bool
    recovery_in_progress: bool

    consecutive_failures: int = Field(ge=0)
    total_failures: int = Field(ge=0)
    total_recovery_attempts: int = Field(ge=0)
    total_recoveries: int = Field(ge=0)

    last_success_at_utc: datetime | None = None
    last_failure_at_utc: datetime | None = None
    last_recovery_attempt_at_utc: datetime | None = None
    last_recovered_at_utc: datetime | None = None

    last_failure_reason: str | None = None
    last_failure_detail: str | None = Field(
        default=None,
        max_length=500,
    )

    recovery_interval_s: float = Field(gt=0.0)
    current_backoff_s: float = Field(gt=0.0)
    next_recovery_in_s: float = Field(ge=0.0)

    fail_open_enabled: bool

    @model_validator(mode="after")
    def validate_redis_state(
        self,
    ) -> RedisReliabilitySnapshot:
        expected_available = (
            self.availability == DependencyState.AVAILABLE
        )

        if self.available != expected_available:
            raise ValueError(
                "available must match availability='available'"
            )

        expected_degraded = (
            self.availability == DependencyState.DEGRADED
        )

        if self.degraded != expected_degraded:
            raise ValueError(
                "degraded must match availability='degraded'"
            )

        expected_recovering = (
            self.availability == DependencyState.RECOVERING
        )

        if self.recovery_in_progress != expected_recovering:
            raise ValueError(
                "recovery_in_progress must match "
                "availability='recovering'"
            )

        if self.consecutive_failures > self.total_failures:
            raise ValueError(
                "consecutive_failures cannot exceed total_failures"
            )

        return self


class TimeoutRuleSnapshot(BaseModel):
    """Public representation of one endpoint timeout rule."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        from_attributes=True,
    )

    method: str = Field(min_length=1)
    path: str = Field(min_length=1)
    category: TimeoutCategory
    timeout_s: float | None = Field(default=None, gt=0.0)

    @model_validator(mode="after")
    def normalize_rule(self) -> TimeoutRuleSnapshot:
        if self.method != self.method.upper():
            raise ValueError("method must be uppercase")

        if not self.path.startswith("/"):
            raise ValueError("path must start with '/'")

        return self


class TimeoutPolicyReliabilitySnapshot(BaseModel):
    """Public snapshot of the endpoint timeout policy."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        from_attributes=True,
    )

    rule_count: int = Field(ge=0)
    enabled_rule_count: int = Field(ge=0)
    disabled_rule_count: int = Field(ge=0)

    rules: tuple[TimeoutRuleSnapshot, ...] = ()

    @model_validator(mode="after")
    def validate_policy(
        self,
    ) -> TimeoutPolicyReliabilitySnapshot:
        if self.rule_count != len(self.rules):
            raise ValueError(
                "rule_count must equal the number of rules"
            )

        if (
            self.enabled_rule_count
            + self.disabled_rule_count
            != self.rule_count
        ):
            raise ValueError(
                "enabled and disabled rule counts must equal "
                "rule_count"
            )

        actual_enabled = sum(
            rule.timeout_s is not None
            for rule in self.rules
        )

        if actual_enabled != self.enabled_rule_count:
            raise ValueError(
                "enabled_rule_count does not match the rules"
            )

        return self


class ReliabilitySnapshot(BaseModel):
    """
    Complete public Phase 11 reliability snapshot.

    This model can later be returned by an internal diagnostics endpoint,
    consumed by evidence probes, or written into Phase 11 JSON artifacts.

    Do not expose raw exceptions, cache keys, coordinates, driver IDs, order
    IDs, or other high-cardinality data through this schema.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        from_attributes=True,
    )

    phase: str = Field(min_length=1)
    mode: ReliabilityMode

    alive: bool = True
    ready: bool

    components: ReliabilityComponents

    lifecycle: LifecycleReliabilitySnapshot
    admission: AdmissionReliabilitySnapshot

    redis: RedisReliabilitySnapshot
    timeout_policy: TimeoutPolicyReliabilitySnapshot

    degraded_dependencies: tuple[str, ...] = ()
    failure_reasons: tuple[str, ...] = ()

    generated_at_utc: datetime

    @model_validator(mode="after")
    def validate_overall_state(
        self,
    ) -> ReliabilitySnapshot:
        if self.mode == ReliabilityMode.STARTING and self.ready:
            raise ValueError(
                "starting mode cannot report ready=true"
            )

        if (
            self.mode
            in {
                ReliabilityMode.SHUTTING_DOWN,
                ReliabilityMode.STOPPED,
            }
            and self.ready
        ):
            raise ValueError(
                "shutdown or stopped mode cannot report ready=true"
            )

        if (
            self.mode == ReliabilityMode.NORMAL
            and not self.ready
        ):
            raise ValueError(
                "normal mode requires ready=true"
            )

        if (
            self.mode == ReliabilityMode.DEGRADED
            and not self.degraded_dependencies
        ):
            raise ValueError(
                "degraded mode requires at least one "
                "degraded dependency"
            )

        if (
            self.mode == ReliabilityMode.OVERLOADED
            and self.admission.total_rejected_requests == 0
        ):
            raise ValueError(
                "overloaded mode requires at least one rejection"
            )

        return self


class ReliabilityErrorDetail(BaseModel):
    """Consistent error body for Phase 11 reliability failures."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    error: str = Field(min_length=1)
    message: str = Field(min_length=1)

    endpoint: str | None = None
    method: str | None = None

    reason: OverloadReason | str | None = None
    timeout_category: TimeoutCategory | None = None
    timeout_s: float | None = Field(default=None, gt=0.0)

    retry_after_s: int | None = Field(default=None, ge=0)


class ReliabilityErrorResponse(BaseModel):
    """Top-level structured reliability error response."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    detail: ReliabilityErrorDetail


__all__ = [
    "AdmissionDecision",
    "AdmissionReliabilitySnapshot",
    "DependencyState",
    "LifecycleReliabilitySnapshot",
    "OverloadReason",
    "RedisReliabilitySnapshot",
    "ReliabilityComponents",
    "ReliabilityErrorDetail",
    "ReliabilityErrorResponse",
    "ReliabilityMode",
    "ReliabilitySnapshot",
    "RequestOutcome",
    "ShutdownState",
    "TimeoutCategory",
    "TimeoutPolicyReliabilitySnapshot",
    "TimeoutRuleSnapshot",
]