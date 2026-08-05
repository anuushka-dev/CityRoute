# benchmarks/phase_11/phase11_concurrency_limit_probe.py

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

# Support both direct execution and module execution:
#   python benchmarks/phase_11/phase11_concurrency_limit_probe.py
#   python -m benchmarks.phase_11.phase11_concurrency_limit_probe
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


DEFAULT_MATRIX_SIZE = 25
DEFAULT_ROUNDS = 3
DEFAULT_MONITOR_INTERVAL_S = 0.02
DEFAULT_OVERFLOW_REQUESTS = 4

CONTROLLED_REJECTION_STATUS_CODES = {429, 503}
SUCCESS_STATUS_CODES = {200}

RELIABILITY_METRICS = (
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
class ConcurrentRequestResult:
    round_index: int
    request_index: int
    status_code: int | None
    elapsed_ms: float
    outcome: str
    rejection_reason: str | None
    response_json: Any | None
    response_text: str | None
    response_headers: dict[str, str]
    error_type: str | None
    error_message: str | None
    started_at_utc: str
    finished_at_utc: str


@dataclass(frozen=True)
class MetricsSample:
    round_index: int
    captured_at_utc: str
    elapsed_from_round_start_ms: float
    status_code: int | None
    values: dict[str, float | None]
    counter_values: dict[str, float | None]
    error_type: str | None
    error_message: str | None


@dataclass(frozen=True)
class LivenessSample:
    round_index: int
    captured_at_utc: str
    elapsed_from_round_start_ms: float
    status_code: int | None
    ok: bool
    response_json: Any | None
    error_type: str | None
    error_message: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prove that Phase 11 protected request concurrency and waiting "
            "are bounded by the configured process-local limiter."
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
            "Concurrent requests per round. Default: configured active + "
            "waiting capacity + --overflow-requests."
        ),
    )
    parser.add_argument(
        "--overflow-requests",
        type=int,
        default=DEFAULT_OVERFLOW_REQUESTS,
        help=(
            "Requests above configured active + waiting capacity when "
            "--requests is omitted. "
            f"Default: {DEFAULT_OVERFLOW_REQUESTS}"
        ),
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=DEFAULT_ROUNDS,
        help=(
            "Number of independent concurrency bursts. "
            f"Default: {DEFAULT_ROUNDS}"
        ),
    )
    parser.add_argument(
        "--matrix-size",
        type=int,
        default=DEFAULT_MATRIX_SIZE,
        help=(
            "Number of locations in each uncached /matrix request. "
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
            "Enable matrix caching. Disabled by default so requests remain "
            "long enough to expose active/waiting limits."
        ),
    )
    parser.add_argument(
        "--payload-file",
        type=Path,
        default=None,
        help=(
            "Optional JSON request payload for /matrix. When omitted, a "
            "deterministic Kanpur Central matrix payload is generated."
        ),
    )
    parser.add_argument(
        "--monitor-interval-s",
        type=float,
        default=DEFAULT_MONITOR_INTERVAL_S,
        help=(
            "Interval between /metrics samples during a burst. "
            f"Default: {DEFAULT_MONITOR_INTERVAL_S}"
        ),
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=max(DEFAULT_TIMEOUT_S, 60.0),
        help="Per-load-request timeout in seconds. Default: 60",
    )
    parser.add_argument(
        "--startup-timeout-s",
        type=float,
        default=180.0,
        help="Maximum wait for liveness/readiness. Default: 180",
    )
    parser.add_argument(
        "--expect-overload",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Require at least one controlled 429/503 rejection when the "
            "burst exceeds configured active + waiting capacity. "
            "Default: enabled."
        ),
    )
    parser.add_argument(
        "--require-active-saturation",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Require observed active_requests to reach max_active_requests. "
            "Default: enabled."
        ),
    )
    parser.add_argument(
        "--require-waiting-observed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Require at least one metrics sample with waiting_requests > 0. "
            "Default: enabled."
        ),
    )
    parser.add_argument(
        "--fail-on-validation-error",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Exit non-zero when the bounded-concurrency proof fails. "
            "Default: enabled."
        ),
    )

    args = parser.parse_args()

    if args.requests is not None and args.requests <= 0:
        parser.error("--requests must be greater than zero")

    if args.overflow_requests < 0:
        parser.error("--overflow-requests must be zero or greater")

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

    return args


