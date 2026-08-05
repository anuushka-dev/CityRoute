# app/middleware/lifecycle_guard.py

from __future__ import annotations

import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Literal

from starlette import status
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.infrastructure.resilience_state import (
    ComponentName,
    ResilienceSnapshot,
    ResilienceState,
    RuntimeComponentStatus,
)

logger = logging.getLogger(__name__)

EndpointKey = tuple[str, str]

LifecycleRejectionReason = Literal[
    "startup_incomplete",
    "not_accepting_requests",
    "service_shutting_down",
    "required_component_not_ready",
]


DEFAULT_ENDPOINT_REQUIREMENTS: dict[
    EndpointKey,
    frozenset[ComponentName],
] = {
    ("GET", "/route"): frozenset(
        {
            "graph",
            "snap_index",
        }
    ),
    ("GET", "/route/compare"): frozenset(
        {
            "graph",
            "snap_index",
        }
    ),
    ("POST", "/matrix"): frozenset(
        {
            "graph",
            "snap_index",
        }
    ),
    ("POST", "/vrp/greedy"): frozenset(
        {
            "graph",
            "snap_index",
        }
    ),
    ("POST", "/vrp/compare"): frozenset(
        {
            "graph",
            "snap_index",
        }
    ),
    ("POST", "/vrp/compare/advanced"): frozenset(
        {
            "graph",
            "snap_index",
        }
    ),
    ("POST", "/dispatch/compare"): frozenset(
        {
            "graph",
            "snap_index",
            "dispatch_adjacency",
        }
    ),
}


_ALLOWED_COMPONENTS: frozenset[str] = frozenset(
    {
        "graph",
        "snap_index",
        "dispatch_adjacency",
        "redis",
    }
)


_REJECTION_MESSAGES: dict[LifecycleRejectionReason, str] = {
    "startup_incomplete": (
        "CityRoute startup initialization has not completed."
    ),
    "not_accepting_requests": (
        "CityRoute is temporarily not accepting protected requests."
    ),
    "service_shutting_down": (
        "CityRoute is shutting down and cannot accept new protected work."
    ),
    "required_component_not_ready": (
        "One or more components required by this endpoint are not ready."
    ),
}


@dataclass(frozen=True, slots=True)
class LifecycleDecision:
    """
    Result of evaluating one request against the current lifecycle state.
    """

    allowed: bool
    reason: LifecycleRejectionReason | None

    method: str
    path: str

    required_components: tuple[ComponentName, ...]
    unavailable_components: tuple[ComponentName, ...]

    component_states: tuple[
        tuple[ComponentName, RuntimeComponentStatus],
        ...,
    ]


def _normalize_method(method: str) -> str:
    normalized = method.strip().upper()

    if not normalized:
        raise ValueError("HTTP method must not be empty")

    return normalized


def _normalize_path(path: str) -> str:
    normalized = path.strip().split("?", maxsplit=1)[0]

    if not normalized:
        normalized = "/"

    if not normalized.startswith("/"):
        normalized = f"/{normalized}"

    if len(normalized) > 1:
        normalized = normalized.rstrip("/")

    return normalized


def _normalize_endpoint_key(endpoint: EndpointKey) -> EndpointKey:
    method, path = endpoint

    normalized_method = (
        "*"
        if method.strip() == "*"
        else _normalize_method(method)
    )

    return normalized_method, _normalize_path(path)


def _component_status(
    snapshot: ResilienceSnapshot,
    component: ComponentName,
) -> RuntimeComponentStatus:
    states: dict[ComponentName, RuntimeComponentStatus] = {
        "graph": snapshot.graph,
        "snap_index": snapshot.snap_index,
        "dispatch_adjacency": snapshot.dispatch_adjacency,
        "redis": snapshot.redis,
    }

    return states[component]


