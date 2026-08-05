# app/services/readiness_service.py

from __future__ import annotations

from dataclasses import dataclass

from app.infrastructure.resilience_state import (
    ComponentName,
    ResilienceSnapshot,
    ResilienceState,
    RuntimeComponentStatus,
)
from app.schemas.health import (
    ComponentStatus,
    ReadinessComponents,
    ReadinessResponse,
)

_COMPONENT_ORDER: tuple[ComponentName, ...] = (
    "graph",
    "snap_index",
    "dispatch_adjacency",
    "redis",
)


def _require_bool_setting(
    settings: object,
    field_name: str,
) -> bool:
    if not hasattr(settings, field_name):
        raise AttributeError(
            f"Settings object is missing readiness field: {field_name}"
        )

    value = getattr(settings, field_name)

    if not isinstance(value, bool):
        raise TypeError(
            f"Settings field {field_name!r} must be a boolean"
        )

    return value


@dataclass(frozen=True, slots=True)
class ReadinessPolicy:
    """
    Defines which CityRoute components are required for global readiness.

    Redis is optional by default because supported routing, matrix, VRP, and
    dispatch operations can compute without cache when fail-open behavior is
    enabled.
    """

    require_graph: bool = True
    require_snap_index: bool = True
    require_dispatch_adjacency: bool = True
    require_redis: bool = False

    redis_fail_open: bool = True

    def __post_init__(self) -> None:
        fields = {
            "require_graph": self.require_graph,
            "require_snap_index": self.require_snap_index,
            "require_dispatch_adjacency": (
                self.require_dispatch_adjacency
            ),
            "require_redis": self.require_redis,
            "redis_fail_open": self.redis_fail_open,
        }

        for field_name, value in fields.items():
            if not isinstance(value, bool):
                raise TypeError(
                    f"{field_name} must be a boolean"
                )

    @classmethod
    def from_settings(
        cls,
        settings: object,
    ) -> ReadinessPolicy:
        """
        Build a readiness policy from the CityRoute settings object.

        Expected settings fields:

            readiness_require_graph
            readiness_require_snap_index
            readiness_require_adjacency
            readiness_require_redis
            redis_fail_open
        """

        return cls(
            require_graph=_require_bool_setting(
                settings,
                "readiness_require_graph",
            ),
            require_snap_index=_require_bool_setting(
                settings,
                "readiness_require_snap_index",
            ),
            require_dispatch_adjacency=_require_bool_setting(
                settings,
                "readiness_require_adjacency",
            ),
            require_redis=_require_bool_setting(
                settings,
                "readiness_require_redis",
            ),
            redis_fail_open=_require_bool_setting(
                settings,
                "redis_fail_open",
            ),
        )

    def component_required(
        self,
        component: ComponentName,
    ) -> bool:
        """Return whether a component blocks global readiness."""

        requirements: dict[ComponentName, bool] = {
            "graph": self.require_graph,
            "snap_index": self.require_snap_index,
            "dispatch_adjacency": (
                self.require_dispatch_adjacency
            ),
            "redis": self.require_redis,
        }

        return requirements[component]


