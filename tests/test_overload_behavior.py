# tests/test_overload_behavior.py

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
from app.middleware.lifecycle_guard import (
    LifecycleGuardMiddleware,
)


@pytest.fixture
def anyio_backend() -> str:
    """Run overload tests using asyncio."""

    return "asyncio"


class OverloadTestApp:
    """
    Minimal application used to create deterministic request saturation.

    Requests to protected routing endpoints wait until `release_routes` is
    set. Operational endpoints execute immediately.
    """

    def __init__(self) -> None:
        self.release_routes = asyncio.Event()
        self.route_call_count = 0
        self.operational_call_count = 0

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        del receive

        path = str(scope.get("path", "/"))

        if path == "/route":
            self.route_call_count += 1
            await self.release_routes.wait()
        else:
            self.operational_call_count += 1

        await _send_json(
            send,
            content={
                "status": "executed",
                "path": path,
                "method": scope.get("method"),
            },
        )


async def _send_json(
    send: Send,
    *,
    status_code: int = 200,
    content: dict[str, Any],
) -> None:
    body = json.dumps(content).encode()

    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
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

    response_body = b"".join(
        message.get("body", b"")
        for message in sent_messages
        if message["type"] == "http.response.body"
    )

    headers = {
        key.decode().lower(): value.decode()
        for key, value in response_start.get("headers", [])
    }

    payload: dict[str, Any]

    if response_body:
        payload = json.loads(response_body)
    else:
        payload = {}

    return (
        int(response_start["status"]),
        headers,
        payload,
    )


async def _initialize_ready_state(
    state: ResilienceState,
) -> None:
    await state.mark_startup_started()
    await state.set_graph_ready(True)
    await state.set_snap_index_ready(True)
    await state.set_dispatch_adjacency_ready(True)
    await state.mark_redis_success()
    await state.mark_startup_complete()


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
                "Limiter did not reach expected overload state: "
                f"expected active={active_requests}, "
                f"waiting={waiting_requests}; "
                f"actual active={snapshot.active_requests}, "
                f"waiting={snapshot.waiting_requests}"
            )

        await asyncio.sleep(0.001)


def _build_reliability_stack(
    app: ASGIApp,
    *,
    state: ResilienceState,
    limiter: ConcurrencyLimiter,
    wait_timeout_s: float | None = None,
    retry_after_s: int = 1,
) -> ASGIApp:
    """
    Build the Phase 11 middleware chain used by overload tests.

    Request order:

        lifecycle guard
            → concurrency admission
            → endpoint
    """

    concurrency_app = ConcurrencyControlMiddleware(
        app,
        limiter=limiter,
        resilience_state=state,
        wait_timeout_s=wait_timeout_s,
        retry_after_s=retry_after_s,
    )

    return LifecycleGuardMiddleware(
        concurrency_app,
        resilience_state=state,
    )


@pytest.mark.anyio
async def test_burst_is_bounded_by_active_and_waiting_limits() -> None:
    state = ResilienceState()
    await _initialize_ready_state(state)

    limiter = ConcurrencyLimiter(
        max_active_requests=2,
        max_waiting_requests=2,
        default_wait_timeout_s=1.0,
    )

    endpoint_app = OverloadTestApp()

    app = _build_reliability_stack(
        endpoint_app,
        state=state,
        limiter=limiter,
        retry_after_s=2,
    )

    active_tasks = [
        asyncio.create_task(_request(app))
        for _ in range(2)
    ]

    await _wait_for_limiter_state(
        limiter,
        active_requests=2,
        waiting_requests=0,
    )

    queued_tasks = [
        asyncio.create_task(_request(app))
        for _ in range(2)
    ]

    await _wait_for_limiter_state(
        limiter,
        active_requests=2,
        waiting_requests=2,
    )

    rejected_responses = await asyncio.gather(
        _request(app),
        _request(app),
    )

    for status_code, headers, payload in rejected_responses:
        assert status_code == 429
        assert headers["retry-after"] == "2"
        assert (
            headers["x-cityroute-rejection-reason"]
            == "queue_full"
        )

        detail = payload["detail"]

        assert detail["error"] == "request_overloaded"
        assert detail["reason"] == "queue_full"
        assert detail["capacity"] == {
            "max_active_requests": 2,
            "max_waiting_requests": 2,
            "active_requests": 2,
            "waiting_requests": 2,
        }

    endpoint_app.release_routes.set()

    accepted_responses = await asyncio.gather(
        *active_tasks,
        *queued_tasks,
    )

    assert [
        response[0]
        for response in accepted_responses
    ] == [200, 200, 200, 200]

    limiter_snapshot = await limiter.snapshot()
    state_snapshot = await state.snapshot()

    assert limiter_snapshot.active_requests == 0
    assert limiter_snapshot.waiting_requests == 0

    assert limiter_snapshot.max_observed_active_requests == 2
    assert limiter_snapshot.max_observed_waiting_requests == 2

    assert limiter_snapshot.total_admitted_requests == 4
    assert limiter_snapshot.total_released_requests == 4
    assert limiter_snapshot.total_rejected_requests == 2
    assert limiter_snapshot.queue_full_rejections == 2

    assert state_snapshot.active_requests == 0
    assert state_snapshot.completed_requests == 4
    assert state_snapshot.rejected_requests == 2
    assert state_snapshot.overload_events == 2
    assert state_snapshot.last_rejection_reason == "queue_full"


