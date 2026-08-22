# app/middleware/concurrency_control.py

from __future__ import annotations

import logging
from collections.abc import Collection

from starlette import status
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.concurrency_limiter import (
    AdmissionOutcome,
    AdmissionRejectionReason,
    ConcurrencyLimiter,
)
from app.infrastructure.resilience_state import ResilienceState
from app.observability.reliability_metrics import ReliabilityMetrics

logger = logging.getLogger(__name__)

EndpointKey = tuple[str, str]


DEFAULT_PROTECTED_ENDPOINTS: frozenset[EndpointKey] = frozenset(
    {
        ("GET", "/route"),
        ("GET", "/route/compare"),
        ("POST", "/matrix"),
        ("POST", "/vrp/greedy"),
        ("POST", "/vrp/compare"),
        ("POST", "/vrp/compare/advanced"),
        ("POST", "/dispatch/compare"),
    }
)


_REJECTION_STATUS_CODES: dict[AdmissionRejectionReason, int] = {
    "queue_full": status.HTTP_429_TOO_MANY_REQUESTS,
    "wait_timeout": status.HTTP_503_SERVICE_UNAVAILABLE,
    "limiter_closed": status.HTTP_503_SERVICE_UNAVAILABLE,
}


_REJECTION_MESSAGES: dict[AdmissionRejectionReason, str] = {
    "queue_full": (
        "CityRoute is at its active-request and waiting-queue capacity."
    ),
    "wait_timeout": (
        "CityRoute could not admit the request before the configured "
        "admission deadline."
    ),
    "limiter_closed": (
        "CityRoute is not accepting new protected requests."
    ),
}


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

    if method.strip() == "*":
        normalized_method = "*"
    else:
        normalized_method = _normalize_method(method)

    return normalized_method, _normalize_path(path)


