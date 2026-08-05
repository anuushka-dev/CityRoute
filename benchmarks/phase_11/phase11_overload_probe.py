# benchmarks/phase_11/phase11_overload_probe.py

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

# Support both:
#   python benchmarks/phase_11/phase11_overload_probe.py
#   python -m benchmarks.phase_11.phase11_overload_probe
PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.phase_11.phase11_common import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT_S,
    PROJECT_PHASE_CODE,
    PROJECT_PHASE_NAME,
    build_result_path,
    collect_runtime_metadata,
    percentile,
    print_json,
    timestamp_slug,
    utc_now_iso,
    wait_for_liveness,
    wait_for_readiness,
    write_json,
)


DEFAULT_ROUNDS = 3
DEFAULT_MATRIX_SIZE = 25
DEFAULT_MONITOR_INTERVAL_S = 0.025
DEFAULT_RECOVERY_TIMEOUT_S = 15.0

SUCCESS_STATUS_CODES = {200}
CONTROLLED_OVERLOAD_STATUS_CODES = {429, 503}

GAUGE_METRICS = (
    "cityroute_active_requests",
    "cityroute_waiting_requests",
    "cityroute_max_active_requests",
    "cityroute_max_waiting_requests",
    "cityroute_readiness",
    "cityroute_accepting_requests",
    "cityroute_redis_available",
    "cityroute_graceful_shutdown_inflight",
)

COUNTER_METRICS = (
    "cityroute_admission_decisions_total",
    "cityroute_request_rejections_total",
    "cityroute_overload_events_total",
)


@dataclass(frozen=True)
class MetricObservation:
    declared: bool
    sample_count: int
    total: float | None


@dataclass(frozen=True)
class OverloadRequestResult:
    round_index: int
    request_index: int
    status_code: int | None
    outcome: str
    reason: str | None
    elapsed_ms: float
    admission_wait_ms: float | None
    retry_after: str | None
    response_headers: dict[str, str]
    response_summary: Any | None
    validation_errors: tuple[str, ...]
    error_type: str | None
    error_message: str | None
    started_at_utc: str
    finished_at_utc: str


@dataclass(frozen=True)
class MonitorSample:
    round_index: int
    captured_at_utc: str
    elapsed_from_round_start_ms: float
    metrics_status_code: int | None
    gauges: dict[str, float | None]
    counters: dict[str, MetricObservation]
    liveness_status_code: int | None
    liveness_json: Any | None
    readiness_status_code: int | None
    readiness_json: Any | None
    validation_errors: tuple[str, ...]
    error_type: str | None
    error_message: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate sustained Phase 11 overload and prove that CityRoute "
            "rejects excess work in a controlled, bounded, observable way "
            "without losing liveness, readiness, or post-load recovery."
        )
    )

    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=(
            "CityRoute API base URL. "
            f"Default: {DEFAULT_BASE_URL}"
        ),
    )
    parser.add_argument(
        "--target",
        choices=("docker", "local"),
        default=None,
        help=(
            "Standard Phase 11 result directory. When omitted, "
            "CITYROUTE_BENCHMARK_RESULT_TARGET is used."
        ),
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=None,
        help=(
            "Explicit output directory. Overrides --target when provided."
        ),
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=None,
        help=(
            "Concurrent requests per overload round. Default: two times "
            "the configured active + waiting capacity."
        ),
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=DEFAULT_ROUNDS,
        help=(
            "Number of overload bursts. "
            f"Default: {DEFAULT_ROUNDS}"
        ),
    )
    parser.add_argument(
        "--matrix-size",
        type=int,
        default=DEFAULT_MATRIX_SIZE,
        help=(
            "Locations in each uncached /matrix request. "
            f"Default: {DEFAULT_MATRIX_SIZE}"
        ),
    )
    parser.add_argument(
        "--algorithm",
        choices=(
            "source_dijkstra",
            "bidirectional_astar",
            "astar",
        ),
        default="source_dijkstra",
        help="Matrix algorithm used for load. Default: source_dijkstra",
    )
    parser.add_argument(
        "--use-cache",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Enable matrix caching. Disabled by default so the overload "
            "workload remains computationally meaningful."
        ),
    )
    parser.add_argument(
        "--payload-file",
        type=Path,
        default=None,
        help=(
            "Optional JSON object used as the /matrix request body. "
            "When omitted, a valid Kanpur Central payload is generated."
        ),
    )
    parser.add_argument(
        "--monitor-interval-s",
        type=float,
        default=DEFAULT_MONITOR_INTERVAL_S,
        help=(
            "Delay between overload-state samples. "
            f"Default: {DEFAULT_MONITOR_INTERVAL_S}"
        ),
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=max(DEFAULT_TIMEOUT_S, 60.0),
        help="Per-request client timeout in seconds. Default: 60",
    )
    parser.add_argument(
        "--startup-timeout-s",
        type=float,
        default=180.0,
        help="Maximum startup wait in seconds. Default: 180",
    )
    parser.add_argument(
        "--recovery-timeout-s",
        type=float,
        default=DEFAULT_RECOVERY_TIMEOUT_S,
        help=(
            "Maximum wait for active and waiting gauges to return to zero. "
            f"Default: {DEFAULT_RECOVERY_TIMEOUT_S}"
        ),
    )
    parser.add_argument(
        "--require-queue-full",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Require at least one HTTP 429 queue_full rejection. "
            "Default: enabled."
        ),
    )
    parser.add_argument(
        "--require-wait-timeout",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Require at least one HTTP 503 wait_timeout rejection. "
            "Default: enabled."
        ),
    )
    parser.add_argument(
        "--require-counter-evidence",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Fail when overload counter series are absent or do not "
            "increase. Disabled by default because the HTTP contract and "
            "bounded gauges remain authoritative evidence."
        ),
    )
    parser.add_argument(
        "--fail-on-validation-error",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Exit non-zero when overload behavior fails validation. "
            "Default: enabled."
        ),
    )

    args = parser.parse_args()

    if args.requests is not None and args.requests <= 0:
        parser.error("--requests must be greater than zero")

    if args.rounds <= 0:
        parser.error("--rounds must be greater than zero")

    if not 2 <= args.matrix_size <= 25:
        parser.error("--matrix-size must be between 2 and 25")

    if args.monitor_interval_s <= 0:
        parser.error("--monitor-interval-s must be greater than zero")

    if args.timeout_s <= 0:
        parser.error("--timeout-s must be greater than zero")

    if args.startup_timeout_s <= 0:
        parser.error("--startup-timeout-s must be greater than zero")

    if args.recovery_timeout_s <= 0:
        parser.error("--recovery-timeout-s must be greater than zero")

    return args