@pytest.mark.anyio
async def test_liveness_bypasses_saturation() -> None:
    state = ResilienceState()
    await _initialize_ready_state(state)

    limiter = ConcurrencyLimiter(
        max_active_requests=1,
        max_waiting_requests=1,
        default_wait_timeout_s=2.0,
    )

    endpoint_app = OverloadTestApp()

    app = _build_reliability_stack(
        endpoint_app,
        state=state,
        limiter=limiter,
    )

    active_task = asyncio.create_task(
        _request(app)
    )

    await _wait_for_limiter_state(
        limiter,
        active_requests=1,
        waiting_requests=0,
    )

    queued_task = asyncio.create_task(
        _request(app)
    )

    await _wait_for_limiter_state(
        limiter,
        active_requests=1,
        waiting_requests=1,
    )

    status_code, headers, payload = await _request(
        app,
        path="/health/live",
    )

    assert status_code == 200
    assert payload["status"] == "executed"
    assert payload["path"] == "/health/live"

    assert "x-cityroute-admission-queued" not in headers
    assert "x-cityroute-admission-wait-ms" not in headers

    saturated_snapshot = await limiter.snapshot()

    assert saturated_snapshot.active_requests == 1
    assert saturated_snapshot.waiting_requests == 1
    assert saturated_snapshot.total_rejected_requests == 0

    endpoint_app.release_routes.set()

    await asyncio.gather(
        active_task,
        queued_task,
    )

    limiter_snapshot = await limiter.snapshot()
    state_snapshot = await state.snapshot()

    # Only protected routing requests are counted by the limiter.
    assert limiter_snapshot.total_admitted_requests == 2
    assert limiter_snapshot.total_released_requests == 2

    assert state_snapshot.completed_requests == 2
    assert endpoint_app.operational_call_count == 1


@pytest.mark.anyio
async def test_waiting_request_receives_controlled_503_timeout() -> None:
    state = ResilienceState()
    await _initialize_ready_state(state)

    limiter = ConcurrencyLimiter(
        max_active_requests=1,
        max_waiting_requests=1,
        default_wait_timeout_s=1.0,
    )

    endpoint_app = OverloadTestApp()

    app = _build_reliability_stack(
        endpoint_app,
        state=state,
        limiter=limiter,
        wait_timeout_s=0.02,
    )

    active_task = asyncio.create_task(
        _request(app)
    )

    await _wait_for_limiter_state(
        limiter,
        active_requests=1,
    )

    timed_out_response = await _request(app)

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
    assert detail["capacity"]["active_requests"] == 1
    assert detail["capacity"]["waiting_requests"] == 0

    endpoint_app.release_routes.set()
    await active_task

    limiter_snapshot = await limiter.snapshot()
    state_snapshot = await state.snapshot()

    assert limiter_snapshot.active_requests == 0
    assert limiter_snapshot.waiting_requests == 0
    assert limiter_snapshot.wait_timeout_rejections == 1
    assert limiter_snapshot.total_rejected_requests == 1

    assert state_snapshot.rejected_requests == 1
    assert state_snapshot.overload_events == 1
    assert state_snapshot.last_rejection_reason == "wait_timeout"


