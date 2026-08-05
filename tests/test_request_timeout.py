# tests/test_request_timeout.py

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.timeout_policy import (
    TimeoutCategory,
    TimeoutPolicy,
    TimeoutRule,
)
from app.infrastructure.resilience_state import ResilienceState
from app.middleware.request_timeout import RequestTimeoutMiddleware


@pytest.fixture
def anyio_backend() -> str:
    """Run asynchronous middleware tests with asyncio."""

    return "asyncio"


def _build_policy(
    *,
    method: str = "GET",
    path: str = "/slow",
    timeout_s: float | None = 0.05,
) -> TimeoutPolicy:
    rule = TimeoutRule(
        method=method,
        path=path,
        category=TimeoutCategory.ROUTE,
        timeout_s=timeout_s,
    )

    return TimeoutPolicy(
        {
            (rule.method, rule.path): rule,
        }
    )


def _http_scope(
    *,
    method: str = "GET",
    path: str = "/slow",
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
    path: str = "/slow",
) -> tuple[
    int,
    dict[str, str],
    bytes,
    list[Message],
]:
    sent_messages: list[Message] = []
    request_received = False

    async def receive() -> Message:
        nonlocal request_received

        if not request_received:
            request_received = True

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

    response_start = next(
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
        for key, value in response_start.get("headers", [])
    }

    return (
        int(response_start["status"]),
        headers,
        body,
        sent_messages,
    )


async def _send_json(
    send: Send,
    *,
    status_code: int = 200,
    content: dict[str, Any] | None = None,
) -> None:
    body = json.dumps(
        content or {"status": "ok"}
    ).encode()

    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (
                    b"content-length",
                    str(len(body)).encode(),
                ),
            ],
        }
    )

    await send(
        {
            "type": "http.response.body",
            "body": body,
            "more_body": False,
        }
    )


def _json_body(body: bytes) -> dict[str, Any]:
    return json.loads(body.decode())


def test_constructor_rejects_invalid_cancellation_grace() -> None:
    policy = _build_policy()

    with pytest.raises(
        ValueError,
        match="cancellation_grace_s",
    ):
        RequestTimeoutMiddleware(
            _successful_app,
            timeout_policy=policy,
            cancellation_grace_s=-0.1,
        )

    with pytest.raises(
        ValueError,
        match="cancellation_grace_s",
    ):
        RequestTimeoutMiddleware(
            _successful_app,
            timeout_policy=policy,
            cancellation_grace_s=float("inf"),
        )

    with pytest.raises(
        ValueError,
        match="cancellation_grace_s",
    ):
        RequestTimeoutMiddleware(
            _successful_app,
            timeout_policy=policy,
            cancellation_grace_s=True,
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
            "status": "completed",
            "method": scope.get("method"),
            "path": scope.get("path"),
        },
    )


@pytest.mark.anyio
async def test_protected_request_completes_before_deadline() -> None:
    state = ResilienceState()

    middleware = RequestTimeoutMiddleware(
        _successful_app,
        timeout_policy=_build_policy(
            timeout_s=0.5
        ),
        resilience_state=state,
    )

    status_code, headers, body, _ = await _request(
        middleware
    )

    payload = _json_body(body)

    assert status_code == 200
    assert payload["status"] == "completed"
    assert payload["path"] == "/slow"

    assert (
        headers["x-cityroute-timeout-enforced"]
        == "true"
    )
    assert (
        headers["x-cityroute-timeout-category"]
        == "route"
    )
    assert (
        float(
            headers["x-cityroute-timeout-limit-s"]
        )
        == 0.5
    )

    snapshot = await state.snapshot()

    assert snapshot.timed_out_requests == 0
    assert snapshot.last_timeout_endpoint is None


@pytest.mark.anyio
async def test_unprotected_endpoint_bypasses_timeout() -> None:
    middleware = RequestTimeoutMiddleware(
        _successful_app,
        timeout_policy=_build_policy(),
    )

    status_code, headers, body, _ = await _request(
        middleware,
        path="/health/live",
    )

    payload = _json_body(body)

    assert status_code == 200
    assert payload["status"] == "completed"
    assert "x-cityroute-timeout-enforced" not in headers
    assert "x-cityroute-timeout-limit-s" not in headers
    assert "x-cityroute-timeout-category" not in headers


