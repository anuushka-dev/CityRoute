# benchmarks/phase_11/phase11_graceful_shutdown_probe.py

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import subprocess
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

# Support both:
#   python benchmarks/phase_11/phase11_graceful_shutdown_probe.py
#   python -m benchmarks.phase_11.phase11_graceful_shutdown_probe

PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from benchmarks.phase_11.phase11_common import (
    DEFAULT_BASE_URL,
    PROJECT_PHASE_CODE,
    PROJECT_PHASE_NAME,
    build_result_path,
    collect_runtime_metadata,
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

DEFAULT_MATRIX_SIZE = 25
DEFAULT_INFLIGHT_REQUESTS = 8
DEFAULT_PRE_SHUTDOWN_DELAY_S = 0.20
DEFAULT_MONITOR_INTERVAL_S = 0.02
DEFAULT_SHUTDOWN_TIMEOUT_S = 60.0
DEFAULT_REQUEST_TIMEOUT_S = 60.0
DEFAULT_STARTUP_TIMEOUT_S = 180.0
DEFAULT_DOWN_TIMEOUT_S = 20.0
DEFAULT_COMMAND_TIMEOUT_S = 120.0
DEFAULT_DOCKER_LOG_LINES = 2000
DEFAULT_LOG_TAIL_CHARACTERS = 20_000

MIN_MATRIX_SIZE = 2
MAX_MATRIX_SIZE = 25

MIN_INFLIGHT_REQUESTS = 1
MAX_INFLIGHT_REQUESTS = 64

MIN_MONITOR_INTERVAL_S = 0.005
MAX_MONITOR_INTERVAL_S = 5.0

MIN_SHUTDOWN_TIMEOUT_S = 1.0
MAX_SHUTDOWN_TIMEOUT_S = 300.0

MIN_REQUEST_TIMEOUT_S = 1.0
MAX_REQUEST_TIMEOUT_S = 300.0

MIN_STARTUP_TIMEOUT_S = 1.0
MAX_STARTUP_TIMEOUT_S = 600.0

MIN_DOWN_TIMEOUT_S = 1.0
MAX_DOWN_TIMEOUT_S = 120.0

MATRIX_PATH = "/matrix"
LIVENESS_PATH = "/health/live"
READINESS_PATH = "/health/ready"
METRICS_PATH = "/metrics"

MATRIX_ALGORITHM = "source_dijkstra"
MATRIX_USE_CACHE = False

HTTP_SUCCESS_STATUS = 200
HTTP_CONTROLLED_REJECTION_STATUSES = frozenset(
    {
        429,
        503,
    }
)

OUTCOME_COMPLETED = "completed"
OUTCOME_CONTROLLED_REJECTION = "controlled_rejection"
OUTCOME_UNEXPECTED_RESPONSE = "unexpected_response"
OUTCOME_CLIENT_ERROR = "client_error"
OUTCOME_CANCELLED = "cancelled"

METRIC_ACTIVE_REQUESTS = "cityroute_active_requests"
METRIC_WAITING_REQUESTS = "cityroute_waiting_requests"
METRIC_SHUTDOWN_INFLIGHT = (
    "cityroute_graceful_shutdown_inflight"
)
METRIC_READINESS = "cityroute_readiness"
METRIC_ACCEPTING_REQUESTS = (
    "cityroute_accepting_requests"
)

LOG_SHUTDOWN_REQUESTED = (
    "CityRoute shutdown requested"
)

LOG_GRACEFUL_SHUTDOWN_STARTED = (
    "Graceful shutdown started"
)

LOG_DRAIN_COMPLETED = (
    "Protected request drain completed"
)

LOG_GRACEFUL_SHUTDOWN_FINISHED = (
    "Graceful shutdown finished"
)

LOG_APPLICATION_SHUTDOWN_COMPLETE = (
    "CityRoute shutdown complete"
)

SHUTDOWN_LOG_REQUIRED_FLAGS = (
    "shutdown_requested",
    "graceful_shutdown_started",
    "drain_completed",
    "graceful_shutdown_finished_complete",
    "application_shutdown_complete",
)


# ---------------------------------------------------------------------------
# Dataclasses / Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandResult:
    """Structured result of an OS or Docker lifecycle command."""

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
class ContainerState:
    """Observed Docker container lifecycle state."""

    container_id: str
    container_name: str
    image: str
    state: str
    running: bool
    restarting: bool
    exited: bool
    captured_at_utc: str
    error_type: str | None
    error_message: str | None


@dataclass(frozen=True)
class MetricsSample:
    """One point-in-time sample of reliability metrics."""

    stage: str
    captured_at_utc: str
    elapsed_from_start_ms: float
    status_code: int | None
    active_requests: float | None
    waiting_requests: float | None
    shutdown_inflight: float | None
    readiness: float | None
    accepting_requests: float | None
    error_type: str | None
    error_message: str | None


@dataclass(frozen=True)
class MatrixRequestResult:
    """Result of one protected matrix request."""

    request_index: int
    status_code: int | None
    elapsed_ms: float
    outcome: str
    response_summary: Any | None
    error_type: str | None
    error_message: str | None
    started_at_utc: str
    finished_at_utc: str


@dataclass(frozen=True)
class ShutdownLogEvidence:
    """Evidence extracted from application/container logs."""

    shutdown_requested: bool
    graceful_shutdown_started: bool
    drain_completed: bool
    graceful_shutdown_finished_complete: bool
    application_shutdown_complete: bool


@dataclass(frozen=True)
class RecoveryEvidence:
    """Post-shutdown recovery evidence."""

    restart_command: CommandResult | None
    container_state: ContainerState | None
    liveness_ok: bool
    readiness_ok: bool
    metrics_ok: bool


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
    """Parse and validate benchmark CLI arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Prove Phase 11 graceful shutdown at the real "
            "process/container lifecycle level. The probe begins from "
            "healthy service state, creates protected /matrix work, "
            "samples reliability metrics, sends a real shutdown signal, "
            "validates drain/shutdown evidence, proves service "
            "unavailability, restarts Docker targets when required, "
            "and validates recovery."
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
            "Execution target. Docker performs container lifecycle "
            "validation; local performs process-level signal validation."
        ),
    )

    parser.add_argument(
        "--results-dir",
        type=Path,
        default=None,
        help=(
            "Explicit Phase 11 results directory. "
            "Overrides the standard target-based directory."
        ),
    )

    parser.add_argument(
        "--container",
        default=None,
        help=(
            "Exact CityRoute Docker container name or ID. "
            "When omitted, a running CityRoute container is discovered."
        ),
    )

    parser.add_argument(
        "--docker-bin",
        default="docker",
        help="Docker CLI executable. Default: docker",
    )

    parser.add_argument(
        "--pid",
        type=int,
        default=None,
        help=(
            "Local API process PID for --target local. "
            "Required for local process-level shutdown."
        ),
    )

    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help=(
            "Optional local API log file. Required for complete "
            "local shutdown-log validation."
        ),
    )

    parser.add_argument(
        "--matrix-size",
        type=int,
        default=DEFAULT_MATRIX_SIZE,
        help=(
            "Number of locations per uncached /matrix request. "
            f"Default: {DEFAULT_MATRIX_SIZE}"
        ),
    )

    parser.add_argument(
        "--inflight-requests",
        type=int,
        default=DEFAULT_INFLIGHT_REQUESTS,
        help=(
            "Concurrent matrix requests started before shutdown. "
            f"Default: {DEFAULT_INFLIGHT_REQUESTS}"
        ),
    )

    parser.add_argument(
        "--pre-shutdown-delay-s",
        type=float,
        default=DEFAULT_PRE_SHUTDOWN_DELAY_S,
        help=(
            "Delay between starting protected work and sending "
            f"the shutdown signal. Default: {DEFAULT_PRE_SHUTDOWN_DELAY_S}"
        ),
    )

    parser.add_argument(
        "--monitor-interval-s",
        type=float,
        default=DEFAULT_MONITOR_INTERVAL_S,
        help=(
            "Metrics sampling interval during protected work and "
            f"shutdown. Default: {DEFAULT_MONITOR_INTERVAL_S}"
        ),
    )

    parser.add_argument(
        "--shutdown-timeout-s",
        type=float,
        default=DEFAULT_SHUTDOWN_TIMEOUT_S,
        help=(
            "Maximum graceful-drain duration and request-join window. "
            f"Default: {DEFAULT_SHUTDOWN_TIMEOUT_S}"
        ),
    )

    parser.add_argument(
        "--request-timeout-s",
        type=float,
        default=DEFAULT_REQUEST_TIMEOUT_S,
        help=(
            "HTTP timeout for protected matrix requests. "
            f"Default: {DEFAULT_REQUEST_TIMEOUT_S}"
        ),
    )

    parser.add_argument(
        "--startup-timeout-s",
        type=float,
        default=DEFAULT_STARTUP_TIMEOUT_S,
        help=(
            "Maximum wait for liveness/readiness during recovery. "
            f"Default: {DEFAULT_STARTUP_TIMEOUT_S}"
        ),
    )

    parser.add_argument(
        "--down-timeout-s",
        type=float,
        default=DEFAULT_DOWN_TIMEOUT_S,
        help=(
            "Maximum wait for the API to become unreachable after "
            f"shutdown. Default: {DEFAULT_DOWN_TIMEOUT_S}"
        ),
    )

    parser.add_argument(
        "--require-inflight",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Require active_requests > 0 immediately before shutdown. "
            "Disabled by default because request completion timing can "
            "otherwise create false failures."
        ),
    )

    parser.add_argument(
        "--require-shutdown-logs",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Require all canonical graceful-shutdown log markers. "
            "Default: enabled."
        ),
    )

    parser.add_argument(
        "--fail-on-validation-error",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Exit non-zero when validation fails. "
            "Default: enabled."
        ),
    )

    args = parser.parse_args()

    if not (
        MIN_MATRIX_SIZE
        <= args.matrix_size
        <= MAX_MATRIX_SIZE
    ):
        parser.error(
            "--matrix-size must be between "
            f"{MIN_MATRIX_SIZE} and {MAX_MATRIX_SIZE}"
        )

    if not (
        MIN_INFLIGHT_REQUESTS
        <= args.inflight_requests
        <= MAX_INFLIGHT_REQUESTS
    ):
        parser.error(
            "--inflight-requests must be between "
            f"{MIN_INFLIGHT_REQUESTS} and {MAX_INFLIGHT_REQUESTS}"
        )

    if args.pre_shutdown_delay_s < 0:
        parser.error(
            "--pre-shutdown-delay-s must be zero or greater"
        )

    if not (
        MIN_MONITOR_INTERVAL_S
        <= args.monitor_interval_s
        <= MAX_MONITOR_INTERVAL_S
    ):
        parser.error(
            "--monitor-interval-s must be between "
            f"{MIN_MONITOR_INTERVAL_S} and "
            f"{MAX_MONITOR_INTERVAL_S}"
        )

    if not (
        MIN_SHUTDOWN_TIMEOUT_S
        <= args.shutdown_timeout_s
        <= MAX_SHUTDOWN_TIMEOUT_S
    ):
        parser.error(
            "--shutdown-timeout-s must be between "
            f"{MIN_SHUTDOWN_TIMEOUT_S} and "
            f"{MAX_SHUTDOWN_TIMEOUT_S}"
        )

    if not (
        MIN_REQUEST_TIMEOUT_S
        <= args.request_timeout_s
        <= MAX_REQUEST_TIMEOUT_S
    ):
        parser.error(
            "--request-timeout-s must be between "
            f"{MIN_REQUEST_TIMEOUT_S} and "
            f"{MAX_REQUEST_TIMEOUT_S}"
        )

    if not (
        MIN_STARTUP_TIMEOUT_S
        <= args.startup_timeout_s
        <= MAX_STARTUP_TIMEOUT_S
    ):
        parser.error(
            "--startup-timeout-s must be between "
            f"{MIN_STARTUP_TIMEOUT_S} and "
            f"{MAX_STARTUP_TIMEOUT_S}"
        )

    if not (
        MIN_DOWN_TIMEOUT_S
        <= args.down_timeout_s
        <= MAX_DOWN_TIMEOUT_S
    ):
        parser.error(
            "--down-timeout-s must be between "
            f"{MIN_DOWN_TIMEOUT_S} and "
            f"{MAX_DOWN_TIMEOUT_S}"
        )

    if args.target == "local" and args.pid is None:
        parser.error(
            "--target local requires --pid"
        )

    if args.target == "local" and args.log_file is None:
        parser.error(
            "--target local requires --log-file "
            "for complete shutdown-log validation"
        )

    return args


# ---------------------------------------------------------------------------
# Generic command helpers
# ---------------------------------------------------------------------------


def _run_command(
    command: list[str],
    *,
    timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S,
) -> CommandResult:
    """Execute one command while preserving failure context."""

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
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()

    except subprocess.TimeoutExpired as exc:
        error_type = type(exc).__name__
        error_message = (
            f"Command exceeded timeout of {timeout_s:.3f}s"
        )

        if isinstance(exc.stdout, str):
            stdout = exc.stdout.strip()

        if isinstance(exc.stderr, str):
            stderr = exc.stderr.strip()

    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    return CommandResult(
        command=tuple(command),
        return_code=return_code,
        ok=(
            return_code == 0
            and error_type is None
        ),
        elapsed_ms=(
            time.perf_counter() - started
        ) * 1000.0,
        stdout=stdout,
        stderr=stderr,
        error_type=error_type,
        error_message=error_message,
        started_at_utc=started_at_utc,
        finished_at_utc=utc_now_iso(),
    )


# ---------------------------------------------------------------------------
# Docker helpers
# ---------------------------------------------------------------------------


def _parse_bool(value: str) -> bool | None:
    """Parse Docker boolean text explicitly."""

    normalized = value.strip().lower()

    if normalized == "true":
        return True

    if normalized == "false":
        return False

    return None


def _inspect_container(
    *,
    docker_bin: str,
    container: str,
) -> tuple[ContainerState | None, CommandResult]:
    """Inspect one Docker container."""

    result = _run_command(
        [
            docker_bin,
            "inspect",
            "--format",
            (
                "{{.Id}}\t"
                "{{.Name}}\t"
                "{{.Config.Image}}\t"
                "{{.State.Status}}\t"
                "{{.State.Running}}\t"
                "{{.State.Restarting}}\t"
                "{{.State.ExitCode}}"
            ),
            container,
        ]
    )

    if not result.ok:
        return None, result

    fields = result.stdout.split("\t")

    if len(fields) != 7:
        return (
            None,
            CommandResult(
                **{
                    **asdict(result),
                    "ok": False,
                    "error_type": "ContainerParseError",
                    "error_message": (
                        "Unexpected docker inspect output: "
                        f"{result.stdout!r}"
                    ),
                }
            ),
        )

    (
        container_id,
        raw_name,
        image,
        state,
        raw_running,
        raw_restarting,
        _,
    ) = fields

    running = _parse_bool(raw_running)
    restarting = _parse_bool(raw_restarting)

    if running is None or restarting is None:
        return (
            None,
            CommandResult(
                **{
                    **asdict(result),
                    "ok": False,
                    "error_type": "ContainerBooleanParseError",
                    "error_message": (
                        "Unable to parse Docker running/restarting "
                        f"flags from {result.stdout!r}"
                    ),
                }
            ),
        )

    return (
        ContainerState(
            container_id=container_id,
            container_name=raw_name.lstrip("/"),
            image=image,
            state=state,
            running=running,
            restarting=restarting,
            exited=state == "exited",
            captured_at_utc=utc_now_iso(),
            error_type=None,
            error_message=None,
        ),
        result,
    )


def _discover_container(
    *,
    docker_bin: str,
) -> tuple[dict[str, str], CommandResult]:
    """Discover a unique running CityRoute container."""

    result = _run_command(
        [
            docker_bin,
            "ps",
            "-a",
            "--format",
            "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.State}}",
        ]
    )

    if not result.ok:
        raise RuntimeError(
            "Unable to list Docker containers: "
            f"{result.stderr or result.error_message}"
        )

    candidates: list[dict[str, str]] = []

    for line in result.stdout.splitlines():
        parts = line.split("\t")

        if len(parts) != 4:
            continue

        container_id, name, image, state = parts
        searchable = (
            f"{name} {image}".lower()
        )

        if "cityroute" not in searchable:
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
        return running[0], result

    if len(candidates) == 1:
        candidate = candidates[0]

        if candidate["state"] != "running":
            raise RuntimeError(
                "Discovered CityRoute container is not running: "
                f"state={candidate['state']}"
            )

        return candidate, result

    if not candidates:
        raise RuntimeError(
            "No CityRoute Docker container was found. "
            "Pass the exact container name using --container."
        )

    choices = ", ".join(
        (
            f"{candidate['name']} "
            f"({candidate['state']})"
        )
        for candidate in candidates
    )

    raise RuntimeError(
        "Multiple CityRoute containers were found. "
        f"Pass one exact name with --container. "
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
    """Resolve the selected Docker target."""

    if requested is None:
        container, result = _discover_container(
            docker_bin=docker_bin,
        )

        return (
            container,
            {
                "mode": "auto_discovery",
                "command": asdict(result),
            },
        )

    state, result = _inspect_container(
        docker_bin=docker_bin,
        container=requested,
    )

    if state is None:
        raise RuntimeError(
            f"CityRoute container {requested!r} was not found: "
            f"{result.stderr or result.error_message}"
        )

    if not state.running:
        raise RuntimeError(
            "CityRoute container is not running: "
            f"state={state.state}"
        )

    return (
        {
            "id": state.container_id,
            "name": state.container_name,
            "image": state.image,
            "state": state.state,
        },
        {
            "mode": "explicit",
            "command": asdict(result),
        },
    )


def _wait_for_container_state(
    *,
    docker_bin: str,
    container: str,
    expected_state: str,
    timeout_s: float,
    poll_interval_s: float,
) -> ContainerState:
    """Wait until Docker reports a requested lifecycle state."""

    deadline = (
        time.perf_counter()
        + timeout_s
    )

    last_state: ContainerState | None = None

    while time.perf_counter() < deadline:
        last_state, result = _inspect_container(
            docker_bin=docker_bin,
            container=container,
        )

        if last_state is None:
            raise RuntimeError(
                "Unable to inspect container while waiting for "
                f"state={expected_state!r}: "
                f"{result.error_message}"
            )

        if last_state.state == expected_state:
            return last_state

        time.sleep(
            poll_interval_s
        )

    raise TimeoutError(
        "Container did not reach expected state within "
        f"{timeout_s:.3f}s. "
        f"expected={expected_state!r}, "
        f"last_state="
        f"{asdict(last_state) if last_state else None}"
    )


# ---------------------------------------------------------------------------
# Workload helpers
# ---------------------------------------------------------------------------


def _generated_locations(
    *,
    matrix_size: int,
    request_variant: int,
) -> list[dict[str, Any]]:
    """Generate deterministic Kanpur-area routing locations."""

    center_lat = 26.4499
    center_lon = 80.3319
    spacing = 0.0016

    variant_shift = (
        request_variant % 100
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
    """Build one deterministic uncached matrix payload."""

    return {
        "locations": _generated_locations(
            matrix_size=matrix_size,
            request_variant=request_variant,
        ),
        "algorithm": MATRIX_ALGORITHM,
        "use_cache": MATRIX_USE_CACHE,
    }


# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------


def _parse_metrics(
    metrics_text: str,
) -> dict[str, float]:
    """Aggregate Prometheus samples by metric family."""

    values: dict[str, float] = {}

    for raw_line in metrics_text.splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        sample, separator, raw_value = line.rpartition(" ")

        if not separator:
            continue

        metric_name = sample.split(
            "{",
            maxsplit=1,
        )[0]

        try:
            value = float(raw_value)
        except ValueError:
            continue

        values[metric_name] = (
            values.get(
                metric_name,
                0.0,
            )
            + value
        )

    return values


async def _fetch_metrics(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    stage: str,
    started: float,
) -> MetricsSample:
    """Capture shutdown-sensitive metrics."""

    try:
        response = await client.get(
            f"{base_url}{METRICS_PATH}"
        )

        values = _parse_metrics(
            response.text
        )

        return MetricsSample(
            stage=stage,
            captured_at_utc=utc_now_iso(),
            elapsed_from_start_ms=(
                time.perf_counter()
                - started
            ) * 1000.0,
            status_code=response.status_code,
            active_requests=values.get(
                METRIC_ACTIVE_REQUESTS
            ),
            waiting_requests=values.get(
                METRIC_WAITING_REQUESTS
            ),
            shutdown_inflight=values.get(
                METRIC_SHUTDOWN_INFLIGHT
            ),
            readiness=values.get(
                METRIC_READINESS
            ),
            accepting_requests=values.get(
                METRIC_ACCEPTING_REQUESTS
            ),
            error_type=None,
            error_message=None,
        )

    except Exception as exc:
        return MetricsSample(
            stage=stage,
            captured_at_utc=utc_now_iso(),
            elapsed_from_start_ms=(
                time.perf_counter()
                - started
            ) * 1000.0,
            status_code=None,
            active_requests=None,
            waiting_requests=None,
            shutdown_inflight=None,
            readiness=None,
            accepting_requests=None,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )


async def _monitor_metrics(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    started: float,
    stop_event: asyncio.Event,
    interval_s: float,
) -> list[MetricsSample]:
    """Continuously sample reliability metrics."""

    samples: list[MetricsSample] = []

    while not stop_event.is_set():
        samples.append(
            await _fetch_metrics(
                client,
                base_url=base_url,
                stage="monitoring",
                started=started,
            )
        )

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=interval_s,
            )
        except TimeoutError:
            continue

    return samples


# ---------------------------------------------------------------------------
# Protected request helpers
# ---------------------------------------------------------------------------


async def _matrix_request(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    request_index: int,
    matrix_size: int,
) -> MatrixRequestResult:
    """Execute and classify one protected /matrix request."""

    started_at_utc = utc_now_iso()
    started = time.perf_counter()

    try:
        response = await client.post(
            f"{base_url}{MATRIX_PATH}",
            json=_build_matrix_payload(
                matrix_size=matrix_size,
                request_variant=request_index + 1,
            ),
        )

        try:
            response_json: Any | None = (
                response.json()
            )
        except ValueError:
            response_json = None

        if response.status_code == HTTP_SUCCESS_STATUS:
            outcome = OUTCOME_COMPLETED

        elif (
            response.status_code
            in HTTP_CONTROLLED_REJECTION_STATUSES
        ):
            outcome = OUTCOME_CONTROLLED_REJECTION

        else:
            outcome = OUTCOME_UNEXPECTED_RESPONSE

        response_summary = None

        if isinstance(
            response_json,
            dict,
        ):
            response_summary = {
                "status": response_json.get(
                    "status"
                ),
                "n": response_json.get(
                    "n"
                ),
                "algorithm": response_json.get(
                    "algorithm"
                ),
                "cache": response_json.get(
                    "cache"
                ),
            }

        return MatrixRequestResult(
            request_index=request_index,
            status_code=response.status_code,
            elapsed_ms=(
                time.perf_counter()
                - started
            ) * 1000.0,
            outcome=outcome,
            response_summary=response_summary,
            error_type=None,
            error_message=None,
            started_at_utc=started_at_utc,
            finished_at_utc=utc_now_iso(),
        )

    except asyncio.CancelledError:
        return MatrixRequestResult(
            request_index=request_index,
            status_code=None,
            elapsed_ms=(
                time.perf_counter()
                - started
            ) * 1000.0,
            outcome=OUTCOME_CANCELLED,
            response_summary=None,
            error_type="CancelledError",
            error_message=(
                "Request task was cancelled while "
                "shutdown was being processed."
            ),
            started_at_utc=started_at_utc,
            finished_at_utc=utc_now_iso(),
        )

    except Exception as exc:
        return MatrixRequestResult(
            request_index=request_index,
            status_code=None,
            elapsed_ms=(
                time.perf_counter()
                - started
            ) * 1000.0,
            outcome=OUTCOME_CLIENT_ERROR,
            response_summary=None,
            error_type=type(exc).__name__,
            error_message=str(exc),
            started_at_utc=started_at_utc,
            finished_at_utc=utc_now_iso(),
        )


# ---------------------------------------------------------------------------
# Availability helpers
# ---------------------------------------------------------------------------


async def _wait_until_unreachable(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    timeout_s: float,
) -> bool:
    """Verify that the API becomes unavailable after shutdown."""

    deadline = (
        time.perf_counter()
        + timeout_s
    )

    while time.perf_counter() < deadline:
        try:
            response = await client.get(
                f"{base_url}{LIVENESS_PATH}"
            )

            if response.status_code >= 500:
                return True

        except Exception:
            return True

        await asyncio.sleep(
            min(
                0.20,
                max(
                    DEFAULT_MONITOR_INTERVAL_S,
                    0.05,
                ),
            )
        )

    return False


# ---------------------------------------------------------------------------
# Shutdown signal helpers
# ---------------------------------------------------------------------------


def _docker_stop_command(
    *,
    docker_bin: str,
    container: str,
    shutdown_timeout_s: float,
) -> CommandResult:
    """Perform Docker graceful stop."""

    stop_timeout = max(
        1,
        int(
            shutdown_timeout_s
        ),
    )

    return _run_command(
        [
            docker_bin,
            "stop",
            "--time",
            str(stop_timeout),
            container,
        ],
        timeout_s=(
            shutdown_timeout_s
            + DEFAULT_COMMAND_TIMEOUT_S
        ),
    )


def _signal_local_process(
    *,
    pid: int,
) -> CommandResult:
    """Send a platform-appropriate graceful process signal."""

    if pid <= 0:
        raise ValueError(
            f"PID must be positive; received {pid}"
        )

    started_at_utc = utc_now_iso()
    started = time.perf_counter()

    error_type: str | None = None
    error_message: str | None = None
    return_code: int | None = 0

    signal_name = (
        "CTRL_BREAK_EVENT"
        if os.name == "nt"
        else "SIGTERM"
    )

    try:
        if os.name == "nt":
            os.kill(
                pid,
                signal.CTRL_BREAK_EVENT,
            )
        else:
            os.kill(
                pid,
                signal.SIGTERM,
            )

    except Exception as exc:
        return_code = None
        error_type = type(exc).__name__
        error_message = str(exc)

    return CommandResult(
        command=(
            "signal",
            str(pid),
            signal_name,
        ),
        return_code=return_code,
        ok=(
            error_type is None
        ),
        elapsed_ms=(
            time.perf_counter()
            - started
        ) * 1000.0,
        stdout="",
        stderr="",
        error_type=error_type,
        error_message=error_message,
        started_at_utc=started_at_utc,
        finished_at_utc=utc_now_iso(),
    )


# ---------------------------------------------------------------------------
# Log helpers
# ---------------------------------------------------------------------------


def _shutdown_log_evidence(
    logs: str,
) -> ShutdownLogEvidence:
    """Extract canonical graceful-shutdown lifecycle evidence."""

    shutdown_finished = (
        LOG_GRACEFUL_SHUTDOWN_FINISHED in logs
        and "phase=complete" in logs
        and "graceful=True" in logs
        and "drained=True" in logs
        and "cleanup_success=True" in logs
    )

    application_complete = (
        LOG_APPLICATION_SHUTDOWN_COMPLETE
        in logs
        and "phase=complete" in logs
        and "graceful=True" in logs
        and "forced=False" in logs
        and "drained=True" in logs
        and "cleanup_success=True" in logs
    )

    return ShutdownLogEvidence(
        shutdown_requested=(
            LOG_SHUTDOWN_REQUESTED in logs
        ),
        graceful_shutdown_started=(
            LOG_GRACEFUL_SHUTDOWN_STARTED in logs
        ),
        drain_completed=(
            LOG_DRAIN_COMPLETED in logs
        ),
        graceful_shutdown_finished_complete=(
            shutdown_finished
        ),
        application_shutdown_complete=(
            application_complete
        ),
    )


def _read_logs(
    *,
    target: str,
    docker_bin: str,
    container: str | None,
    log_file: Path | None,
) -> tuple[str, CommandResult | None]:
    """Read lifecycle logs from Docker or local output."""

    if target == "docker":
        if container is None:
            raise RuntimeError(
                "Docker log collection requires a container."
            )

        result = _run_command(
            [
                docker_bin,
                "logs",
                "--tail",
                str(DEFAULT_DOCKER_LOG_LINES),
                container,
            ]
        )

        return (
            result.stdout + "\n" + result.stderr,
            result,
        )

    if log_file is None:
        return "", None

    if not log_file.exists():
        return (
            "",
            CommandResult(
                command=(
                    "read-log-file",
                    str(log_file),
                ),
                return_code=None,
                ok=False,
                elapsed_ms=0.0,
                stdout="",
                stderr="",
                error_type="LogFileNotFound",
                error_message=(
                    f"Log file does not exist: {log_file}"
                ),
                started_at_utc=utc_now_iso(),
                finished_at_utc=utc_now_iso(),
            ),
        )

    started = time.perf_counter()
    started_at_utc = utc_now_iso()

    try:
        content = log_file.read_text(
            encoding="utf-8",
            errors="replace",
        )

        return (
            content,
            CommandResult(
                command=(
                    "read-log-file",
                    str(log_file),
                ),
                return_code=0,
                ok=True,
                elapsed_ms=(
                    time.perf_counter()
                    - started
                ) * 1000.0,
                stdout="",
                stderr="",
                error_type=None,
                error_message=None,
                started_at_utc=started_at_utc,
                finished_at_utc=utc_now_iso(),
            ),
        )

    except Exception as exc:
        return (
            "",
            CommandResult(
                command=(
                    "read-log-file",
                    str(log_file),
                ),
                return_code=None,
                ok=False,
                elapsed_ms=(
                    time.perf_counter()
                    - started
                ) * 1000.0,
                stdout="",
                stderr="",
                error_type=type(exc).__name__,
                error_message=str(exc),
                started_at_utc=started_at_utc,
                finished_at_utc=utc_now_iso(),
            ),
        )


def _trim_logs(
    logs: str,
) -> str:
    """Bound log evidence retained in the raw report."""

    if len(logs) <= DEFAULT_LOG_TAIL_CHARACTERS:
        return logs

    return logs[
        -DEFAULT_LOG_TAIL_CHARACTERS:
    ]


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_baseline(
    *,
    baseline_liveness: Any,
    baseline_readiness: Any,
) -> list[str]:
    """Validate healthy pre-shutdown state."""

    errors: list[str] = []

    if not getattr(
        baseline_liveness,
        "ok",
        False,
    ):
        errors.append(
            "Baseline liveness was not healthy."
        )

    if not getattr(
        baseline_readiness,
        "ok",
        False,
    ):
        errors.append(
            "Baseline readiness was not healthy."
        )

    return errors


def _validate_request_results(
    *,
    request_results: list[MatrixRequestResult],
    require_inflight: bool,
    peak_active_requests: float | None,
) -> list[str]:
    """Validate protected-work execution and shutdown timing evidence."""

    errors: list[str] = []

    if not request_results:
        errors.append(
            "No protected matrix request results were collected."
        )

    if require_inflight and (
        peak_active_requests is None
        or peak_active_requests <= 0
    ):
        errors.append(
            "No active protected request was observed before shutdown."
        )

    return errors


def _validate_shutdown_command(
    shutdown_command: CommandResult | None,
) -> list[str]:
    """Validate the shutdown signal invocation."""

    if shutdown_command is None:
        return [
            "No shutdown command result was produced."
        ]

    if shutdown_command.ok:
        return []

    return [
        "Shutdown command failed: "
        f"{shutdown_command.error_message or shutdown_command.stderr}"
    ]


def _validate_service_down(
    service_down: bool,
) -> list[str]:
    """Validate post-shutdown unavailability."""

    if service_down:
        return []

    return [
        "Service did not become unreachable after shutdown."
    ]


def _validate_shutdown_logs(
    *,
    evidence: ShutdownLogEvidence,
    required: bool,
) -> list[str]:
    """Validate canonical shutdown lifecycle log markers."""

    if not required:
        return []

    evidence_dict = asdict(
        evidence
    )

    errors: list[str] = []

    for flag in SHUTDOWN_LOG_REQUIRED_FLAGS:
        if not evidence_dict.get(
            flag,
            False,
        ):
            errors.append(
                "Missing required shutdown log evidence: "
                f"{flag}"
            )

    return errors


def _validate_metrics_samples(
    samples: list[MetricsSample],
) -> list[str]:
    """Validate collection of shutdown metrics."""

    if not samples:
        return [
            "No shutdown-period metric samples were captured."
        ]

    valid_shutdown_samples = [
        sample
        for sample in samples
        if sample.shutdown_inflight is not None
    ]

    if not valid_shutdown_samples:
        return [
            "No samples contained "
            "cityroute_graceful_shutdown_inflight."
        ]

    return []


def _validate_recovery(
    *,
    target: str,
    recovery: RecoveryEvidence,
) -> list[str]:
    """Validate recovery after graceful shutdown."""

    errors: list[str] = []

    if target == "docker":
        if (
            recovery.restart_command is None
            or not recovery.restart_command.ok
        ):
            errors.append(
                "Docker container did not restart successfully."
            )

        if (
            recovery.container_state is None
            or not recovery.container_state.running
        ):
            errors.append(
                "Docker container was not observed running "
                "after restart."
            )

    if not recovery.liveness_ok:
        errors.append(
            "Liveness did not recover after shutdown."
        )

    if not recovery.readiness_ok:
        errors.append(
            "Readiness did not recover after shutdown."
        )

    if not recovery.metrics_ok:
        errors.append(
            "Metrics endpoint did not recover after shutdown."
        )

    return errors


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def _peak_metric(
    samples: list[MetricsSample],
    attribute: str,
) -> float | None:
    """Return the peak numeric value for one metric attribute."""

    values = [
        getattr(
            sample,
            attribute,
        )
        for sample in samples
    ]

    numeric_values = [
        value
        for value in values
        if isinstance(
            value,
            (int, float),
        )
    ]

    return (
        max(numeric_values)
        if numeric_values
        else None
    )


def _minimum_metric(
    samples: list[MetricsSample],
    attribute: str,
) -> float | None:
    """Return the minimum numeric value for one metric attribute."""

    values = [
        getattr(
            sample,
            attribute,
        )
        for sample in samples
    ]

    numeric_values = [
        value
        for value in values
        if isinstance(
            value,
            (int, float),
        )
    ]

    return (
        min(numeric_values)
        if numeric_values
        else None
    )


def _outcome_counts(
    request_results: list[MatrixRequestResult],
) -> dict[str, int]:
    """Build deterministic request outcome counts."""

    counts: dict[str, int] = {}

    for result in request_results:
        counts[result.outcome] = (
            counts.get(
                result.outcome,
                0,
            )
            + 1
        )

    return dict(
        sorted(
            counts.items()
        )
    )


def _metrics_summary(
    samples: list[MetricsSample],
) -> dict[str, Any]:
    """Build a concise reliability-metric summary."""

    return {
        "sample_count": len(samples),
        "peak_active_requests": _peak_metric(
            samples,
            "active_requests",
        ),
        "peak_waiting_requests": _peak_metric(
            samples,
            "waiting_requests",
        ),
        "peak_shutdown_inflight": _peak_metric(
            samples,
            "shutdown_inflight",
        ),
        "minimum_readiness": _minimum_metric(
            samples,
            "readiness",
        ),
        "minimum_accepting_requests": _minimum_metric(
            samples,
            "accepting_requests",
        ),
    }


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


async def async_main(
    args: argparse.Namespace,
) -> int:
    """Run the complete graceful-shutdown benchmark."""

    base_url = (
        args.base_url
        .strip()
        .rstrip("/")
    )

    started_at_utc = utc_now_iso()
    validation_errors: list[str] = []
    warnings: list[str] = []

    baseline_liveness = await asyncio.to_thread(
        wait_for_liveness,
        base_url=base_url,
        startup_timeout_s=args.startup_timeout_s,
    )

    baseline_readiness = await asyncio.to_thread(
        wait_for_readiness,
        base_url=base_url,
        startup_timeout_s=args.startup_timeout_s,
        allow_degraded=True,
    )

    validation_errors.extend(
        _validate_baseline(
            baseline_liveness=baseline_liveness,
            baseline_readiness=baseline_readiness,
        )
    )

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

    metrics_before: MetricsSample | None = None
    metrics_at_shutdown: MetricsSample | None = None

    metrics_samples: list[MetricsSample] = []
    request_results: list[MatrixRequestResult] = []

    shutdown_command: CommandResult | None = None
    service_down = False

    logs = ""
    log_command: CommandResult | None = None

    shutdown_log_evidence = ShutdownLogEvidence(
        shutdown_requested=False,
        graceful_shutdown_started=False,
        drain_completed=False,
        graceful_shutdown_finished_complete=False,
        application_shutdown_complete=False,
    )

    recovery = RecoveryEvidence(
        restart_command=None,
        container_state=None,
        liveness_ok=False,
        readiness_ok=False,
        metrics_ok=False,
    )

    async with httpx.AsyncClient(
        timeout=args.request_timeout_s,
        limits=httpx.Limits(
            max_connections=max(
                50,
                args.inflight_requests * 2,
            ),
            max_keepalive_connections=max(
                50,
                args.inflight_requests * 2,
            ),
        ),
    ) as client:
        metrics_before = await _fetch_metrics(
            client,
            base_url=base_url,
            stage="baseline",
            started=time.perf_counter(),
        )

        load_started = time.perf_counter()
        monitor_stop = asyncio.Event()

        monitor_task = asyncio.create_task(
            _monitor_metrics(
                client=client,
                base_url=base_url,
                started=load_started,
                stop_event=monitor_stop,
                interval_s=args.monitor_interval_s,
            ),
            name="phase11-graceful-shutdown-monitor",
        )

        request_tasks = [
            asyncio.create_task(
                _matrix_request(
                    client=client,
                    base_url=base_url,
                    request_index=request_index,
                    matrix_size=args.matrix_size,
                ),
                name=(
                    "phase11-graceful-shutdown-matrix-"
                    f"{request_index}"
                ),
            )
            for request_index in range(
                args.inflight_requests
            )
        ]

        await asyncio.sleep(
            args.pre_shutdown_delay_s
        )

        metrics_at_shutdown = await _fetch_metrics(
            client,
            base_url=base_url,
            stage="shutdown_trigger",
            started=load_started,
        )

        try:
            if args.target == "docker":
                if container is None:
                    raise RuntimeError(
                        "Docker target requires a resolved container."
                    )

                shutdown_command = (
                    await asyncio.to_thread(
                        _docker_stop_command,
                        docker_bin=args.docker_bin,
                        container=container["name"],
                        shutdown_timeout_s=(
                            args.shutdown_timeout_s
                        ),
                    )
                )

            else:
                shutdown_command = (
                    await asyncio.to_thread(
                        _signal_local_process,
                        pid=args.pid,
                    )
                )

        except Exception as exc:
            validation_errors.append(
                "Unable to issue graceful-shutdown signal: "
                f"{type(exc).__name__}: {exc}"
            )

        finally:
            monitor_stop.set()

        try:
            request_results = await asyncio.wait_for(
                asyncio.gather(
                    *request_tasks,
                ),
                timeout=args.shutdown_timeout_s,
            )

        except TimeoutError:
            for task in request_tasks:
                if not task.done():
                    task.cancel()

            gathered_results = await asyncio.gather(
                *request_tasks,
                return_exceptions=True,
            )

            request_results = []

            for request_index, result in enumerate(
                gathered_results
            ):
                if isinstance(
                    result,
                    MatrixRequestResult,
                ):
                    request_results.append(
                        result
                    )
                    continue

                request_results.append(
                    MatrixRequestResult(
                        request_index=request_index,
                        status_code=None,
                        elapsed_ms=0.0,
                        outcome=OUTCOME_CANCELLED,
                        response_summary=None,
                        error_type=(
                            type(result).__name__
                            if isinstance(
                                result,
                                BaseException,
                            )
                            else "UnknownTaskFailure"
                        ),
                        error_message=str(
                            result
                        ),
                        started_at_utc=utc_now_iso(),
                        finished_at_utc=utc_now_iso(),
                    )
                )

        finally:
            for task in request_tasks:
                if not task.done():
                    task.cancel()

        try:
            metrics_samples = await monitor_task
        except Exception as exc:
            validation_errors.append(
                "Shutdown metrics monitor failed: "
                f"{type(exc).__name__}: {exc}"
            )

        service_down = await _wait_until_unreachable(
            client=client,
            base_url=base_url,
            timeout_s=args.down_timeout_s,
        )

        logs, log_command = _read_logs(
            target=args.target or "local",
            docker_bin=args.docker_bin,
            container=(
                None
                if container is None
                else container["name"]
            ),
            log_file=args.log_file,
        )

        shutdown_log_evidence = (
            _shutdown_log_evidence(
                logs
            )
        )

        if args.target == "docker":
            if container is None:
                raise RuntimeError(
                    "Docker recovery requires the target container."
                )

            restart_command = await asyncio.to_thread(
                _run_command,
                [
                    args.docker_bin,
                    "start",
                    container["name"],
                ],
            )

            recovery_container_state = None

            if restart_command.ok:
                try:
                    recovery_container_state = (
                        await asyncio.to_thread(
                            _wait_for_container_state,
                            docker_bin=args.docker_bin,
                            container=container["name"],
                            expected_state="running",
                            timeout_s=args.startup_timeout_s,
                            poll_interval_s=(
                                args.monitor_interval_s
                            ),
                        )
                    )
                except Exception as exc:
                    validation_errors.append(
                        "Unable to verify Docker running state "
                        "after restart: "
                        f"{type(exc).__name__}: {exc}"
                    )

            recovery_liveness = None
            recovery_readiness = None
            recovery_metrics = None

            if restart_command.ok:
                recovery_liveness = (
                    await asyncio.to_thread(
                        wait_for_liveness,
                        base_url=base_url,
                        startup_timeout_s=(
                            args.startup_timeout_s
                        ),
                    )
                )

                recovery_readiness = (
                    await asyncio.to_thread(
                        wait_for_readiness,
                        base_url=base_url,
                        startup_timeout_s=(
                            args.startup_timeout_s
                        ),
                        allow_degraded=True,
                    )
                )

                recovery_metrics = await _fetch_metrics(
                    client,
                    base_url=base_url,
                    stage="recovery",
                    started=load_started,
                )

            recovery = RecoveryEvidence(
                restart_command=restart_command,
                container_state=(
                    recovery_container_state
                ),
                liveness_ok=(
                    recovery_liveness is not None
                    and getattr(
                        recovery_liveness,
                        "ok",
                        False,
                    )
                ),
                readiness_ok=(
                    recovery_readiness is not None
                    and getattr(
                        recovery_readiness,
                        "ok",
                        False,
                    )
                ),
                metrics_ok=(
                    recovery_metrics is not None
                    and recovery_metrics.status_code
                    == HTTP_SUCCESS_STATUS
                ),
            )

        else:
            recovery_liveness = (
                await asyncio.to_thread(
                    wait_for_liveness,
                    base_url=base_url,
                    startup_timeout_s=(
                        args.startup_timeout_s
                    ),
                )
            )

            recovery_readiness = (
                await asyncio.to_thread(
                    wait_for_readiness,
                    base_url=base_url,
                    startup_timeout_s=(
                        args.startup_timeout_s
                    ),
                    allow_degraded=True,
                )
            )

            recovery_metrics = await _fetch_metrics(
                client,
                base_url=base_url,
                stage="recovery",
                started=load_started,
            )

            recovery = RecoveryEvidence(
                restart_command=None,
                container_state=None,
                liveness_ok=(
                    getattr(
                        recovery_liveness,
                        "ok",
                        False,
                    )
                ),
                readiness_ok=(
                    getattr(
                        recovery_readiness,
                        "ok",
                        False,
                    )
                ),
                metrics_ok=(
                    recovery_metrics.status_code
                    == HTTP_SUCCESS_STATUS
                ),
            )

    peak_active_requests = _peak_metric(
        metrics_samples,
        "active_requests",
    )

    peak_waiting_requests = _peak_metric(
        metrics_samples,
        "waiting_requests",
    )

    validation_errors.extend(
        _validate_request_results(
            request_results=request_results,
            require_inflight=args.require_inflight,
            peak_active_requests=(
                peak_active_requests
            ),
        )
    )

    validation_errors.extend(
        _validate_shutdown_command(
            shutdown_command
        )
    )

    validation_errors.extend(
        _validate_service_down(
            service_down
        )
    )

    validation_errors.extend(
        _validate_metrics_samples(
            metrics_samples
        )
    )

    validation_errors.extend(
        _validate_shutdown_logs(
            evidence=shutdown_log_evidence,
            required=args.require_shutdown_logs,
        )
    )

    validation_errors.extend(
        _validate_recovery(
            target=args.target or "local",
            recovery=recovery,
        )
    )

    if (
        not args.require_inflight
        and (
            peak_active_requests is None
            or peak_active_requests <= 0
        )
    ):
        warnings.append(
            "No active protected request was observed before "
            "shutdown. --require-inflight is disabled, so this "
            "is recorded as a warning rather than a validation failure."
        )

    if (
        args.target == "local"
        and log_command is not None
        and not log_command.ok
    ):
        warnings.append(
            "Local shutdown logs could not be completely read."
        )

    if metrics_before is not None and (
        metrics_before.status_code
        != HTTP_SUCCESS_STATUS
    ):
        warnings.append(
            "Baseline /metrics did not return HTTP 200."
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

    outcome_counts = _outcome_counts(
        request_results
    )

    timestamp = timestamp_slug()

    raw_path = build_result_path(
        "phase11_graceful_shutdown_probe_raw",
        results_dir=args.results_dir,
        target=args.target,
        timestamp=timestamp,
    )

    summary_path = build_result_path(
        "phase11_graceful_shutdown_probe_summary",
        results_dir=args.results_dir,
        target=args.target,
        timestamp=timestamp,
    )

    raw_payload: dict[str, Any] = {
        "phase_code": PROJECT_PHASE_CODE,
        "phase_name": PROJECT_PHASE_NAME,
        "benchmark": "phase11_graceful_shutdown_probe",
        "started_at_utc": started_at_utc,
        "finished_at_utc": utc_now_iso(),
        "base_url": base_url,
        "target": args.target,
        "configuration": {
            "matrix_size": args.matrix_size,
            "inflight_requests": (
                args.inflight_requests
            ),
            "pre_shutdown_delay_s": (
                args.pre_shutdown_delay_s
            ),
            "monitor_interval_s": (
                args.monitor_interval_s
            ),
            "shutdown_timeout_s": (
                args.shutdown_timeout_s
            ),
            "request_timeout_s": (
                args.request_timeout_s
            ),
            "startup_timeout_s": (
                args.startup_timeout_s
            ),
            "down_timeout_s": (
                args.down_timeout_s
            ),
            "require_inflight": (
                args.require_inflight
            ),
            "require_shutdown_logs": (
                args.require_shutdown_logs
            ),
            "docker_bin": args.docker_bin,
            "container": args.container,
            "pid": args.pid,
            "log_file": (
                None
                if args.log_file is None
                else str(args.log_file)
            ),
        },
        "runtime_metadata": asdict(
            collect_runtime_metadata(
                base_url=base_url,
            )
        ),
        "container_resolution": (
            container_resolution
        ),
        "baseline": {
            "liveness": asdict(
                baseline_liveness
            ),
            "readiness": asdict(
                baseline_readiness
            ),
            "metrics": (
                None
                if metrics_before is None
                else asdict(
                    metrics_before
                )
            ),
        },
        "shutdown": {
            "command": (
                None
                if shutdown_command is None
                else asdict(
                    shutdown_command
                )
            ),
            "service_down": service_down,
            "metrics_at_shutdown": (
                None
                if metrics_at_shutdown is None
                else asdict(
                    metrics_at_shutdown
                )
            ),
            "peak_active_requests": (
                peak_active_requests
            ),
            "peak_waiting_requests": (
                peak_waiting_requests
            ),
            "metrics_summary": _metrics_summary(
                metrics_samples
            ),
            "metrics_samples": [
                asdict(sample)
                for sample in metrics_samples
            ],
            "request_results": [
                asdict(result)
                for result in request_results
            ],
            "outcome_counts": outcome_counts,
            "shutdown_log_evidence": asdict(
                shutdown_log_evidence
            ),
            "log_command": (
                None
                if log_command is None
                else asdict(
                    log_command
                )
            ),
            "logs_tail": _trim_logs(
                logs
            ),
        },
        "recovery": asdict(
            recovery
        ),
        "validation": asdict(
            validation
        ),
    }

    summary_payload: dict[str, Any] = {
        "phase_code": PROJECT_PHASE_CODE,
        "phase_name": PROJECT_PHASE_NAME,
        "benchmark": "phase11_graceful_shutdown_probe",
        "target": args.target,
        "base_url": base_url,
        "overall_ok": validation.overall_ok,
        "validation_errors": list(
            validation.validation_errors
        ),
        "warnings": list(
            validation.warnings
        ),
        "baseline_liveness_ok": getattr(
            baseline_liveness,
            "ok",
            False,
        ),
        "baseline_readiness_ok": getattr(
            baseline_readiness,
            "ok",
            False,
        ),
        "shutdown_command_ok": (
            shutdown_command is not None
            and shutdown_command.ok
        ),
        "service_down_after_shutdown": (
            service_down
        ),
        "peak_active_requests": (
            peak_active_requests
        ),
        "peak_waiting_requests": (
            peak_waiting_requests
        ),
        "inflight_observed": (
            peak_active_requests is not None
            and peak_active_requests > 0
        ),
        "shutdown_metrics": _metrics_summary(
            metrics_samples
        ),
        "shutdown_log_evidence": asdict(
            shutdown_log_evidence
        ),
        "request_outcome_counts": (
            outcome_counts
        ),
        "recovery": {
            "restart_ok": (
                recovery.restart_command is not None
                and recovery.restart_command.ok
            ),
            "container_running": (
                recovery.container_state is not None
                and recovery.container_state.running
            ),
            "liveness_ok": (
                recovery.liveness_ok
            ),
            "readiness_ok": (
                recovery.readiness_ok
            ),
            "metrics_ok": (
                recovery.metrics_ok
            ),
        },
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

    return (
        0
        if validation.overall_ok
        else 1
    )


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
            "Phase 11 graceful-shutdown probe interrupted",
            file=sys.stderr,
        )
        raise SystemExit(130) from None