@pytest.mark.anyio
async def test_startup_rejection_occurs_before_concurrency_admission() -> None:
    state = ResilienceState()

    limiter = ConcurrencyLimiter(
        max_active_requests=1,
        max_waiting_requests=1,
        default_wait_timeout_s=1.0,
    )

    endpoint_app = OverloadTestApp()

    app = _build_reliability_stack(
        endpoint_app,
        state=state,
        limiter=limiter,
    )

    status_code, headers, payload = await _request(app)

    assert status_code == 503
    assert (
        headers["x-cityroute-lifecycle-rejection-reason"]
        == "startup_incomplete"
    )
    assert payload["detail"]["reason"] == "startup_incomplete"

    limiter_snapshot = await limiter.snapshot()
    state_snapshot = await state.snapshot()

    assert limiter_snapshot.total_admitted_requests == 0
    assert limiter_snapshot.total_rejected_requests == 0

    assert state_snapshot.rejected_requests == 1
    assert (
        state_snapshot.last_rejection_reason
        == "startup_incomplete"
    )

    assert endpoint_app.route_call_count == 0


@pytest.mark.anyio
async def test_shutdown_rejection_does_not_consume_capacity() -> None:
    state = ResilienceState()
    await _initialize_ready_state(state)
    await state.begin_shutdown()

    limiter = ConcurrencyLimiter(
        max_active_requests=1,
        max_waiting_requests=1,
        default_wait_timeout_s=1.0,
    )

    endpoint_app = OverloadTestApp()

    app = _build_reliability_stack(
        endpoint_app,
        state=state,
        limiter=limiter,
    )

    status_code, headers, payload = await _request(app)

    assert status_code == 503
    assert (
        headers["x-cityroute-lifecycle-rejection-reason"]
        == "service_shutting_down"
    )

    detail = payload["detail"]

    assert detail["error"] == "service_unavailable"
    assert detail["reason"] == "service_shutting_down"
    assert detail["lifecycle"]["shutdown_requested"] is True
    assert detail["lifecycle"]["accepting_requests"] is False

    limiter_snapshot = await limiter.snapshot()
    state_snapshot = await state.snapshot()

    assert limiter_snapshot.active_requests == 0
    assert limiter_snapshot.waiting_requests == 0
    assert limiter_snapshot.total_admitted_requests == 0
    assert limiter_snapshot.total_rejected_requests == 0

    assert state_snapshot.rejected_requests == 1
    assert (
        state_snapshot.last_rejection_reason
        == "service_shutting_down"
    )

    assert endpoint_app.route_call_count == 0


@pytest.mark.anyio
async def test_service_recovers_after_queue_full_overload() -> None:
    state = ResilienceState()
    await _initialize_ready_state(state)

    limiter = ConcurrencyLimiter(
        max_active_requests=1,
        max_waiting_requests=1,
        default_wait_timeout_s=1.0,
    )

    endpoint_app = OverloadTestApp()

    app = _build_reliability_stack(
        endpoint_app,
        state=state,
        limiter=limiter,
    )

    active_task = asyncio.create_task(
        _request(app)
    )

    await _wait_for_limiter_state(
        limiter,
        active_requests=1,
        waiting_requests=0,
    )

    queued_task = asyncio.create_task(
        _request(app)
    )

    await _wait_for_limiter_state(
        limiter,
        active_requests=1,
        waiting_requests=1,
    )

    overloaded_response = await _request(app)

    assert overloaded_response[0] == 429
    assert (
        overloaded_response[2]["detail"]["reason"]
        == "queue_full"
    )

    endpoint_app.release_routes.set()

    first_response, second_response = await asyncio.gather(
        active_task,
        queued_task,
    )

    assert first_response[0] == 200
    assert second_response[0] == 200

    # Capacity must be reusable immediately after the burst drains.
    recovered_response = await _request(app)

    assert recovered_response[0] == 200
    assert recovered_response[2]["status"] == "executed"

    limiter_snapshot = await limiter.snapshot()
    state_snapshot = await state.snapshot()

    assert limiter_snapshot.active_requests == 0
    assert limiter_snapshot.waiting_requests == 0

    assert limiter_snapshot.total_admitted_requests == 3
    assert limiter_snapshot.total_released_requests == 3
    assert limiter_snapshot.total_rejected_requests == 1

    assert state_snapshot.active_requests == 0
    assert state_snapshot.completed_requests == 3
    assert state_snapshot.rejected_requests == 1
    assert state_snapshot.overload_events == 1