@pytest.mark.anyio
async def test_disabled_timeout_rule_bypasses_enforcement() -> None:
    async def slow_app(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        del scope
        del receive

        await asyncio.sleep(0.02)
        await _send_json(send)

    middleware = RequestTimeoutMiddleware(
        slow_app,
        timeout_policy=_build_policy(
            timeout_s=None
        ),
    )

    status_code, headers, body, _ = await _request(
        middleware
    )

    assert status_code == 200
    assert _json_body(body)["status"] == "ok"
    assert "x-cityroute-timeout-enforced" not in headers


@pytest.mark.anyio
async def test_timeout_returns_controlled_504() -> None:
    state = ResilienceState()

    async def slow_app(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        del scope
        del receive
        del send

        await asyncio.sleep(1.0)

    middleware = RequestTimeoutMiddleware(
        slow_app,
        timeout_policy=_build_policy(
            timeout_s=0.02
        ),
        resilience_state=state,
    )

    status_code, headers, body, _ = await _request(
        middleware
    )

    payload = _json_body(body)
    detail = payload["detail"]

    assert status_code == 504

    assert (
        headers["x-cityroute-timeout-enforced"]
        == "true"
    )
    assert (
        headers["x-cityroute-timeout-category"]
        == "route"
    )
    assert float(
        headers["x-cityroute-timeout-limit-s"]
    ) == pytest.approx(0.02)

    assert detail["error"] == "request_timeout"
    assert detail["endpoint"] == "/slow"
    assert detail["method"] == "GET"
    assert detail["category"] == "route"
    assert detail["timeout_s"] == pytest.approx(0.02)
    assert detail["task_cancelled_cleanly"] is True

    snapshot = await state.snapshot()

    assert snapshot.timed_out_requests == 1
    assert snapshot.last_timeout_endpoint == "/slow"


@pytest.mark.anyio
async def test_timeout_works_without_resilience_state() -> None:
    async def slow_app(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        del scope
        del receive
        del send

        await asyncio.sleep(1.0)

    middleware = RequestTimeoutMiddleware(
        slow_app,
        timeout_policy=_build_policy(
            timeout_s=0.01
        ),
        resilience_state=None,
    )

    status_code, _, body, _ = await _request(
        middleware
    )

    assert status_code == 504
    assert (
        _json_body(body)["detail"]["error"]
        == "request_timeout"
    )


@pytest.mark.anyio
async def test_timeout_policy_is_method_specific() -> None:
    async def slow_app(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        del scope
        del receive

        await asyncio.sleep(0.02)
        await _send_json(send)

    middleware = RequestTimeoutMiddleware(
        slow_app,
        timeout_policy=_build_policy(
            method="GET",
            timeout_s=0.001,
        ),
    )

    status_code, headers, body, _ = await _request(
        middleware,
        method="POST",
    )

    assert status_code == 200
    assert _json_body(body)["status"] == "ok"
    assert "x-cityroute-timeout-enforced" not in headers


@pytest.mark.anyio
async def test_trailing_slash_is_normalized() -> None:
    async def slow_app(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        del scope
        del receive
        del send

        await asyncio.sleep(1.0)

    middleware = RequestTimeoutMiddleware(
        slow_app,
        timeout_policy=_build_policy(
            path="/slow",
            timeout_s=0.01,
        ),
    )

    status_code, _, body, _ = await _request(
        middleware,
        path="/slow/",
    )

    assert status_code == 504
    assert (
        _json_body(body)["detail"]["endpoint"]
        == "/slow"
    )


@pytest.mark.anyio
async def test_timeout_headers_can_be_disabled() -> None:
    middleware = RequestTimeoutMiddleware(
        _successful_app,
        timeout_policy=_build_policy(
            timeout_s=0.5
        ),
        emit_timeout_headers=False,
    )

    status_code, headers, _, _ = await _request(
        middleware
    )

    assert status_code == 200
    assert "x-cityroute-timeout-enforced" not in headers
    assert "x-cityroute-timeout-limit-s" not in headers
    assert "x-cityroute-timeout-category" not in headers


@pytest.mark.anyio
async def test_application_exception_propagates() -> None:
    async def failing_app(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        del scope
        del receive
        del send

        raise RuntimeError("endpoint failure")

    state = ResilienceState()

    middleware = RequestTimeoutMiddleware(
        failing_app,
        timeout_policy=_build_policy(
            timeout_s=1.0
        ),
        resilience_state=state,
    )

    with pytest.raises(
        RuntimeError,
        match="endpoint failure",
    ):
        await _request(middleware)

    snapshot = await state.snapshot()

    assert snapshot.timed_out_requests == 0
    assert snapshot.last_timeout_endpoint is None


@pytest.mark.anyio
async def test_started_response_is_terminated_not_replaced() -> None:
    state = ResilienceState()
    response_started = asyncio.Event()

    async def partial_response_app(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        del scope
        del receive

        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (
                        b"content-type",
                        b"application/json",
                    ),
                ],
            }
        )

        response_started.set()
        await asyncio.sleep(1.0)

    middleware = RequestTimeoutMiddleware(
        partial_response_app,
        timeout_policy=_build_policy(
            timeout_s=0.02
        ),
        resilience_state=state,
    )

    status_code, headers, body, messages = await _request(
        middleware
    )

    assert response_started.is_set()
    assert status_code == 200
    assert body == b""

    assert (
        headers["x-cityroute-timeout-enforced"]
        == "true"
    )

    response_start_messages = [
        message
        for message in messages
        if message["type"] == "http.response.start"
    ]

    assert len(response_start_messages) == 1
    assert response_start_messages[0]["status"] == 200

    response_body_messages = [
        message
        for message in messages
        if message["type"] == "http.response.body"
    ]

    assert response_body_messages[-1]["body"] == b""
    assert (
        response_body_messages[-1]["more_body"]
        is False
    )

    snapshot = await state.snapshot()

    assert snapshot.timed_out_requests == 1


@pytest.mark.anyio
async def test_completed_response_is_preserved_when_background_work_times_out(
) -> None:
    state = ResilienceState()

    async def response_then_background_work(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        del scope
        del receive

        await _send_json(
            send,
            content={"status": "response-sent"},
        )

        await asyncio.sleep(1.0)

    middleware = RequestTimeoutMiddleware(
        response_then_background_work,
        timeout_policy=_build_policy(
            timeout_s=0.02
        ),
        resilience_state=state,
    )

    status_code, _, body, messages = await _request(
        middleware
    )

    assert status_code == 200
    assert (
        _json_body(body)["status"]
        == "response-sent"
    )

    response_start_messages = [
        message
        for message in messages
        if message["type"] == "http.response.start"
    ]

    assert len(response_start_messages) == 1

    snapshot = await state.snapshot()

    assert snapshot.timed_out_requests == 1
    assert snapshot.last_timeout_endpoint == "/slow"


@pytest.mark.anyio
async def test_stubborn_task_is_detached_and_late_send_is_blocked(
) -> None:
    cleanup_finished = asyncio.Event()

    async def cancellation_resistant_app(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        del scope
        del receive

        try:
            await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            await asyncio.sleep(0.05)

            await _send_json(
                send,
                content={
                    "status": "late-response",
                },
            )

            cleanup_finished.set()

    middleware = RequestTimeoutMiddleware(
        cancellation_resistant_app,
        timeout_policy=_build_policy(
            timeout_s=0.01
        ),
        cancellation_grace_s=0.001,
    )

    status_code, _, body, messages = await _request(
        middleware
    )

    payload = _json_body(body)

    assert status_code == 504
    assert (
        payload["detail"]["task_cancelled_cleanly"]
        is False
    )

    await asyncio.wait_for(
        cleanup_finished.wait(),
        timeout=1.0,
    )

    response_start_messages = [
        message
        for message in messages
        if message["type"] == "http.response.start"
    ]

    # The late application response must be discarded.
    assert len(response_start_messages) == 1
    assert response_start_messages[0]["status"] == 504


@pytest.mark.anyio
async def test_outer_cancellation_cancels_application_task() -> None:
    application_started = asyncio.Event()
    application_finished = asyncio.Event()

    async def cancellable_app(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        del scope
        del receive
        del send

        application_started.set()

        try:
            await asyncio.sleep(10.0)
        finally:
            application_finished.set()

    state = ResilienceState()

    middleware = RequestTimeoutMiddleware(
        cancellable_app,
        timeout_policy=_build_policy(
            timeout_s=30.0
        ),
        resilience_state=state,
    )

    request_task = asyncio.create_task(
        _request(middleware)
    )

    await asyncio.wait_for(
        application_started.wait(),
        timeout=1.0,
    )

    request_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await request_task

    await asyncio.wait_for(
        application_finished.wait(),
        timeout=1.0,
    )

    snapshot = await state.snapshot()

    assert snapshot.timed_out_requests == 0
    assert snapshot.last_timeout_endpoint is None


@pytest.mark.anyio
async def test_non_http_scope_bypasses_timeout_policy() -> None:
    called = False

    async def websocket_app(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        nonlocal called

        del receive
        del send

        called = True
        assert scope["type"] == "websocket"

    middleware = RequestTimeoutMiddleware(
        websocket_app,
        timeout_policy=_build_policy(
            timeout_s=0.001
        ),
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
            "path": "/slow",
            "raw_path": b"/slow",
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