def _parse_prometheus_samples(
    metrics_text: str,
) -> dict[str, list[float]]:
    parsed: dict[str, list[float]] = {}

    for raw_line in metrics_text.splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        sample, separator, raw_value = line.rpartition(" ")

        if not separator:
            continue

        metric_name = sample.split("{", 1)[0]

        try:
            value = float(raw_value)
        except ValueError:
            continue

        parsed.setdefault(metric_name, []).append(value)

    return parsed


def _metric_value(
    parsed: dict[str, list[float]],
    metric_name: str,
) -> float | None:
    values = parsed.get(metric_name)

    if not values:
        return None

    if len(values) == 1:
        return values[0]

    return sum(values)


def _extract_metric_values(
    metrics_text: str,
) -> tuple[dict[str, float | None], dict[str, float | None]]:
    parsed = _parse_prometheus_samples(metrics_text)

    gauges = {
        metric_name: _metric_value(parsed, metric_name)
        for metric_name in RELIABILITY_METRICS
    }
    counters = {
        metric_name: _metric_value(parsed, metric_name)
        for metric_name in COUNTER_METRICS
    }

    return gauges, counters


async def _fetch_metrics_text(
    client: httpx.AsyncClient,
    *,
    base_url: str,
) -> tuple[int | None, str | None, str | None, str | None]:
    try:
        response = await client.get(
            f"{base_url}/metrics",
        )
    except Exception as exc:
        return None, None, type(exc).__name__, str(exc)

    return response.status_code, response.text, None, None


async def _fetch_metrics_snapshot(
    client: httpx.AsyncClient,
    *,
    base_url: str,
) -> dict[str, Any]:
    status_code, text, error_type, error_message = (
        await _fetch_metrics_text(
            client,
            base_url=base_url,
        )
    )

    if text is None:
        return {
            "status_code": status_code,
            "gauges": {},
            "counters": {},
            "error_type": error_type,
            "error_message": error_message,
        }

    gauges, counters = _extract_metric_values(text)

    return {
        "status_code": status_code,
        "gauges": gauges,
        "counters": counters,
        "error_type": error_type,
        "error_message": error_message,
    }


def _load_payload_file(
    path: Path,
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise ValueError("--payload-file must contain one JSON object")

    return payload


def _generated_locations(
    *,
    matrix_size: int,
    unique_shift: int,
) -> list[dict[str, Any]]:
    # Compact deterministic grid around Kanpur Central. The tiny per-request
    # shift keeps payloads unique without materially changing the workload.
    center_lat = 26.4499
    center_lon = 80.3319
    spacing = 0.0016
    shift = unique_shift * 0.000001

    locations: list[dict[str, Any]] = []

    for index in range(matrix_size):
        row, column = divmod(index, 5)
        lat = center_lat + ((row - 2) * spacing) + shift
        lon = center_lon + ((column - 2) * spacing) - shift

        locations.append(
            {
                "id": f"p{index:02d}",
                "lat": round(lat, 7),
                "lon": round(lon, 7),
            }
        )

    return locations


def _build_matrix_payload(
    *,
    matrix_size: int,
    algorithm: str,
    use_cache: bool,
    unique_shift: int,
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
            unique_shift=unique_shift,
        ),
        "algorithm": algorithm,
        "use_cache": use_cache,
    }


