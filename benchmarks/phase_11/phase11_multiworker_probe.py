# benchmarks/phase_11/phase11_multiworker_probe.py

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

# Support both:
#   python benchmarks/phase_11/phase11_multiworker_probe.py
#   python -m benchmarks.phase_11.phase11_multiworker_probe

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

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

DEFAULT_REQUESTS = 300
DEFAULT_CONCURRENCY = 32
DEFAULT_TIMEOUT_SECONDS = max(
    DEFAULT_TIMEOUT_S,
    30.0,
)
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10.0

MIN_REQUESTS = 1
MAX_REQUESTS = 10_000

MIN_CONCURRENCY = 1
MAX_CONCURRENCY = 512

DEFAULT_MAX_CONNECTIONS = 512
DEFAULT_MAX_KEEPALIVE_CONNECTIONS = 128

DEFAULT_STARTUP_TIMEOUT_S = 180.0

HEALTH_ENDPOINTS = (
    "/health/live",
    "/health/ready",
)

BENCHMARK_ENDPOINTS = (
    "/health/live",
    "/health/ready",
    "/metrics",
    "/route",
    "/matrix",
)

ROUTE_ENDPOINT = "/route"
MATRIX_ENDPOINT = "/matrix"

MATRIX_LOCATIONS = (
    {
        "id": "point_1",
        "lat": 26.455,
        "lon": 80.331,
    },
    {
        "id": "point_2",
        "lat": 26.462,
        "lon": 80.338,
    },
    {
        "id": "point_3",
        "lat": 26.468,
        "lon": 80.352,
    },
)

ROUTE_PAYLOAD = {
    "start_lat": 26.455,
    "start_lon": 80.331,
    "end_lat": 26.468,
    "end_lon": 80.352,
}

MATRIX_PAYLOAD = {
    "locations": MATRIX_LOCATIONS,
    "algorithm": "source_dijkstra",
    "use_cache": False,
}

EXPECTED_SUCCESS_STATUS = 200

METRICS_REQUEST_COUNTER = (
    "cityroute_http_requests_total"
)
METRICS_EXECUTION_HISTOGRAM = (
    "cityroute_request_execution_seconds"
)

CONTROLLED_FAILURE_STATUSES = frozenset(
    {
        429,
        500,
        502,
        503,
        504,
    }
)

DEFAULT_RUNTIME_ENDPOINT = "/health/live"

# The metric response can become large. Keep report payloads bounded.
MAX_RESPONSE_TEXT = 1_000
MAX_ERROR_TEXT = 1_000
MAX_SAMPLE_RESPONSES = 5


# ---------------------------------------------------------------------------
# Dataclasses / Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuntimeState:
    """Runtime and worker information captured before/after the benchmark."""

    stage: str
    captured_at_utc: str
    liveness_status_code: int | None
    readiness_status_code: int | None
    liveness_ok: bool
    readiness_ok: bool
    readiness_payload: dict[str, Any] | None
    process_environment: dict[str, str]
    detected_worker_count: int | None
    worker_detection_source: str | None
    container_id: str | None
    container_name: str | None
    container_state: str | None
    container_image: str | None
    error_type: str | None
    error_message: str | None


@dataclass(frozen=True)
class RequestResult:
    """Result of one benchmark HTTP request."""

    request_index: int
    endpoint: str
    method: str
    status_code: int | None
    elapsed_ms: float
    success: bool
    outcome: str
    response_fingerprint: str | None
    response_summary: Any | None
    error_type: str | None
    error_message: str | None
    started_at_utc: str
    finished_at_utc: str


@dataclass(frozen=True)
class EndpointStatistics:
    """Aggregated benchmark statistics for one endpoint."""

    endpoint: str
    requests: int
    success: int
    failures: int
    min_ms: float | None
    max_ms: float | None
    mean_ms: float | None
    median_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    throughput_rps: float | None
    status_code_counts: dict[str, int]
    outcome_counts: dict[str, int]
    distinct_response_fingerprints: int
    consistency_ok: bool
    consistency_applicable: bool


@dataclass(frozen=True)
class ConsistencyResult:
    """Cross-worker consistency evidence."""

    endpoint: str
    sampled_successful_responses: int
    distinct_response_fingerprints: int
    consistency_ok: bool
    fingerprints: tuple[str, ...]
    validation_errors: tuple[str, ...]


@dataclass(frozen=True)
class MetricsSnapshot:
    """Selected Prometheus values around the worker benchmark."""

    stage: str
    status_code: int | None
    request_counter_samples: int
    request_counter_total: float | None
    execution_metric_samples: int
    raw_text_available: bool
    error_type: str | None
    error_message: str | None


@dataclass(frozen=True)
class CommandResult:
    """Structured operating-system / Docker command result."""

    operation: str
    command: tuple[str, ...]
    return_code: int | None
    ok: bool
    elapsed_ms: float
    stdout: str
    stderr: str
    error_type: str | None
    error_message: str | None
    started_at_utc: str
    finished_at_utc: str


