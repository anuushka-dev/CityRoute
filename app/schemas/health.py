# app/schemas/health.py

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

LivenessStatus = Literal["alive"]

LegacyHealthStatus = Literal[
    "ok",
    "degraded",
    "starting",
    "shutting_down",
]

ReadinessStatus = Literal[
    "ready",
    "degraded",
    "not_ready",
    "shutting_down",
]

ComponentStatus = Literal[
    "ready",
    "degraded",
    "unavailable",
    "not_ready",
    "not_initialized",
    "not_required",
]

ReadinessComponentName = Literal[
    "graph",
    "snap_index",
    "dispatch_adjacency",
    "redis",
]


class LegacyHealthResponse(BaseModel):
    """
    Backward-compatible response for GET /health.

    Phase 11 adds dedicated liveness and readiness endpoints, but the existing
    health contract remains available for clients created during earlier
    CityRoute phases.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    status: LegacyHealthStatus
    graph_loaded: bool
    uptime_s: float = Field(ge=0.0)

    @model_validator(mode="after")
    def validate_legacy_health(self) -> LegacyHealthResponse:
        if self.status == "ok" and not self.graph_loaded:
            raise ValueError(
                "status='ok' requires graph_loaded=true"
            )

        if self.status == "starting" and self.graph_loaded:
            raise ValueError(
                "status='starting' cannot report graph_loaded=true"
            )

        return self


class LivenessResponse(BaseModel):
    """
    Response for GET /health/live.

    Liveness answers only whether the process and event loop are alive.
    Redis, graph, cache, or readiness failures must not make this endpoint
    return an unhealthy status while the process itself remains responsive.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    status: LivenessStatus = "alive"
    phase: str = Field(min_length=1)
    uptime_s: float = Field(ge=0.0)


class ReadinessComponents(BaseModel):
    """
    Operational state of CityRoute runtime components.

    Required-component policy is evaluated by ReadinessService. Redis may be
    reported as degraded while the overall service remains ready when
    fail-open behavior is enabled.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    graph: ComponentStatus = "not_initialized"
    snap_index: ComponentStatus = "not_initialized"
    dispatch_adjacency: ComponentStatus = "not_initialized"
    redis: ComponentStatus = "not_initialized"

    def status_for(
        self,
        component: ReadinessComponentName,
    ) -> ComponentStatus:
        """Return the status for one known readiness component."""

        return getattr(self, component)


class ReadinessResponse(BaseModel):
    """
    Response for GET /health/ready.

    API status mapping:

        ready=True
            -> HTTP 200

        ready=False
            -> HTTP 503

    `degraded` is allowed to remain ready when only recoverable dependencies,
    such as optional Redis caching, are unavailable.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    status: ReadinessStatus
    ready: bool

    phase: str = Field(min_length=1)
    uptime_s: float = Field(ge=0.0)

    startup_complete: bool
    accepting_requests: bool
    shutting_down: bool

    components: ReadinessComponents

    degraded_dependencies: list[ReadinessComponentName] = Field(
        default_factory=list
    )
    failure_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_readiness_state(self) -> ReadinessResponse:
        if self.shutting_down:
            if self.status != "shutting_down":
                raise ValueError(
                    "shutting_down=true requires "
                    "status='shutting_down'"
                )

            if self.ready:
                raise ValueError(
                    "A shutting-down service cannot be ready"
                )

            if self.accepting_requests:
                raise ValueError(
                    "A shutting-down service cannot accept requests"
                )

        if self.status == "ready":
            if not self.ready:
                raise ValueError(
                    "status='ready' requires ready=true"
                )

            if self.degraded_dependencies:
                raise ValueError(
                    "status='ready' cannot contain degraded dependencies"
                )

            if self.failure_reasons:
                raise ValueError(
                    "status='ready' cannot contain failure reasons"
                )

        if self.status == "degraded":
            if not self.ready:
                raise ValueError(
                    "status='degraded' requires ready=true"
                )

            if not self.degraded_dependencies:
                raise ValueError(
                    "status='degraded' requires at least one "
                    "degraded dependency"
                )

            if self.failure_reasons:
                raise ValueError(
                    "A ready-but-degraded response cannot contain "
                    "blocking failure reasons"
                )

        if self.status == "not_ready":
            if self.ready:
                raise ValueError(
                    "status='not_ready' requires ready=false"
                )

            if not self.failure_reasons:
                raise ValueError(
                    "status='not_ready' requires at least one "
                    "failure reason"
                )

        if self.ready:
            if not self.startup_complete:
                raise ValueError(
                    "ready=true requires startup_complete=true"
                )

            if not self.accepting_requests:
                raise ValueError(
                    "ready=true requires accepting_requests=true"
                )

        if not self.ready and self.status in {"ready", "degraded"}:
            raise ValueError(
                "ready and degraded statuses require ready=true"
            )

        if len(self.degraded_dependencies) != len(
            set(self.degraded_dependencies)
        ):
            raise ValueError(
                "degraded_dependencies must not contain duplicates"
            )

        for dependency in self.degraded_dependencies:
            component_status = self.components.status_for(
                dependency
            )

            if component_status not in {
                "degraded",
                "unavailable",
                "not_ready",
            }:
                raise ValueError(
                    f"Degraded dependency {dependency!r} has "
                    f"incompatible status {component_status!r}"
                )

        return self


__all__ = [
    "ComponentStatus",
    "LegacyHealthResponse",
    "LegacyHealthStatus",
    "LivenessResponse",
    "LivenessStatus",
    "ReadinessComponentName",
    "ReadinessComponents",
    "ReadinessResponse",
    "ReadinessStatus",
]