def _filtered_response_headers(
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


def _extract_rejection_reason(
    response_json: Any,
    headers: dict[str, str],
) -> str | None:
    for header_name in (
        "x-cityroute-rejection-reason",
        "x-cityroute-admission",
        "x-cityroute-admission-reason",
    ):
        value = headers.get(header_name)

        if value:
            return value

    candidates: list[Any] = [response_json]

    if isinstance(response_json, dict):
        candidates.append(response_json.get("detail"))

    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate

        if not isinstance(candidate, dict):
            continue

        for key in (
            "reason",
            "error",
            "code",
            "message",
        ):
            value = candidate.get(key)

            if isinstance(value, str) and value:
                return value

    return None


def _classify_outcome(
    status_code: int | None,
) -> str:
    if status_code in SUCCESS_STATUS_CODES:
        return "accepted"

    if status_code in CONTROLLED_REJECTION_STATUS_CODES:
        return "controlled_rejection"

    if status_code is None:
        return "client_error"

    return "unexpected_http_status"


async def _run_one_request(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    start_event: asyncio.Event,
    round_index: int,
    request_index: int,
    payload: dict[str, Any],
) -> ConcurrentRequestResult:
    await start_event.wait()

    started_at_utc = utc_now_iso()
    started = time.perf_counter()

    status_code: int | None = None
    response_json: Any | None = None
    response_text: str | None = None
    response_headers: dict[str, str] = {}
    error_type: str | None = None
    error_message: str | None = None

    try:
        response = await client.post(
            f"{base_url}/matrix",
            json=payload,
        )
        status_code = response.status_code
        response_text = response.text
        response_headers = _filtered_response_headers(response)

        try:
            response_json = response.json()
        except ValueError:
            response_json = None
    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    elapsed_ms = (time.perf_counter() - started) * 1000.0

    return ConcurrentRequestResult(
        round_index=round_index,
        request_index=request_index,
        status_code=status_code,
        elapsed_ms=elapsed_ms,
        outcome=_classify_outcome(status_code),
        rejection_reason=_extract_rejection_reason(
            response_json,
            response_headers,
        ),
        response_json=response_json,
        response_text=response_text,
        response_headers=response_headers,
        error_type=error_type,
        error_message=error_message,
        started_at_utc=started_at_utc,
        finished_at_utc=utc_now_iso(),
    )


async def _monitor_round(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    round_index: int,
    round_started: float,
    stop_event: asyncio.Event,
    interval_s: float,
) -> tuple[list[MetricsSample], list[LivenessSample]]:
    metrics_samples: list[MetricsSample] = []
    liveness_samples: list[LivenessSample] = []
    sample_index = 0

    while not stop_event.is_set():
        captured_at_utc = utc_now_iso()
        elapsed_ms = (
            time.perf_counter() - round_started
        ) * 1000.0

        status_code, text, error_type, error_message = (
            await _fetch_metrics_text(
                client,
                base_url=base_url,
            )
        )

        if text is None:
            gauges: dict[str, float | None] = {}
            counters: dict[str, float | None] = {}
        else:
            gauges, counters = _extract_metric_values(text)

        metrics_samples.append(
            MetricsSample(
                round_index=round_index,
                captured_at_utc=captured_at_utc,
                elapsed_from_round_start_ms=elapsed_ms,
                status_code=status_code,
                values=gauges,
                counter_values=counters,
                error_type=error_type,
                error_message=error_message,
            )
        )

        # Liveness is sampled less frequently than metrics to keep monitoring
        # overhead low while still proving it bypasses protected saturation.
        if sample_index % 5 == 0:
            live_status_code: int | None = None
            live_json: Any | None = None
            live_error_type: str | None = None
            live_error_message: str | None = None

            try:
                response = await client.get(
                    f"{base_url}/health/live",
                )
                live_status_code = response.status_code

                try:
                    live_json = response.json()
                except ValueError:
                    live_json = None
            except Exception as exc:
                live_error_type = type(exc).__name__
                live_error_message = str(exc)

            liveness_samples.append(
                LivenessSample(
                    round_index=round_index,
                    captured_at_utc=utc_now_iso(),
                    elapsed_from_round_start_ms=(
                        time.perf_counter() - round_started
                    )
                    * 1000.0,
                    status_code=live_status_code,
                    ok=(
                        live_status_code == 200
                        and isinstance(live_json, dict)
                        and live_json.get("status") == "alive"
                    ),
                    response_json=live_json,
                    error_type=live_error_type,
                    error_message=live_error_message,
                )
            )

        sample_index += 1

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=interval_s,
            )
        except TimeoutError:
            pass

    # Capture one final post-completion metrics sample for each round.
    final_snapshot = await _fetch_metrics_snapshot(
        client,
        base_url=base_url,
    )

    metrics_samples.append(
        MetricsSample(
            round_index=round_index,
            captured_at_utc=utc_now_iso(),
            elapsed_from_round_start_ms=(
                time.perf_counter() - round_started
            )
            * 1000.0,
            status_code=final_snapshot["status_code"],
            values=final_snapshot["gauges"],
            counter_values=final_snapshot["counters"],
            error_type=final_snapshot["error_type"],
            error_message=final_snapshot["error_message"],
        )
    )

    return metrics_samples, liveness_samples