@dataclass(frozen=True)
class ValidationResult:
    """Final benchmark validation result."""

    validation_errors: tuple[str, ...]
    warnings: tuple[str, ...]
    overall_ok: bool


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parse and validate multi-worker benchmark configuration."""

    parser = argparse.ArgumentParser(
        description=(
            "Benchmark CityRoute under concurrent multi-worker-style "
            "request load. The probe measures latency, throughput, "
            "failure behavior, deterministic response consistency, "
            "runtime worker information, and post-benchmark health."
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
            "Standard Phase 11 result directory target. "
            "When omitted, phase11_common determines the default."
        ),
    )

    parser.add_argument(
        "--results-dir",
        type=Path,
        default=None,
        help=(
            "Explicit output directory. "
            "Overrides the target-based output path."
        ),
    )

    parser.add_argument(
        "--requests",
        type=int,
        default=DEFAULT_REQUESTS,
        help=(
            "Total requests distributed across selected endpoints. "
            f"Default: {DEFAULT_REQUESTS}"
        ),
    )

    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=(
            "Maximum concurrent requests. "
            f"Default: {DEFAULT_CONCURRENCY}"
        ),
    )

    parser.add_argument(
        "--timeout-s",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=(
            "Per-request timeout. "
            f"Default: {DEFAULT_TIMEOUT_SECONDS}"
        ),
    )

    parser.add_argument(
        "--connect-timeout-s",
        type=float,
        default=DEFAULT_CONNECT_TIMEOUT_SECONDS,
        help=(
            "HTTP connection timeout. "
            f"Default: {DEFAULT_CONNECT_TIMEOUT_SECONDS}"
        ),
    )

    parser.add_argument(
        "--startup-timeout-s",
        type=float,
        default=DEFAULT_STARTUP_TIMEOUT_S,
        help=(
            "Maximum wait for liveness/readiness before and after "
            f"the benchmark. Default: {DEFAULT_STARTUP_TIMEOUT_S}"
        ),
    )

    parser.add_argument(
        "--endpoint",
        action="append",
        choices=BENCHMARK_ENDPOINTS,
        dest="endpoints",
        help=(
            "Endpoint to benchmark. May be specified multiple times. "
            "When omitted, the default Phase 11 endpoint set is used."
        ),
    )

    parser.add_argument(
        "--consistency-samples",
        type=int,
        default=MAX_SAMPLE_RESPONSES,
        help=(
            "Maximum successful responses retained per endpoint for "
            f"consistency comparison. Default: {MAX_SAMPLE_RESPONSES}"
        ),
    )

    parser.add_argument(
        "--expected-workers",
        type=int,
        default=None,
        help=(
            "Expected worker count. When provided, the benchmark fails "
            "if runtime worker detection succeeds with a different value."
        ),
    )

    parser.add_argument(
        "--require-multiworker",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Require detected worker count to be greater than one. "
            "Disabled by default so the benchmark can also document a "
            "single-worker baseline."
        ),
    )

    parser.add_argument(
        "--require-response-consistency",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Require deterministic endpoints to produce consistent "
            "responses under concurrent execution. Default: enabled."
        ),
    )

    parser.add_argument(
        "--allow-controlled-failures",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Allow controlled overload/rejection responses without "
            "automatically failing the benchmark. Default: enabled."
        ),
    )

    parser.add_argument(
        "--fail-on-validation-error",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Exit non-zero when benchmark validation fails. "
            "Default: enabled."
        ),
    )

    args = parser.parse_args()

    if not (
        MIN_REQUESTS
        <= args.requests
        <= MAX_REQUESTS
    ):
        parser.error(
            "--requests must be between "
            f"{MIN_REQUESTS} and {MAX_REQUESTS}"
        )

    if not (
        MIN_CONCURRENCY
        <= args.concurrency
        <= MAX_CONCURRENCY
    ):
        parser.error(
            "--concurrency must be between "
            f"{MIN_CONCURRENCY} and {MAX_CONCURRENCY}"
        )

    if args.concurrency > args.requests:
        parser.error(
            "--concurrency cannot exceed --requests"
        )

    if args.timeout_s <= 0:
        parser.error(
            "--timeout-s must be greater than zero"
        )

    if args.connect_timeout_s <= 0:
        parser.error(
            "--connect-timeout-s must be greater than zero"
        )

    if args.startup_timeout_s <= 0:
        parser.error(
            "--startup-timeout-s must be greater than zero"
        )

    if not (
        1
        <= args.consistency_samples
        <= MAX_SAMPLE_RESPONSES
    ):
        parser.error(
            "--consistency-samples must be between 1 and "
            f"{MAX_SAMPLE_RESPONSES}"
        )

    if (
        args.expected_workers is not None
        and args.expected_workers <= 0
    ):
        parser.error(
            "--expected-workers must be greater than zero"
        )

    if args.endpoints is not None and not args.endpoints:
        parser.error(
            "At least one endpoint must be selected"
        )

    return args


# ---------------------------------------------------------------------------
# Validation / normalization helpers
# ---------------------------------------------------------------------------


def _normalize_base_url(
    base_url: str,
) -> str:
    """Normalize the API base URL."""

    normalized = base_url.strip().rstrip("/")

    if not normalized:
        raise ValueError(
            "Base URL must not be empty."
        )

    return normalized


def _safe_text(
    value: str | None,
    *,
    maximum: int,
) -> str | None:
    """Bound text retained in structured evidence."""

    if value is None:
        return None

    if len(value) <= maximum:
        return value

    return (
        value[:maximum]
        + "...[truncated]"
    )


def _response_fingerprint(
    response: httpx.Response,
) -> str | None:
    """Generate a deterministic response fingerprint for comparisons."""

    try:
        payload = response.json()

    except ValueError:
        text = _safe_text(
            response.text,
            maximum=MAX_RESPONSE_TEXT,
        )

        return (
            json.dumps(
                text,
                sort_keys=True,
                separators=(
                    ",",
                    ":",
                ),
            )
        )

    normalized = _normalize_json_for_fingerprint(
        payload
    )

    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
        default=str,
    )


def _normalize_json_for_fingerprint(
    value: Any,
) -> Any:
    """Remove intentionally unstable response fields where known."""

    if isinstance(value, dict):
        return {
            key: _normalize_json_for_fingerprint(
                item
            )
            for key, item in sorted(
                value.items()
            )
            if key not in {
                "time_ms",
                "generation_time_ms",
                "optimization_time_ms",
                "elapsed_ms",
                "snap_time_ms",
                "route_time_ms",
                "total_time_ms",
                "request_id",
            }
        }

    if isinstance(value, list):
        return [
            _normalize_json_for_fingerprint(
                item
            )
            for item in value
        ]

    return value


def _endpoint_response_is_deterministic(
    endpoint: str,
) -> bool:
    """Identify endpoints whose semantic response should remain stable."""

    return endpoint in {
        ROUTE_ENDPOINT,
        MATRIX_ENDPOINT,
    }


def _response_summary(
    response: httpx.Response,
) -> Any | None:
    """Create a bounded, human-readable response summary."""

    try:
        payload = response.json()

    except ValueError:
        return _safe_text(
            response.text,
            maximum=MAX_RESPONSE_TEXT,
        )

    if isinstance(payload, dict):
        keys = (
            "status",
            "algorithm",
            "n",
            "cache",
            "driver_count",
            "order_count",
            "assigned_order_count",
            "unassigned_order_count",
        )

        return {
            key: payload.get(key)
            for key in keys
            if key in payload
        }

    return payload


# ---------------------------------------------------------------------------
# Command / runtime inspection
# ---------------------------------------------------------------------------


def _run_command(
    *,
    operation: str,
    command: list[str],
    timeout_s: float = DEFAULT_TIMEOUT_SECONDS,
) -> CommandResult:
    """Execute a local command with complete structured evidence."""

    started_at_utc = utc_now_iso()
    started = time.perf_counter()

    return_code: int | None = None
    stdout = ""
    stderr = ""
    error_type: str | None = None
    error_message: str | None = None

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=PROJECT_ROOT,
        )

        return_code = completed.returncode
        stdout = _safe_text(
            completed.stdout.strip(),
            maximum=MAX_RESPONSE_TEXT,
        ) or ""
        stderr = _safe_text(
            completed.stderr.strip(),
            maximum=MAX_ERROR_TEXT,
        ) or ""

    except subprocess.TimeoutExpired as exc:
        error_type = type(exc).__name__
        error_message = (
            f"Command exceeded timeout of "
            f"{timeout_s:.3f}s"
        )

        if isinstance(
            exc.stdout,
            str,
        ):
            stdout = _safe_text(
                exc.stdout.strip(),
                maximum=MAX_RESPONSE_TEXT,
            ) or ""

        if isinstance(
            exc.stderr,
            str,
        ):
            stderr = _safe_text(
                exc.stderr.strip(),
                maximum=MAX_ERROR_TEXT,
            ) or ""

    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    return CommandResult(
        operation=operation,
        command=tuple(command),
        return_code=return_code,
        ok=(
            return_code == 0
            and error_type is None
        ),
        elapsed_ms=(
            time.perf_counter()
            - started
        )
        * 1000.0,
        stdout=stdout,
        stderr=stderr,
        error_type=error_type,
        error_message=error_message,
        started_at_utc=started_at_utc,
        finished_at_utc=utc_now_iso(),
    )


def _detect_worker_count_from_environment() -> tuple[
    int | None,
    str | None,
]:
    """Read worker count from common deployment environment variables."""

    candidates = (
        "WEB_CONCURRENCY",
        "GUNICORN_WORKERS",
        "UVICORN_WORKERS",
    )

    for variable_name in candidates:
        raw_value = os.getenv(
            variable_name
        )

        if raw_value is None:
            continue

        try:
            value = int(
                raw_value
            )

        except ValueError:
            continue

        if value > 0:
            return (
                value,
                f"environment:{variable_name}",
            )

    return (
        None,
        None,
    )


def _detect_worker_count_from_process_table() -> tuple[
    int | None,
    str | None,
]:
    """Best-effort detection of Uvicorn/Gunicorn worker processes."""

    if os.name == "nt":
        command = [
            "tasklist",
            "/FO",
            "CSV",
            "/NH",
        ]

    else:
        command = [
            "ps",
            "-eo",
            "pid=,ppid=,command=",
        ]

    result = _run_command(
        operation="inspect_process_table",
        command=command,
        timeout_s=10.0,
    )

    if not result.ok:
        return (
            None,
            None,
        )

    process_lines = result.stdout.splitlines()

    matching_processes = [
        line
        for line in process_lines
        if (
            "uvicorn" in line.lower()
            or "gunicorn" in line.lower()
        )
    ]

    if not matching_processes:
        return (
            None,
            None,
        )

    return (
        len(matching_processes),
        "process_table",
    )

def _detect_worker_count_from_docker(
    *,
    container_name: str,
    docker_bin: str = "docker",
) -> tuple[int | None, str | None]:
    """Read worker count from supported environment variables in Docker."""

    candidates = (
        "WEB_CONCURRENCY",
        "GUNICORN_WORKERS",
        "UVICORN_WORKERS",
    )

    for variable_name in candidates:
        result = _run_command(
            operation=(
                "inspect_docker_worker_environment_"
                f"{variable_name.lower()}"
            ),
            command=[
                docker_bin,
                "exec",
                container_name,
                "sh",
                "-c",
                (
                    "printf '%s\\n' "
                    f"\"${{{variable_name}:-}}\""
                ),
            ],
            timeout_s=10.0,
        )

        if not result.ok:
            continue

        raw_value = result.stdout.strip()

        if not raw_value:
            continue

        try:
            worker_count = int(raw_value)
        except ValueError:
            continue

        if worker_count <= 0:
            continue

        return (
            worker_count,
            f"docker:{variable_name}",
        )

    return (
        None,
        None,
    )

def _detect_worker_count() -> tuple[
    int | None,
    str | None,
]:
    """Resolve worker count using stable environment data first."""

    environment_value = (
        _detect_worker_count_from_environment()
    )

    if environment_value[0] is not None:
        return environment_value

    return _detect_worker_count_from_process_table()


def _inspect_docker_runtime(
    docker_bin: str = "docker",
) -> dict[str, Any]:
    """Capture Docker runtime information when available."""

    result = _run_command(
        operation="inspect_docker_cityroute_runtime",
        command=[
            docker_bin,
            "ps",
            "--filter",
            "name=cityroute-api",
            "--format",
            "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.State}}",
        ],
        timeout_s=10.0,
    )

    if not result.ok:
        return {
            "available": False,
            "error_type": result.error_type,
            "error_message": (
                result.error_message
                or result.stderr
            ),
        }

    candidates = []

    for line in result.stdout.splitlines():
        fields = line.split("\t")

        if len(fields) != 4:
            continue

        candidates.append(
            {
                "container_id": fields[0],
                "container_name": fields[1],
                "container_image": fields[2],
                "container_state": fields[3],
            }
        )

    return {
        "available": bool(candidates),
        "containers": candidates,
    }


def _collect_runtime_state(
    *,
    stage: str,
    base_url: str,
    startup_timeout_s: float,
    target: str | None,
    docker_bin: str = "docker",
) -> RuntimeState:
    """Capture API health, worker information, and runtime state."""

    liveness_status_code: int | None = None
    readiness_status_code: int | None = None
    liveness_ok = False
    readiness_ok = False
    readiness_payload: dict[str, Any] | None = None
    error_type: str | None = None
    error_message: str | None = None

    try:
        liveness = wait_for_liveness(
            base_url=base_url,
            startup_timeout_s=startup_timeout_s,
        )

        readiness = wait_for_readiness(
            base_url=base_url,
            startup_timeout_s=startup_timeout_s,
            allow_degraded=True,
        )

        liveness_status_code = liveness.status_code
        liveness_ok = liveness.ok

        readiness_status_code = readiness.status_code
        readiness_ok = (
            readiness.status_code == 200
        )

        readiness_payload = (
            readiness.response_json
            if isinstance(
                readiness.response_json,
                dict,
            )
            else None
        )

    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    docker_runtime: dict[str, Any] = {}
    selected_container: dict[str, str] = {}

    worker_count: int | None = None
    worker_source: str | None = None

    if target == "docker":
        docker_runtime = _inspect_docker_runtime(
            docker_bin=docker_bin,
        )

        docker_candidates = docker_runtime.get(
            "containers",
            [],
        )

        if len(docker_candidates) == 1:
            selected_container = docker_candidates[0]

        container_name = selected_container.get(
            "container_name"
        )

        if container_name:
            docker_worker_count = (
                _detect_worker_count_from_docker(
                    container_name=container_name,
                    docker_bin=docker_bin,
                )
            )

            if docker_worker_count[0] is not None:
                worker_count, worker_source = (
                    docker_worker_count
                )

    if worker_count is None:
        worker_count, worker_source = (
            _detect_worker_count()
        )

    return RuntimeState(
        stage=stage,
        captured_at_utc=utc_now_iso(),
        liveness_status_code=liveness_status_code,
        readiness_status_code=readiness_status_code,
        liveness_ok=liveness_ok,
        readiness_ok=readiness_ok,
        readiness_payload=readiness_payload,
        process_environment={
            key: value
            for key, value in os.environ.items()
            if key in {
                "WEB_CONCURRENCY",
                "GUNICORN_WORKERS",
                "UVICORN_WORKERS",
                "CITYROUTE_ENVIRONMENT",
            }
        },
        detected_worker_count=worker_count,
        worker_detection_source=worker_source,
        container_id=(
            selected_container.get(
                "container_id"
            )
        ),
        container_name=(
            selected_container.get(
                "container_name"
            )
        ),
        container_state=(
            selected_container.get(
                "container_state"
            )
        ),
        container_image=(
            selected_container.get(
                "container_image"
            )
        ),
        error_type=error_type,
        error_message=error_message,
    )


# ---------------------------------------------------------------------------
# HTTP execution
# ---------------------------------------------------------------------------


def _request_spec(
    endpoint: str,
) -> tuple[
    str,
    dict[str, Any] | None,
]:
    """Return HTTP method and payload for a benchmark endpoint."""

    if endpoint in {
        "/health/live",
        "/health/ready",
        "/metrics",
    }:
        return (
            "GET",
            None,
        )

    if endpoint == "/route":
        return "GET", ROUTE_PAYLOAD

    if endpoint == MATRIX_ENDPOINT:
        return (
            "POST",
            MATRIX_PAYLOAD,
        )

    raise ValueError(
        f"Unsupported benchmark endpoint: {endpoint}"
    )


async def _execute_request(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    endpoint: str,
    request_index: int,
) -> RequestResult:
    """Execute and classify one benchmark request."""

    method, payload = _request_spec(
        endpoint
    )

    started_at_utc = utc_now_iso()
    started = time.perf_counter()

    status_code: int | None = None
    response_fingerprint: str | None = None
    response_summary: Any | None = None
    error_type: str | None = None
    error_message: str | None = None

    try:
        if endpoint == ROUTE_ENDPOINT:
            response = await client.get(
                f"{base_url}{endpoint}",
                params=payload,
            )

        elif method == "GET":
            response = await client.get(
                f"{base_url}{endpoint}"
            )

        else:
            response = await client.post(
                f"{base_url}{endpoint}",
                json=payload,
            )

        status_code = response.status_code
        response_fingerprint = (
            _response_fingerprint(
                response
            )
        )
        response_summary = (
            _response_summary(
                response
            )
        )

        success = (
            status_code
            == EXPECTED_SUCCESS_STATUS
        )

        if success:
            outcome = "success"

        elif (
            status_code
            in CONTROLLED_FAILURE_STATUSES
        ):
            outcome = "controlled_failure"

        else:
            outcome = "unexpected_failure"

    except asyncio.CancelledError as exc:
        error_type = type(exc).__name__
        error_message = (
            "Request task was cancelled."
        )

        success = False
        outcome = "cancelled"

    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

        success = False
        outcome = "request_error"

    return RequestResult(
        request_index=request_index,
        endpoint=endpoint,
        method=method,
        status_code=status_code,
        elapsed_ms=(
            time.perf_counter()
            - started
        )
        * 1000.0,
        success=success,
        outcome=outcome,
        response_fingerprint=response_fingerprint,
        response_summary=response_summary,
        error_type=error_type,
        error_message=error_message,
        started_at_utc=started_at_utc,
        finished_at_utc=utc_now_iso(),
    )


async def _run_concurrent_requests(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    endpoints: tuple[str, ...],
    requests: int,
    concurrency: int,
) -> list[RequestResult]:
    """Execute a deterministic concurrent workload."""

    semaphore = asyncio.Semaphore(
        concurrency
    )

    async def worker(
        request_index: int,
    ) -> RequestResult:
        endpoint = endpoints[
            request_index % len(endpoints)
        ]

        async with semaphore:
            return await _execute_request(
                client=client,
                base_url=base_url,
                endpoint=endpoint,
                request_index=request_index,
            )

    tasks = [
        asyncio.create_task(
            worker(request_index),
            name=(
                "phase11-multiworker-request-"
                f"{request_index}"
            ),
        )
        for request_index in range(
            requests
        )
    ]

    return list(
        await asyncio.gather(
            *tasks
        )
    )


def _percentile_or_none(
    values: list[float],
    percentile_value: float,
) -> float | None:
    """Return a percentile when latency data exists."""

    if not values:
        return None

    return percentile(
        values,
        percentile_value,
    )


def _throughput_rps(
    *,
    request_count: int,
    elapsed_s: float,
) -> float | None:
    """Calculate throughput while protecting against zero duration."""

    if elapsed_s <= 0:
        return None

    return request_count / elapsed_s

def _endpoint_response_is_deterministic(
    endpoint: str,
) -> bool:
    return endpoint in {
        "/route",
        "/matrix",
    }


def _endpoint_statistics(
    *,
    endpoint: str,
    results: list[RequestResult],
    elapsed_s: float,
) -> EndpointStatistics:
    """Aggregate benchmark results for one endpoint."""

    latencies = [
        result.elapsed_ms
        for result in results
    ]

    success_results = [
        result
        for result in results
        if result.success
    ]

    status_code_counts: dict[str, int] = {}

    outcome_counts: dict[str, int] = {}

    fingerprints = {
        result.response_fingerprint
        for result in success_results
        if result.response_fingerprint is not None
    }

    for result in results:
        status_key = (
            str(result.status_code)
            if result.status_code is not None
            else "none"
        )

        status_code_counts[status_key] = (
            status_code_counts.get(
                status_key,
                0,
            )
            + 1
        )

        outcome_counts[result.outcome] = (
            outcome_counts.get(
                result.outcome,
                0,
            )
            + 1
        )

    consistency_applicable = (
        _endpoint_response_is_deterministic(
            endpoint
        )
    )

    return EndpointStatistics(
        endpoint=endpoint,
        requests=len(results),
        success=len(success_results),
        failures=(
            len(results)
            - len(success_results)
        ),
        min_ms=(
            min(latencies)
            if latencies
            else None
        ),
        max_ms=(
            max(latencies)
            if latencies
            else None
        ),
        mean_ms=(
            statistics.fmean(latencies)
            if latencies
            else None
        ),
        median_ms=(
            statistics.median(latencies)
            if latencies
            else None
        ),
        p95_ms=_percentile_or_none(
            latencies,
            95.0,
        ),
        p99_ms=_percentile_or_none(
            latencies,
            99.0,
        ),
        throughput_rps=_throughput_rps(
            request_count=len(results),
            elapsed_s=elapsed_s,
        ),
        status_code_counts=dict(
            sorted(
                status_code_counts.items()
            )
        ),
        outcome_counts=dict(
            sorted(
                outcome_counts.items()
            )
        ),
        distinct_response_fingerprints=len(
            fingerprints
        ),
        consistency_applicable=(
            consistency_applicable
        ),
        consistency_ok=(
            True
            if not consistency_applicable
            else bool(fingerprints)
            and len(fingerprints) <= 1
        ),
    )


def _consistency_result(
    *,
    endpoint: str,
    results: list[RequestResult],
    maximum_samples: int,
) -> ConsistencyResult:
    """Validate semantic response consistency."""

    if not _endpoint_response_is_deterministic(
        endpoint
    ):
        return ConsistencyResult(
            endpoint=endpoint,
            sampled_successful_responses=0,
            distinct_response_fingerprints=0,
            consistency_ok=True,
            fingerprints=(),
            validation_errors=(),
        )

    successful_fingerprints = [
        result.response_fingerprint
        for result in results
        if (
            result.success
            and result.response_fingerprint
            is not None
        )
    ]

    sampled = successful_fingerprints[
        :maximum_samples
    ]

    distinct_fingerprints = tuple(
        sorted(
            set(sampled)
        )
    )

    errors: list[str] = []

    if not sampled:
        errors.append(
            "Deterministic endpoint produced no successful "
            "responses; consistency cannot be evaluated."
        )

    elif len(distinct_fingerprints) > 1:
        errors.append(
            "Deterministic endpoint produced multiple "
            "response fingerprints under concurrent load."
        )

    return ConsistencyResult(
        endpoint=endpoint,
        sampled_successful_responses=len(
            sampled
        ),
        distinct_response_fingerprints=len(
            distinct_fingerprints
        ),
        consistency_ok=(
            bool(sampled)
            and len(distinct_fingerprints) <= 1
        ),
        fingerprints=distinct_fingerprints,
        validation_errors=tuple(errors),
    )

def _extract_metric_samples(
    text: str,
    metric_name: str,
) -> list[float]:
    """Extract numeric samples from one Prometheus metric family."""

    values: list[float] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if (
            not line
            or line.startswith("#")
        ):
            continue

        sample_name, separator, raw_value = (
            line.rpartition(" ")
        )

        if not separator:
            continue

        normalized_name = sample_name.split(
            "{",
            maxsplit=1,
        )[0]

        if normalized_name != metric_name:
            continue

        try:
            values.append(
                float(raw_value)
            )
        except ValueError:
            continue

    return values


async def _capture_metrics(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    stage: str,
) -> MetricsSnapshot:
    """Capture request and execution metrics."""

    try:
        response = await client.get(
            f"{base_url}{METRICS_ENDPOINT_SUFFIX}"
        )

    except Exception as exc:
        return MetricsSnapshot(
            stage=stage,
            status_code=None,
            request_counter_samples=0,
            request_counter_total=None,
            execution_metric_samples=0,
            raw_text_available=False,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )

    request_counter_samples = (
        _extract_metric_samples(
            response.text,
            METRICS_REQUEST_COUNTER,
        )
    )

    execution_samples = (
        _extract_metric_samples(
            response.text,
            f"{METRICS_EXECUTION_HISTOGRAM}_count",
        )
    )

    return MetricsSnapshot(
        stage=stage,
        status_code=response.status_code,
        request_counter_samples=len(
            request_counter_samples
        ),
        request_counter_total=(
            sum(request_counter_samples)
            if request_counter_samples
            else None
        ),
        execution_metric_samples=len(
            execution_samples
        ),
        raw_text_available=bool(
            response.text
        ),
        error_type=None,
        error_message=None,
    )


# Defined separately so the helper above has one named source of truth.
METRICS_ENDPOINT_SUFFIX = "/metrics"


# ---------------------------------------------------------------------------
# Benchmark validation
# ---------------------------------------------------------------------------


def _validate_runtime(
    *,
    state: RuntimeState,
    expected_workers: int | None,
    require_multiworker: bool,
) -> list[str]:
    """Validate runtime worker configuration."""

    errors: list[str] = []

    if not state.liveness_ok:
        errors.append(
            "Baseline liveness was not healthy."
        )

    if not state.readiness_ok:
        errors.append(
            "Baseline readiness was not healthy."
        )

    if expected_workers is not None:
        if state.detected_worker_count is None:
            errors.append(
                "Expected worker count was supplied, but "
                "runtime worker count could not be detected."
            )

        elif (
            state.detected_worker_count
            != expected_workers
        ):
            errors.append(
                "Detected worker count does not match expected "
                f"value: detected={state.detected_worker_count}, "
                f"expected={expected_workers}."
            )

    if require_multiworker:
        if state.detected_worker_count is None:
            errors.append(
                "Multi-worker mode was required but worker count "
                "could not be detected."
            )

        elif state.detected_worker_count <= 1:
            errors.append(
                "Multi-worker mode was required but detected "
                f"worker count={state.detected_worker_count}."
            )

    return errors


def _validate_request_results(
    *,
    results: list[RequestResult],
    allow_controlled_failures: bool,
) -> tuple[
    list[str],
    list[str],
]:
    """Validate request execution outcomes."""

    errors: list[str] = []
    warnings: list[str] = []

    if not results:
        errors.append(
            "No benchmark request results were collected."
        )
        return (
            errors,
            warnings,
        )

    for result in results:
        if result.success:
            continue

        if (
            allow_controlled_failures
            and result.outcome
            == "controlled_failure"
        ):
            warnings.append(
                "Controlled request failure observed at "
                f"endpoint={result.endpoint}, "
                f"status={result.status_code}."
            )
            continue

        errors.append(
            "Unexpected benchmark request failure: "
            f"endpoint={result.endpoint}, "
            f"status={result.status_code}, "
            f"outcome={result.outcome}, "
            f"error={result.error_message}"
        )

    return (
        errors,
        warnings,
    )


def _validate_consistency(
    *,
    consistency_results: list[ConsistencyResult],
    require_consistency: bool,
) -> list[str]:
    """Validate deterministic endpoint consistency."""

    if not require_consistency:
        return []

    errors: list[str] = []

    for result in consistency_results:
        errors.extend(
            result.validation_errors
        )

    return errors


def _validate_metrics(
    *,
    before: MetricsSnapshot,
    after: MetricsSnapshot,
) -> list[str]:
    """Validate metrics availability and monotonic request accounting."""

    errors: list[str] = []

    if before.status_code != 200:
        errors.append(
            "Metrics endpoint was not healthy before the benchmark."
        )

    if after.status_code != 200:
        errors.append(
            "Metrics endpoint was not healthy after the benchmark."
        )

    if (
        before.request_counter_total is None
    ):
        errors.append(
            "HTTP request metric was not exposed before the benchmark."
        )

    if (
        after.request_counter_total is None
    ):
        errors.append(
            "HTTP request metric was not exposed after the benchmark."
        )

    if (
        before.request_counter_total is not None
        and after.request_counter_total is not None
        and after.request_counter_total
        < before.request_counter_total
    ):
        errors.append(
            "HTTP request counter decreased during the benchmark."
        )

    return errors


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


async def async_main(
    args: argparse.Namespace,
) -> int:
    """Orchestrate one complete multi-worker benchmark run."""

    base_url = _normalize_base_url(
        args.base_url
    )

    endpoints = tuple(
        args.endpoints
        or BENCHMARK_ENDPOINTS
    )

    started_at_utc = utc_now_iso()

    runtime_before = (
        await asyncio.to_thread(
            _collect_runtime_state,
            stage="before",
            base_url=base_url,
            startup_timeout_s=args.startup_timeout_s,
            target=args.target,
        )
    )

    validation_errors = _validate_runtime(
        state=runtime_before,
        expected_workers=args.expected_workers,
        require_multiworker=args.require_multiworker,
    )

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(
            timeout=args.timeout_s,
            connect=args.connect_timeout_s,
        ),
        limits=httpx.Limits(
            max_connections=max(
                DEFAULT_MAX_CONNECTIONS,
                args.concurrency,
            ),
            max_keepalive_connections=max(
                DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
                min(
                    args.concurrency,
                    DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
                ),
            ),
        ),
        follow_redirects=False,
    ) as client:
        metrics_before = await _capture_metrics(
            client=client,
            base_url=base_url,
            stage="before",
        )

        benchmark_started = time.perf_counter()

        request_results = (
            await _run_concurrent_requests(
                client=client,
                base_url=base_url,
                endpoints=endpoints,
                requests=args.requests,
                concurrency=args.concurrency,
            )
        )

        benchmark_elapsed_s = (
            time.perf_counter()
            - benchmark_started
        )

        metrics_after = await _capture_metrics(
            client=client,
            base_url=base_url,
            stage="after",
        )

    runtime_after = (
        await asyncio.to_thread(
            _collect_runtime_state,
            stage="after",
            base_url=base_url,
            startup_timeout_s=args.startup_timeout_s,
            target=args.target,
        )
    )

    after_runtime_errors = _validate_runtime(
        state=runtime_after,
        expected_workers=(
            args.expected_workers
        ),
        require_multiworker=(
            args.require_multiworker
        ),
    )

    validation_errors.extend(
        after_runtime_errors
    )

    request_errors, warnings = (
        _validate_request_results(
            results=request_results,
            allow_controlled_failures=(
                args.allow_controlled_failures
            ),
        )
    )

    validation_errors.extend(
        request_errors
    )

    endpoint_statistics: list[
        EndpointStatistics
    ] = []

    consistency_results: list[
        ConsistencyResult
    ] = []

    for endpoint in endpoints:
        endpoint_results = [
            result
            for result in request_results
            if result.endpoint == endpoint
        ]

        endpoint_statistics.append(
            _endpoint_statistics(
                endpoint=endpoint,
                results=endpoint_results,
                elapsed_s=benchmark_elapsed_s,
            )
        )

        consistency_results.append(
            _consistency_result(
                endpoint=endpoint,
                results=endpoint_results,
                maximum_samples=(
                    args.consistency_samples
                ),
            )
        )

    validation_errors.extend(
        _validate_consistency(
            consistency_results=consistency_results,
            require_consistency=(
                args.require_response_consistency
            ),
        )
    )

    validation_errors.extend(
        _validate_metrics(
            before=metrics_before,
            after=metrics_after,
        )
    )

    successful_requests = sum(
        result.success
        for result in request_results
    )

    failed_requests = (
        len(request_results)
        - successful_requests
    )

    overall_elapsed_ms = (
        benchmark_elapsed_s
        * 1000.0
    )

    overall_throughput = (
        successful_requests
        / benchmark_elapsed_s
        if benchmark_elapsed_s > 0
        else None
    )

    overall_latencies = [
        result.elapsed_ms
        for result in request_results
        if result.status_code is not None
    ]

    validation = ValidationResult(
        validation_errors=tuple(
            validation_errors
        ),
        warnings=tuple(
            warnings
        ),
        overall_ok=not validation_errors,
    )

    timestamp = timestamp_slug()

    raw_path = build_result_path(
        "phase11_multiworker_probe_raw",
        results_dir=args.results_dir,
        target=args.target,
        timestamp=timestamp,
    )

    summary_path = build_result_path(
        "phase11_multiworker_probe_summary",
        results_dir=args.results_dir,
        target=args.target,
        timestamp=timestamp,
    )

    raw_payload: dict[str, Any] = {
        "phase_code": PROJECT_PHASE_CODE,
        "phase_name": PROJECT_PHASE_NAME,
        "benchmark": "phase11_multiworker_probe",
        "started_at_utc": started_at_utc,
        "finished_at_utc": utc_now_iso(),
        "base_url": base_url,
        "target": args.target,
        "configuration": {
            "requests": args.requests,
            "concurrency": args.concurrency,
            "timeout_s": args.timeout_s,
            "connect_timeout_s": (
                args.connect_timeout_s
            ),
            "startup_timeout_s": (
                args.startup_timeout_s
            ),
            "endpoints": list(endpoints),
            "consistency_samples": (
                args.consistency_samples
            ),
            "expected_workers": (
                args.expected_workers
            ),
            "require_multiworker": (
                args.require_multiworker
            ),
            "require_response_consistency": (
                args.require_response_consistency
            ),
            "allow_controlled_failures": (
                args.allow_controlled_failures
            ),
        },
        "runtime_metadata": asdict(
            collect_runtime_metadata(
                base_url=base_url,
            )
        ),
        "runtime_before": asdict(
            runtime_before
        ),
        "runtime_after": asdict(
            runtime_after
        ),
        "metrics_before": asdict(
            metrics_before
        ),
        "metrics_after": asdict(
            metrics_after
        ),
        "benchmark_timing": {
            "elapsed_s": benchmark_elapsed_s,
            "elapsed_ms": overall_elapsed_ms,
        },
        "request_results": [
            asdict(result)
            for result in request_results
        ],
        "endpoint_statistics": [
            asdict(statistics_result)
            for statistics_result
            in endpoint_statistics
        ],
        "consistency_results": [
            asdict(result)
            for result in consistency_results
        ],
        "aggregate": {
            "total_requests": len(
                request_results
            ),
            "successful_requests": (
                successful_requests
            ),
            "failed_requests": (
                failed_requests
            ),
            "success_rate": (
                successful_requests
                / len(request_results)
                if request_results
                else None
            ),
            "throughput_rps": (
                overall_throughput
            ),
            "min_ms": (
                min(overall_latencies)
                if overall_latencies
                else None
            ),
            "max_ms": (
                max(overall_latencies)
                if overall_latencies
                else None
            ),
            "mean_ms": (
                statistics.fmean(
                    overall_latencies
                )
                if overall_latencies
                else None
            ),
            "median_ms": (
                statistics.median(
                    overall_latencies
                )
                if overall_latencies
                else None
            ),
            "p95_ms": _percentile_or_none(
                overall_latencies,
                95.0,
            ),
            "p99_ms": _percentile_or_none(
                overall_latencies,
                99.0,
            ),
        },
        "validation": asdict(
            validation
        ),
    }

    summary_payload: dict[str, Any] = {
        "phase_code": PROJECT_PHASE_CODE,
        "phase_name": PROJECT_PHASE_NAME,
        "benchmark": "phase11_multiworker_probe",
        "base_url": base_url,
        "target": args.target,
        "overall_ok": validation.overall_ok,
        "worker_runtime": {
            "before": {
                "worker_count": (
                    runtime_before.detected_worker_count
                ),
                "detection_source": (
                    runtime_before.worker_detection_source
                ),
            },
            "after": {
                "worker_count": (
                    runtime_after.detected_worker_count
                ),
                "detection_source": (
                    runtime_after.worker_detection_source
                ),
            },
        },
        "configuration": {
            "requests": args.requests,
            "concurrency": args.concurrency,
            "endpoints": list(endpoints),
        },
        "aggregate": raw_payload[
            "aggregate"
        ],
        "endpoint_statistics": [
            asdict(statistics_result)
            for statistics_result
            in endpoint_statistics
        ],
        "consistency": {
            result.endpoint: {
                "sampled_successful_responses": (
                    result.sampled_successful_responses
                ),
                "distinct_response_fingerprints": (
                    result.distinct_response_fingerprints
                ),
                "consistency_ok": (
                    result.consistency_ok
                ),
                "validation_errors": list(
                    result.validation_errors
                ),
            }
            for result in consistency_results
        },
        "metrics": {
            "request_counter_before": (
                metrics_before.request_counter_total
            ),
            "request_counter_after": (
                metrics_after.request_counter_total
            ),
            "request_counter_delta": (
                None
                if (
                    metrics_before.request_counter_total
                    is None
                    or metrics_after.request_counter_total
                    is None
                )
                else (
                    metrics_after.request_counter_total
                    - metrics_before.request_counter_total
                )
            ),
            "execution_metric_samples_before": (
                metrics_before.execution_metric_samples
            ),
            "execution_metric_samples_after": (
                metrics_after.execution_metric_samples
            ),
        },
        "validation_errors": list(
            validation.validation_errors
        ),
        "warnings": list(
            validation.warnings
        ),
        "raw_result_path": str(
            raw_path
        ),
        "summary_result_path": str(
            summary_path
        ),
    }

    write_json(
        raw_path,
        raw_payload,
    )

    write_json(
        summary_path,
        summary_payload,
    )

    print_json(
        summary_payload
    )

    if (
        args.fail_on_validation_error
        and validation.validation_errors
    ):
        return 1

    return 0 if validation.overall_ok else 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Parse CLI arguments and execute the benchmark."""

    args = parse_args()

    return asyncio.run(
        async_main(args)
    )


if __name__ == "__main__":
    try:
        raise SystemExit(
            main()
        )
    except KeyboardInterrupt:
        print(
            "Phase 11 multi-worker probe interrupted",
            file=sys.stderr,
        )
        raise SystemExit(130) from None