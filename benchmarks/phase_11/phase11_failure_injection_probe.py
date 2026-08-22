# benchmarks/phase_11/phase11_failure_injection_probe.py

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

# Support both:
#   python benchmarks/phase_11/phase11_failure_injection_probe.py
#   python -m benchmarks.phase_11.phase11_failure_injection_probe

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
    print_json,
    timestamp_slug,
    utc_now_iso,
    wait_for_liveness,
    wait_for_readiness,
    write_json,
)

DEFAULT_DOCKER_BIN = "docker"
DEFAULT_STATE_TIMEOUT_S = 30.0
DEFAULT_POLL_INTERVAL_S = 0.5
DEFAULT_PAUSE_HOLD_S = 3.0
DEFAULT_HTTP_TIMEOUT_S = max(DEFAULT_TIMEOUT_S, 10.0)

API_CONTAINER_IMAGE_NAME = "cityroute-api"

METRICS_PATH = "/metrics"
LIVENESS_PATH = "/health/live"
READINESS_PATH = "/health/ready"
ROUTE_PATH = "/route"

ROUTE_PARAMS = {
    "start_lat": 26.455,
    "start_lon": 80.331,
    "end_lat": 26.468,
    "end_lon": 80.352,
}

PAUSE_COMMAND = "pause"
UNPAUSE_COMMAND = "unpause"

EXPECTED_PAUSED_STATE = True
EXPECTED_RUNNING_STATE = False

REQUESTS_METRIC = "cityroute_http_requests_total"
EXECUTION_METRIC = "cityroute_request_execution_seconds"

PAUSE_STATE_FIELD = "Paused"
STATUS_STATE_FIELD = "Status"
RUNNING_STATE = "running"


@dataclass(frozen=True)
class DockerCommandResult:
    """Result of one Docker CLI operation."""

    operation: str
    command: tuple[str, ...]
    return_code: int | None
    stdout: str
    stderr: str
    elapsed_ms: float
    ok: bool
    error_type: str | None
    error_message: str | None
    started_at_utc: str
    finished_at_utc: str


@dataclass(frozen=True)
class ContainerState:
    """Observable Docker container state."""

    container_id: str
    container_name: str
    status: str | None
    paused: bool | None
    running: bool | None
    captured_at_utc: str
    error_type: str | None
    error_message: str | None


@dataclass(frozen=True)
class HttpProbeResult:
    """One HTTP observation against the running API."""

    stage: str
    path: str
    status_code: int | None
    elapsed_ms: float
    ok: bool
    response_summary: Any | None
    error_type: str | None
    error_message: str | None
    started_at_utc: str
    finished_at_utc: str


@dataclass(frozen=True)
class MetricsSnapshot:
    """Selected Prometheus metrics captured at one point in time."""

    stage: str
    status_code: int | None
    elapsed_ms: float
    raw_text_available: bool
    request_counter_total: float | None
    execution_sample_count: float | None
    error_type: str | None
    error_message: str | None
    captured_at_utc: str


@dataclass(frozen=True)
class FreezeEvidence:
    """Evidence that the failure injection really paused the container."""

    requested: bool
    docker_pause_ok: bool
    paused_state_observed: bool
    pause_state: ContainerState
    pause_command: DockerCommandResult
    captured_at_utc: str


@dataclass(frozen=True)
class RecoveryEvidence:
    """Evidence that the same container recovered without restart."""

    unpause_command: DockerCommandResult
    running_state_observed: bool
    restored_container_state: ContainerState
    liveness_recovered: bool
    readiness_recovered: bool
    recovered_metrics: MetricsSnapshot
    captured_at_utc: str


@dataclass(frozen=True)
class ValidationResult:
    """Structured benchmark validation result."""

    validation_errors: tuple[str, ...]
    warnings: tuple[str, ...]
    overall_ok: bool


