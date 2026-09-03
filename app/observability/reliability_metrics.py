# app/observability/reliability_metrics.py

from __future__ import annotations

from math import isfinite
from threading import Lock

from prometheus_client import (
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
)

from app.core.concurrency_limiter import ConcurrencyLimiterSnapshot
from app.infrastructure.redis_resilience import RedisHealthSnapshot
from app.infrastructure.resilience_state import ResilienceSnapshot

_ENDPOINT_GROUPS: dict[str, str] = {
    "/route": "route",
    "/route/compare": "route_compare",
    "/matrix": "matrix",
    "/vrp/greedy": "vrp_greedy",
    "/vrp/compare": "vrp_compare",
    "/vrp/compare/advanced": "vrp_advanced",
    "/dispatch/compare": "dispatch",
    "/health": "health",
    "/health/live": "health_live",
    "/health/ready": "health_ready",
    "/metrics": "metrics",
}

_ALLOWED_REJECTION_REASONS: frozenset[str] = frozenset(
    {
        "queue_full",
        "wait_timeout",
        "limiter_closed",
        "startup_incomplete",
        "not_accepting_requests",
        "service_shutting_down",
        "required_component_not_ready",
        "other",
    }
)

_ALLOWED_TIMEOUT_CATEGORIES: frozenset[str] = frozenset(
    {
        "route",
        "route_compare",
        "matrix",
        "vrp_greedy",
        "vrp_compare",
        "vrp_advanced",
        "dispatch",
        "other",
    }
)

_ALLOWED_EXECUTION_OUTCOMES: frozenset[str] = frozenset(
    {
        "success",
        "client_error",
        "server_error",
        "timeout",
        "rejected",
        "cancelled",
        "error",
        "other",
    }
)

_ALLOWED_REDIS_FAILURE_REASONS: frozenset[str] = frozenset(
    {
        "connection_error",
        "timeout",
        "authentication_error",
        "healthcheck_failed",
        "unavailable_at_startup",
        "corrupted_payload",
        "invalid_payload_type",
        "serialization_error",
        "read_error",
        "write_error",
        "delete_error",
        "operation_error",
        "unknown",
        "other",
    }
)

_ALLOWED_OVERLOAD_REASONS: frozenset[str] = frozenset(
    {
        "queue_full",
        "wait_timeout",
        "active_capacity",
        "waiting_capacity",
        "other",
    }
)

_ADMISSION_DECISIONS: frozenset[str] = frozenset(
    {
        "immediate",
        "queued",
        "rejected",
        "other",
    }
)


def _normalize_path(path: str) -> str:
    normalized = path.strip().split("?", maxsplit=1)[0]

    if not normalized:
        normalized = "/"

    if not normalized.startswith("/"):
        normalized = f"/{normalized}"

    if len(normalized) > 1:
        normalized = normalized.rstrip("/")

    return normalized


def endpoint_group_for(path: str) -> str:

    return _ENDPOINT_GROUPS.get(
        _normalize_path(path),
        "other",
    )


def _controlled_label(
    value: object,
    *,
    allowed_values: frozenset[str],
    fallback: str = "other",
) -> str:
    normalized = str(value).strip().lower()

    if normalized in allowed_values:
        return normalized

    return fallback


def _validate_non_negative_number(
    value: float,
    *,
    field_name: str,
) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a number")

    numeric_value = float(value)

    if not isfinite(numeric_value) or numeric_value < 0:
        raise ValueError(
            f"{field_name} must be finite and greater than or equal to 0"
        )

    return numeric_value