def _load_payload_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise ValueError("--payload-file must contain one JSON object")

    return payload


def _generated_locations(
    *,
    matrix_size: int,
    safe_variant: int = 0,
) -> list[dict[str, Any]]:
    """
    Generate points safely inside the configured central Kanpur bounding box.

    ``safe_variant`` is intentionally bounded. This avoids the previous
    benchmark bug where a very large uniqueness shift moved the recovery
    coordinate outside the graph and produced an unrelated HTTP 422.
    """

    center_lat = 26.4499
    center_lon = 80.3319
    spacing = 0.0016
    bounded_variant = safe_variant % 100
    shift = bounded_variant * 0.0000001

    locations: list[dict[str, Any]] = []

    for index in range(matrix_size):
        row, column = divmod(index, 5)

        locations.append(
            {
                "id": f"p{index:02d}",
                "lat": round(
                    center_lat
                    + ((row - 2) * spacing)
                    + shift,
                    7,
                ),
                "lon": round(
                    center_lon
                    + ((column - 2) * spacing)
                    - shift,
                    7,
                ),
            }
        )

    return locations


def _build_matrix_payload(
    *,
    matrix_size: int,
    algorithm: str,
    use_cache: bool,
    safe_variant: int,
    payload_template: dict[str, Any] | None,
) -> dict[str, Any]:
    if payload_template is not None:
        payload = json.loads(json.dumps(payload_template))
        payload["algorithm"] = algorithm
        payload["use_cache"] = use_cache
        return payload

    return {
        "locations": _generated_locations(
            matrix_size=matrix_size,
            safe_variant=safe_variant,
        ),
        "algorithm": algorithm,
        "use_cache": use_cache,
    }


def _parse_prometheus(
    text: str,
) -> tuple[
    dict[str, float | None],
    dict[str, MetricObservation],
]:
    declared_metrics: set[str] = set()
    samples: dict[str, list[float]] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if line.startswith("# TYPE "):
            parts = line.split()

            if len(parts) >= 3:
                declared_metrics.add(parts[2])

            continue

        if line.startswith("#"):
            continue

        sample_name, separator, raw_value = line.rpartition(" ")

        if not separator:
            continue

        metric_name = sample_name.split("{", 1)[0]

        try:
            value = float(raw_value)
        except ValueError:
            continue

        samples.setdefault(metric_name, []).append(value)

    gauges: dict[str, float | None] = {}

    for metric_name in GAUGE_METRICS:
        values = samples.get(metric_name, [])
        gauges[metric_name] = (
            sum(values)
            if values
            else None
        )

    counters: dict[str, MetricObservation] = {}

    for metric_name in COUNTER_METRICS:
        values = samples.get(metric_name, [])
        counters[metric_name] = MetricObservation(
            declared=metric_name in declared_metrics,
            sample_count=len(values),
            total=sum(values) if values else None,
        )

    return gauges, counters


async def _fetch_metrics(
    client: httpx.AsyncClient,
    *,
    base_url: str,
) -> tuple[
    int | None,
    dict[str, float | None],
    dict[str, MetricObservation],
    str | None,
    str | None,
]:
    try:
        response = await client.get(f"{base_url}/metrics")
    except Exception as exc:
        return (
            None,
            {},
            {},
            type(exc).__name__,
            str(exc),
        )

    gauges, counters = _parse_prometheus(response.text)

    return (
        response.status_code,
        gauges,
        counters,
        None,
        None,
    )


def _summarize_json_response(
    *,
    status_code: int,
    response_json: Any,
    response_text: str,
) -> Any:
    if not isinstance(response_json, dict):
        return {
            "body_preview": response_text[:2000],
        }

    if status_code == 200:
        return {
            "status": response_json.get("status"),
            "n": response_json.get("n"),
            "algorithm": response_json.get("algorithm"),
            "pair_count": response_json.get("pair_count"),
            "computed_pairs": response_json.get("computed_pairs"),
            "failed_pairs": response_json.get("failed_pairs"),
            "generation_time_ms": response_json.get(
                "generation_time_ms"
            ),
            "parallel_workers": response_json.get(
                "parallel_workers"
            ),
            "cache": response_json.get("cache"),
        }

    return response_json


def _filtered_headers(
    response: httpx.Response,
) -> dict[str, str]:
    headers: dict[str, str] = {}

    for key, value in response.headers.items():
        normalized = key.lower()

        if (
            normalized.startswith("x-cityroute-")
            or normalized == "retry-after"
        ):
            headers[normalized] = value

    return headers


def _detail_object(response_json: Any) -> dict[str, Any] | None:
    if not isinstance(response_json, dict):
        return None

    detail = response_json.get("detail")

    return detail if isinstance(detail, dict) else None


def _reason_from_response(
    *,
    response_json: Any,
    headers: dict[str, str],
) -> str | None:
    header_reason = headers.get(
        "x-cityroute-rejection-reason"
    )

    if header_reason:
        return header_reason

    detail = _detail_object(response_json)

    if detail is None:
        return None

    reason = detail.get("reason")
    return reason if isinstance(reason, str) else None


def _float_header(
    headers: dict[str, str],
    name: str,
) -> float | None:
    raw_value = headers.get(name)

    if raw_value is None:
        return None

    try:
        return float(raw_value)
    except ValueError:
        return None


def _classify_outcome(
    *,
    status_code: int | None,
    reason: str | None,
) -> str:
    if status_code in SUCCESS_STATUS_CODES:
        return "accepted"

    if (
        status_code in CONTROLLED_OVERLOAD_STATUS_CODES
        and reason in {"queue_full", "wait_timeout"}
    ):
        return "controlled_overload"

    if status_code is None:
        return "client_error"

    return "unexpected_response"


