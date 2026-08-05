# app/middleware/request_timeout.py

from __future__ import annotations

import asyncio
import logging
from math import isfinite

from starlette import status
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.timeout_policy import TimeoutDecision, TimeoutPolicy
from app.infrastructure.resilience_state import ResilienceState

logger = logging.getLogger(__name__)


def _validate_cancellation_grace(timeout_s: float) -> None:
    if isinstance(timeout_s, bool):
        raise ValueError("cancellation_grace_s must be a number")

    if not isfinite(timeout_s) or timeout_s < 0:
        raise ValueError(
            "cancellation_grace_s must be finite and greater than or equal to 0"
        )


class RequestTimeoutMiddleware:
    """
    Pure ASGI middleware enforcing endpoint-specific execution time limits.

    Only endpoints registered in TimeoutPolicy are protected. Lightweight
    operational endpoints such as health, readiness, metrics, documentation,
    and OpenAPI remain outside this middleware unless explicitly configured.

    Timeout lifecycle:

        resolve endpoint policy
            ↓
        execute protected request in an independent task
            ↓
        request completes before deadline
            → return normal response

        deadline expires
            → block further sends from timed-out task
            → cancel request task
            → record timeout
            → return controlled HTTP 504 response

    Important boundary:

    Cancelling an asyncio task cannot forcibly stop native or thread-based CPU
    work that has already begun. The cancelled task is prevented from sending
    additional ASGI response messages, but underlying work dispatched through
    asyncio.to_thread() or an executor may continue until that operation
    naturally finishes.

    Phase 11 timeout probes must measure this behavior and confirm that timed-out
    work does not produce unbounded resource consumption.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        timeout_policy: TimeoutPolicy,
        resilience_state: ResilienceState | None = None,
        cancellation_grace_s: float = 0.05,
        emit_timeout_headers: bool = True,
    ) -> None:
        _validate_cancellation_grace(cancellation_grace_s)

        self._app = app
        self._timeout_policy = timeout_policy
        self._resilience_state = resilience_state
        self._cancellation_grace_s = cancellation_grace_s
        self._emit_timeout_headers = emit_timeout_headers

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        method = str(scope.get("method", "GET"))
        path = str(scope.get("path", "/"))

        decision = self._timeout_policy.resolve(
            method=method,
            path=path,
        )

        if not decision.protected or not decision.enabled:
            await self._app(scope, receive, send)
            return

        timeout_s = decision.timeout_s

        if timeout_s is None:
            raise RuntimeError(
                "Timeout policy returned enabled=True without a timeout value"
            )

        response_started = False
        response_complete = False
        application_send_enabled = True

        async def guarded_send(message: Message) -> None:
            """
            Prevent a timed-out application task from writing after HTTP 504.

            Once the deadline expires, the outer middleware owns the response
            channel. Any late response messages from cancelled or detached work
            are discarded.
            """

            nonlocal response_complete
            nonlocal response_started

            if not application_send_enabled:
                return

            message_type = message["type"]

            if message_type == "http.response.start":
                response_started = True

                if self._emit_timeout_headers:
                    headers = MutableHeaders(scope=message)
                    headers["X-CityRoute-Timeout-Enforced"] = "true"
                    headers["X-CityRoute-Timeout-Limit-S"] = (
                        f"{timeout_s:.3f}"
                    )

                    if decision.category is not None:
                        headers["X-CityRoute-Timeout-Category"] = (
                            decision.category.value
                        )

            elif message_type == "http.response.body":
                if not bool(message.get("more_body", False)):
                    response_complete = True

            await send(message)

        application_task = asyncio.create_task(
            self._app(
                scope,
                receive,
                guarded_send,
            ),
            name=(
                "cityroute-request:"
                f"{decision.method}:{decision.path}"
            ),
        )

        try:
            completed, _ = await asyncio.wait(
                {application_task},
                timeout=timeout_s,
            )
        except asyncio.CancelledError:
            application_send_enabled = False
            application_task.cancel()
            self._consume_task_later(application_task)
            raise

        if application_task in completed:
            await application_task
            return

        # The deadline has expired. Prevent the application task from sending
        # anything further before cancellation and timeout-response handling.
        application_send_enabled = False
        application_task.cancel()

        cancelled_cleanly = await self._wait_for_task_cancellation(
            application_task
        )

        if self._resilience_state is not None:
            await self._resilience_state.request_timed_out(
                decision.path
            )

        logger.warning(
            "Request timeout enforced | "
            "method=%s | path=%s | category=%s | "
            "timeout_s=%.3f | response_started=%s | "
            "response_complete=%s | task_cancelled_cleanly=%s",
            decision.method,
            decision.path,
            (
                decision.category.value
                if decision.category is not None
                else "unknown"
            ),
            timeout_s,
            response_started,
            response_complete,
            cancelled_cleanly,
        )

        if response_complete:
            # The client already received the complete response. This can
            # happen when post-response background work exceeds the limit.
            return

        if response_started:
            # HTTP status and headers have already reached the client, so they
            # cannot legally be replaced with a new 504 response. Terminate the
            # partially started body instead.
            await self._finish_started_response(send)
            return

        response = self._build_timeout_response(
            decision=decision,
            timeout_s=timeout_s,
            cancelled_cleanly=cancelled_cleanly,
        )

        await response(scope, receive, send)

    def _build_timeout_response(
        self,
        *,
        decision: TimeoutDecision,
        timeout_s: float,
        cancelled_cleanly: bool,
    ) -> JSONResponse:
        category = (
            decision.category.value
            if decision.category is not None
            else "unknown"
        )

        return JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            content={
                "detail": {
                    "error": "request_timeout",
                    "message": (
                        "The operation exceeded its configured "
                        "execution limit."
                    ),
                    "endpoint": decision.path,
                    "method": decision.method,
                    "category": category,
                    "timeout_s": timeout_s,
                    "task_cancelled_cleanly": cancelled_cleanly,
                }
            },
            headers={
                "X-CityRoute-Timeout-Enforced": "true",
                "X-CityRoute-Timeout-Limit-S": f"{timeout_s:.3f}",
                "X-CityRoute-Timeout-Category": category,
            },
        )

    async def _wait_for_task_cancellation(
        self,
        task: asyncio.Task[None],
    ) -> bool:
        """
        Give the cancelled request task a short bounded cleanup period.

        A task that does not finish during this grace period is detached from
        the response channel. Its eventual result is consumed by a callback to
        avoid "Task exception was never retrieved" warnings.
        """

        if task.done():
            self._consume_task_result(task)
            return True

        if self._cancellation_grace_s == 0:
            self._consume_task_later(task)
            return False

        completed, _ = await asyncio.wait(
            {task},
            timeout=self._cancellation_grace_s,
        )

        if task in completed:
            self._consume_task_result(task)
            return True

        self._consume_task_later(task)
        return False

    @staticmethod
    async def _finish_started_response(send: Send) -> None:
        """
        Finish an already-started response after timeout cancellation.

        A different status code cannot be sent once the original
        `http.response.start` message has reached the server.
        """

        try:
            await send(
                {
                    "type": "http.response.body",
                    "body": b"",
                    "more_body": False,
                }
            )
        except (OSError, RuntimeError):
            logger.warning(
                "Unable to terminate partially started timed-out response",
                exc_info=True,
            )

    @classmethod
    def _consume_task_later(
        cls,
        task: asyncio.Task[None],
    ) -> None:
        if task.done():
            cls._consume_task_result(task)
            return

        task.add_done_callback(cls._consume_task_result)

    @staticmethod
    def _consume_task_result(
        task: asyncio.Task[None],
    ) -> None:
        """
        Consume the result of a cancelled or detached task.

        This prevents unhandled task-exception warnings while retaining an
        error log when detached work fails unexpectedly.
        """

        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.error(
                "Detached timed-out request task failed",
                exc_info=(
                    type(exc),
                    exc,
                    exc.__traceback__,
                ),
            )


__all__ = ["RequestTimeoutMiddleware"]