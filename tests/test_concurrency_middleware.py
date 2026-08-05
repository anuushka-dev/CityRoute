# tests/test_concurrency_middleware.py

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.concurrency_limiter import ConcurrencyLimiter
from app.infrastructure.resilience_state import ResilienceState
from app.middleware.concurrency_control import (
    ConcurrencyControlMiddleware,
)


@pytest.fixture
def anyio_backend() -> str:
    """Run asynchronous middleware tests with asyncio."""

    return "asyncio"


async def _send_json(
    send: Send,
    *,
    status_code: int = 200,
    content: dict[str, Any] | None = None,
) -> None:
    payload = json.dumps(
        content or {"status": "ok"}
    ).encode()

    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode()),
            ],
        }
    )

    await send(
        {
            "type": "http.response.body",
            "body": payload,
            "more_body": False,
        }
    )


async def _successful_app(
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    del receive

    await _send_json(
        send,
        content={
            "status": "executed",
            "method": scope.get("method"),
            "path": scope.get("path"),
        },
    )


class BlockingApp:
    """ASGI application that waits until the test releases it."""

    def __init__(self) -> None:
        self.first_request_started = asyncio.Event()
        self.release_requests = asyncio.Event()
        self.call_count = 0

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        del receive

        self.call_count += 1

        if self.call_count == 1:
            self.first_request_started.set()

        await self.release_requests.wait()

        await _send_json(
            send,
            content={
                "status": "executed",
                "call_count": self.call_count,
                "path": scope.get("path"),
            },
        )


def _http_scope(
    *,
    method: str = "GET",
    path: str = "/route",
) -> Scope:
    return {
        "type": "http",
        "asgi": {
            "version": "3.0",
            "spec_version": "2.3",
        },
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    }


async def _request(
    app: ASGIApp,
    *,
    method: str = "GET",
    path: str = "/route",
) -> tuple[int, dict[str, str], dict[str, Any]]:
    sent_messages: list[Message] = []
    request_consumed = False

    async def receive() -> Message:
        nonlocal request_consumed

        if not request_consumed:
            request_consumed = True

            return {
                "type": "http.request",
                "body": b"",
                "more_body": False,
            }

        await asyncio.sleep(3600)

        return {
            "type": "http.disconnect",
        }

    async def send(message: Message) -> None:
        sent_messages.append(message)

    await app(
        _http_scope(
            method=method,
            path=path,
        ),
        receive,
        send,
    )

    start_message = next(
        message
        for message in sent_messages
        if message["type"] == "http.response.start"
    )

    body = b"".join(
        message.get("body", b"")
        for message in sent_messages
        if message["type"] == "http.response.body"
    )

    headers = {
        key.decode().lower(): value.decode()
        for key, value in start_message.get("headers", [])
    }

    payload: dict[str, Any]

    if body:
        payload = json.loads(body)
    else:
        payload = {}

    return (
        int(start_message["status"]),
        headers,
        payload,
    )


async def _wait_for_limiter_state(
    limiter: ConcurrencyLimiter,
    *,
    active_requests: int | None = None,
    waiting_requests: int | None = None,
    timeout_s: float = 1.0,
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s

    while True:
        snapshot = await limiter.snapshot()

        active_matches = (
            active_requests is None
            or snapshot.active_requests == active_requests
        )
        waiting_matches = (
            waiting_requests is None
            or snapshot.waiting_requests == waiting_requests
        )

        if active_matches and waiting_matches:
            return

        if loop.time() >= deadline:
            raise AssertionError(
                "Concurrency limiter did not reach expected state: "
                f"expected active={active_requests}, "
                f"waiting={waiting_requests}; "
                f"actual active={snapshot.active_requests}, "
                f"waiting={snapshot.waiting_requests}"
            )

        await asyncio.sleep(0.001)


def _build_middleware(
    app: ASGIApp,
    *,
    limiter: ConcurrencyLimiter | None = None,
    resilience_state: ResilienceState | None = None,
    wait_timeout_s: float | None = None,
    retry_after_s: int = 1,
    emit_admission_headers: bool = True,
    protected_endpoints: set[tuple[str, str]] | None = None,
) -> tuple[
    ConcurrencyControlMiddleware,
    ConcurrencyLimiter,
]:
    actual_limiter = limiter or ConcurrencyLimiter(
        max_active_requests=1,
        max_waiting_requests=1,
        default_wait_timeout_s=1.0,
    )

    middleware = ConcurrencyControlMiddleware(
        app,
        limiter=actual_limiter,
        resilience_state=resilience_state,
        protected_endpoints=protected_endpoints,
        wait_timeout_s=wait_timeout_s,
        retry_after_s=retry_after_s,
        emit_admission_headers=emit_admission_headers,
    )

    return middleware, actual_limiter


def test_constructor_rejects_invalid_retry_after() -> None:
    limiter = ConcurrencyLimiter(
        max_active_requests=1,
        max_waiting_requests=1,
        default_wait_timeout_s=1.0,
    )

    with pytest.raises(
        ValueError,
        match="retry_after_s",
    ):
        ConcurrencyControlMiddleware(
            _successful_app,
            limiter=limiter,
            retry_after_s=-1,
        )

    with pytest.raises(
        ValueError,
        match="retry_after_s",
    ):
        ConcurrencyControlMiddleware(
            _successful_app,
            limiter=limiter,
            retry_after_s=True,
        )


@pytest.mark.anyio
async def test_protected_request_is_admitted_immediately() -> None:
    state = ResilienceState()

    middleware, limiter = _build_middleware(
        _successful_app,
        resilience_state=state,
    )

    status_code, headers, payload = await _request(
        middleware,
        path="/route",
    )

    assert status_code == 200
    assert payload["status"] == "executed"
    assert payload["path"] == "/route"

    assert (
        headers["x-cityroute-admission-queued"]
        == "false"
    )
    assert float(
        headers["x-cityroute-admission-wait-ms"]
    ) >= 0.0

    limiter_snapshot = await limiter.snapshot()
    state_snapshot = await state.snapshot()

    assert limiter_snapshot.active_requests == 0
    assert limiter_snapshot.total_admitted_requests == 1
    assert limiter_snapshot.total_released_requests == 1

    assert state_snapshot.active_requests == 0
    assert state_snapshot.completed_requests == 1
    assert state_snapshot.rejected_requests == 0


@pytest.mark.anyio
async def test_unprotected_endpoint_bypasses_closed_limiter() -> None:
    middleware, limiter = _build_middleware(
        _successful_app
    )

    await limiter.close(
        reason="service_shutdown"
    )

    status_code, headers, payload = await _request(
        middleware,
        path="/health/live",
    )

    assert status_code == 200
    assert payload["status"] == "executed"

    assert "x-cityroute-admission-queued" not in headers
    assert "x-cityroute-admission-wait-ms" not in headers

    snapshot = await limiter.snapshot()

    assert snapshot.total_admitted_requests == 0
    assert snapshot.total_rejected_requests == 0


@pytest.mark.anyio
async def test_endpoint_protection_is_method_specific() -> None:
    middleware, limiter = _build_middleware(
        _successful_app
    )

    await limiter.close(
        reason="service_shutdown"
    )

    status_code, headers, payload = await _request(
        middleware,
        method="POST",
        path="/route",
    )

    assert status_code == 200
    assert payload["method"] == "POST"
    assert "x-cityroute-admission-queued" not in headers

    snapshot = await limiter.snapshot()

    assert snapshot.total_rejected_requests == 0


@pytest.mark.anyio
async def test_queued_request_is_admitted_after_release() -> None:
    blocking_app = BlockingApp()
    state = ResilienceState()

    middleware, limiter = _build_middleware(
        blocking_app,
        resilience_state=state,
    )

    first_task = asyncio.create_task(
        _request(
            middleware,
            path="/route",
        )
    )

    await asyncio.wait_for(
        blocking_app.first_request_started.wait(),
        timeout=1.0,
    )

    second_task = asyncio.create_task(
        _request(
            middleware,
            path="/route",
        )
    )

    await _wait_for_limiter_state(
        limiter,
        active_requests=1,
        waiting_requests=1,
    )

    blocking_app.release_requests.set()

    first_response, second_response = await asyncio.gather(
        first_task,
        second_task,
    )

    first_status, first_headers, _ = first_response
    second_status, second_headers, _ = second_response

    assert first_status == 200
    assert second_status == 200

    assert (
        first_headers["x-cityroute-admission-queued"]
        == "false"
    )
    assert (
        second_headers["x-cityroute-admission-queued"]
        == "true"
    )

    limiter_snapshot = await limiter.snapshot()
    state_snapshot = await state.snapshot()

    assert limiter_snapshot.active_requests == 0
    assert limiter_snapshot.waiting_requests == 0
    assert limiter_snapshot.total_admitted_requests == 2
    assert limiter_snapshot.total_released_requests == 2

    assert state_snapshot.active_requests == 0
    assert state_snapshot.completed_requests == 2


@pytest.mark.anyio
async def test_queue_full_returns_429() -> None:
    blocking_app = BlockingApp()
    state = ResilienceState()

    middleware, limiter = _build_middleware(
        blocking_app,
        resilience_state=state,
        retry_after_s=3,
    )

    first_task = asyncio.create_task(
        _request(middleware)
    )

    await asyncio.wait_for(
        blocking_app.first_request_started.wait(),
        timeout=1.0,
    )

    queued_task = asyncio.create_task(
        _request(middleware)
    )

    await _wait_for_limiter_state(
        limiter,
        active_requests=1,
        waiting_requests=1,
    )

    rejected_response = await _request(middleware)

    blocking_app.release_requests.set()

    await asyncio.gather(
        first_task,
        queued_task,
    )

    status_code, headers, payload = rejected_response

    assert status_code == 429
    assert headers["retry-after"] == "3"
    assert (
        headers["x-cityroute-rejection-reason"]
        == "queue_full"
    )

    detail = payload["detail"]

    assert detail["error"] == "request_overloaded"
    assert detail["reason"] == "queue_full"
    assert detail["endpoint"] == "/route"
    assert detail["method"] == "GET"

    assert detail["capacity"] == {
        "max_active_requests": 1,
        "max_waiting_requests": 1,
        "active_requests": 1,
        "waiting_requests": 1,
    }

    limiter_snapshot = await limiter.snapshot()
    state_snapshot = await state.snapshot()

    assert limiter_snapshot.total_rejected_requests == 1
    assert limiter_snapshot.queue_full_rejections == 1

    assert state_snapshot.rejected_requests == 1
    assert state_snapshot.overload_events == 1
    assert state_snapshot.last_rejection_reason == "queue_full"


@pytest.mark.anyio
async def test_wait_timeout_returns_503() -> None:
    blocking_app = BlockingApp()
    state = ResilienceState()

    middleware, limiter = _build_middleware(
        blocking_app,
        resilience_state=state,
        wait_timeout_s=0.02,
    )

    first_task = asyncio.create_task(
        _request(middleware)
    )

    await asyncio.wait_for(
        blocking_app.first_request_started.wait(),
        timeout=1.0,
    )

    timed_out_response = await _request(middleware)

    blocking_app.release_requests.set()
    await first_task

    status_code, headers, payload = timed_out_response

    assert status_code == 503
    assert (
        headers["x-cityroute-rejection-reason"]
        == "wait_timeout"
    )

    detail = payload["detail"]

    assert detail["error"] == "request_overloaded"
    assert detail["reason"] == "wait_timeout"
    assert detail["waited_ms"] >= 0.0

    limiter_snapshot = await limiter.snapshot()
    state_snapshot = await state.snapshot()

    assert limiter_snapshot.wait_timeout_rejections == 1
    assert limiter_snapshot.total_rejected_requests == 1

    assert state_snapshot.rejected_requests == 1
    assert state_snapshot.overload_events == 1
    assert state_snapshot.last_rejection_reason == "wait_timeout"


@pytest.mark.anyio
async def test_closed_limiter_rejects_new_protected_request() -> None:
    state = ResilienceState()

    middleware, limiter = _build_middleware(
        _successful_app,
        resilience_state=state,
    )

    await limiter.close(
        reason="service_shutdown"
    )

    status_code, headers, payload = await _request(
        middleware
    )

    assert status_code == 503
    assert (
        headers["x-cityroute-rejection-reason"]
        == "limiter_closed"
    )
    assert payload["detail"]["reason"] == "limiter_closed"

    limiter_snapshot = await limiter.snapshot()
    state_snapshot = await state.snapshot()

    assert limiter_snapshot.limiter_closed_rejections == 1
    assert state_snapshot.rejected_requests == 1

    # Limiter closure is lifecycle rejection, not an overload event.
    assert state_snapshot.overload_events == 0


@pytest.mark.anyio
async def test_close_wakes_and_rejects_queued_request() -> None:
    blocking_app = BlockingApp()
    state = ResilienceState()

    middleware, limiter = _build_middleware(
        blocking_app,
        resilience_state=state,
        wait_timeout_s=5.0,
    )

    first_task = asyncio.create_task(
        _request(middleware)
    )

    await asyncio.wait_for(
        blocking_app.first_request_started.wait(),
        timeout=1.0,
    )

    queued_task = asyncio.create_task(
        _request(middleware)
    )

    await _wait_for_limiter_state(
        limiter,
        active_requests=1,
        waiting_requests=1,
    )

    await limiter.close(
        reason="service_shutdown"
    )

    queued_response = await asyncio.wait_for(
        queued_task,
        timeout=1.0,
    )

    blocking_app.release_requests.set()
    await first_task

    status_code, headers, payload = queued_response

    assert status_code == 503
    assert (
        headers["x-cityroute-rejection-reason"]
        == "limiter_closed"
    )
    assert payload["detail"]["reason"] == "limiter_closed"
    assert payload["detail"]["waited_ms"] >= 0.0

    limiter_snapshot = await limiter.snapshot()

    assert limiter_snapshot.active_requests == 0
    assert limiter_snapshot.waiting_requests == 0
    assert limiter_snapshot.limiter_closed_rejections == 1


@pytest.mark.anyio
async def test_options_request_bypasses_limiter() -> None:
    middleware, limiter = _build_middleware(
        _successful_app
    )

    await limiter.close(
        reason="service_shutdown"
    )

    status_code, headers, payload = await _request(
        middleware,
        method="OPTIONS",
        path="/route",
    )

    assert status_code == 200
    assert payload["method"] == "OPTIONS"
    assert "x-cityroute-admission-queued" not in headers

    snapshot = await limiter.snapshot()

    assert snapshot.total_rejected_requests == 0


@pytest.mark.anyio
async def test_trailing_slash_is_normalized() -> None:
    middleware, limiter = _build_middleware(
        _successful_app
    )

    await limiter.close(
        reason="service_shutdown"
    )

    status_code, _, payload = await _request(
        middleware,
        path="/route/",
    )

    assert status_code == 503
    assert payload["detail"]["reason"] == "limiter_closed"


@pytest.mark.anyio
async def test_wildcard_method_protects_custom_endpoint() -> None:
    middleware, limiter = _build_middleware(
        _successful_app,
        protected_endpoints={
            ("*", "/custom"),
        },
    )

    await limiter.close(
        reason="service_shutdown"
    )

    status_code, _, payload = await _request(
        middleware,
        method="POST",
        path="/custom",
    )

    assert status_code == 503
    assert payload["detail"]["reason"] == "limiter_closed"


@pytest.mark.anyio
async def test_application_exception_releases_capacity() -> None:
    state = ResilienceState()

    async def failing_app(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        del scope
        del receive
        del send

        raise RuntimeError("endpoint failure")

    middleware, limiter = _build_middleware(
        failing_app,
        resilience_state=state,
    )

    with pytest.raises(
        RuntimeError,
        match="endpoint failure",
    ):
        await _request(middleware)

    limiter_snapshot = await limiter.snapshot()
    state_snapshot = await state.snapshot()

    assert limiter_snapshot.active_requests == 0
    assert limiter_snapshot.total_admitted_requests == 1
    assert limiter_snapshot.total_released_requests == 1

    assert state_snapshot.active_requests == 0
    assert state_snapshot.completed_requests == 1


@pytest.mark.anyio
async def test_admission_headers_can_be_disabled() -> None:
    middleware, _ = _build_middleware(
        _successful_app,
        emit_admission_headers=False,
    )

    status_code, headers, _ = await _request(
        middleware
    )

    assert status_code == 200
    assert "x-cityroute-admission-queued" not in headers
    assert "x-cityroute-admission-wait-ms" not in headers


@pytest.mark.anyio
async def test_middleware_works_without_resilience_state() -> None:
    middleware, limiter = _build_middleware(
        _successful_app,
        resilience_state=None,
    )

    status_code, headers, payload = await _request(
        middleware
    )

    assert status_code == 200
    assert payload["status"] == "executed"
    assert (
        headers["x-cityroute-admission-queued"]
        == "false"
    )

    snapshot = await limiter.snapshot()

    assert snapshot.active_requests == 0
    assert snapshot.total_admitted_requests == 1
    assert snapshot.total_released_requests == 1


@pytest.mark.anyio
async def test_non_http_scope_bypasses_limiter() -> None:
    called = False

    async def non_http_app(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        nonlocal called

        del receive
        del send

        called = True
        assert scope["type"] == "websocket"

    middleware, limiter = _build_middleware(
        non_http_app
    )

    async def receive() -> Message:
        return {
            "type": "websocket.connect",
        }

    async def send(message: Message) -> None:
        del message

    await middleware(
        {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "path": "/route",
            "raw_path": b"/route",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 50000),
            "server": ("127.0.0.1", 8000),
            "scheme": "ws",
            "subprotocols": [],
        },
        receive,
        send,
    )

    assert called is True

    snapshot = await limiter.snapshot()

    assert snapshot.total_admitted_requests == 0
    assert snapshot.total_rejected_requests == 0