def _validate_accepted_response(
    *,
    response_json: Any,
    matrix_size: int,
) -> list[str]:
    errors: list[str] = []

    if not isinstance(response_json, dict):
        return ["accepted response must be a JSON object"]

    if response_json.get("status") != "ok":
        errors.append("accepted response status must be 'ok'")

    if response_json.get("n") != matrix_size:
        errors.append(
            "accepted response matrix size mismatch: "
            f"{response_json.get('n')!r} != {matrix_size}"
        )

    if response_json.get("failed_pairs") not in {0, None}:
        errors.append(
            "accepted response contains failed matrix pairs"
        )

    return errors


def _validate_overload_response(
    *,
    status_code: int,
    reason: str | None,
    response_json: Any,
    headers: dict[str, str],
    configured_max_active: int,
    configured_max_waiting: int,
) -> list[str]:
    errors: list[str] = []

    expected_status = {
        "queue_full": 429,
        "wait_timeout": 503,
    }.get(reason)

    if expected_status is None:
        errors.append(
            f"unsupported overload reason: {reason!r}"
        )
    elif status_code != expected_status:
        errors.append(
            f"{reason} must return HTTP {expected_status}, "
            f"got {status_code}"
        )

    detail = _detail_object(response_json)

    if detail is None:
        return errors + [
            "overload response detail must be a JSON object"
        ]

    if detail.get("error") != "request_overloaded":
        errors.append(
            "overload detail.error must be 'request_overloaded'"
        )

    if detail.get("reason") != reason:
        errors.append(
            "overload body reason does not match rejection reason"
        )

    if detail.get("endpoint") != "/matrix":
        errors.append(
            "overload detail.endpoint must be '/matrix'"
        )

    if detail.get("method") != "POST":
        errors.append(
            "overload detail.method must be 'POST'"
        )

    body_waited_ms = detail.get("waited_ms")

    if (
        not isinstance(body_waited_ms, int | float)
        or body_waited_ms < 0
    ):
        errors.append(
            "overload detail.waited_ms must be non-negative"
        )

    header_reason = headers.get(
        "x-cityroute-rejection-reason"
    )

    if header_reason != reason:
        errors.append(
            "x-cityroute-rejection-reason does not match body"
        )

    admission_wait_ms = _float_header(
        headers,
        "x-cityroute-admission-wait-ms",
    )

    if admission_wait_ms is None or admission_wait_ms < 0:
        errors.append(
            "x-cityroute-admission-wait-ms is missing or invalid"
        )

    retry_after = headers.get("retry-after")

    if retry_after is None:
        errors.append("Retry-After header is missing")
    else:
        try:
            if float(retry_after) < 0:
                errors.append(
                    "Retry-After header must be non-negative"
                )
        except ValueError:
            errors.append(
                "Retry-After header must be numeric"
            )

    capacity = detail.get("capacity")

    if not isinstance(capacity, dict):
        errors.append(
            "overload detail.capacity must be an object"
        )
        return errors

    active_requests = capacity.get("active_requests")
    waiting_requests = capacity.get("waiting_requests")
    max_active_requests = capacity.get(
        "max_active_requests"
    )
    max_waiting_requests = capacity.get(
        "max_waiting_requests"
    )

    if max_active_requests != configured_max_active:
        errors.append(
            "response max_active_requests differs from configured "
            "capacity"
        )

    if max_waiting_requests != configured_max_waiting:
        errors.append(
            "response max_waiting_requests differs from configured "
            "capacity"
        )

    if (
        not isinstance(active_requests, int | float)
        or active_requests < 0
        or active_requests > configured_max_active
    ):
        errors.append(
            "response active_requests violates configured bound"
        )

    if (
        not isinstance(waiting_requests, int | float)
        or waiting_requests < 0
        or waiting_requests > configured_max_waiting
    ):
        errors.append(
            "response waiting_requests violates configured bound"
        )

    if (
        reason == "queue_full"
        and (
            active_requests != configured_max_active
            or waiting_requests != configured_max_waiting
        )
    ):
        errors.append(
            "queue_full must report both active and waiting "
            "capacity saturated"
        )

    return errors


async def _execute_request(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    start_event: asyncio.Event,
    round_index: int,
    request_index: int,
    matrix_size: int,
    payload: dict[str, Any],
) -> OverloadRequestResult:
    await start_event.wait()

    started_at_utc = utc_now_iso()
    started = time.perf_counter()

    status_code: int | None = None
    response_json: Any | None = None
    response_text = ""
    response_headers: dict[str, str] = {}
    reason: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    validation_errors: list[str] = []

    try:
        response = await client.post(
            f"{base_url}/matrix",
            json=payload,
        )
        status_code = response.status_code
        response_text = response.text
        response_headers = _filtered_headers(response)

        try:
            response_json = response.json()
        except ValueError:
            response_json = None

        reason = _reason_from_response(
            response_json=response_json,
            headers=response_headers,
        )

        if status_code == 200:
            validation_errors.extend(
                _validate_accepted_response(
                    response_json=response_json,
                    matrix_size=matrix_size,
                )
            )
    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    outcome = _classify_outcome(
        status_code=status_code,
        reason=reason,
    )

    return OverloadRequestResult(
        round_index=round_index,
        request_index=request_index,
        status_code=status_code,
        outcome=outcome,
        reason=reason,
        elapsed_ms=(
            time.perf_counter() - started
        )
        * 1000.0,
        admission_wait_ms=_float_header(
            response_headers,
            "x-cityroute-admission-wait-ms",
        ),
        retry_after=response_headers.get("retry-after"),
        response_headers=response_headers,
        response_summary=(
            None
            if status_code is None
            else _summarize_json_response(
                status_code=status_code,
                response_json=response_json,
                response_text=response_text,
            )
        ),
        validation_errors=tuple(validation_errors),
        error_type=error_type,
        error_message=error_message,
        started_at_utc=started_at_utc,
        finished_at_utc=utc_now_iso(),
    )


