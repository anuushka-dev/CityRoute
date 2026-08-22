# benchmarks/phase_11/phase11_worker_restart_probe.py

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

# Support both:
#   python benchmarks/phase_11/phase11_worker_restart_probe.py
#   python -m benchmarks.phase_11.phase11_worker_restart_probe

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

DEFAULT_DOCKER_BIN = "docker"

DEFAULT_REQUEST_COUNT = 8
DEFAULT_MATRIX_SIZE = 10

DEFAULT_REQUEST_TIMEOUT_S = max(
    DEFAULT_TIMEOUT_S,
    30.0,
)
DEFAULT_STARTUP_TIMEOUT_S = 180.0
DEFAULT_DOWN_TIMEOUT_S = 30.0
DEFAULT_POLL_INTERVAL_S = 0.5
DEFAULT_COMMAND_TIMEOUT_S = 120.0

MIN_REQUEST_COUNT = 1
MAX_REQUEST_COUNT = 100

MIN_MATRIX_SIZE = 2
MAX_MATRIX_SIZE = 25

MIN_TIMEOUT_S = 1.0
MAX_TIMEOUT_S = 600.0

MIN_POLL_INTERVAL_S = 0.05
MAX_POLL_INTERVAL_S = 5.0

MATRIX_ENDPOINT = "/matrix"
LIVENESS_ENDPOINT = "/health/live"
READINESS_ENDPOINT = "/health/ready"
HEALTH_ENDPOINT = "/health"
METRICS_ENDPOINT = "/metrics"

MATRIX_ALGORITHM = "source_dijkstra"
MATRIX_USE_CACHE = False

HTTP_SUCCESS_STATUS = 200

PROCESS_START_METRIC = "process_start_time_seconds"

EXECUTION_METRIC = (
    "cityroute_request_execution_seconds"
)
REQUEST_COUNTER_METRIC = (
    "cityroute_http_requests_total"
)

EXPECTED_RESTART_STATES = frozenset(
    {
        "created",
        "restarting",
        "exited",
        "running",
    }
)

MAX_RESPONSE_TEXT = 1_000
MAX_ERROR_TEXT = 1_000
MAX_LOG_TAIL_CHARS = 20_000

@dataclass(frozen=True)
class CommandResult:
    """Structured result of one process or Docker command."""

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
class RuntimeState:
    """Observed service and process state."""

    stage: str
    captured_at_utc: str
    container_id: str | None
    container_name: str | None
    container_image: str | None
    container_state: str | None
    container_running: bool | None
    container_restarting: bool | None
    process_start_time_seconds: float | None
    liveness_status_code: int | None
    readiness_status_code: int | None
    liveness_ok: bool
    readiness_ok: bool
    readiness_payload: dict[str, Any] | None
    error_type: str | None
    error_message: str | None


@dataclass(frozen=True)
class EndpointResult:
    """Result of one endpoint request."""

    stage: str
    request_index: int
    path: str
    method: str
    status_code: int | None
    elapsed_ms: float
    success: bool
    response_fingerprint: str | None
    response_summary: Any | None
    error_type: str | None
    error_message: str | None
    started_at_utc: str
    finished_at_utc: str


@dataclass(frozen=True)
class MetricsSnapshot:
    """Selected metrics captured before or after worker restart."""

    stage: str
    status_code: int | None
    raw_text_available: bool
    process_start_time_seconds: float | None
    request_counter_total: float | None
    execution_metric_samples: int
    error_type: str | None
    error_message: str | None


@dataclass(frozen=True)
class RestartEvidence:
    """Evidence proving an actual worker/container restart occurred."""

    restart_command: CommandResult
    restart_command_ok: bool
    pre_restart_container_id: str | None
    post_restart_container_id: str | None
    pre_restart_process_start_time: float | None
    post_restart_process_start_time: float | None
    process_start_time_changed: bool
    container_identity_changed: bool
    recovery_state_observed: bool


@dataclass(frozen=True)
class ValidationResult:
    """Final worker-restart validation state."""

    validation_errors: tuple[str, ...]
    warnings: tuple[str, ...]
    overall_ok: bool