class ReadinessService:
    """
    Evaluate CityRoute's operational readiness from ResilienceState.

    Readiness is false when:

        graceful shutdown has started
        startup has not completed
        the service is not accepting protected traffic
        any required component is not ready

    Readiness can remain true but degraded when an optional dependency is
    unavailable. The primary example is Redis in fail-open mode.

    The service does not choose the HTTP status code. The API router should
    return:

        HTTP 200 when response.ready is True
        HTTP 503 when response.ready is False
    """

    def __init__(
        self,
        *,
        resilience_state: ResilienceState,
        phase: str,
        policy: ReadinessPolicy | None = None,
    ) -> None:
        normalized_phase = phase.strip()

        if not normalized_phase:
            raise ValueError("phase must not be empty")

        self._resilience_state = resilience_state
        self._phase = normalized_phase
        self._policy = policy or ReadinessPolicy()

    @property
    def policy(self) -> ReadinessPolicy:
        return self._policy

    async def get_readiness(self) -> ReadinessResponse:
        """Return readiness based on a consistent state snapshot."""

        snapshot = await self._resilience_state.snapshot()
        return self.evaluate_snapshot(snapshot)

    def evaluate_snapshot(
        self,
        snapshot: ResilienceSnapshot,
    ) -> ReadinessResponse:
        """
        Evaluate a previously captured resilience snapshot.

        This method is synchronous so unit tests and evidence collectors can
        evaluate deterministic snapshots without creating additional state
        mutations.
        """

        runtime_states = self._runtime_component_states(snapshot)

        rendered_states = {
            component: self._render_component_status(
                component=component,
                runtime_status=runtime_states[component],
            )
            for component in _COMPONENT_ORDER
        }

        degraded_dependencies = self._degraded_dependencies(
            runtime_states
        )

        failure_reasons = self._failure_reasons(
            snapshot=snapshot,
            runtime_states=runtime_states,
        )

        if (
            snapshot.shutdown_requested
            or snapshot.shutdown_complete
        ):
            readiness_status = "shutting_down"
            ready = False
        elif failure_reasons:
            readiness_status = "not_ready"
            ready = False
        elif degraded_dependencies:
            readiness_status = "degraded"
            ready = True
        else:
            readiness_status = "ready"
            ready = True

        return ReadinessResponse(
            status=readiness_status,
            ready=ready,
            phase=self._phase,
            uptime_s=snapshot.uptime_s,
            startup_complete=snapshot.startup_complete,
            accepting_requests=snapshot.accepting_requests,
            shutting_down=(
                snapshot.shutdown_requested
                or snapshot.shutdown_complete
            ),
            components=ReadinessComponents(
                graph=rendered_states["graph"],
                snap_index=rendered_states["snap_index"],
                dispatch_adjacency=rendered_states[
                    "dispatch_adjacency"
                ],
                redis=rendered_states["redis"],
            ),
            degraded_dependencies=degraded_dependencies,
            failure_reasons=failure_reasons,
        )

    def _failure_reasons(
        self,
        *,
        snapshot: ResilienceSnapshot,
        runtime_states: dict[
            ComponentName,
            RuntimeComponentStatus,
        ],
    ) -> list[str]:
        if (
            snapshot.shutdown_requested
            or snapshot.shutdown_complete
        ):
            return ["service_shutting_down"]

        reasons: list[str] = []

        if not snapshot.startup_complete:
            reasons.append("startup_incomplete")
        elif not snapshot.accepting_requests:
            reasons.append("not_accepting_requests")

        for component in _COMPONENT_ORDER:
            if not self._policy.component_required(component):
                continue

            component_status = runtime_states[component]

            if component_status != "ready":
                reasons.append(
                    f"{component}_not_ready:{component_status}"
                )

        return reasons

    def _degraded_dependencies(
        self,
        runtime_states: dict[
            ComponentName,
            RuntimeComponentStatus,
        ],
    ) -> list[str]:
        degraded: list[str] = []

        for component in _COMPONENT_ORDER:
            if self._policy.component_required(component):
                continue

            status = runtime_states[component]

            if status in {"not_ready", "unavailable"}:
                degraded.append(component)

        return degraded

    def _render_component_status(
        self,
        *,
        component: ComponentName,
        runtime_status: RuntimeComponentStatus,
    ) -> ComponentStatus:
        required = self._policy.component_required(component)

        if runtime_status == "ready":
            return "ready"

        if runtime_status == "not_initialized":
            if required:
                return "not_initialized"

            return "not_required"

        if (
            component == "redis"
            and not required
            and self._policy.redis_fail_open
        ):
            return "degraded"

        if not required:
            return "degraded"

        if runtime_status == "unavailable":
            return "unavailable"

        return "not_ready"

    @staticmethod
    def _runtime_component_states(
        snapshot: ResilienceSnapshot,
    ) -> dict[
        ComponentName,
        RuntimeComponentStatus,
    ]:
        return {
            "graph": snapshot.graph,
            "snap_index": snapshot.snap_index,
            "dispatch_adjacency": snapshot.dispatch_adjacency,
            "redis": snapshot.redis,
        }


__all__ = [
    "ReadinessPolicy",
    "ReadinessService",
]