async def _sample_monitor_state(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    round_index: int,
    round_started: float,
) -> MonitorSample:
    captured_at_utc = utc_now_iso()
    validation_errors: list[str] = []
    error_type: str | None = None
    error_message: str | None = None

    (
        metrics_status_code,
        gauges,
        counters,
        metrics_error_type,
        metrics_error_message,
    ) = await _fetch_metrics(
        client,
        base_url=base_url,
    )

    if metrics_status_code != 200:
        validation_errors.append(
            "metrics endpoint was unavailable during overload"
        )

    if metrics_error_type is not None:
        error_type = metrics_error_type
        error_message = metrics_error_message

    liveness_status_code: int | None = None
    liveness_json: Any | None = None

    try:
        response = await client.get(
            f"{base_url}/health/live",
        )
        liveness_status_code = response.status_code

        try:
            liveness_json = response.json()
        except ValueError:
            liveness_json = None
    except Exception as exc:
        validation_errors.append(
            "liveness request failed during overload"
        )
        error_type = type(exc).__name__
        error_message = str(exc)

    if (
        liveness_status_code != 200
        or not isinstance(liveness_json, dict)
        or liveness_json.get("status") != "alive"
    ):
        validation_errors.append(
            "liveness was not healthy during overload"
        )

    readiness_status_code: int | None = None
    readiness_json: Any | None = None

    try:
        response = await client.get(
            f"{base_url}/health/ready",
        )
        readiness_status_code = response.status_code

        try:
            readiness_json = response.json()
        except ValueError:
            readiness_json = None
    except Exception as exc:
        validation_errors.append(
            "readiness request failed during overload"
        )
        error_type = type(exc).__name__
        error_message = str(exc)

    if (
        readiness_status_code != 200
        or not isinstance(readiness_json, dict)
        or readiness_json.get("ready") is not True
        or readiness_json.get("accepting_requests") is not True
        or readiness_json.get("shutting_down") is not False
    ):
        validation_errors.append(
            "readiness was not healthy during overload"
        )

    active = gauges.get("cityroute_active_requests")
    waiting = gauges.get("cityroute_waiting_requests")
    max_active = gauges.get(
        "cityroute_max_active_requests"
    )
    max_waiting = gauges.get(
        "cityroute_max_waiting_requests"
    )

    if (
        active is not None
        and max_active is not None
        and active > max_active
    ):
        validation_errors.append(
            "active request gauge exceeded configured maximum"
        )

    if (
        waiting is not None
        and max_waiting is not None
        and waiting > max_waiting
    ):
        validation_errors.append(
            "waiting request gauge exceeded configured maximum"
        )

    return MonitorSample(
        round_index=round_index,
        captured_at_utc=captured_at_utc,
        elapsed_from_round_start_ms=(
            time.perf_counter() - round_started
        )
        * 1000.0,
        metrics_status_code=metrics_status_code,
        gauges=gauges,
        counters=counters,
        liveness_status_code=liveness_status_code,
        liveness_json=liveness_json,
        readiness_status_code=readiness_status_code,
        readiness_json=readiness_json,
        validation_errors=tuple(validation_errors),
        error_type=error_type,
        error_message=error_message,
    )


async def _monitor_round(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    round_index: int,
    round_started: float,
    stop_event: asyncio.Event,
    interval_s: float,
) -> list[MonitorSample]:
    samples: list[MonitorSample] = []

    while not stop_event.is_set():
        samples.append(
            await _sample_monitor_state(
                client=client,
                base_url=base_url,
                round_index=round_index,
                round_started=round_started,
            )
        )

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=interval_s,
            )
        except TimeoutError:
            pass

    samples.append(
        await _sample_monitor_state(
            client=client,
            base_url=base_url,
            round_index=round_index,
            round_started=round_started,
        )
    )

    return samples


async def _run_overload_round(
    *,
    load_client: httpx.AsyncClient,
    monitor_client: httpx.AsyncClient,
    base_url: str,
    round_index: int,
    request_count: int,
    matrix_size: int,
    algorithm: str,
    use_cache: bool,
    payload_template: dict[str, Any] | None,
    configured_max_active: int,
    configured_max_waiting: int,
    monitor_interval_s: float,
) -> dict[str, Any]:
    start_event = asyncio.Event()
    stop_event = asyncio.Event()
    round_started = time.perf_counter()

    request_tasks: list[
        asyncio.Task[OverloadRequestResult]
    ] = []

    for request_index in range(request_count):
        payload = _build_matrix_payload(
            matrix_size=matrix_size,
            algorithm=algorithm,
            use_cache=use_cache,
            safe_variant=(
                (round_index * request_count)
                + request_index
            ),
            payload_template=payload_template,
        )

        request_tasks.append(
            asyncio.create_task(
                _execute_request(
                    client=load_client,
                    base_url=base_url,
                    start_event=start_event,
                    round_index=round_index,
                    request_index=request_index,
                    matrix_size=matrix_size,
                    payload=payload,
                )
            )
        )

    monitor_task = asyncio.create_task(
        _monitor_round(
            client=monitor_client,
            base_url=base_url,
            round_index=round_index,
            round_started=round_started,
            stop_event=stop_event,
            interval_s=monitor_interval_s,
        )
    )

    await asyncio.sleep(0)
    start_event.set()

    request_results = await asyncio.gather(*request_tasks)
    stop_event.set()
    monitor_samples = await monitor_task

    validated_results: list[OverloadRequestResult] = []

    for result in request_results:
        errors = list(result.validation_errors)

        if (
            result.outcome == "controlled_overload"
            and result.status_code is not None
        ):
            errors.extend(
                _validate_overload_response(
                    status_code=result.status_code,
                    reason=result.reason,
                    response_json=result.response_summary,
                    headers=result.response_headers,
                    configured_max_active=(
                        configured_max_active
                    ),
                    configured_max_waiting=(
                        configured_max_waiting
                    ),
                )
            )

        validated_results.append(
            OverloadRequestResult(
                **{
                    **asdict(result),
                    "validation_errors": tuple(errors),
                }
            )
        )

    return {
        "round_index": round_index,
        "elapsed_ms": (
            time.perf_counter() - round_started
        )
        * 1000.0,
        "request_results": validated_results,
        "monitor_samples": monitor_samples,
    }