async def _preflight_matrix(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()

    response = await client.post(
        f"{base_url}/matrix",
        json=payload,
    )

    try:
        response_json: Any | None = response.json()
    except ValueError:
        response_json = None

    result = {
        "status_code": response.status_code,
        "elapsed_ms": (
            time.perf_counter() - started
        )
        * 1000.0,
        "response_json": response_json,
        "response_text": response.text,
        "headers": _filtered_response_headers(response),
    }

    if response.status_code != 200:
        raise RuntimeError(
            "Matrix preflight failed. Confirm the payload schema and "
            "coordinates before running concurrency evidence. "
            f"status={response.status_code}, "
            f"response={response.text!r}"
        )

    return result


async def _run_round(
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
    monitor_interval_s: float,
) -> dict[str, Any]:
    start_event = asyncio.Event()
    stop_event = asyncio.Event()
    round_started = time.perf_counter()

    request_tasks = []

    for request_index in range(request_count):
        unique_shift = (
            (round_index * request_count)
            + request_index
            + 1
        )

        payload = _build_matrix_payload(
            matrix_size=matrix_size,
            algorithm=algorithm,
            use_cache=use_cache,
            unique_shift=unique_shift,
            payload_template=payload_template,
        )

        request_tasks.append(
            asyncio.create_task(
                _run_one_request(
                    client=load_client,
                    base_url=base_url,
                    start_event=start_event,
                    round_index=round_index,
                    request_index=request_index,
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

    results = await asyncio.gather(*request_tasks)
    stop_event.set()
    metrics_samples, liveness_samples = await monitor_task

    return {
        "round_index": round_index,
        "elapsed_ms": (
            time.perf_counter() - round_started
        )
        * 1000.0,
        "request_results": results,
        "metrics_samples": metrics_samples,
        "liveness_samples": liveness_samples,
    }


def _maximum_metric(
    samples: list[MetricsSample],
    metric_name: str,
) -> float | None:
    values = [
        sample.values.get(metric_name)
        for sample in samples
        if sample.values.get(metric_name) is not None
    ]

    return max(values) if values else None


def _minimum_metric(
    samples: list[MetricsSample],
    metric_name: str,
) -> float | None:
    values = [
        sample.values.get(metric_name)
        for sample in samples
        if sample.values.get(metric_name) is not None
    ]

    return min(values) if values else None


def _counter_delta(
    before: dict[str, Any],
    after: dict[str, Any],
    metric_name: str,
) -> float | None:
    before_value = before.get("counters", {}).get(metric_name)
    after_value = after.get("counters", {}).get(metric_name)

    if before_value is None or after_value is None:
        return None

    return after_value - before_value


def _latency_summary(
    results: list[ConcurrentRequestResult],
) -> dict[str, float | int | None]:
    latencies = [
        result.elapsed_ms
        for result in results
    ]

    if not latencies:
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
        "count": len(latencies),
        "min_ms": min(latencies),
        "max_ms": max(latencies),
        "mean_ms": sum(latencies) / len(latencies),
        "median_ms": percentile(latencies, 50.0),
        "p90_ms": percentile(latencies, 90.0),
        "p95_ms": percentile(latencies, 95.0),
        "p99_ms": percentile(latencies, 99.0),
    }


def _validate_evidence(
    *,
    request_count: int,
    configured_max_active: int,
    configured_max_waiting: int,
    request_results: list[ConcurrentRequestResult],
    metrics_samples: list[MetricsSample],
    liveness_samples: list[LivenessSample],
    counter_deltas: dict[str, float | None],
    recovery: dict[str, Any],
    expect_overload: bool,
    require_active_saturation: bool,
    require_waiting_observed: bool,
) -> list[str]:
    errors: list[str] = []

    peak_active = _maximum_metric(
        metrics_samples,
        "cityroute_active_requests",
    )
    peak_waiting = _maximum_metric(
        metrics_samples,
        "cityroute_waiting_requests",
    )

    if peak_active is None:
        errors.append(
            "No cityroute_active_requests metric samples were captured"
        )
    elif peak_active > configured_max_active:
        errors.append(
            "Observed active request count exceeded configured maximum: "
            f"{peak_active} > {configured_max_active}"
        )

    if peak_waiting is None:
        errors.append(
            "No cityroute_waiting_requests metric samples were captured"
        )
    elif peak_waiting > configured_max_waiting:
        errors.append(
            "Observed waiting request count exceeded configured maximum: "
            f"{peak_waiting} > {configured_max_waiting}"
        )

    if (
        peak_active is not None
        and peak_waiting is not None
        and (
            peak_active + peak_waiting
            > configured_max_active + configured_max_waiting
        )
    ):
        errors.append(
            "Observed active + waiting work exceeded total bounded "
            "capacity"
        )

    if (
        require_active_saturation
        and peak_active is not None
        and peak_active < configured_max_active
    ):
        errors.append(
            "Active limit was not saturated. Increase workload duration "
            "or request count: "
            f"peak_active={peak_active}, "
            f"configured={configured_max_active}"
        )

    if (
        require_waiting_observed
        and peak_waiting is not None
        and peak_waiting <= 0
    ):
        errors.append(
            "No waiting request was observed. The workload completed too "
            "quickly to prove bounded waiting."
        )

    outcomes = Counter(
        result.outcome
        for result in request_results
    )

    if outcomes["accepted"] <= 0:
        errors.append("No concurrency-load request was accepted")

    if outcomes["client_error"] > 0:
        errors.append(
            f"{outcomes['client_error']} load requests failed at the "
            "HTTP client layer"
        )

    if outcomes["unexpected_http_status"] > 0:
        errors.append(
            f"{outcomes['unexpected_http_status']} load requests returned "
            "unexpected HTTP status codes"
        )

    bounded_capacity = (
        configured_max_active + configured_max_waiting
    )

    if (
        expect_overload
        and request_count > bounded_capacity
        and outcomes["controlled_rejection"] <= 0
    ):
        errors.append(
            "Burst exceeded active + waiting capacity but no controlled "
            "429/503 rejection was observed"
        )

    if any(
        not sample.ok
        for sample in liveness_samples
    ):
        errors.append(
            "One or more liveness samples failed during saturation"
        )

    rejection_delta = counter_deltas.get(
        "cityroute_request_rejections_total"
    )
    overload_delta = counter_deltas.get(
        "cityroute_overload_events_total"
    )

    if (
        outcomes["controlled_rejection"] > 0
        and rejection_delta is not None
        and rejection_delta <= 0
    ):
        errors.append(
            "Controlled rejections occurred but the rejection counter did "
            "not increase"
        )

    if (
        outcomes["controlled_rejection"] > 0
        and overload_delta is not None
        and overload_delta <= 0
    ):
        errors.append(
            "Controlled rejections occurred but the overload counter did "
            "not increase"
        )

    if recovery.get("readiness_status_code") != 200:
        errors.append(
            "Readiness did not recover to HTTP 200 after load"
        )

    readiness_payload = recovery.get("readiness_json")

    if (
        not isinstance(readiness_payload, dict)
        or readiness_payload.get("ready") is not True
        or readiness_payload.get("accepting_requests") is not True
        or readiness_payload.get("shutting_down") is not False
    ):
        errors.append(
            "Readiness payload did not return to accepting steady state"
        )

    if recovery.get("matrix_status_code") != 200:
        errors.append(
            "Post-load matrix recovery request did not return HTTP 200"
        )

    final_active = recovery.get("final_metric_values", {}).get(
        "cityroute_active_requests"
    )
    final_waiting = recovery.get("final_metric_values", {}).get(
        "cityroute_waiting_requests"
    )

    if final_active not in {0.0}:
        errors.append(
            "active_requests did not return to zero after load"
        )

    if final_waiting not in {0.0}:
        errors.append(
            "waiting_requests did not return to zero after load"
        )

    return errors


async def async_main(
    args: argparse.Namespace,
) -> int:
    base_url = args.base_url.rstrip("/")
    started_at_utc = utc_now_iso()

    # Common synchronous wait helpers are run outside the active event loop.
    await asyncio.to_thread(
        wait_for_liveness,
        base_url=base_url,
        startup_timeout_s=args.startup_timeout_s,
    )
    await asyncio.to_thread(
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

    load_limits = httpx.Limits(
        max_connections=100,
        max_keepalive_connections=100,
    )
    monitor_limits = httpx.Limits(
        max_connections=10,
        max_keepalive_connections=10,
    )

    async with (
        httpx.AsyncClient(
            timeout=args.timeout_s,
            limits=load_limits,
        ) as load_client,
        httpx.AsyncClient(
            timeout=min(args.timeout_s, 10.0),
            limits=monitor_limits,
        ) as monitor_client,
    ):
        preflight_payload = _build_matrix_payload(
            matrix_size=min(args.matrix_size, 5),
            algorithm=args.algorithm,
            use_cache=False,
            unique_shift=0,
            payload_template=payload_template,
        )
        preflight = await _preflight_matrix(
            client=load_client,
            base_url=base_url,
            payload=preflight_payload,
        )

        before_metrics = await _fetch_metrics_snapshot(
            monitor_client,
            base_url=base_url,
        )

        max_active_value = before_metrics.get(
            "gauges",
            {},
        ).get("cityroute_max_active_requests")
        max_waiting_value = before_metrics.get(
            "gauges",
            {},
        ).get("cityroute_max_waiting_requests")

        if max_active_value is None or max_waiting_value is None:
            raise RuntimeError(
                "The concurrency capacity metrics are missing from "
                "/metrics"
            )

        configured_max_active = int(max_active_value)
        configured_max_waiting = int(max_waiting_value)

        if configured_max_active <= 0:
            raise RuntimeError(
                "cityroute_max_active_requests must be greater than zero"
            )

        if configured_max_waiting < 0:
            raise RuntimeError(
                "cityroute_max_waiting_requests must be non-negative"
            )

        request_count = args.requests

        if request_count is None:
            request_count = (
                configured_max_active
                + configured_max_waiting
                + args.overflow_requests
            )

        all_rounds: list[dict[str, Any]] = []

        for round_index in range(args.rounds):
            round_result = await _run_round(
                load_client=load_client,
                monitor_client=monitor_client,
                base_url=base_url,
                round_index=round_index,
                request_count=request_count,
                matrix_size=args.matrix_size,
                algorithm=args.algorithm,
                use_cache=args.use_cache,
                payload_template=payload_template,
                monitor_interval_s=args.monitor_interval_s,
            )
            all_rounds.append(round_result)

            if round_index < args.rounds - 1:
                await asyncio.sleep(0.25)

        after_metrics = await _fetch_metrics_snapshot(
            monitor_client,
            base_url=base_url,
        )

        recovery_payload = _build_matrix_payload(
            matrix_size=min(args.matrix_size, 5),
            algorithm=args.algorithm,
            use_cache=False,
            unique_shift=999_999,
            payload_template=payload_template,
        )

        recovery_started = time.perf_counter()
        recovery_response = await load_client.post(
            f"{base_url}/matrix",
            json=recovery_payload,
        )
        recovery_elapsed_ms = (
            time.perf_counter() - recovery_started
        ) * 1000.0

        try:
            recovery_matrix_json: Any | None = (
                recovery_response.json()
            )
        except ValueError:
            recovery_matrix_json = None

        readiness_response = await monitor_client.get(
            f"{base_url}/health/ready",
        )

        try:
            readiness_json: Any | None = (
                readiness_response.json()
            )
        except ValueError:
            readiness_json = None

        final_metrics = await _fetch_metrics_snapshot(
            monitor_client,
            base_url=base_url,
        )

    request_results = [
        result
        for round_result in all_rounds
        for result in round_result["request_results"]
    ]
    metrics_samples = [
        sample
        for round_result in all_rounds
        for sample in round_result["metrics_samples"]
    ]
    liveness_samples = [
        sample
        for round_result in all_rounds
        for sample in round_result["liveness_samples"]
    ]

    outcomes = Counter(
        result.outcome
        for result in request_results
    )
    status_codes = Counter(
        str(result.status_code)
        for result in request_results
    )
    rejection_reasons = Counter(
        result.rejection_reason or "unknown"
        for result in request_results
        if result.outcome == "controlled_rejection"
    )

    counter_deltas = {
        metric_name: _counter_delta(
            before_metrics,
            after_metrics,
            metric_name,
        )
        for metric_name in COUNTER_METRICS
    }

    recovery = {
        "matrix_status_code": recovery_response.status_code,
        "matrix_elapsed_ms": recovery_elapsed_ms,
        "matrix_response_json": recovery_matrix_json,
        "readiness_status_code": readiness_response.status_code,
        "readiness_json": readiness_json,
        "final_metric_values": final_metrics.get("gauges", {}),
        "final_counter_values": final_metrics.get("counters", {}),
    }

    validation_errors = _validate_evidence(
        request_count=request_count,
        configured_max_active=configured_max_active,
        configured_max_waiting=configured_max_waiting,
        request_results=request_results,
        metrics_samples=metrics_samples,
        liveness_samples=liveness_samples,
        counter_deltas=counter_deltas,
        recovery=recovery,
        expect_overload=args.expect_overload,
        require_active_saturation=args.require_active_saturation,
        require_waiting_observed=args.require_waiting_observed,
    )

    peak_active = _maximum_metric(
        metrics_samples,
        "cityroute_active_requests",
    )
    peak_waiting = _maximum_metric(
        metrics_samples,
        "cityroute_waiting_requests",
    )
    minimum_readiness = _minimum_metric(
        metrics_samples,
        "cityroute_readiness",
    )
    minimum_accepting = _minimum_metric(
        metrics_samples,
        "cityroute_accepting_requests",
    )

    overall_ok = not validation_errors
    timestamp = timestamp_slug()

    raw_path = build_result_path(
        "phase11_concurrency_limit_probe_raw",
        results_dir=args.results_dir,
        target=args.target,
        timestamp=timestamp,
    )
    summary_path = build_result_path(
        "phase11_concurrency_limit_probe_summary",
        results_dir=args.results_dir,
        target=args.target,
        timestamp=timestamp,
    )

    raw_payload: dict[str, Any] = {
        "phase_code": PROJECT_PHASE_CODE,
        "phase_name": PROJECT_PHASE_NAME,
        "benchmark": "phase11_concurrency_limit_probe",
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
            "request_count_per_round": request_count,
            "rounds": args.rounds,
            "matrix_size": args.matrix_size,
            "algorithm": args.algorithm,
            "use_cache": args.use_cache,
            "monitor_interval_s": args.monitor_interval_s,
            "timeout_s": args.timeout_s,
            "expect_overload": args.expect_overload,
            "require_active_saturation": (
                args.require_active_saturation
            ),
            "require_waiting_observed": (
                args.require_waiting_observed
            ),
            "configured_max_active": configured_max_active,
            "configured_max_waiting": configured_max_waiting,
            "configured_total_capacity": (
                configured_max_active + configured_max_waiting
            ),
        },
        "runtime_metadata": asdict(
            collect_runtime_metadata(base_url=base_url)
        ),
        "preflight": preflight,
        "before_metrics": before_metrics,
        "after_metrics": after_metrics,
        "counter_deltas": counter_deltas,
        "rounds": [
            {
                "round_index": round_result["round_index"],
                "elapsed_ms": round_result["elapsed_ms"],
                "request_results": [
                    asdict(result)
                    for result in round_result["request_results"]
                ],
                "metrics_samples": [
                    asdict(sample)
                    for sample in round_result["metrics_samples"]
                ],
                "liveness_samples": [
                    asdict(sample)
                    for sample in round_result["liveness_samples"]
                ],
            }
            for round_result in all_rounds
        ],
        "recovery": recovery,
        "outcome_counts": dict(sorted(outcomes.items())),
        "status_code_counts": dict(sorted(status_codes.items())),
        "rejection_reason_counts": dict(
            sorted(rejection_reasons.items())
        ),
        "latency_summary": _latency_summary(request_results),
        "peak_active_requests": peak_active,
        "peak_waiting_requests": peak_waiting,
        "peak_total_in_system": (
            None
            if peak_active is None or peak_waiting is None
            else peak_active + peak_waiting
        ),
        "minimum_readiness_metric": minimum_readiness,
        "minimum_accepting_requests_metric": minimum_accepting,
        "liveness_sample_count": len(liveness_samples),
        "liveness_failure_count": sum(
            not sample.ok
            for sample in liveness_samples
        ),
        "validation_errors": validation_errors,
        "overall_ok": overall_ok,
    }

    summary_payload: dict[str, Any] = {
        "phase_code": PROJECT_PHASE_CODE,
        "phase_name": PROJECT_PHASE_NAME,
        "benchmark": "phase11_concurrency_limit_probe",
        "base_url": base_url,
        "target": args.target,
        "overall_ok": overall_ok,
        "configured_max_active": configured_max_active,
        "configured_max_waiting": configured_max_waiting,
        "configured_total_capacity": (
            configured_max_active + configured_max_waiting
        ),
        "request_count_per_round": request_count,
        "rounds": args.rounds,
        "total_request_count": len(request_results),
        "outcome_counts": dict(sorted(outcomes.items())),
        "status_code_counts": dict(sorted(status_codes.items())),
        "rejection_reason_counts": dict(
            sorted(rejection_reasons.items())
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
        "latency_summary": _latency_summary(request_results),
        "counter_deltas": counter_deltas,
        "liveness_sample_count": len(liveness_samples),
        "liveness_failure_count": sum(
            not sample.ok
            for sample in liveness_samples
        ),
        "recovery_ok": (
            recovery_response.status_code == 200
            and readiness_response.status_code == 200
            and final_metrics.get("gauges", {}).get(
                "cityroute_active_requests"
            )
            == 0.0
            and final_metrics.get("gauges", {}).get(
                "cityroute_waiting_requests"
            )
            == 0.0
        ),
        "validation_errors": validation_errors,
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
            "Phase 11 concurrency-limit probe interrupted",
            file=sys.stderr,
        )
        raise SystemExit(130) from None