class LifecycleGuardMiddleware:
    """
    Pure ASGI middleware preventing expensive work during invalid lifecycle
    states.

    Protected requests are rejected when:

        startup is incomplete
        service admission is disabled
        graceful shutdown has started
        a component required by the endpoint is not ready

    Lightweight operational endpoints are intentionally excluded:

        /health
        /health/live
        /health/ready
        /metrics
        /docs
        /openapi.json

    This allows operators and container orchestration systems to inspect the
    service even while it is starting, degraded, overloaded, or shutting down.

    Redis is not required by the default endpoint map because Phase 11 uses
    fail-open cache behavior. Redis availability should still be exposed by
    readiness and reliability metrics.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        resilience_state: ResilienceState,
        endpoint_requirements: Mapping[
            EndpointKey,
            Collection[ComponentName],
        ]
        | None = None,
        retry_after_s: int = 1,
    ) -> None:
        if isinstance(retry_after_s, bool) or retry_after_s < 0:
            raise ValueError(
                "retry_after_s must be an integer greater than or equal to 0"
            )

        supplied_requirements = (
            DEFAULT_ENDPOINT_REQUIREMENTS
            if endpoint_requirements is None
            else endpoint_requirements
        )

        self._app = app
        self._resilience_state = resilience_state
        self._retry_after_s = retry_after_s

        self._endpoint_requirements = (
            self._normalize_requirements(
                supplied_requirements
            )
        )

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        method = _normalize_method(
            str(scope.get("method", "GET"))
        )
        path = _normalize_path(
            str(scope.get("path", "/"))
        )

        if method == "OPTIONS":
            await self._app(scope, receive, send)
            return

        required_components = self._requirements_for(
            method=method,
            path=path,
        )

        if required_components is None:
            await self._app(scope, receive, send)
            return

        snapshot = await self._resilience_state.snapshot()

        decision = self._evaluate(
            method=method,
            path=path,
            required_components=required_components,
            snapshot=snapshot,
        )

        if decision.allowed:
            await self._app(scope, receive, send)
            return

        await self._handle_rejection(
            scope=scope,
            receive=receive,
            send=send,
            decision=decision,
            snapshot=snapshot,
        )

    def _requirements_for(
        self,
        *,
        method: str,
        path: str,
    ) -> tuple[ComponentName, ...] | None:
        requirements = self._endpoint_requirements.get(
            (method, path)
        )

        if requirements is None:
            requirements = self._endpoint_requirements.get(
                ("*", path)
            )

        return requirements

    def _evaluate(
        self,
        *,
        method: str,
        path: str,
        required_components: tuple[ComponentName, ...],
        snapshot: ResilienceSnapshot,
    ) -> LifecycleDecision:
        component_states = tuple(
            (
                component,
                _component_status(snapshot, component),
            )
            for component in required_components
        )

        if (
            snapshot.shutdown_requested
            or snapshot.shutdown_complete
        ):
            return LifecycleDecision(
                allowed=False,
                reason="service_shutting_down",
                method=method,
                path=path,
                required_components=required_components,
                unavailable_components=(),
                component_states=component_states,
            )

        if not snapshot.startup_complete:
            return LifecycleDecision(
                allowed=False,
                reason="startup_incomplete",
                method=method,
                path=path,
                required_components=required_components,
                unavailable_components=(),
                component_states=component_states,
            )

        if not snapshot.accepting_requests:
            return LifecycleDecision(
                allowed=False,
                reason="not_accepting_requests",
                method=method,
                path=path,
                required_components=required_components,
                unavailable_components=(),
                component_states=component_states,
            )

        unavailable_components = tuple(
            component
            for component, component_status in component_states
            if component_status != "ready"
        )

        if unavailable_components:
            return LifecycleDecision(
                allowed=False,
                reason="required_component_not_ready",
                method=method,
                path=path,
                required_components=required_components,
                unavailable_components=unavailable_components,
                component_states=component_states,
            )

        return LifecycleDecision(
            allowed=True,
            reason=None,
            method=method,
            path=path,
            required_components=required_components,
            unavailable_components=(),
            component_states=component_states,
        )

    async def _handle_rejection(
        self,
        *,
        scope: Scope,
        receive: Receive,
        send: Send,
        decision: LifecycleDecision,
        snapshot: ResilienceSnapshot,
    ) -> None:
        reason = decision.reason

        if reason is None:
            raise RuntimeError(
                "Rejected lifecycle decision has no rejection reason"
            )

        await self._resilience_state.request_rejected(reason)

        component_states = {
            component: component_status
            for component, component_status in decision.component_states
        }

        logger.warning(
            "Request rejected by lifecycle guard | "
            "method=%s | path=%s | reason=%s | "
            "startup_complete=%s | accepting_requests=%s | "
            "shutdown_requested=%s | unavailable_components=%s",
            decision.method,
            decision.path,
            reason,
            snapshot.startup_complete,
            snapshot.accepting_requests,
            snapshot.shutdown_requested,
            list(decision.unavailable_components),
        )

        response = JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": {
                    "error": "service_unavailable",
                    "message": _REJECTION_MESSAGES[reason],
                    "reason": reason,
                    "endpoint": decision.path,
                    "method": decision.method,
                    "lifecycle": {
                        "startup_started": (
                            snapshot.startup_started
                        ),
                        "startup_complete": (
                            snapshot.startup_complete
                        ),
                        "accepting_requests": (
                            snapshot.accepting_requests
                        ),
                        "shutdown_requested": (
                            snapshot.shutdown_requested
                        ),
                        "shutdown_complete": (
                            snapshot.shutdown_complete
                        ),
                    },
                    "required_components": list(
                        decision.required_components
                    ),
                    "unavailable_components": list(
                        decision.unavailable_components
                    ),
                    "component_states": component_states,
                }
            },
            headers={
                "Retry-After": str(self._retry_after_s),
                "X-CityRoute-Lifecycle-Rejection-Reason": reason,
            },
        )

        await response(scope, receive, send)

    @staticmethod
    def _normalize_requirements(
        requirements: Mapping[
            EndpointKey,
            Collection[ComponentName],
        ],
    ) -> dict[
        EndpointKey,
        tuple[ComponentName, ...],
    ]:
        normalized: dict[
            EndpointKey,
            tuple[ComponentName, ...],
        ] = {}

        for endpoint, components in requirements.items():
            normalized_endpoint = _normalize_endpoint_key(
                endpoint
            )

            normalized_components: set[ComponentName] = set()

            for component in components:
                if component not in _ALLOWED_COMPONENTS:
                    raise ValueError(
                        "Unsupported lifecycle component "
                        f"requirement: {component!r}"
                    )

                normalized_components.add(component)

            if normalized_endpoint in normalized:
                raise ValueError(
                    "Duplicate lifecycle requirement for "
                    f"{normalized_endpoint!r}"
                )

            normalized[normalized_endpoint] = tuple(
                sorted(normalized_components)
            )

        return normalized


__all__ = [
    "DEFAULT_ENDPOINT_REQUIREMENTS",
    "EndpointKey",
    "LifecycleDecision",
    "LifecycleGuardMiddleware",
    "LifecycleRejectionReason",
]