def _latency_summary(
    values: list[float],
) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "min_ms": None,
            "max_ms": None,
            "mean_ms": None,
            "median_ms": None,
            "p90_ms": None,
            "p95_ms": None,
            "p99_ms": None,
        }

    return {
        "count": len(values),
        "min_ms": min(values),
        "max_ms": max(values),
        "mean_ms": statistics.fmean(values),
        "median_ms": statistics.median(values),
        "p90_ms": percentile(values, 90.0),
        "p95_ms": percentile(values, 95.0),
        "p99_ms": percentile(values, 99.0),
    }


def _metric_peak(
    samples: list[MonitorSample],
    metric_name: str,
) -> float | None:
    values = [
        sample.gauges.get(metric_name)
        for sample in samples
        if sample.gauges.get(metric_name) is not None
    ]

    return max(values) if values else None


def _metric_minimum(
    samples: list[MonitorSample],
    metric_name: str,
) -> float | None:
    values = [
        sample.gauges.get(metric_name)
        for sample in samples
        if sample.gauges.get(metric_name) is not None
    ]

    return min(values) if values else None


def _counter_delta(
    before: MetricObservation | None,
    after: MetricObservation | None,
) -> float | None:
    if (
        before is None
        or after is None
        or before.total is None
        or after.total is None
    ):
        return None

    return after.total - before.total


async def _wait_for_idle_recovery(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    timeout_s: float,
    poll_interval_s: float = 0.05,
) -> dict[str, Any]:
    deadline = time.perf_counter() + timeout_s
    samples: list[dict[str, Any]] = []

    while True:
        (
            metrics_status_code,
            gauges,
            counters,
            error_type,
            error_message,
        ) = await _fetch_metrics(
            client,
            base_url=base_url,
        )

        sample = {
            "captured_at_utc": utc_now_iso(),
            "metrics_status_code": metrics_status_code,
            "gauges": gauges,
            "counters": {
                key: asdict(value)
                for key, value in counters.items()
            },
            "error_type": error_type,
            "error_message": error_message,
        }
        samples.append(sample)

        active = gauges.get("cityroute_active_requests")
        waiting = gauges.get("cityroute_waiting_requests")

        if (
            metrics_status_code == 200
            and active == 0.0
            and waiting == 0.0
        ):
            return {
                "recovered": True,
                "timed_out": False,
                "samples": samples,
                "final_gauges": gauges,
                "final_counters": counters,
            }

        if time.perf_counter() >= deadline:
            return {
                "recovered": False,
                "timed_out": True,
                "samples": samples,
                "final_gauges": gauges,
                "final_counters": counters,
            }

        await asyncio.sleep(poll_interval_s)


async def _recovery_probe(
    *,
    load_client: httpx.AsyncClient,
    monitor_client: httpx.AsyncClient,
    base_url: str,
    algorithm: str,
    payload_template: dict[str, Any] | None,
    recovery_timeout_s: float,
) -> dict[str, Any]:
    idle_recovery = await _wait_for_idle_recovery(
        client=monitor_client,
        base_url=base_url,
        timeout_s=recovery_timeout_s,
    )

    readiness_response = await monitor_client.get(
        f"{base_url}/health/ready"
    )

    try:
        readiness_json: Any | None = (
            readiness_response.json()
        )
    except ValueError:
        readiness_json = None

    liveness_response = await monitor_client.get(
        f"{base_url}/health/live"
    )

    try:
        liveness_json: Any | None = (
            liveness_response.json()
        )
    except ValueError:
        liveness_json = None

    # This uses a tiny, bounded variant and is guaranteed to remain inside
    # the loaded graph area.
    recovery_payload = _build_matrix_payload(
        matrix_size=5,
        algorithm=algorithm,
        use_cache=False,
        safe_variant=7,
        payload_template=payload_template,
    )

    started = time.perf_counter()
    matrix_response = await load_client.post(
        f"{base_url}/matrix",
        json=recovery_payload,
    )
    matrix_elapsed_ms = (
        time.perf_counter() - started
    ) * 1000.0

    try:
        matrix_json: Any | None = matrix_response.json()
    except ValueError:
        matrix_json = None

    return {
        "idle_recovery": {
            **idle_recovery,
            "final_counters": {
                key: asdict(value)
                for key, value in idle_recovery[
                    "final_counters"
                ].items()
            },
        },
        "readiness_status_code": readiness_response.status_code,
        "readiness_json": readiness_json,
        "liveness_status_code": liveness_response.status_code,
        "liveness_json": liveness_json,
        "matrix_status_code": matrix_response.status_code,
        "matrix_elapsed_ms": matrix_elapsed_ms,
        "matrix_response_summary": _summarize_json_response(
            status_code=matrix_response.status_code,
            response_json=matrix_json,
            response_text=matrix_response.text,
        ),
    }