def _validate_non_negative_integer(
    value: int,
    *,
    field_name: str,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")

    if value < 0:
        raise ValueError(
            f"{field_name} must be greater than or equal to 0"
        )

    return value


class ReliabilityMetrics:

    def __init__(
        self,
        *,
        registry: CollectorRegistry = REGISTRY,
    ) -> None:
        self._registry = registry

        self.active_requests = Gauge(
            "cityroute_active_requests",
            "Current protected requests executing in this process.",
            registry=registry,
        )

        self.waiting_requests = Gauge(
            "cityroute_waiting_requests",
            "Current protected requests waiting for admission.",
            registry=registry,
        )

        self.max_active_requests = Gauge(
            "cityroute_max_active_requests",
            "Configured maximum active protected requests.",
            registry=registry,
        )

        self.max_waiting_requests = Gauge(
            "cityroute_max_waiting_requests",
            "Configured maximum protected requests allowed to wait.",
            registry=registry,
        )

        self.readiness = Gauge(
            "cityroute_readiness",
            "CityRoute global readiness: 1 ready, 0 not ready.",
            registry=registry,
        )

        self.accepting_requests = Gauge(
            "cityroute_accepting_requests",
            "Whether protected requests are currently accepted.",
            registry=registry,
        )

        self.redis_available = Gauge(
            "cityroute_redis_available",
            "Redis availability: 1 available, 0 unavailable or degraded.",
            registry=registry,
        )

        self.shutdown_inflight = Gauge(
            "cityroute_graceful_shutdown_inflight",
            "Protected requests still active during graceful shutdown.",
            registry=registry,
        )

        self.http_requests_total = Counter(
            "cityroute_http_requests_total",
            "Total HTTP requests handled by CityRoute.",
            labelnames=(
                "method",
                "endpoint_group",
                "status",
            ),
            registry=registry,
        )

        self.http_request_duration_seconds = Histogram(
            "cityroute_http_request_duration_seconds",
            "HTTP request latency in seconds.",
            labelnames=(
                "method",
                "path",
            ),
            buckets=(
                0.005,
                0.01,
                0.025,
                0.05,
                0.1,
                0.25,
                0.5,
                1.0,
                2.5,
                5.0,
                10.0,
            ),
            registry=registry,
        )

        self.graph_loaded = Gauge(
            "cityroute_graph_loaded",
            "Whether the road graph is loaded (1) or not (0).",
            registry=registry,
        )

        self.snap_index_loaded = Gauge(
            "cityroute_snap_index_loaded",
            "Whether the BallTree snap index is loaded (1) or not (0).",
            registry=registry,
        )

        self.admission_decisions_total = Counter(
            "cityroute_admission_decisions_total",
            "Request admission decisions by endpoint and decision.",
            labelnames=(
                "endpoint_group",
                "decision",
            ),
            registry=registry,
        )

        self.request_rejections_total = Counter(
            "cityroute_request_rejections_total",
            "Controlled request rejections by endpoint and reason.",
            labelnames=(
                "endpoint_group",
                "reason",
            ),
            registry=registry,
        )

        self.request_timeouts_total = Counter(
            "cityroute_request_timeouts_total",
            "Request timeouts by endpoint and timeout category.",
            labelnames=(
                "endpoint_group",
                "category",
            ),
            registry=registry,
        )

        self.overload_events_total = Counter(
            "cityroute_overload_events_total",
            "Observed overload events grouped by controlled reason.",
            labelnames=("reason",),
            registry=registry,
        )

        self.redis_failures_total = Counter(
            "cityroute_redis_failures_total",
            "Redis failures grouped by controlled failure reason.",
            labelnames=("reason",),
            registry=registry,
        )

        self.redis_recoveries_total = Counter(
            "cityroute_redis_recoveries_total",
            "Successful Redis recoveries without an API process restart.",
            registry=registry,
        )

        self.corrupted_cache_payloads_total = Counter(
            "cityroute_corrupted_cache_payloads_total",
            "Rejected corrupted or invalid Redis cache payloads.",
            labelnames=("reason",),
            registry=registry,
        )

        self.shutdown_forced_total = Counter(
            "cityroute_graceful_shutdown_forced_total",
            "Graceful shutdowns that exceeded the configured drain limit.",
            registry=registry,
        )

        self.admission_wait_seconds = Histogram(
            "cityroute_admission_wait_seconds",
            "Time spent waiting for bounded request admission.",
            labelnames=("endpoint_group",),
            buckets=(
                0.001,
                0.005,
                0.010,
                0.025,
                0.050,
                0.100,
                0.250,
                0.500,
                1.000,
                2.500,
                5.000,
            ),
            registry=registry,
        )

        self.request_execution_seconds = Histogram(
            "cityroute_request_execution_seconds",
            "Protected endpoint execution duration by outcome.",
            labelnames=(
                "endpoint_group",
                "outcome",
            ),
            buckets=(
                0.005,
                0.010,
                0.025,
                0.050,
                0.100,
                0.250,
                0.500,
                1.000,
                2.500,
                5.000,
                10.000,
                20.000,
                30.000,
                60.000,
            ),
            registry=registry,
        )

    @property
    def registry(self) -> CollectorRegistry:
        return self._registry

    def set_active_requests(self, value: int) -> None:
        self.active_requests.set(
            _validate_non_negative_integer(
                value,
                field_name="active_requests",
            )
        )

    def set_waiting_requests(self, value: int) -> None:
        self.waiting_requests.set(
            _validate_non_negative_integer(
                value,
                field_name="waiting_requests",
            )
        )

    def set_capacity(
        self,
        *,
        max_active_requests: int,
        max_waiting_requests: int,
    ) -> None:
        self.max_active_requests.set(
            _validate_non_negative_integer(
                max_active_requests,
                field_name="max_active_requests",
            )
        )
        self.max_waiting_requests.set(
            _validate_non_negative_integer(
                max_waiting_requests,
                field_name="max_waiting_requests",
            )
        )

    def set_readiness(self, ready: bool) -> None:
        if not isinstance(ready, bool):
            raise TypeError("ready must be a boolean")

        self.readiness.set(1 if ready else 0)

    def set_accepting_requests(self, accepting: bool) -> None:
        if not isinstance(accepting, bool):
            raise TypeError("accepting must be a boolean")

        self.accepting_requests.set(1 if accepting else 0)

    def set_redis_available(self, available: bool) -> None:
        if not isinstance(available, bool):
            raise TypeError("available must be a boolean")

        self.redis_available.set(1 if available else 0)

    def set_shutdown_inflight(self, value: int) -> None:
        self.shutdown_inflight.set(
            _validate_non_negative_integer(
                value,
                field_name="shutdown_inflight",
            )
        )

    def set_graph_loaded(self, loaded: bool) -> None:
        if not isinstance(loaded, bool):
            raise TypeError("loaded must be a boolean")

        self.graph_loaded.set(1 if loaded else 0)

    def set_snap_index_loaded(self, loaded: bool) -> None:
        if not isinstance(loaded, bool):
            raise TypeError("loaded must be a boolean")

        self.snap_index_loaded.set(1 if loaded else 0)

    def observe_admission(
        self,
        *,
        endpoint: str,
        waited_ms: float,
        queued: bool,
    ) -> None:
        if not isinstance(queued, bool):
            raise TypeError("queued must be a boolean")

        waited_seconds = (
            _validate_non_negative_number(
                waited_ms,
                field_name="waited_ms",
            )
            / 1000.0
        )
        endpoint_group = endpoint_group_for(endpoint)
        decision = "queued" if queued else "immediate"

        self.admission_wait_seconds.labels(
            endpoint_group=endpoint_group
        ).observe(waited_seconds)

        self.admission_decisions_total.labels(
            endpoint_group=endpoint_group,
            decision=decision,
        ).inc()

    def record_admission_rejection(
        self,
        *,
        endpoint: str,
        reason: object,
        waited_ms: float | None = None,
    ) -> None:
        endpoint_group = endpoint_group_for(endpoint)
        normalized_reason = _controlled_label(
            reason,
            allowed_values=_ALLOWED_REJECTION_REASONS,
        )

        self.admission_decisions_total.labels(
            endpoint_group=endpoint_group,
            decision="rejected",
        ).inc()

        self.request_rejections_total.labels(
            endpoint_group=endpoint_group,
            reason=normalized_reason,
        ).inc()

        if waited_ms is not None:
            waited_seconds = (
                _validate_non_negative_number(
                    waited_ms,
                    field_name="waited_ms",
                )
                / 1000.0
            )

            self.admission_wait_seconds.labels(
                endpoint_group=endpoint_group
            ).observe(waited_seconds)

    def record_timeout(
        self,
        *,
        endpoint: str,
        category: object,
    ) -> None:
        normalized_category = _controlled_label(
            category,
            allowed_values=_ALLOWED_TIMEOUT_CATEGORIES,
        )

        self.request_timeouts_total.labels(
            endpoint_group=endpoint_group_for(endpoint),
            category=normalized_category,
        ).inc()

    def record_overload(self, *, reason: object) -> None:
        normalized_reason = _controlled_label(
            reason,
            allowed_values=_ALLOWED_OVERLOAD_REASONS,
        )

        self.overload_events_total.labels(
            reason=normalized_reason
        ).inc()

    def observe_http_request(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        duration_s: float,
    ) -> None:
        if not isinstance(method, str) or not method.strip():
            raise ValueError("method must be a non-empty string")

        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")

        if (
            isinstance(status_code, bool)
            or not isinstance(status_code, int)
            or not 100 <= status_code <= 599
        ):
            raise ValueError(
                "status_code must be an integer between 100 and 599"
            )

        normalized_duration = _validate_non_negative_number(
            duration_s,
            field_name="duration_s",
        )

        normalized_path = _normalize_path(path)

        if normalized_path not in _ENDPOINT_GROUPS:
            normalized_path = "/other"

        self.http_requests_total.labels(
            method=method.strip().upper(),
            endpoint_group=normalized_path,
            status=str(status_code),
        ).inc()

        self.http_request_duration_seconds.labels(
            method=method.strip().upper(),
            endpoint_group=normalized_path,
        ).observe(normalized_duration)

    def observe_execution(
        self,
        *,
        endpoint: str,
        duration_s: float,
        outcome: object,
        method: str | None = None,
        status_code: int | None = None,
    ) -> None:
        normalized_outcome = _controlled_label(
            outcome,
            allowed_values=_ALLOWED_EXECUTION_OUTCOMES,
        )

        normalized_duration = _validate_non_negative_number(
            duration_s,
            field_name="duration_s",
        )

        self.request_execution_seconds.labels(
            endpoint_group=endpoint_group_for(endpoint),
            outcome=normalized_outcome,
        ).observe(normalized_duration)

        if method is not None and status_code is not None:
            self.observe_http_request(
                method=method,
                path=endpoint,
                status_code=status_code,
                duration_s=normalized_duration,
            )

    def record_redis_failure(self, *, reason: object) -> None:
        normalized_reason = _controlled_label(
            reason,
            allowed_values=_ALLOWED_REDIS_FAILURE_REASONS,
        )

        self.redis_failures_total.labels(
            reason=normalized_reason
        ).inc()

    def record_redis_recovery(self) -> None:
        self.redis_recoveries_total.inc()

    def record_corrupted_cache_payload(
        self,
        *,
        reason: object = "corrupted_payload",
    ) -> None:
        normalized_reason = _controlled_label(
            reason,
            allowed_values=frozenset(
                {
                    "corrupted_payload",
                    "invalid_payload_type",
                    "serialization_error",
                    "other",
                }
            ),
        )

        self.corrupted_cache_payloads_total.labels(
            reason=normalized_reason
        ).inc()

        self.redis_failures_total.labels(
            reason=normalized_reason
        ).inc()

    def record_forced_shutdown(self) -> None:
        self.shutdown_forced_total.inc()

    def refresh_gauges(
        self,
        *,
        resilience_snapshot: ResilienceSnapshot,
        limiter_snapshot: ConcurrencyLimiterSnapshot | None = None,
        redis_snapshot: RedisHealthSnapshot | None = None,
        ready: bool | None = None,
    ) -> None:

        if limiter_snapshot is not None:
            active_requests = limiter_snapshot.active_requests
            waiting_requests = limiter_snapshot.waiting_requests

            self.set_capacity(
                max_active_requests=(
                    limiter_snapshot.max_active_requests
                ),
                max_waiting_requests=(
                    limiter_snapshot.max_waiting_requests
                ),
            )
        else:
            active_requests = resilience_snapshot.active_requests
            waiting_requests = resilience_snapshot.waiting_requests

        self.set_active_requests(active_requests)
        self.set_waiting_requests(waiting_requests)
        self.set_accepting_requests(
            resilience_snapshot.accepting_requests
        )

        if ready is not None:
            self.set_readiness(ready)

        if redis_snapshot is not None:
            redis_available = redis_snapshot.available
        else:
            redis_available = resilience_snapshot.redis == "ready"

        self.set_redis_available(redis_available)

        if (
            resilience_snapshot.shutdown_requested
            or resilience_snapshot.shutdown_complete
        ):
            self.set_shutdown_inflight(active_requests)
        else:
            self.set_shutdown_inflight(0)


_default_metrics: ReliabilityMetrics | None = None
_default_metrics_lock = Lock()


def get_reliability_metrics() -> ReliabilityMetrics:
    global _default_metrics

    if _default_metrics is not None:
        return _default_metrics

    with _default_metrics_lock:
        if _default_metrics is None:
            _default_metrics = ReliabilityMetrics(
                registry=REGISTRY
            )

    return _default_metrics


__all__ = [
    "ReliabilityMetrics",
    "endpoint_group_for",
    "get_reliability_metrics",
]