class ConcurrencyControlMiddleware:

    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: ConcurrencyLimiter,
        resilience_state: ResilienceState | None = None,
        reliability_metrics: ReliabilityMetrics | None = None,
        protected_endpoints: Collection[EndpointKey] | None = None,
        wait_timeout_s: float | None = None,
        retry_after_s: int = 1,
        emit_admission_headers: bool = True,
    ) -> None:
        if isinstance(retry_after_s, bool) or retry_after_s < 0:
            raise ValueError(
                "retry_after_s must be an integer greater than or equal to 0"
            )

        endpoints = (
            DEFAULT_PROTECTED_ENDPOINTS
            if protected_endpoints is None
            else protected_endpoints
        )

        self._app = app
        self._limiter = limiter
        self._resilience_state = resilience_state
        self._reliability_metrics = reliability_metrics
        self._protected_endpoints = frozenset(
            _normalize_endpoint_key(endpoint)
            for endpoint in endpoints
        )
        self._wait_timeout_s = wait_timeout_s
        self._retry_after_s = retry_after_s
        self._emit_admission_headers = emit_admission_headers

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        method = _normalize_method(str(scope.get("method", "GET")))
        path = _normalize_path(str(scope.get("path", "/")))

        if not self._is_protected(method=method, path=path):
            await self._app(scope, receive, send)
            return

        outcome = await self._limiter.acquire(
            wait_timeout_s=self._wait_timeout_s,
        )

        if not outcome.accepted:
            await self._handle_rejection(
                scope=scope,
                receive=receive,
                send=send,
                method=method,
                path=path,
                outcome=outcome,
            )
            return

        self._record_admission_metrics(
            endpoint=path,
            outcome=outcome,
        )

        lease = outcome.require_lease()
        state_request_started = False

        async with lease:
            try:
                if self._resilience_state is not None:
                    await self._resilience_state.request_started()
                    state_request_started = True

                wrapped_send = self._build_send_wrapper(
                    send=send,
                    outcome=outcome,
                )

                await self._app(
                    scope,
                    receive,
                    wrapped_send,
                )
            finally:
                if (
                    self._resilience_state is not None
                    and state_request_started
                ):
                    await self._resilience_state.request_finished()

    def _is_protected(
        self,
        *,
        method: str,
        path: str,
    ) -> bool:

        if method == "OPTIONS":
            return False

        return (
            (method, path) in self._protected_endpoints
            or ("*", path) in self._protected_endpoints
        )

    def _record_admission_metrics(
        self,
        *,
        endpoint: str,
        outcome: AdmissionOutcome,
        ) -> None:

        if self._reliability_metrics is None:
            return

        try:
            self._reliability_metrics.observe_admission(
                endpoint=endpoint,
                waited_ms=outcome.waited_ms,
                queued=outcome.queued,
            )
        except Exception:
            logger.exception(
                "Unable to record admission metrics | "
                "endpoint=%s | queued=%s | waited_ms=%.3f",
                endpoint,
                outcome.queued,
                outcome.waited_ms,
            )
    
    def _record_rejection_metrics(
        self,
        *,
        endpoint: str,
        reason: AdmissionRejectionReason,
        waited_ms: float,
    ) -> None:

        if self._reliability_metrics is None:
            return

        try:
            self._reliability_metrics.record_admission_rejection(
                endpoint=endpoint,
                reason=reason,
                waited_ms=waited_ms,
            )

            if reason in {"queue_full", "wait_timeout"}:
                self._reliability_metrics.record_overload(
                    reason=reason,
                )
        except Exception:
            logger.exception(
                "Unable to record rejection metrics | "
                "endpoint=%s | reason=%s | waited_ms=%.3f",
                endpoint,
                reason,
                waited_ms,
            )

    async def _handle_rejection(
        self,
        *,
        scope: Scope,
        receive: Receive,
        send: Send,
        method: str,
        path: str,
        outcome: AdmissionOutcome,
    ) -> None:
        reason = outcome.rejection_reason

        if reason is None:
            reason = "limiter_closed"

        if self._resilience_state is not None:
            await self._resilience_state.request_rejected(reason)

            if reason in {"queue_full", "wait_timeout"}:
                await self._resilience_state.overload_event(reason)

        self._record_rejection_metrics(
            endpoint=path,
            reason=reason,
            waited_ms=outcome.waited_ms,
            )

        status_code = _REJECTION_STATUS_CODES[reason]
        message = _REJECTION_MESSAGES[reason]

        logger.warning(
            "Request rejected by concurrency control | "
            "method=%s | path=%s | reason=%s | "
            "waited_ms=%.3f | active=%d | waiting=%d",
            method,
            path,
            reason,
            outcome.waited_ms,
            outcome.active_requests_at_decision,
            outcome.waiting_requests_at_decision,
        )

        response = JSONResponse(
            status_code=status_code,
            content={
                "detail": {
                    "error": "request_overloaded",
                    "message": message,
                    "reason": reason,
                    "endpoint": path,
                    "method": method,
                    "waited_ms": outcome.waited_ms,
                    "capacity": {
                        "max_active_requests": (
                            self._limiter.max_active_requests
                        ),
                        "max_waiting_requests": (
                            self._limiter.max_waiting_requests
                        ),
                        "active_requests": (
                            outcome.active_requests_at_decision
                        ),
                        "waiting_requests": (
                            outcome.waiting_requests_at_decision
                        ),
                    },
                }
            },
            headers={
                "Retry-After": str(self._retry_after_s),
                "X-CityRoute-Rejection-Reason": reason,
                "X-CityRoute-Admission-Wait-Ms": (
                    f"{outcome.waited_ms:.3f}"
                ),
            },
        )

        await response(scope, receive, send)

    def _build_send_wrapper(
        self,
        *,
        send: Send,
        outcome: AdmissionOutcome,
    ) -> Send:

        if not self._emit_admission_headers:
            return send

        async def send_with_admission_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-CityRoute-Admission-Wait-Ms"] = (
                    f"{outcome.waited_ms:.3f}"
                )
                headers["X-CityRoute-Admission-Queued"] = str(
                    outcome.queued
                ).lower()

            await send(message)

        return send_with_admission_headers


__all__ = [
    "ConcurrencyControlMiddleware",
    "DEFAULT_PROTECTED_ENDPOINTS",
    "EndpointKey",
]