def parse_args() -> argparse.Namespace:
    """Parse and validate worker-restart benchmark arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Prove Phase 11 worker/process restart recovery. The probe "
            "captures healthy runtime state, performs an intentional "
            "worker/container restart, proves the runtime identity changed, "
            "and validates liveness, readiness, metrics, and endpoint "
            "recovery without confusing temporary failure with restart."
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
            "Execution target. Docker restarts the CityRoute container; "
            "local sends a process signal and requires --pid."
        ),
    )

    parser.add_argument(
        "--results-dir",
        type=Path,
        default=None,
        help=(
            "Explicit output directory. Overrides the target-based "
            "Phase 11 result location."
        ),
    )

    parser.add_argument(
        "--container",
        default=None,
        help=(
            "Exact CityRoute Docker container name or ID. When omitted, "
            "a unique running CityRoute container is discovered."
        ),
    )

    parser.add_argument(
        "--docker-bin",
        default=DEFAULT_DOCKER_BIN,
        help=(
            "Docker CLI executable. "
            f"Default: {DEFAULT_DOCKER_BIN}"
        ),
    )

    parser.add_argument(
        "--pid",
        type=int,
        default=None,
        help=(
            "Local API process PID. Required for --target local."
        ),
    )

    parser.add_argument(
        "--request-count",
        type=int,
        default=DEFAULT_REQUEST_COUNT,
        help=(
            "Validation requests before and after restart. "
            f"Default: {DEFAULT_REQUEST_COUNT}"
        ),
    )

    parser.add_argument(
        "--matrix-size",
        type=int,
        default=DEFAULT_MATRIX_SIZE,
        help=(
            "Number of matrix locations for each request. "
            f"Default: {DEFAULT_MATRIX_SIZE}"
        ),
    )

    parser.add_argument(
        "--request-timeout-s",
        type=float,
        default=DEFAULT_REQUEST_TIMEOUT_S,
        help=(
            "HTTP timeout for workload requests. "
            f"Default: {DEFAULT_REQUEST_TIMEOUT_S}"
        ),
    )

    parser.add_argument(
        "--startup-timeout-s",
        type=float,
        default=DEFAULT_STARTUP_TIMEOUT_S,
        help=(
            "Maximum wait for liveness/readiness recovery. "
            f"Default: {DEFAULT_STARTUP_TIMEOUT_S}"
        ),
    )

    parser.add_argument(
        "--down-timeout-s",
        type=float,
        default=DEFAULT_DOWN_TIMEOUT_S,
        help=(
            "Maximum wait for the API to become unavailable after "
            f"restart injection. Default: {DEFAULT_DOWN_TIMEOUT_S}"
        ),
    )

    parser.add_argument(
        "--poll-interval-s",
        type=float,
        default=DEFAULT_POLL_INTERVAL_S,
        help=(
            "Runtime/container polling interval. "
            f"Default: {DEFAULT_POLL_INTERVAL_S}"
        ),
    )

    parser.add_argument(
        "--require-process-start-change",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Require process_start_time_seconds to change across restart. "
            "Default: enabled."
        ),
    )

    parser.add_argument(
        "--require-container-identity-change",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Require Docker container identity to change. Disabled by "
            "default because 'docker restart' normally preserves identity."
        ),
    )

    parser.add_argument(
        "--require-post-restart-metrics",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Require /metrics to expose process/reliability metrics after "
            "restart. Default: enabled."
        ),
    )

    parser.add_argument(
        "--fail-on-validation-error",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Exit non-zero when restart validation fails. "
            "Default: enabled."
        ),
    )

    args = parser.parse_args()

    if not (
        MIN_REQUEST_COUNT
        <= args.request_count
        <= MAX_REQUEST_COUNT
    ):
        parser.error(
            "--request-count must be between "
            f"{MIN_REQUEST_COUNT} and {MAX_REQUEST_COUNT}"
        )

    if not (
        MIN_MATRIX_SIZE
        <= args.matrix_size
        <= MAX_MATRIX_SIZE
    ):
        parser.error(
            "--matrix-size must be between "
            f"{MIN_MATRIX_SIZE} and {MAX_MATRIX_SIZE}"
        )

    for (
        argument_name,
        argument_value,
    ) in (
        ("--request-timeout-s", args.request_timeout_s),
        ("--startup-timeout-s", args.startup_timeout_s),
        ("--down-timeout-s", args.down_timeout_s),
    ):
        if not (
            MIN_TIMEOUT_S
            <= argument_value
            <= MAX_TIMEOUT_S
        ):
            parser.error(
                f"{argument_name} must be between "
                f"{MIN_TIMEOUT_S} and {MAX_TIMEOUT_S}"
            )

    if not (
        MIN_POLL_INTERVAL_S
        <= args.poll_interval_s
        <= MAX_POLL_INTERVAL_S
    ):
        parser.error(
            "--poll-interval-s must be between "
            f"{MIN_POLL_INTERVAL_S} and "
            f"{MAX_POLL_INTERVAL_S}"
        )

    if args.target == "local" and args.pid is None:
        parser.error(
            "--target local requires --pid"
        )

    if args.pid is not None and args.pid <= 0:
        parser.error(
            "--pid must be greater than zero"
        )

    return args

def _safe_text(
    value: str | None,
    *,
    maximum: int,
) -> str | None:
    """Bound text retained in evidence files."""

    if value is None:
        return None

    if len(value) <= maximum:
        return value

    return (
        value[:maximum]
        + "...[truncated]"
    )


def _normalize_base_url(
    base_url: str,
) -> str:
    """Normalize the target API base URL."""

    normalized = base_url.strip().rstrip("/")

    if not normalized:
        raise ValueError(
            "base URL must not be empty"
        )

    return normalized


def _parse_boolean(
    value: str,
) -> bool | None:
    """Parse Docker boolean output explicitly."""

    normalized = value.strip().lower()

    if normalized == "true":
        return True

    if normalized == "false":
        return False

    return None


def _response_fingerprint(
    response: httpx.Response,
) -> str | None:
    """Create a stable semantic fingerprint for JSON responses."""

    try:
        payload = response.json()

    except ValueError:
        return json.dumps(
            _safe_text(
                response.text,
                maximum=MAX_RESPONSE_TEXT,
            ),
            sort_keys=True,
        )

    normalized = _normalize_json(
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


def _normalize_json(
    value: Any,
) -> Any:
    """Remove known runtime-only fields from fingerprints."""

    if isinstance(
        value,
        dict,
    ):
        return {
            key: _normalize_json(item)
            for key, item in sorted(
                value.items()
            )
            if key not in {
                "uptime_s",
                "time_ms",
                "elapsed_ms",
                "generation_time_ms",
                "request_id",
            }
        }

    if isinstance(
        value,
        list,
    ):
        return [
            _normalize_json(item)
            for item in value
        ]

    return value


def _response_summary(
    response: httpx.Response,
) -> Any | None:
    """Build a bounded response summary."""

    try:
        payload = response.json()

    except ValueError:
        return _safe_text(
            response.text,
            maximum=MAX_RESPONSE_TEXT,
        )

    if isinstance(
        payload,
        dict,
    ):
        summary_keys = (
            "status",
            "phase",
            "algorithm",
            "n",
            "cache",
            "graph_loaded",
            "ready",
            "accepting_requests",
            "shutting_down",
        )

        return {
            key: payload.get(key)
            for key in summary_keys
            if key in payload
        }

    return payload

def _run_command(
    *,
    operation: str,
    command: list[str],
    timeout_s: float,
) -> CommandResult:
    """Execute a command while retaining timing and failure context."""

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

    except subprocess.TimeoutExpired:
        error_type = "TimeoutExpired"
        error_message = (
            f"Command exceeded timeout of {timeout_s:.3f}s"
        )

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

def _inspect_container(
    *,
    docker_bin: str,
    container: str,
) -> tuple[
    RuntimeState | None,
    CommandResult,
]:
    """Inspect the selected Docker container."""

    result = _run_command(
        operation="inspect_container",
        command=[
            docker_bin,
            "inspect",
            "--format",
            (
                "{{.Id}}\t"
                "{{.Name}}\t"
                "{{.Config.Image}}\t"
                "{{.State.Status}}\t"
                "{{.State.Running}}\t"
                "{{.State.Restarting}}"
            ),
            container,
        ],
        timeout_s=10.0,
    )

    if not result.ok:
        return None, result

    fields = result.stdout.split("\t")

    if len(fields) != 6:
        parse_result = CommandResult(
            **{
                **asdict(result),
                "ok": False,
                "error_type": "ContainerParseError",
                "error_message": (
                    "Unexpected Docker inspect output: "
                    f"{result.stdout!r}"
                ),
            }
        )

        return None, parse_result

    (
        container_id,
        raw_name,
        image,
        state,
        raw_running,
        raw_restarting,
    ) = fields

    running = _parse_boolean(
        raw_running
    )
    restarting = _parse_boolean(
        raw_restarting
    )

    if running is None or restarting is None:
        parse_result = CommandResult(
            **{
                **asdict(result),
                "ok": False,
                "error_type": "ContainerBooleanParseError",
                "error_message": (
                    "Unable to parse Docker lifecycle flags: "
                    f"{result.stdout!r}"
                ),
            }
        )

        return None, parse_result

    return (
        RuntimeState(
            stage="container_inspection",
            captured_at_utc=utc_now_iso(),
            container_id=container_id,
            container_name=raw_name.lstrip("/"),
            container_image=image,
            container_state=state,
            container_running=running,
            container_restarting=restarting,
            process_start_time_seconds=None,
            liveness_status_code=None,
            readiness_status_code=None,
            liveness_ok=False,
            readiness_ok=False,
            readiness_payload=None,
            error_type=None,
            error_message=None,
        ),
        result,
    )


def _discover_container(
    *,
    docker_bin: str,
) -> tuple[
    dict[str, str],
    CommandResult,
]:
    """Find one unique running CityRoute container."""

    result = _run_command(
        operation="discover_cityroute_container",
        command=[
            docker_bin,
            "ps",
            "-a",
            "--format",
            "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.State}}",
        ],
        timeout_s=10.0,
    )

    if not result.ok:
        raise RuntimeError(
            "Unable to list Docker containers: "
            f"{result.stderr or result.error_message}"
        )

    candidates: list[dict[str, str]] = []

    for line in result.stdout.splitlines():
        fields = line.split("\t")

        if len(fields) != 4:
            continue

        container_id, name, image, state = fields

        if "cityroute" not in (
            f"{name} {image}"
        ).lower():
            continue

        candidates.append(
            {
                "id": container_id,
                "name": name,
                "image": image,
                "state": state,
            }
        )

    running = [
        candidate
        for candidate in candidates
        if candidate["state"] == "running"
    ]

    if len(running) == 1:
        return (
            running[0],
            result,
        )

    if not candidates:
        raise RuntimeError(
            "No CityRoute Docker container found. "
            "Provide --container explicitly."
        )

    choices = ", ".join(
        (
            f"{candidate['name']} "
            f"({candidate['state']})"
        )
        for candidate in candidates
    )

    raise RuntimeError(
        "Unable to uniquely select the CityRoute container. "
        f"Candidates: {choices}"
    )


def _resolve_container(
    *,
    docker_bin: str,
    requested: str | None,
) -> tuple[
    dict[str, str],
    dict[str, Any],
]:
    """Resolve an explicit or automatically discovered container."""

    if requested is None:
        container, command = _discover_container(
            docker_bin=docker_bin
        )

        return (
            container,
            {
                "mode": "auto_discovery",
                "command": asdict(command),
            },
        )

    inspected, command = _inspect_container(
        docker_bin=docker_bin,
        container=requested,
    )

    if inspected is None:
        raise RuntimeError(
            f"Unable to inspect requested container "
            f"{requested!r}: "
            f"{command.stderr or command.error_message}"
        )

    if inspected.container_running is not True:
        raise RuntimeError(
            "Requested CityRoute container is not running: "
            f"{inspected.container_state}"
        )

    return (
        {
            "id": inspected.container_id or requested,
            "name": inspected.container_name or requested,
            "image": inspected.container_image or "",
            "state": inspected.container_state or "",
        },
        {
            "mode": "explicit",
            "command": asdict(command),
        },
    )


def _send_local_restart_signal(
    *,
    pid: int,
) -> CommandResult:
    """Terminate a local worker/process to force a restart."""

    started_at_utc = utc_now_iso()
    started = time.perf_counter()

    error_type: str | None = None
    error_message: str | None = None

    try:
        if os.name == "nt":
            os.kill(
                pid,
                signal.CTRL_BREAK_EVENT,
            )
            signal_name = "CTRL_BREAK_EVENT"

        else:
            os.kill(
                pid,
                signal.SIGTERM,
            )
            signal_name = "SIGTERM"

    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)
        signal_name = (
            "CTRL_BREAK_EVENT"
            if os.name == "nt"
            else "SIGTERM"
        )

    return CommandResult(
        operation="restart_local_process",
        command=(
            "signal",
            str(pid),
            signal_name,
        ),
        return_code=(
            None
            if error_type
            else 0
        ),
        ok=error_type is None,
        elapsed_ms=(
            time.perf_counter()
            - started
        )
        * 1000.0,
        stdout="",
        stderr="",
        error_type=error_type,
        error_message=error_message,
        started_at_utc=started_at_utc,
        finished_at_utc=utc_now_iso(),
    )


def _docker_restart(
    *,
    docker_bin: str,
    container: str,
    timeout_s: float,
) -> CommandResult:
    """Restart the Docker container as the worker restart mechanism."""

    return _run_command(
        operation="restart_cityroute_worker_container",
        command=[
            docker_bin,
            "restart",
            "--time",
            str(
                max(
                    1,
                    int(timeout_s),
                )
            ),
            container,
        ],
        timeout_s=(
            timeout_s
            + DEFAULT_COMMAND_TIMEOUT_S
        ),
    )


def _wait_for_container_running(
    *,
    docker_bin: str,
    container: str,
    timeout_s: float,
    poll_interval_s: float,
) -> RuntimeState:
    """Wait until Docker reports the container running again."""

    deadline = (
        time.perf_counter()
        + timeout_s
    )

    last_state: RuntimeState | None = None

    while time.perf_counter() < deadline:
        state, command = _inspect_container(
            docker_bin=docker_bin,
            container=container,
        )

        if state is None:
            raise RuntimeError(
                "Container inspection failed while waiting for "
                f"recovery: {command.error_message}"
            )

        last_state = state

        if (
            state.container_running is True
            and state.container_restarting is False
            and state.container_state == "running"
        ):
            return state

        time.sleep(
            poll_interval_s
        )

    raise TimeoutError(
        "Docker container did not return to running state within "
        f"{timeout_s:.3f}s. "
        f"last_state={asdict(last_state) if last_state else None}"
    )

def _extract_metric_values(
    text: str,
    metric_name: str,
) -> list[float]:
    """Extract numeric samples from a Prometheus metric family."""

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


async def _get_endpoint(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    path: str,
    stage: str,
    request_index: int,
) -> EndpointResult:
    """Execute one lifecycle or recovery endpoint request."""

    started_at_utc = utc_now_iso()
    started = time.perf_counter()

    status_code: int | None = None
    response_fingerprint: str | None = None
    response_summary: Any | None = None
    error_type: str | None = None
    error_message: str | None = None

    try:
        response = await client.get(
            f"{base_url}{path}"
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

    except asyncio.CancelledError as exc:
        error_type = type(exc).__name__
        error_message = (
            "Request was cancelled."
        )

    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    return EndpointResult(
        stage=stage,
        request_index=request_index,
        path=path,
        method="GET",
        status_code=status_code,
        elapsed_ms=(
            time.perf_counter()
            - started
        )
        * 1000.0,
        success=(
            status_code
            == HTTP_SUCCESS_STATUS
        ),
        response_fingerprint=response_fingerprint,
        response_summary=response_summary,
        error_type=error_type,
        error_message=error_message,
        started_at_utc=started_at_utc,
        finished_at_utc=utc_now_iso(),
    )


async def _capture_metrics(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    stage: str,
) -> MetricsSnapshot:
    """Capture process-start and request metrics."""

    try:
        response = await client.get(
            f"{base_url}{METRICS_ENDPOINT}"
        )

        process_start_values = (
            _extract_metric_values(
                response.text,
                PROCESS_START_METRIC,
            )
        )

        request_counter_values = (
            _extract_metric_values(
                response.text,
                REQUEST_COUNTER_METRIC,
            )
        )

        execution_values = (
            _extract_metric_values(
                response.text,
                EXECUTION_METRIC,
            )
        )

        return MetricsSnapshot(
            stage=stage,
            status_code=response.status_code,
            raw_text_available=bool(
                response.text
            ),
            process_start_time_seconds=(
                process_start_values[0]
                if process_start_values
                else None
            ),
            request_counter_total=(
                sum(request_counter_values)
                if request_counter_values
                else None
            ),
            execution_metric_samples=len(
                execution_values
            ),
            error_type=None,
            error_message=None,
        )

    except Exception as exc:
        return MetricsSnapshot(
            stage=stage,
            status_code=None,
            raw_text_available=False,
            process_start_time_seconds=None,
            request_counter_total=None,
            execution_metric_samples=0,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )


async def _capture_runtime_state(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    stage: str,
    startup_timeout_s: float,
    container: dict[str, str] | None,
    docker_bin: str,
) -> tuple[
    RuntimeState,
    MetricsSnapshot,
]:
    """Capture health/readiness plus process/container identity."""

    error_type: str | None = None
    error_message: str | None = None

    liveness_status_code: int | None = None
    readiness_status_code: int | None = None
    liveness_ok = False
    readiness_ok = False
    readiness_payload: dict[str, Any] | None = None

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

        liveness_status_code = (
            liveness.status_code
        )
        liveness_ok = liveness.ok

        readiness_status_code = (
            readiness.status_code
        )
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

    container_state: RuntimeState | None = None

    if container is not None:
        container_state, inspect_result = (
            _inspect_container(
                docker_bin=docker_bin,
                container=container["name"],
            )
        )

        if (
            container_state is None
            and error_type is None
        ):
            error_type = (
                inspect_result.error_type
                or "ContainerInspectionError"
            )
            error_message = (
                inspect_result.error_message
                or inspect_result.stderr
            )

    metrics = await _capture_metrics(
        client=client,
        base_url=base_url,
        stage=stage,
    )

    state = RuntimeState(
        stage=stage,
        captured_at_utc=utc_now_iso(),
        container_id=(
            None
            if container_state is None
            else container_state.container_id
        ),
        container_name=(
            None
            if container_state is None
            else container_state.container_name
        ),
        container_image=(
            None
            if container_state is None
            else container_state.container_image
        ),
        container_state=(
            None
            if container_state is None
            else container_state.container_state
        ),
        container_running=(
            None
            if container_state is None
            else container_state.container_running
        ),
        container_restarting=(
            None
            if container_state is None
            else container_state.container_restarting
        ),
        process_start_time_seconds=(
            metrics.process_start_time_seconds
        ),
        liveness_status_code=liveness_status_code,
        readiness_status_code=readiness_status_code,
        liveness_ok=liveness_ok,
        readiness_ok=readiness_ok,
        readiness_payload=readiness_payload,
        error_type=error_type,
        error_message=error_message,
    )

    return (
        state,
        metrics,
    )

def _generated_locations(
    *,
    matrix_size: int,
    request_variant: int,
) -> list[dict[str, Any]]:
    """Generate deterministic coordinates for restart validation."""

    center_lat = 26.4499
    center_lon = 80.3319
    spacing = 0.0016
    variant_shift = (
        request_variant % 7
    ) * 0.0000001

    locations: list[dict[str, Any]] = []

    for index in range(matrix_size):
        row, column = divmod(
            index,
            5,
        )

        locations.append(
            {
                "id": f"p{index:02d}",
                "lat": round(
                    center_lat
                    + ((row - 2) * spacing)
                    + variant_shift,
                    7,
                ),
                "lon": round(
                    center_lon
                    + ((column - 2) * spacing)
                    - variant_shift,
                    7,
                ),
            }
        )

    return locations


def _build_matrix_payload(
    *,
    matrix_size: int,
    request_variant: int,
) -> dict[str, Any]:
    """Build one deterministic uncached matrix request."""

    return {
        "locations": _generated_locations(
            matrix_size=matrix_size,
            request_variant=request_variant,
        ),
        "algorithm": MATRIX_ALGORITHM,
        "use_cache": MATRIX_USE_CACHE,
    }


async def _run_matrix_validation_requests(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    stage: str,
    request_count: int,
    matrix_size: int,
) -> list[EndpointResult]:
    """Run post-start validation workload."""

    results: list[EndpointResult] = []

    for request_index in range(
        request_count
    ):
        started_at_utc = utc_now_iso()
        started = time.perf_counter()

        status_code: int | None = None
        fingerprint: str | None = None
        summary: Any | None = None
        error_type: str | None = None
        error_message: str | None = None

        try:
            response = await client.post(
                f"{base_url}{MATRIX_ENDPOINT}",
                json=_build_matrix_payload(
                    matrix_size=matrix_size,
                    request_variant=(
                        request_index + 1
                    ),
                ),
            )

            status_code = response.status_code
            fingerprint = (
                _response_fingerprint(
                    response
                )
            )
            summary = (
                _response_summary(
                    response
                )
            )

        except Exception as exc:
            error_type = type(exc).__name__
            error_message = str(exc)

        results.append(
            EndpointResult(
                stage=stage,
                request_index=request_index,
                path=MATRIX_ENDPOINT,
                method="POST",
                status_code=status_code,
                elapsed_ms=(
                    time.perf_counter()
                    - started
                )
                * 1000.0,
                success=(
                    status_code
                    == HTTP_SUCCESS_STATUS
                ),
                response_fingerprint=fingerprint,
                response_summary=summary,
                error_type=error_type,
                error_message=error_message,
                started_at_utc=started_at_utc,
                finished_at_utc=utc_now_iso(),
            )
        )

    return results

def _validate_baseline(
    *,
    runtime: RuntimeState,
    metrics: MetricsSnapshot,
) -> list[str]:
    """Validate healthy runtime before restart."""

    errors: list[str] = []

    if not runtime.liveness_ok:
        errors.append(
            "Baseline liveness was not healthy."
        )

    if not runtime.readiness_ok:
        errors.append(
            "Baseline readiness was not healthy."
        )

    if (
        metrics.process_start_time_seconds
        is None
    ):
        errors.append(
            "Baseline process_start_time_seconds was not exposed."
        )

    if (
        metrics.status_code
        != HTTP_SUCCESS_STATUS
    ):
        errors.append(
            "Baseline metrics endpoint did not return HTTP 200."
        )

    return errors


def _validate_restart_evidence(
    *,
    evidence: RestartEvidence,
    require_process_start_change: bool,
    require_container_identity_change: bool,
) -> list[str]:
    """Validate that an actual restart happened."""

    errors: list[str] = []

    if not evidence.restart_command_ok:
        errors.append(
            "Worker restart command failed."
        )

    if not evidence.recovery_state_observed:
        errors.append(
            "Post-restart running state was not observed."
        )

    if (
        require_process_start_change
        and not evidence.process_start_time_changed
    ):
        errors.append(
            "Process start time did not change across restart; "
            "an actual worker/process restart was not proven."
        )

    if (
        require_container_identity_change
        and not evidence.container_identity_changed
    ):
        errors.append(
            "Container identity did not change as required."
        )

    return errors


def _validate_recovery(
    *,
    runtime_after: RuntimeState,
    metrics_after: MetricsSnapshot,
    endpoint_results: list[EndpointResult],
    require_post_restart_metrics: bool,
) -> list[str]:
    """Validate service recovery after worker restart."""

    errors: list[str] = []

    if not runtime_after.liveness_ok:
        errors.append(
            "Liveness did not recover after worker restart."
        )

    if not runtime_after.readiness_ok:
        errors.append(
            "Readiness did not recover after worker restart."
        )

    if (
        require_post_restart_metrics
        and metrics_after.status_code
        != HTTP_SUCCESS_STATUS
    ):
        errors.append(
            "Metrics endpoint did not recover after worker restart."
        )

    if (
        require_post_restart_metrics
        and metrics_after.process_start_time_seconds
        is None
    ):
        errors.append(
            "Post-restart process_start_time_seconds was not exposed."
        )

    if not endpoint_results:
        errors.append(
            "No post-restart endpoint validation requests were collected."
        )

    failed_requests = [
        result
        for result in endpoint_results
        if not result.success
    ]

    if failed_requests:
        errors.append(
            "Post-restart endpoint validation produced "
            f"{len(failed_requests)} failed request(s)."
        )

    return errors


def _validate_response_consistency(
    *,
    pre_restart_results: list[EndpointResult],
    post_restart_results: list[EndpointResult],
) -> list[str]:
    """Validate restart non-regression for corresponding workloads."""

    errors: list[str] = []

    if len(pre_restart_results) != len(post_restart_results):
        errors.append(
            "Pre- and post-restart request counts differ: "
            f"before={len(pre_restart_results)}, "
            f"after={len(post_restart_results)}."
        )
        return errors

    for before, after in zip(
        pre_restart_results,
        post_restart_results,
    ):
        if not before.success:
            continue

        if not after.success:
            errors.append(
                "A previously successful workload failed after "
                "worker restart: "
                f"request_index={before.request_index}."
            )
            continue

        if (
            before.response_fingerprint is not None
            and after.response_fingerprint is not None
            and (
                before.response_fingerprint
                != after.response_fingerprint
            )
        ):
            errors.append(
                "Worker restart changed the semantic response for "
                "the same workload: "
                f"request_index={before.request_index}."
            )

    return errors

def _metric_counter_delta(
    before: float | None,
    after: float | None,
) -> float | None:
    """Calculate a monotonic metric delta."""

    if (
        before is None
        or after is None
    ):
        return None

    return after - before

async def async_main(
    args: argparse.Namespace,
) -> int:
    """Orchestrate one worker-restart benchmark."""

    base_url = _normalize_base_url(
        args.base_url
    )

    started_at_utc = utc_now_iso()

    container: dict[str, str] | None = None
    container_resolution: dict[str, Any] | None = None

    if args.target == "docker":
        container, container_resolution = (
            await asyncio.to_thread(
                _resolve_container,
                docker_bin=args.docker_bin,
                requested=args.container,
            )
        )

    async with httpx.AsyncClient(
        timeout=args.request_timeout_s,
        limits=httpx.Limits(
            max_connections=max(
                32,
                args.request_count + 8,
            ),
            max_keepalive_connections=32,
        ),
    ) as client:
        (
            runtime_before,
            metrics_before,
        ) = await _capture_runtime_state(
            client=client,
            base_url=base_url,
            stage="before",
            startup_timeout_s=args.startup_timeout_s,
            container=container,
            docker_bin=args.docker_bin,
        )

        validation_errors = _validate_baseline(
            runtime=runtime_before,
            metrics=metrics_before,
        )

        pre_restart_probe_results = (
            await _run_matrix_validation_requests(
                client=client,
                base_url=base_url,
                stage="before",
                request_count=args.request_count,
                matrix_size=args.matrix_size,
            )
        )

        pre_restart_failures = [
            result
            for result in pre_restart_probe_results
            if not result.success
        ]

        if pre_restart_failures:
            validation_errors.append(
                "Baseline matrix validation produced "
                f"{len(pre_restart_failures)} failed request(s)."
            )

        pre_restart_container_id = (
            runtime_before.container_id
        )
        pre_restart_process_start = (
            runtime_before.process_start_time_seconds
        )

        if args.target == "docker":
            if container is None:
                raise RuntimeError(
                    "Docker target requires a resolved container."
                )

            restart_command = (
                await asyncio.to_thread(
                    _docker_restart,
                    docker_bin=args.docker_bin,
                    container=container["name"],
                    timeout_s=args.startup_timeout_s,
                )
            )

            recovery_state = (
                await asyncio.to_thread(
                    _wait_for_container_running,
                    docker_bin=args.docker_bin,
                    container=container["name"],
                    timeout_s=args.startup_timeout_s,
                    poll_interval_s=args.poll_interval_s,
                )
                if restart_command.ok
                else None
            )

        else:
            if args.pid is None:
                raise RuntimeError(
                    "Local target requires --pid."
                )

            restart_command = (
                await asyncio.to_thread(
                    _send_local_restart_signal,
                    pid=args.pid,
                )
            )

            recovery_state = None

        (
            runtime_after,
            metrics_after,
        ) = await _capture_runtime_state(
            client=client,
            base_url=base_url,
            stage="after",
            startup_timeout_s=args.startup_timeout_s,
            container=container,
            docker_bin=args.docker_bin,
        )

        if recovery_state is not None:
            runtime_after = RuntimeState(
                **{
                    **asdict(runtime_after),
                    "container_id": (
                        recovery_state.container_id
                    ),
                    "container_name": (
                        recovery_state.container_name
                    ),
                    "container_image": (
                        recovery_state.container_image
                    ),
                    "container_state": (
                        recovery_state.container_state
                    ),
                    "container_running": (
                        recovery_state.container_running
                    ),
                    "container_restarting": (
                        recovery_state.container_restarting
                    ),
                }
            )

        post_restart_probe_results = (
            await _run_matrix_validation_requests(
                client=client,
                base_url=base_url,
                stage="after",
                request_count=args.request_count,
                matrix_size=args.matrix_size,
            )
        )

    process_start_changed = (
        pre_restart_process_start is not None
        and runtime_after.process_start_time_seconds
        is not None
        and (
            runtime_after.process_start_time_seconds
            != pre_restart_process_start
        )
    )

    container_identity_changed = (
        pre_restart_container_id is not None
        and runtime_after.container_id is not None
        and (
            runtime_after.container_id
            != pre_restart_container_id
        )
    )

    recovery_state_observed = (
        (
            args.target != "docker"
            and runtime_after.liveness_ok
            and runtime_after.readiness_ok
        )
        or (
            args.target == "docker"
            and runtime_after.container_running
            is True
        )
    )

    restart_evidence = RestartEvidence(
        restart_command=restart_command,
        restart_command_ok=restart_command.ok,
        pre_restart_container_id=(
            pre_restart_container_id
        ),
        post_restart_container_id=(
            runtime_after.container_id
        ),
        pre_restart_process_start_time=(
            pre_restart_process_start
        ),
        post_restart_process_start_time=(
            runtime_after.process_start_time_seconds
        ),
        process_start_time_changed=(
            process_start_changed
        ),
        container_identity_changed=(
            container_identity_changed
        ),
        recovery_state_observed=(
            recovery_state_observed
        ),
    )

    validation_errors.extend(
        _validate_restart_evidence(
            evidence=restart_evidence,
            require_process_start_change=(
                args.require_process_start_change
            ),
            require_container_identity_change=(
                args.require_container_identity_change
            ),
        )
    )

    validation_errors.extend(
        _validate_recovery(
            runtime_after=runtime_after,
            metrics_after=metrics_after,
            endpoint_results=(
                post_restart_probe_results
            ),
            require_post_restart_metrics=(
                args.require_post_restart_metrics
            ),
        )
    )

    validation_errors.extend(
    _validate_response_consistency(
        pre_restart_results=pre_restart_probe_results,
        post_restart_results=post_restart_probe_results,
    )
)

    warnings: list[str] = []

    if (
        args.target == "docker"
        and not container_identity_changed
    ):
        warnings.append(
            "Docker container identity was unchanged. This is expected "
            "for docker restart; process_start_time_seconds is the "
            "primary restart proof."
        )

    if (
        metrics_before.request_counter_total
        is not None
        and metrics_after.request_counter_total
        is not None
        and (
            metrics_after.request_counter_total
            < metrics_before.request_counter_total
        )
    ):
        warnings.append(
            "HTTP request counter decreased after restart. "
            "The metric may be process-local and reset on worker restart."
        )

    validation = ValidationResult(
        validation_errors=tuple(
            validation_errors
        ),
        warnings=tuple(
            warnings
        ),
        overall_ok=not validation_errors,
    )

    pre_restart_latencies = [
        result.elapsed_ms
        for result in pre_restart_probe_results
    ]

    post_restart_latencies = [
        result.elapsed_ms
        for result in post_restart_probe_results
    ]

    timestamp = timestamp_slug()

    raw_path = build_result_path(
        "phase11_worker_restart_probe_raw",
        results_dir=args.results_dir,
        target=args.target,
        timestamp=timestamp,
    )

    summary_path = build_result_path(
        "phase11_worker_restart_probe_summary",
        results_dir=args.results_dir,
        target=args.target,
        timestamp=timestamp,
    )

    raw_payload: dict[str, Any] = {
        "phase_code": PROJECT_PHASE_CODE,
        "phase_name": PROJECT_PHASE_NAME,
        "benchmark": "phase11_worker_restart_probe",
        "started_at_utc": started_at_utc,
        "finished_at_utc": utc_now_iso(),
        "base_url": base_url,
        "target": args.target,
        "configuration": {
            "request_count": args.request_count,
            "matrix_size": args.matrix_size,
            "request_timeout_s": (
                args.request_timeout_s
            ),
            "startup_timeout_s": (
                args.startup_timeout_s
            ),
            "down_timeout_s": (
                args.down_timeout_s
            ),
            "poll_interval_s": (
                args.poll_interval_s
            ),
            "require_process_start_change": (
                args.require_process_start_change
            ),
            "require_container_identity_change": (
                args.require_container_identity_change
            ),
            "require_post_restart_metrics": (
                args.require_post_restart_metrics
            ),
        },
        "runtime_metadata": asdict(
            collect_runtime_metadata(
                base_url=base_url
            )
        ),
        "container_resolution": (
            container_resolution
        ),
        "runtime_before": asdict(
            runtime_before
        ),
        "metrics_before": asdict(
            metrics_before
        ),
        "pre_restart_requests": [
            asdict(result)
            for result in pre_restart_probe_results
        ],
        "restart_evidence": asdict(
            restart_evidence
        ),
        "runtime_after": asdict(
            runtime_after
        ),
        "metrics_after": asdict(
            metrics_after
        ),
        "post_restart_requests": [
            asdict(result)
            for result in post_restart_probe_results
        ],
        "metric_deltas": {
            "request_counter": _metric_counter_delta(
                metrics_before.request_counter_total,
                metrics_after.request_counter_total,
            ),
            "process_start_time_seconds": _metric_counter_delta(
                metrics_before.process_start_time_seconds,
                metrics_after.process_start_time_seconds,
            ),
        },
        "validation": asdict(
            validation
        ),
    }

    summary_payload: dict[str, Any] = {
        "phase_code": PROJECT_PHASE_CODE,
        "phase_name": PROJECT_PHASE_NAME,
        "benchmark": "phase11_worker_restart_probe",
        "target": args.target,
        "base_url": base_url,
        "overall_ok": validation.overall_ok,
        "restart_command_ok": restart_command.ok,
        "restart_runtime_state_observed": (
            recovery_state_observed
        ),
        "process_start_time_before": (
            metrics_before.process_start_time_seconds
        ),
        "process_start_time_after": (
            metrics_after.process_start_time_seconds
        ),
        "process_start_time_changed": (
            process_start_changed
        ),
        "container_id_before": (
            pre_restart_container_id
        ),
        "container_id_after": (
            runtime_after.container_id
        ),
        "container_identity_changed": (
            container_identity_changed
        ),
        "baseline_liveness_ok": (
            runtime_before.liveness_ok
        ),
        "baseline_readiness_ok": (
            runtime_before.readiness_ok
        ),
        "recovery_liveness_ok": (
            runtime_after.liveness_ok
        ),
        "recovery_readiness_ok": (
            runtime_after.readiness_ok
        ),
        "post_restart_requests": len(
            post_restart_probe_results
        ),
        "post_restart_successful_requests": sum(
            result.success
            for result in post_restart_probe_results
        ),
        "post_restart_p95_ms": (
            percentile(
                post_restart_latencies,
                95.0,
            )
            if post_restart_latencies
            else None
        ),
        "pre_restart_mean_ms": (
            statistics.fmean(
                pre_restart_latencies
            )
            if pre_restart_latencies
            else None
        ),
        "post_restart_mean_ms": (
            statistics.fmean(
                post_restart_latencies
            )
            if post_restart_latencies
            else None
        ),
        "request_counter_before": (
            metrics_before.request_counter_total
        ),
        "request_counter_after": (
            metrics_after.request_counter_total
        ),
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

def main() -> int:
    """Parse CLI arguments and execute the worker-restart benchmark."""

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
            "Phase 11 worker-restart probe interrupted",
            file=sys.stderr,
        )
        raise SystemExit(130) from None