def parse_args() -> argparse.Namespace:
    """Parse and validate command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Inject a transient Docker container freeze into the CityRoute "
            "API, verify the frozen runtime state, unpause the same "
            "container without restarting it, and prove service recovery."
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
        choices=("docker",),
        default="docker",
        help="Phase 11 failure-injection target. Default: docker",
    )

    parser.add_argument(
        "--results-dir",
        type=Path,
        default=None,
        help=(
            "Explicit Phase 11 result directory. "
            "Overrides the standard result location."
        ),
    )

    parser.add_argument(
        "--api-container",
        default=None,
        help=(
            "Exact CityRoute API container name or ID. "
            "When omitted, the probe discovers a suitable running "
            "container from Docker."
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
        "--state-timeout-s",
        type=float,
        default=DEFAULT_STATE_TIMEOUT_S,
        help=(
            "Maximum wait for Docker paused/running state transitions. "
            f"Default: {DEFAULT_STATE_TIMEOUT_S}"
        ),
    )

    parser.add_argument(
        "--poll-interval-s",
        type=float,
        default=DEFAULT_POLL_INTERVAL_S,
        help=(
            "Polling interval for Docker state transitions. "
            f"Default: {DEFAULT_POLL_INTERVAL_S}"
        ),
    )

    parser.add_argument(
        "--pause-hold-s",
        type=float,
        default=DEFAULT_PAUSE_HOLD_S,
        help=(
            "Time to keep the API container paused before unpausing. "
            f"Default: {DEFAULT_PAUSE_HOLD_S}"
        ),
    )

    parser.add_argument(
        "--timeout-s",
        type=float,
        default=DEFAULT_HTTP_TIMEOUT_S,
        help=(
            "HTTP timeout used while probing liveness, readiness, "
            f"and metrics. Default: {DEFAULT_HTTP_TIMEOUT_S}"
        ),
    )

    parser.add_argument(
        "--require-readiness-recovery",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Require /health/ready to recover after unpause. "
            "Default: enabled."
        ),
    )

    parser.add_argument(
        "--require-metrics-recovery",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Require /metrics to become scrapeable after unpause. "
            "Default: enabled."
        ),
    )

    parser.add_argument(
        "--fail-on-validation-error",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Exit non-zero when failure-injection validation fails. "
            "Default: enabled."
        ),
    )

    args = parser.parse_args()

    if args.state_timeout_s <= 0:
        parser.error(
            "--state-timeout-s must be greater than zero"
        )

    if args.poll_interval_s <= 0:
        parser.error(
            "--poll-interval-s must be greater than zero"
        )

    if args.pause_hold_s <= 0:
        parser.error(
            "--pause-hold-s must be greater than zero"
        )

    if args.timeout_s <= 0:
        parser.error(
            "--timeout-s must be greater than zero"
        )

    return args


def _run_docker_command(
    *,
    docker_bin: str,
    arguments: list[str],
    operation: str,
) -> DockerCommandResult:
    """Execute one Docker CLI operation with structured failure capture."""

    command = (
        docker_bin,
        *arguments,
    )

    started_at_utc = utc_now_iso()
    started = time.perf_counter()

    return_code: int | None = None
    stdout = ""
    stderr = ""
    error_type: str | None = None
    error_message: str | None = None

    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )

        return_code = completed.returncode
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()

    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    return DockerCommandResult(
        operation=operation,
        command=command,
        return_code=return_code,
        stdout=stdout,
        stderr=stderr,
        elapsed_ms=(
            time.perf_counter() - started
        ) * 1000.0,
        ok=(
            return_code == 0
            and error_type is None
        ),
        error_type=error_type,
        error_message=error_message,
        started_at_utc=started_at_utc,
        finished_at_utc=utc_now_iso(),
    )


def _discover_api_container(
    *,
    docker_bin: str,
    explicit_container: str | None,
) -> str:
    """Resolve the CityRoute API container from Docker."""

    if explicit_container:
        return explicit_container

    result = _run_docker_command(
        docker_bin=docker_bin,
        arguments=[
            "ps",
            "--filter",
            f"ancestor={API_CONTAINER_IMAGE_NAME}",
            "--format",
            "{{.ID}}",
        ],
        operation="discover_api_container",
    )

    if not result.ok:
        raise RuntimeError(
            "Unable to discover CityRoute API container. "
            f"docker_error={result.error_message or result.stderr}"
        )

    candidates = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
    ]

    if len(candidates) == 1:
        return candidates[0]

    if not candidates:
        fallback = _run_docker_command(
            docker_bin=docker_bin,
            arguments=[
                "ps",
                "--format",
                "{{.ID}}\t{{.Image}}\t{{.Names}}",
            ],
            operation="discover_api_container_fallback",
        )

        if not fallback.ok:
            raise RuntimeError(
                "No CityRoute API container found and fallback discovery "
                "failed."
            )

        matching = [
            line.split("\t", maxsplit=2)
            for line in fallback.stdout.splitlines()
            if line.strip()
            and "cityroute-api" in line.lower()
        ]

        if len(matching) == 1:
            return matching[0][0]

        raise RuntimeError(
            "Unable to uniquely identify a running CityRoute API container."
        )

    raise RuntimeError(
        "Multiple candidate CityRoute API containers were discovered. "
        "Specify --api-container explicitly."
    )


def _inspect_container(
    *,
    docker_bin: str,
    container: str,
) -> ContainerState:
    """Read authoritative container state from Docker."""

    result = _run_docker_command(
        docker_bin=docker_bin,
        arguments=[
            "inspect",
            "--format",
            (
                "{{.Id}}\t"
                "{{.Name}}\t"
                "{{.State.Status}}\t"
                "{{.State.Paused}}\t"
                "{{.State.Running}}"
            ),
            container,
        ],
        operation="inspect_container",
    )

    if not result.ok:
        return ContainerState(
            container_id=container,
            container_name=container,
            status=None,
            paused=None,
            running=None,
            captured_at_utc=utc_now_iso(),
            error_type=(
                result.error_type
                or "DockerInspectError"
            ),
            error_message=(
                result.error_message
                or result.stderr
                or "docker inspect failed"
            ),
        )

    fields = result.stdout.split("\t")

    if len(fields) != 5:
        return ContainerState(
            container_id=container,
            container_name=container,
            status=None,
            paused=None,
            running=None,
            captured_at_utc=utc_now_iso(),
            error_type="InvalidInspectOutput",
            error_message=(
                "Unexpected docker inspect output: "
                f"{result.stdout!r}"
            ),
        )

    return ContainerState(
        container_id=fields[0],
        container_name=fields[1].lstrip("/"),
        status=fields[2] or None,
        paused=_parse_bool(fields[3]),
        running=_parse_bool(fields[4]),
        captured_at_utc=utc_now_iso(),
        error_type=None,
        error_message=None,
    )


def _parse_bool(value: str) -> bool | None:
    """Parse Docker boolean text without silently accepting invalid values."""

    normalized = value.strip().lower()

    if normalized == "true":
        return True

    if normalized == "false":
        return False

    return None


def _wait_for_container_state(
    *,
    docker_bin: str,
    container: str,
    expected_paused: bool,
    timeout_s: float,
    poll_interval_s: float,
) -> ContainerState:
    """Wait until Docker reports the expected paused state."""

    started = time.perf_counter()
    last_state = _inspect_container(
        docker_bin=docker_bin,
        container=container,
    )

    while time.perf_counter() - started <= timeout_s:
        if (
            last_state.paused
            is expected_paused
        ):
            return last_state

        time.sleep(poll_interval_s)

        last_state = _inspect_container(
            docker_bin=docker_bin,
            container=container,
        )

    raise TimeoutError(
        "Container state transition was not observed within "
        f"{timeout_s:.3f}s. "
        f"expected_paused={expected_paused} "
        f"last_state={asdict(last_state)}"
    )


async def _request(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    stage: str,
    path: str,
    timeout_s: float,
    params: dict[str, Any] | None = None,
) -> HttpProbeResult:
    """Execute one HTTP probe and preserve failure context."""

    started_at_utc = utc_now_iso()
    started = time.perf_counter()

    status_code: int | None = None
    response_summary: Any | None = None
    error_type: str | None = None
    error_message: str | None = None

    try:
        response = await client.get(
            f"{base_url.rstrip('/')}{path}",
            params=params,
            timeout=timeout_s,
        )

        status_code = response.status_code

        try:
            response_summary = response.json()
        except (ValueError, json.JSONDecodeError):
            response_summary = response.text[:500]

    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    elapsed_ms = (
        time.perf_counter() - started
    ) * 1000.0

    return HttpProbeResult(
        stage=stage,
        path=path,
        status_code=status_code,
        elapsed_ms=elapsed_ms,
        ok=(
            status_code == 200
            and error_type is None
        ),
        response_summary=response_summary,
        error_type=error_type,
        error_message=error_message,
        started_at_utc=started_at_utc,
        finished_at_utc=utc_now_iso(),
    )


def _parse_metric_value(
    *,
    body: str,
    metric_name: str,
) -> float | None:
    """Extract the first numeric Prometheus sample for a metric family."""

    for line in body.splitlines():
        normalized = line.strip()

        if not normalized.startswith(
            metric_name
        ):
            continue

        if normalized.startswith(
            f"# {metric_name}"
        ):
            continue

        if "{" not in normalized:
            continue

        _, value_text = normalized.rsplit(
            "}",
            maxsplit=1,
        )

        value_text = value_text.strip()

        try:
            return float(value_text)
        except ValueError:
            continue

    return None


def _count_metric_samples(
    *,
    body: str,
    metric_name: str,
) -> float | None:
    """Count exposed samples belonging to a Prometheus metric family."""

    count = 0

    for line in body.splitlines():
        normalized = line.strip()

        if normalized.startswith(
            f"# {metric_name}"
        ):
            continue

        if normalized.startswith(
            f"# TYPE {metric_name}"
        ):
            continue

        if normalized.startswith(
            f"{metric_name}_count{{"
        ):
            count += 1

    return float(count) if count else None


async def _capture_metrics(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    stage: str,
    timeout_s: float,
) -> MetricsSnapshot:
    """Capture selected reliability metrics."""

    started_at_utc = utc_now_iso()
    started = time.perf_counter()

    status_code: int | None = None
    raw_text_available = False
    request_counter_total: float | None = None
    execution_sample_count: float | None = None
    error_type: str | None = None
    error_message: str | None = None

    try:
        response = await client.get(
            f"{base_url.rstrip('/')}{METRICS_PATH}",
            timeout=timeout_s,
        )

        status_code = response.status_code
        raw_text_available = bool(
            response.text
        )

        if response.status_code == 200:
            request_counter_total = _parse_metric_value(
                body=response.text,
                metric_name=REQUESTS_METRIC,
            )

            execution_sample_count = _count_metric_samples(
                body=response.text,
                metric_name=EXECUTION_METRIC,
            )

    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    return MetricsSnapshot(
        stage=stage,
        status_code=status_code,
        elapsed_ms=(
            time.perf_counter() - started
        ) * 1000.0,
        raw_text_available=raw_text_available,
        request_counter_total=request_counter_total,
        execution_sample_count=execution_sample_count,
        error_type=error_type,
        error_message=error_message,
        captured_at_utc=utc_now_iso(),
    )


async def _capture_baseline(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    timeout_s: float,
) -> tuple[
    HttpProbeResult,
    HttpProbeResult,
    HttpProbeResult,
    MetricsSnapshot,
]:
    """Collect healthy baseline evidence before failure injection."""

    liveness = await _request(
        client=client,
        base_url=base_url,
        stage="baseline",
        path=LIVENESS_PATH,
        timeout_s=timeout_s,
    )

    readiness = await _request(
        client=client,
        base_url=base_url,
        stage="baseline",
        path=READINESS_PATH,
        timeout_s=timeout_s,
    )

    protected_request = await _request(
        client=client,
        base_url=base_url,
        stage="baseline",
        path=ROUTE_PATH,
        timeout_s=timeout_s,
        params=ROUTE_PARAMS,
    )

    metrics = await _capture_metrics(
        client=client,
        base_url=base_url,
        stage="baseline",
        timeout_s=timeout_s,
    )

    return (
        liveness,
        readiness,
        protected_request,
        metrics,
    )


async def _probe_paused_container(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    timeout_s: float,
) -> tuple[
    HttpProbeResult,
    HttpProbeResult,
    MetricsSnapshot,
]:
    """Observe expected API unavailability while the container is paused."""

    liveness = await _request(
        client=client,
        base_url=base_url,
        stage="paused",
        path=LIVENESS_PATH,
        timeout_s=timeout_s,
    )

    readiness = await _request(
        client=client,
        base_url=base_url,
        stage="paused",
        path=READINESS_PATH,
        timeout_s=timeout_s,
    )

    metrics = await _capture_metrics(
        client=client,
        base_url=base_url,
        stage="paused",
        timeout_s=timeout_s,
    )

    return (
        liveness,
        readiness,
        metrics,
    )


async def _probe_recovery(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    timeout_s: float,
    startup_timeout_s: float,
) -> tuple[
    HttpProbeResult,
    HttpProbeResult,
    HttpProbeResult,
    MetricsSnapshot,
]:
    """Wait for API recovery and capture post-failure evidence."""

    liveness_response = await asyncio.to_thread(
        wait_for_liveness,
        base_url=base_url,
        startup_timeout_s=startup_timeout_s,
    )

    liveness = HttpProbeResult(
        stage="recovered",
        path=LIVENESS_PATH,
        status_code=liveness_response.status_code,
        elapsed_ms=liveness_response.elapsed_ms,
        ok=liveness_response.ok,
        response_summary=liveness_response.response_json,
        error_type=liveness_response.error_type,
        error_message=liveness_response.error_message,
        started_at_utc=liveness_response.started_at_utc,
finished_at_utc=liveness_response.finished_at_utc,
    )

    readiness_response = await asyncio.to_thread(
        wait_for_readiness,
        base_url=base_url,
        startup_timeout_s=startup_timeout_s,
        allow_degraded=True,
    )

    readiness = HttpProbeResult(
        stage="recovered",
        path=READINESS_PATH,
        status_code=readiness_response.status_code,
        elapsed_ms=readiness_response.elapsed_ms,
        ok=readiness_response.status_code == 200,
        response_summary=readiness_response.response_json,
        error_type=readiness_response.error_type,
        error_message=readiness_response.error_message,
        started_at_utc=readiness_response.started_at_utc,
        finished_at_utc=readiness_response.finished_at_utc,
    )

    protected_request = await _request(
        client=client,
        base_url=base_url,
        stage="recovered",
        path=ROUTE_PATH,
        timeout_s=timeout_s,
        params=ROUTE_PARAMS,
    )

    metrics = await _capture_metrics(
        client=client,
        base_url=base_url,
        stage="recovered",
        timeout_s=timeout_s,
    )

    return (
        liveness,
        readiness,
        protected_request,
        metrics,
    )


def _validate_baseline(
    *,
    liveness: HttpProbeResult,
    readiness: HttpProbeResult,
    protected_request: HttpProbeResult,
    metrics: MetricsSnapshot,
) -> list[str]:
    """Validate that the service was healthy before fault injection."""

    errors: list[str] = []

    if not liveness.ok:
        errors.append(
            "Baseline liveness check did not return HTTP 200"
        )

    if not readiness.ok:
        errors.append(
            "Baseline readiness check did not return HTTP 200"
        )

    if not protected_request.ok:
        errors.append(
            "Baseline protected endpoint request did not return HTTP 200"
        )

    if metrics.status_code != 200:
        errors.append(
            "Baseline metrics endpoint did not return HTTP 200"
        )

    if not metrics.raw_text_available:
        errors.append(
            "Baseline metrics response contained no body"
        )

    return errors


def _validate_freeze(
    *,
    pause_command: DockerCommandResult,
    paused_state: ContainerState,
    paused_liveness: HttpProbeResult,
    paused_readiness: HttpProbeResult,
    paused_metrics: MetricsSnapshot,
) -> tuple[list[str], list[str]]:
    """Validate the injected freeze and its expected API impact."""

    errors: list[str] = []
    warnings: list[str] = []

    if not pause_command.ok:
        errors.append(
            "Docker pause command failed"
        )

    if paused_state.paused is not EXPECTED_PAUSED_STATE:
        errors.append(
            "Docker did not report the API container as paused"
        )

    if paused_state.status != RUNNING_STATE:
        warnings.append(
            "Container status changed away from running while paused"
        )

    paused_api_unavailable = not paused_liveness.ok
    paused_readiness_unavailable = not paused_readiness.ok
    paused_metrics_unavailable = (
        paused_metrics.status_code != 200
    )

    if not paused_api_unavailable:
        errors.append(
            "API liveness remained successful while the worker "
            "was expected to be frozen"
        )

    if not paused_readiness_unavailable:
        errors.append(
            "API readiness remained successful while the worker "
            "was expected to be frozen"
        )

    if not paused_metrics_unavailable:
        errors.append(
            "Metrics remained scrapeable while the container "
            "was expected to be frozen"
        )

    return errors, warnings


def _validate_recovery(
    *,
    unpause_command: DockerCommandResult,
    restored_state: ContainerState,
    recovered_liveness: HttpProbeResult,
    recovered_readiness: HttpProbeResult,
    recovered_protected_request: HttpProbeResult,
    recovered_metrics: MetricsSnapshot,
    require_readiness_recovery: bool,
    require_metrics_recovery: bool,
) -> list[str]:
    """Validate recovery without restarting the API container."""

    errors: list[str] = []

    if not unpause_command.ok:
        errors.append(
            "Docker unpause command failed"
        )

    if restored_state.paused is not EXPECTED_RUNNING_STATE:
        errors.append(
            "Docker did not report the API container as unpaused"
        )

    if restored_state.running is not True:
        errors.append(
            "API container did not return to running state"
        )

    if not recovered_liveness.ok:
        errors.append(
            "API liveness did not recover after unpause"
        )

    if not recovered_protected_request.ok:
        errors.append(
            "Protected endpoint did not recover after unpause"
        )

    if (
        require_readiness_recovery
        and not recovered_readiness.ok
    ):
        errors.append(
            "API readiness did not recover after unpause"
        )

    if (
        require_metrics_recovery
        and recovered_metrics.status_code != 200
    ):
        errors.append(
            "Metrics endpoint did not recover after unpause"
        )

    return errors


def _validate_metric_continuity(
    *,
    baseline: MetricsSnapshot,
    recovered: MetricsSnapshot,
) -> list[str]:
    """Validate that metrics remained available after recovery."""

    errors: list[str] = []

    if baseline.request_counter_total is None:
        errors.append(
            f"Baseline metric {REQUESTS_METRIC} was not exposed"
        )

    if recovered.request_counter_total is None:
        errors.append(
            f"Recovered metric {REQUESTS_METRIC} was not exposed"
        )

    if baseline.execution_sample_count is None:
        errors.append(
            f"Baseline metric family {EXECUTION_METRIC} was not exposed"
        )

    if recovered.execution_sample_count is None:
        errors.append(
            f"Recovered metric family {EXECUTION_METRIC} was not exposed"
        )

    if (
        baseline.request_counter_total is not None
        and recovered.request_counter_total is not None
        and recovered.request_counter_total
        < baseline.request_counter_total
    ):
        errors.append(
            f"{REQUESTS_METRIC} decreased after recovery"
        )

    return errors


def _build_validation_result(
    *,
    baseline_errors: list[str],
    freeze_errors: list[str],
    recovery_errors: list[str],
    metric_errors: list[str],
    warnings: list[str],
) -> ValidationResult:
    """Assemble final benchmark validation state."""

    validation_errors = (
        *baseline_errors,
        *freeze_errors,
        *recovery_errors,
        *metric_errors,
    )

    return ValidationResult(
        validation_errors=tuple(
            validation_errors
        ),
        warnings=tuple(warnings),
        overall_ok=not validation_errors,
    )


async def async_main(
    args: argparse.Namespace,
) -> int:
    """Orchestrate the complete failure-injection benchmark."""

    base_url = args.base_url.rstrip("/")
    started_at_utc = utc_now_iso()

    container = _discover_api_container(
        docker_bin=args.docker_bin,
        explicit_container=args.api_container,
    )

    initial_container_state = _inspect_container(
        docker_bin=args.docker_bin,
        container=container,
    )

    if initial_container_state.error_type is not None:
        raise RuntimeError(
            "Unable to inspect selected API container: "
            f"{initial_container_state.error_message}"
        )

    if initial_container_state.paused is True:
        raise RuntimeError(
            "Selected API container is already paused. "
            "Refusing to run failure injection against a pre-paused container."
        )

    if initial_container_state.running is not True:
        raise RuntimeError(
            "Selected API container is not running. "
            "Start CityRoute before running the failure-injection probe."
        )

    baseline_liveness: HttpProbeResult
    baseline_readiness: HttpProbeResult
    baseline_protected_request: HttpProbeResult
    baseline_metrics: MetricsSnapshot

    paused_liveness: HttpProbeResult | None = None
    paused_readiness: HttpProbeResult | None = None
    paused_metrics: MetricsSnapshot | None = None

    pause_command: DockerCommandResult | None = None
    unpause_command: DockerCommandResult | None = None

    paused_state: ContainerState | None = None
    restored_state: ContainerState | None = None

    recovered_liveness: HttpProbeResult | None = None
    recovered_readiness: HttpProbeResult | None = None
    recovered_protected_request: HttpProbeResult | None = None
    recovered_metrics: MetricsSnapshot | None = None

    baseline_errors: list[str] = []
    freeze_errors: list[str] = []
    recovery_errors: list[str] = []
    metric_errors: list[str] = []
    warnings: list[str] = []

    async with httpx.AsyncClient(
        timeout=args.timeout_s,
    ) as client:
        (
            baseline_liveness,
            baseline_readiness,
            baseline_protected_request,
            baseline_metrics,
        ) = await _capture_baseline(
            client=client,
            base_url=base_url,
            timeout_s=args.timeout_s,
        )

        baseline_errors.extend(
            _validate_baseline(
                liveness=baseline_liveness,
                readiness=baseline_readiness,
                protected_request=baseline_protected_request,
                metrics=baseline_metrics,
            )
        )

        if baseline_errors:
            validation = _build_validation_result(
                baseline_errors=baseline_errors,
                freeze_errors=freeze_errors,
                recovery_errors=recovery_errors,
                metric_errors=metric_errors,
                warnings=warnings,
            )

            return _write_report_and_return(
                args=args,
                base_url=base_url,
                container=container,
                initial_container_state=initial_container_state,
                baseline_liveness=baseline_liveness,
                baseline_readiness=baseline_readiness,
                baseline_protected_request=(
                    baseline_protected_request
                ),
                baseline_metrics=baseline_metrics,
                pause_command=None,
                paused_state=None,
                paused_liveness=None,
                paused_readiness=None,
                paused_metrics=None,
                unpause_command=None,
                restored_state=None,
                recovered_liveness=None,
                recovered_readiness=None,
                recovered_protected_request=None,
                recovered_metrics=None,
                validation=validation,
                started_at_utc=started_at_utc,
            )

        pause_command = await asyncio.to_thread(
            _run_docker_command,
            docker_bin=args.docker_bin,
            arguments=[
                PAUSE_COMMAND,
                container,
            ],
            operation="pause_api_container",
        )

        try:
            paused_state = await asyncio.to_thread(
                _wait_for_container_state,
                docker_bin=args.docker_bin,
                container=container,
                expected_paused=EXPECTED_PAUSED_STATE,
                timeout_s=args.state_timeout_s,
                poll_interval_s=args.poll_interval_s,
            )

            (
                paused_liveness,
                paused_readiness,
                paused_metrics,
            ) = await _probe_paused_container(
                client=client,
                base_url=base_url,
                timeout_s=args.timeout_s,
            )

            freeze_errors, freeze_warnings = _validate_freeze(
                pause_command=pause_command,
                paused_state=paused_state,
                paused_liveness=paused_liveness,
                paused_readiness=paused_readiness,
                paused_metrics=paused_metrics,
            )

            warnings.extend(
                freeze_warnings
            )

            if args.pause_hold_s > 0:
                await asyncio.sleep(
                    args.pause_hold_s
                )

        finally:
            unpause_command = await asyncio.to_thread(
                _run_docker_command,
                docker_bin=args.docker_bin,
                arguments=[
                    UNPAUSE_COMMAND,
                    container,
                ],
                operation="unpause_api_container",
            )

        restored_state = await asyncio.to_thread(
            _wait_for_container_state,
            docker_bin=args.docker_bin,
            container=container,
            expected_paused=EXPECTED_RUNNING_STATE,
            timeout_s=args.state_timeout_s,
            poll_interval_s=args.poll_interval_s,
        )

        (
            recovered_liveness,
            recovered_readiness,
            recovered_protected_request,
            recovered_metrics,
        ) = await _probe_recovery(
            client=client,
            base_url=base_url,
            timeout_s=args.timeout_s,
            startup_timeout_s=args.state_timeout_s,
        )

        recovery_errors.extend(
            _validate_recovery(
                unpause_command=unpause_command,
                restored_state=restored_state,
                recovered_liveness=recovered_liveness,
                recovered_readiness=recovered_readiness,
                recovered_protected_request=(
                    recovered_protected_request
                ),
                recovered_metrics=recovered_metrics,
                require_readiness_recovery=(
                    args.require_readiness_recovery
                ),
                require_metrics_recovery=(
                    args.require_metrics_recovery
                ),
            )
        )

        metric_errors.extend(
            _validate_metric_continuity(
                baseline=baseline_metrics,
                recovered=recovered_metrics,
            )
        )

    validation = _build_validation_result(
        baseline_errors=baseline_errors,
        freeze_errors=freeze_errors,
        recovery_errors=recovery_errors,
        metric_errors=metric_errors,
        warnings=warnings,
    )

    return _write_report_and_return(
        args=args,
        base_url=base_url,
        container=container,
        initial_container_state=initial_container_state,
        baseline_liveness=baseline_liveness,
        baseline_readiness=baseline_readiness,
        baseline_protected_request=(
            baseline_protected_request
        ),
        baseline_metrics=baseline_metrics,
        pause_command=pause_command,
        paused_state=paused_state,
        paused_liveness=paused_liveness,
        paused_readiness=paused_readiness,
        paused_metrics=paused_metrics,
        unpause_command=unpause_command,
        restored_state=restored_state,
        recovered_liveness=recovered_liveness,
        recovered_readiness=recovered_readiness,
        recovered_protected_request=(
            recovered_protected_request
        ),
        recovered_metrics=recovered_metrics,
        validation=validation,
        started_at_utc=started_at_utc,
    )

def _write_report_and_return(
    *,
    args: argparse.Namespace,
    base_url: str,
    container: str,
    initial_container_state: ContainerState,
    baseline_liveness: HttpProbeResult,
    baseline_readiness: HttpProbeResult,
    baseline_protected_request: HttpProbeResult,
    baseline_metrics: MetricsSnapshot,
    pause_command: DockerCommandResult | None,
    paused_state: ContainerState | None,
    paused_liveness: HttpProbeResult | None,
    paused_readiness: HttpProbeResult | None,
    paused_metrics: MetricsSnapshot | None,
    unpause_command: DockerCommandResult | None,
    restored_state: ContainerState | None,
    recovered_liveness: HttpProbeResult | None,
    recovered_readiness: HttpProbeResult | None,
    recovered_protected_request: HttpProbeResult | None,
    recovered_metrics: MetricsSnapshot | None,
    validation: ValidationResult,
    started_at_utc: str,
) -> int:
    """Serialize detailed evidence and concise benchmark summary."""

    timestamp = timestamp_slug()

    raw_path = build_result_path(
        "phase11_failure_injection_probe_raw",
        results_dir=args.results_dir,
        target=args.target,
        timestamp=timestamp,
    )

    summary_path = build_result_path(
        "phase11_failure_injection_probe_summary",
        results_dir=args.results_dir,
        target=args.target,
        timestamp=timestamp,
    )

    freeze_evidence = None

    if (
        pause_command is not None
        and paused_state is not None
    ):
        freeze_evidence = FreezeEvidence(
            requested=True,
            docker_pause_ok=pause_command.ok,
            paused_state_observed=(
                paused_state.paused is True
            ),
            pause_state=paused_state,
            pause_command=pause_command,
            captured_at_utc=utc_now_iso(),
        )

    recovery_evidence = None

    if (
        unpause_command is not None
        and restored_state is not None
        and recovered_liveness is not None
        and recovered_readiness is not None
        and recovered_metrics is not None
    ):
        recovery_evidence = RecoveryEvidence(
            unpause_command=unpause_command,
            running_state_observed=(
                restored_state.paused is False
                and restored_state.running is True
            ),
            restored_container_state=restored_state,
            liveness_recovered=recovered_liveness.ok,
            readiness_recovered=recovered_readiness.ok,
            recovered_metrics=recovered_metrics,
            captured_at_utc=utc_now_iso(),
        )

    raw_payload: dict[str, Any] = {
        "phase_code": PROJECT_PHASE_CODE,
        "phase_name": PROJECT_PHASE_NAME,
        "benchmark": "phase11_failure_injection_probe",
        "started_at_utc": started_at_utc,
        "finished_at_utc": utc_now_iso(),
        "base_url": base_url,
        "target": args.target,
        "failure_mode": "transient_api_container_freeze",
        "failure_mechanism": (
            "docker pause / docker unpause"
        ),
        "configuration": {
            "api_container": container,
            "docker_bin": args.docker_bin,
            "state_timeout_s": args.state_timeout_s,
            "poll_interval_s": args.poll_interval_s,
            "pause_hold_s": args.pause_hold_s,
            "timeout_s": args.timeout_s,
            "require_readiness_recovery": (
                args.require_readiness_recovery
            ),
            "require_metrics_recovery": (
                args.require_metrics_recovery
            ),
            "fail_on_validation_error": (
                args.fail_on_validation_error
            ),
        },
        "runtime_metadata": asdict(
            collect_runtime_metadata(
                base_url=base_url,
            )
        ),
        "container": {
            "id": initial_container_state.container_id,
            "name": initial_container_state.container_name,
        },
        "initial_container_state": asdict(
            initial_container_state
        ),
        "baseline": {
            "liveness": asdict(
                baseline_liveness
            ),
            "readiness": asdict(
                baseline_readiness
            ),
            "protected_request": asdict(
                baseline_protected_request
            ),
            "metrics": asdict(
                baseline_metrics
            ),
        },
        "freeze_evidence": (
            None
            if freeze_evidence is None
            else asdict(freeze_evidence)
        ),
        "paused_observations": {
            "liveness": (
                None
                if paused_liveness is None
                else asdict(paused_liveness)
            ),
            "readiness": (
                None
                if paused_readiness is None
                else asdict(paused_readiness)
            ),
            "metrics": (
                None
                if paused_metrics is None
                else asdict(paused_metrics)
            ),
        },
        "recovery_evidence": (
            None
            if recovery_evidence is None
            else asdict(recovery_evidence)
        ),
        "recovered_observations": {
            "liveness": (
                None
                if recovered_liveness is None
                else asdict(recovered_liveness)
            ),
            "readiness": (
                None
                if recovered_readiness is None
                else asdict(recovered_readiness)
            ),
            "protected_request": (
                None
                if recovered_protected_request is None
                else asdict(
                    recovered_protected_request
                )
            ),
            "metrics": (
                None
                if recovered_metrics is None
                else asdict(recovered_metrics)
            ),
        },
        "validation": asdict(validation),
    }

    summary_payload: dict[str, Any] = {
        "phase_code": PROJECT_PHASE_CODE,
        "phase_name": PROJECT_PHASE_NAME,
        "benchmark": "phase11_failure_injection_probe",
        "failure_mode": "transient_api_container_freeze",
        "failure_mechanism": (
            "docker pause / docker unpause"
        ),
        "overall_ok": validation.overall_ok,
        "container": {
            "id": container,
            "name": initial_container_state.container_name,
        },
        "baseline": {
            "liveness_ok": baseline_liveness.ok,
            "readiness_ok": baseline_readiness.ok,
            "protected_request_ok": (
                baseline_protected_request.ok
            ),
        },
        "injection": {
            "pause_command_ok": (
                pause_command is not None
                and pause_command.ok
            ),
            "paused_state_observed": (
                paused_state is not None
                and paused_state.paused is True
            ),
            "paused_liveness_unavailable": (
                paused_liveness is not None
                and not paused_liveness.ok
            ),
            "paused_readiness_unavailable": (
                paused_readiness is not None
                and not paused_readiness.ok
            ),
        },
        "recovery": {
            "unpause_command_ok": (
                unpause_command is not None
                and unpause_command.ok
            ),
            "running_state_observed": (
                restored_state is not None
                and restored_state.paused is False
                and restored_state.running is True
            ),
            "liveness_recovered": (
                recovered_liveness is not None
                and recovered_liveness.ok
            ),
            "readiness_recovered": (
                recovered_readiness is not None
                and recovered_readiness.ok
            ),
            "protected_request_recovered": (
                recovered_protected_request is not None
                and recovered_protected_request.ok
            ),
            "metrics_recovered": (
                recovered_metrics is not None
                and recovered_metrics.status_code == 200
            ),
        },
        "metrics": {
            "baseline_request_counter": (
                baseline_metrics.request_counter_total
            ),
            "recovered_request_counter": (
                None
                if recovered_metrics is None
                else recovered_metrics.request_counter_total
            ),
            "baseline_execution_sample_count": (
                baseline_metrics.execution_sample_count
            ),
            "recovered_execution_sample_count": (
                None
                if recovered_metrics is None
                else recovered_metrics.execution_sample_count
            ),
        },
        "validation_errors": list(
            validation.validation_errors
        ),
        "warnings": list(
            validation.warnings
        ),
        "raw_result_path": str(raw_path),
        "summary_result_path": str(summary_path),
    }

    write_json(
        raw_path,
        raw_payload,
    )

    write_json(
        summary_path,
        summary_payload,
    )

    print_json(summary_payload)

    if (
        args.fail_on_validation_error
        and validation.validation_errors
    ):
        return 1

    return 0 if validation.overall_ok else 1


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
            "Phase 11 failure-injection probe interrupted",
            file=sys.stderr,
        )
        raise SystemExit(130) from None