def _validate_global_evidence(
    *,
    request_count: int,
    configured_max_active: int,
    configured_max_waiting: int,
    request_results: list[OverloadRequestResult],
    monitor_samples: list[MonitorSample],
    recovery: dict[str, Any],
    counter_deltas: dict[str, float | None],
    require_queue_full: bool,
    require_wait_timeout: bool,
    require_counter_evidence: bool,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    outcome_counts = Counter(
        result.outcome
        for result in request_results
    )
    reason_counts = Counter(
        result.reason
        for result in request_results
        if result.reason is not None
    )

    if outcome_counts["accepted"] <= 0:
        errors.append(
            "No request was accepted during overload"
        )

    if outcome_counts["client_error"] > 0:
        errors.append(
            f"{outcome_counts['client_error']} requests failed at "
            "the HTTP client layer"
        )

    if outcome_counts["unexpected_response"] > 0:
        errors.append(
            f"{outcome_counts['unexpected_response']} requests returned "
            "unexpected status/reason combinations"
        )

    if require_queue_full and reason_counts["queue_full"] <= 0:
        errors.append(
            "No queue_full HTTP 429 rejection was observed"
        )

    if (
        require_wait_timeout
        and reason_counts["wait_timeout"] <= 0
    ):
        errors.append(
            "No wait_timeout HTTP 503 rejection was observed"
        )

    bounded_capacity = (
        configured_max_active + configured_max_waiting
    )

    if (
        request_count > bounded_capacity
        and outcome_counts["controlled_overload"] <= 0
    ):
        errors.append(
            "The burst exceeded bounded capacity but produced no "
            "controlled overload responses"
        )

    request_validation_errors = [
        error
        for result in request_results
        for error in result.validation_errors
    ]

    errors.extend(request_validation_errors)

    monitor_validation_errors = [
        error
        for sample in monitor_samples
        for error in sample.validation_errors
    ]

    errors.extend(monitor_validation_errors)

    peak_active = _metric_peak(
        monitor_samples,
        "cityroute_active_requests",
    )
    peak_waiting = _metric_peak(
        monitor_samples,
        "cityroute_waiting_requests",
    )

    if peak_active is None:
        errors.append(
            "No active-request gauge samples were captured"
        )
    elif peak_active > configured_max_active:
        errors.append(
            "Active requests exceeded configured maximum"
        )

    if peak_waiting is None:
        errors.append(
            "No waiting-request gauge samples were captured"
        )
    elif peak_waiting > configured_max_waiting:
        errors.append(
            "Waiting requests exceeded configured maximum"
        )

    if (
        peak_active is not None
        and peak_waiting is not None
        and (
            peak_active + peak_waiting
            > bounded_capacity
        )
    ):
        errors.append(
            "Active + waiting work exceeded bounded capacity"
        )

    minimum_readiness = _metric_minimum(
        monitor_samples,
        "cityroute_readiness",
    )
    minimum_accepting = _metric_minimum(
        monitor_samples,
        "cityroute_accepting_requests",
    )

    if minimum_readiness != 1.0:
        errors.append(
            "Readiness metric dropped during overload"
        )

    if minimum_accepting != 1.0:
        errors.append(
            "Accepting-requests metric dropped during overload"
        )

    idle_recovery = recovery.get("idle_recovery", {})

    if idle_recovery.get("recovered") is not True:
        errors.append(
            "Active and waiting gauges did not return to zero"
        )

    readiness_json = recovery.get("readiness_json")

    if (
        recovery.get("readiness_status_code") != 200
        or not isinstance(readiness_json, dict)
        or readiness_json.get("ready") is not True
        or readiness_json.get("accepting_requests") is not True
        or readiness_json.get("shutting_down") is not False
    ):
        errors.append(
            "Readiness did not recover after overload"
        )

    liveness_json = recovery.get("liveness_json")

    if (
        recovery.get("liveness_status_code") != 200
        or not isinstance(liveness_json, dict)
        or liveness_json.get("status") != "alive"
    ):
        errors.append(
            "Liveness did not remain healthy after overload"
        )

    if recovery.get("matrix_status_code") != 200:
        errors.append(
            "Valid post-overload matrix request did not return HTTP 200"
        )

    rejection_delta = counter_deltas.get(
        "cityroute_request_rejections_total"
    )
    overload_delta = counter_deltas.get(
        "cityroute_overload_events_total"
    )

    if (
        outcome_counts["controlled_overload"] > 0
        and (
            rejection_delta is None
            or overload_delta is None
        )
    ):
        warning = (
            "Overload HTTP responses were proven, but labeled rejection "
            "or overload counter series were absent from /metrics."
        )

        if require_counter_evidence:
            errors.append(warning)
        else:
            warnings.append(warning)

    elif outcome_counts["controlled_overload"] > 0:
        if rejection_delta is not None and rejection_delta <= 0:
            message = (
                "Overload occurred but request rejection counter did not "
                "increase."
            )

            if require_counter_evidence:
                errors.append(message)
            else:
                warnings.append(message)

        if overload_delta is not None and overload_delta <= 0:
            message = (
                "Overload occurred but overload event counter did not "
                "increase."
            )

            if require_counter_evidence:
                errors.append(message)
            else:
                warnings.append(message)

    return errors, warnings


async def async_main(
    args: argparse.Namespace,
) -> int:
    base_url = args.base_url.rstrip("/")
    started_at_utc = utc_now_iso()

    startup_liveness = await asyncio.to_thread(
        wait_for_liveness,
        base_url=base_url,
        startup_timeout_s=args.startup_timeout_s,
    )
    startup_readiness = await asyncio.to_thread(
        wait_for_readiness,
        base_url=base_url,
        startup_timeout_s=args.startup_timeout_s,
        allow_degraded=True,
    )

    payload_template = (
        _load_payload_file(args.payload_file)
        if args.payload_file is not None
        else None
    )

    async with (
        httpx.AsyncClient(
            timeout=args.timeout_s,
            limits=httpx.Limits(
                max_connections=150,
                max_keepalive_connections=150,
            ),
        ) as load_client,
        httpx.AsyncClient(
            timeout=min(args.timeout_s, 10.0),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=20,
            ),
        ) as monitor_client,
    ):
        (
            baseline_metrics_status,
            baseline_gauges,
            baseline_counters,
            baseline_metrics_error_type,
            baseline_metrics_error_message,
        ) = await _fetch_metrics(
            monitor_client,
            base_url=base_url,
        )

        if baseline_metrics_status != 200:
            raise RuntimeError(
                "The /metrics endpoint must return HTTP 200 before "
                "overload probing"
            )

        max_active_value = baseline_gauges.get(
            "cityroute_max_active_requests"
        )
        max_waiting_value = baseline_gauges.get(
            "cityroute_max_waiting_requests"
        )

        if max_active_value is None or max_waiting_value is None:
            raise RuntimeError(
                "Concurrency capacity gauges are missing from /metrics"
            )

        configured_max_active = int(max_active_value)
        configured_max_waiting = int(max_waiting_value)
        configured_total_capacity = (
            configured_max_active + configured_max_waiting
        )

        request_count = args.requests

        if request_count is None:
            request_count = configured_total_capacity * 2

        if request_count <= configured_total_capacity:
            raise ValueError(
                "--requests must exceed configured active + waiting "
                "capacity for an overload probe"
            )

        preflight_payload = _build_matrix_payload(
            matrix_size=5,
            algorithm=args.algorithm,
            use_cache=False,
            safe_variant=1,
            payload_template=payload_template,
        )

        preflight_started = time.perf_counter()
        preflight_response = await load_client.post(
            f"{base_url}/matrix",
            json=preflight_payload,
        )
        preflight_elapsed_ms = (
            time.perf_counter() - preflight_started
        ) * 1000.0

        try:
            preflight_json: Any | None = (
                preflight_response.json()
            )
        except ValueError:
            preflight_json = None

        if preflight_response.status_code != 200:
            raise RuntimeError(
                "Valid matrix preflight failed: "
                f"status={preflight_response.status_code}, "
                f"response={preflight_response.text!r}"
            )

        rounds: list[dict[str, Any]] = []

        for round_index in range(args.rounds):
            rounds.append(
                await _run_overload_round(
                    load_client=load_client,
                    monitor_client=monitor_client,
                    base_url=base_url,
                    round_index=round_index,
                    request_count=request_count,
                    matrix_size=args.matrix_size,
                    algorithm=args.algorithm,
                    use_cache=args.use_cache,
                    payload_template=payload_template,
                    configured_max_active=(
                        configured_max_active
                    ),
                    configured_max_waiting=(
                        configured_max_waiting
                    ),
                    monitor_interval_s=(
                        args.monitor_interval_s
                    ),
                )
            )

            if round_index < args.rounds - 1:
                await asyncio.sleep(0.25)

        (
            after_metrics_status,
            after_gauges,
            after_counters,
            after_metrics_error_type,
            after_metrics_error_message,
        ) = await _fetch_metrics(
            monitor_client,
            base_url=base_url,
        )

        recovery = await _recovery_probe(
            load_client=load_client,
            monitor_client=monitor_client,
            base_url=base_url,
            algorithm=args.algorithm,
            payload_template=payload_template,
            recovery_timeout_s=args.recovery_timeout_s,
        )

    request_results = [
        result
        for round_result in rounds
        for result in round_result["request_results"]
    ]
    monitor_samples = [
        sample
        for round_result in rounds
        for sample in round_result["monitor_samples"]
    ]

    outcome_counts = Counter(
        result.outcome
        for result in request_results
    )
    status_counts = Counter(
        str(result.status_code)
        for result in request_results
    )
    reason_counts = Counter(
        result.reason
        for result in request_results
        if result.reason is not None
    )

    counter_deltas = {
        metric_name: _counter_delta(
            baseline_counters.get(metric_name),
            after_counters.get(metric_name),
        )
        for metric_name in COUNTER_METRICS
    }

    validation_errors, warnings = _validate_global_evidence(
        request_count=request_count,
        configured_max_active=configured_max_active,
        configured_max_waiting=configured_max_waiting,
        request_results=request_results,
        monitor_samples=monitor_samples,
        recovery=recovery,
        counter_deltas=counter_deltas,
        require_queue_full=args.require_queue_full,
        require_wait_timeout=args.require_wait_timeout,
        require_counter_evidence=args.require_counter_evidence,
    )

    accepted_results = [
        result
        for result in request_results
        if result.outcome == "accepted"
    ]
    queue_full_results = [
        result
        for result in request_results
        if result.reason == "queue_full"
    ]
    wait_timeout_results = [
        result
        for result in request_results
        if result.reason == "wait_timeout"
    ]

    peak_active = _metric_peak(
        monitor_samples,
        "cityroute_active_requests",
    )
    peak_waiting = _metric_peak(
        monitor_samples,
        "cityroute_waiting_requests",
    )

    per_round_summaries = []

    for round_result in rounds:
        results = round_result["request_results"]
        samples = round_result["monitor_samples"]

        per_round_summaries.append(
            {
                "round_index": round_result["round_index"],
                "elapsed_ms": round_result["elapsed_ms"],
                "outcome_counts": dict(
                    sorted(
                        Counter(
                            result.outcome
                            for result in results
                        ).items()
                    )
                ),
                "status_code_counts": dict(
                    sorted(
                        Counter(
                            str(result.status_code)
                            for result in results
                        ).items()
                    )
                ),
                "reason_counts": dict(
                    sorted(
                        Counter(
                            result.reason
                            for result in results
                            if result.reason is not None
                        ).items()
                    )
                ),
                "peak_active_requests": _metric_peak(
                    samples,
                    "cityroute_active_requests",
                ),
                "peak_waiting_requests": _metric_peak(
                    samples,
                    "cityroute_waiting_requests",
                ),
                "monitor_sample_count": len(samples),
                "monitor_validation_error_count": sum(
                    len(sample.validation_errors)
                    for sample in samples
                ),
            }
        )

    overall_ok = not validation_errors
    timestamp = timestamp_slug()

    raw_path = build_result_path(
        "phase11_overload_probe_raw",
        results_dir=args.results_dir,
        target=args.target,
        timestamp=timestamp,
    )
    summary_path = build_result_path(
        "phase11_overload_probe_summary",
        results_dir=args.results_dir,
        target=args.target,
        timestamp=timestamp,
    )

    raw_payload: dict[str, Any] = {
        "phase_code": PROJECT_PHASE_CODE,
        "phase_name": PROJECT_PHASE_NAME,
        "benchmark": "phase11_overload_probe",
        "started_at_utc": started_at_utc,
        "finished_at_utc": utc_now_iso(),
        "base_url": base_url,
        "target": args.target,
        "results_dir_override": (
            None
            if args.results_dir is None
            else str(args.results_dir)
        ),
        "configuration": {
            "requests_per_round": request_count,
            "rounds": args.rounds,
            "matrix_size": args.matrix_size,
            "algorithm": args.algorithm,
            "use_cache": args.use_cache,
            "monitor_interval_s": args.monitor_interval_s,
            "timeout_s": args.timeout_s,
            "startup_timeout_s": args.startup_timeout_s,
            "recovery_timeout_s": args.recovery_timeout_s,
            "require_queue_full": args.require_queue_full,
            "require_wait_timeout": (
                args.require_wait_timeout
            ),
            "require_counter_evidence": (
                args.require_counter_evidence
            ),
            "configured_max_active": configured_max_active,
            "configured_max_waiting": configured_max_waiting,
            "configured_total_capacity": (
                configured_total_capacity
            ),
        },
        "runtime_metadata": asdict(
            collect_runtime_metadata(base_url=base_url)
        ),
        "startup_probes": {
            "liveness": asdict(startup_liveness),
            "readiness": asdict(startup_readiness),
        },
        "preflight": {
            "status_code": preflight_response.status_code,
            "elapsed_ms": preflight_elapsed_ms,
            "response_summary": _summarize_json_response(
                status_code=preflight_response.status_code,
                response_json=preflight_json,
                response_text=preflight_response.text,
            ),
        },
        "baseline_metrics": {
            "status_code": baseline_metrics_status,
            "gauges": baseline_gauges,
            "counters": {
                key: asdict(value)
                for key, value in baseline_counters.items()
            },
            "error_type": baseline_metrics_error_type,
            "error_message": baseline_metrics_error_message,
        },
        "after_metrics": {
            "status_code": after_metrics_status,
            "gauges": after_gauges,
            "counters": {
                key: asdict(value)
                for key, value in after_counters.items()
            },
            "error_type": after_metrics_error_type,
            "error_message": after_metrics_error_message,
        },
        "counter_deltas": counter_deltas,
        "rounds": [
            {
                "round_index": round_result["round_index"],
                "elapsed_ms": round_result["elapsed_ms"],
                "request_results": [
                    asdict(result)
                    for result in round_result[
                        "request_results"
                    ]
                ],
                "monitor_samples": [
                    asdict(sample)
                    for sample in round_result[
                        "monitor_samples"
                    ]
                ],
            }
            for round_result in rounds
        ],
        "per_round_summaries": per_round_summaries,
        "recovery": recovery,
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "status_code_counts": dict(
            sorted(status_counts.items())
        ),
        "reason_counts": dict(sorted(reason_counts.items())),
        "accepted_latency": _latency_summary(
            [
                result.elapsed_ms
                for result in accepted_results
            ]
        ),
        "queue_full_latency": _latency_summary(
            [
                result.elapsed_ms
                for result in queue_full_results
            ]
        ),
        "queue_full_admission_wait": _latency_summary(
            [
                result.admission_wait_ms
                for result in queue_full_results
                if result.admission_wait_ms is not None
            ]
        ),
        "wait_timeout_latency": _latency_summary(
            [
                result.elapsed_ms
                for result in wait_timeout_results
            ]
        ),
        "wait_timeout_admission_wait": _latency_summary(
            [
                result.admission_wait_ms
                for result in wait_timeout_results
                if result.admission_wait_ms is not None
            ]
        ),
        "peak_active_requests": peak_active,
        "peak_waiting_requests": peak_waiting,
        "peak_total_in_system": (
            None
            if peak_active is None or peak_waiting is None
            else peak_active + peak_waiting
        ),
        "minimum_readiness_metric": _metric_minimum(
            monitor_samples,
            "cityroute_readiness",
        ),
        "minimum_accepting_requests_metric": (
            _metric_minimum(
                monitor_samples,
                "cityroute_accepting_requests",
            )
        ),
        "validation_errors": validation_errors,
        "warnings": warnings,
        "overall_ok": overall_ok,
    }

    summary_payload: dict[str, Any] = {
        "phase_code": PROJECT_PHASE_CODE,
        "phase_name": PROJECT_PHASE_NAME,
        "benchmark": "phase11_overload_probe",
        "base_url": base_url,
        "target": args.target,
        "overall_ok": overall_ok,
        "configured_max_active": configured_max_active,
        "configured_max_waiting": configured_max_waiting,
        "configured_total_capacity": (
            configured_total_capacity
        ),
        "requests_per_round": request_count,
        "rounds": args.rounds,
        "total_request_count": len(request_results),
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "status_code_counts": dict(
            sorted(status_counts.items())
        ),
        "reason_counts": dict(sorted(reason_counts.items())),
        "overload_response_count": (
            outcome_counts["controlled_overload"]
        ),
        "unexpected_response_count": (
            outcome_counts["unexpected_response"]
            + outcome_counts["client_error"]
        ),
        "peak_active_requests": peak_active,
        "peak_waiting_requests": peak_waiting,
        "peak_total_in_system": (
            None
            if peak_active is None or peak_waiting is None
            else peak_active + peak_waiting
        ),
        "active_limit_respected": (
            peak_active is not None
            and peak_active <= configured_max_active
        ),
        "waiting_limit_respected": (
            peak_waiting is not None
            and peak_waiting <= configured_max_waiting
        ),
        "accepted_latency": raw_payload[
            "accepted_latency"
        ],
        "queue_full_latency": raw_payload[
            "queue_full_latency"
        ],
        "queue_full_admission_wait": raw_payload[
            "queue_full_admission_wait"
        ],
        "wait_timeout_latency": raw_payload[
            "wait_timeout_latency"
        ],
        "wait_timeout_admission_wait": raw_payload[
            "wait_timeout_admission_wait"
        ],
        "minimum_readiness_metric": raw_payload[
            "minimum_readiness_metric"
        ],
        "minimum_accepting_requests_metric": raw_payload[
            "minimum_accepting_requests_metric"
        ],
        "counter_deltas": counter_deltas,
        "recovery_ok": (
            recovery["idle_recovery"]["recovered"]
            and recovery["readiness_status_code"] == 200
            and recovery["liveness_status_code"] == 200
            and recovery["matrix_status_code"] == 200
        ),
        "per_round_summaries": per_round_summaries,
        "validation_errors": validation_errors,
        "warnings": warnings,
        "raw_result_path": str(raw_path),
        "summary_result_path": str(summary_path),
    }

    write_json(raw_path, raw_payload)
    write_json(summary_path, summary_payload)
    print_json(summary_payload)

    if args.fail_on_validation_error and validation_errors:
        return 1

    return 0 if overall_ok else 1


def main() -> int:
    args = parse_args()
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print(
            "Phase 11 overload probe interrupted",
            file=sys.stderr,
        )
        raise SystemExit(130) from None