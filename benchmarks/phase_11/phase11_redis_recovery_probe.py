# benchmarks/phase_11/phase11_redis_recovery_probe.py

from __future__ import annotations

import argparse
import asyncio
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

# Support both:
#   python benchmarks/phase_11/phase11_redis_recovery_probe.py
#   python -m benchmarks.phase_11.phase11_redis_recovery_probe
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

DEFAULT_MATRIX_SIZE = 10
DEFAULT_STATE_TIMEOUT_S = 30.0
DEFAULT_POLL_INTERVAL_S = 0.5

REDIS_AVAILABLE_METRIC = "cityroute_redis_available"
REDIS_FAILURES_METRIC = "cityroute_redis_failures_total"
REDIS_RECOVERIES_METRIC = "cityroute_redis_recoveries_total"
PROCESS_START_METRIC = "process_start_time_seconds"


@dataclass(frozen=True)
class DockerContainer:
    container_id: str
    name: str
    image: str
    state: str
    health: str | None


@dataclass(frozen=True)
class CommandResult:
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
class MatrixResult:
    stage: str
    attempt_index: int
    status_code: int | None
    elapsed_ms: float
    cache_enabled: bool | None
    cache_hit: bool | None
    cache_error: str | None
    cache_key: str | None
    response_summary: Any | None
    error_type: str | None
    error_message: str | None
    started_at_utc: str
    finished_at_utc: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prove Phase 11 Redis recovery without restarting the CityRoute "
            "API. The probe discovers or validates the real Redis container, "
            "stops it, proves fail-open degraded operation, starts it, and "
            "proves automatic recovery plus restored cache hits."
        )
    )

    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"CityRoute API base URL. Default: {DEFAULT_BASE_URL}",
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
        help="Explicit output directory. Overrides --target.",
    )
    parser.add_argument(
        "--redis-container",
        default=None,
        help=(
            "Exact Redis container name or ID. When omitted, the probe "
            "auto-discovers one Redis container from 'docker ps -a'."
        ),
    )
    parser.add_argument(
        "--docker-bin",
        default="docker",
        help="Docker CLI executable. Default: docker",
    )
    parser.add_argument(
        "--matrix-size",
        type=int,
        default=DEFAULT_MATRIX_SIZE,
        help=f"Cache probe matrix size. Default: {DEFAULT_MATRIX_SIZE}",
    )
    parser.add_argument(
        "--algorithm",
        choices=("source_dijkstra", "bidirectional_astar"),
        default="source_dijkstra",
        help="Matrix algorithm. Default: source_dijkstra",
    )
    parser.add_argument(
        "--state-timeout-s",
        type=float,
        default=DEFAULT_STATE_TIMEOUT_S,
        help=(
            "Maximum wait for degraded or recovered state. "
            f"Default: {DEFAULT_STATE_TIMEOUT_S}"
        ),
    )
    parser.add_argument(
        "--poll-interval-s",
        type=float,
        default=DEFAULT_POLL_INTERVAL_S,
        help=f"Polling interval. Default: {DEFAULT_POLL_INTERVAL_S}",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=max(DEFAULT_TIMEOUT_S, 30.0),
        help="Per-request HTTP timeout. Default: 30",
    )
    parser.add_argument(
        "--startup-timeout-s",
        type=float,
        default=180.0,
        help="Maximum startup wait. Default: 180",
    )
    parser.add_argument(
        "--require-recovery-counter",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Require cityroute_redis_recoveries_total to increase. "
            "Default: enabled."
        ),
    )
    parser.add_argument(
        "--fail-on-validation-error",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Exit non-zero when recovery proof fails. Default: enabled.",
    )

    args = parser.parse_args()

    if not 2 <= args.matrix_size <= 25:
        parser.error("--matrix-size must be between 2 and 25")

    if args.state_timeout_s <= 0:
        parser.error("--state-timeout-s must be greater than zero")

    if args.poll_interval_s <= 0:
        parser.error("--poll-interval-s must be greater than zero")

    if args.timeout_s <= 0:
        parser.error("--timeout-s must be greater than zero")

    if args.startup_timeout_s <= 0:
        parser.error("--startup-timeout-s must be greater than zero")

    return args


def _run_command(
    command: list[str],
    *,
    timeout_s: float = 60.0,
) -> CommandResult:
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
        )
        return_code = completed.returncode
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    return CommandResult(
        command=tuple(command),
        return_code=return_code,
        ok=return_code == 0 and error_type is None,
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
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
) -> tuple[DockerContainer | None, CommandResult]:
    command = [
        docker_bin,
        "inspect",
        "--format",
        (
            "{{.Id}}\t{{.Name}}\t{{.Config.Image}}\t"
            "{{.State.Status}}\t"
            "{{if .State.Health}}{{.State.Health.Status}}"
            "{{else}}none{{end}}"
        ),
        container,
    ]
    result = _run_command(command)

    if not result.ok:
        return None, result

    parts = result.stdout.split("\t")

    if len(parts) != 5:
        return None, CommandResult(
            **{
                **asdict(result),
                "ok": False,
                "error_type": "ContainerParseError",
                "error_message": (
                    "Unexpected docker inspect output: "
                    f"{result.stdout!r}"
                ),
            }
        )

    container_id, raw_name, image, state, raw_health = parts
    name = raw_name.lstrip("/")
    health = None if raw_health == "none" else raw_health

    return (
        DockerContainer(
            container_id=container_id,
            name=name,
            image=image,
            state=state,
            health=health,
        ),
        result,
    )


def _discover_redis_container(
    *,
    docker_bin: str,
) -> tuple[DockerContainer, CommandResult]:
    command = [
        docker_bin,
        "ps",
        "-a",
        "--format",
        "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.State}}",
    ]
    result = _run_command(command)

    if not result.ok:
        raise RuntimeError(
            "Unable to list Docker containers: "
            f"{result.stderr or result.error_message}"
        )

    candidates: list[DockerContainer] = []

    for line in result.stdout.splitlines():
        parts = line.split("\t")

        if len(parts) != 4:
            continue

        container_id, name, image, state = parts
        searchable = f"{name} {image}".lower()

        if "redis" not in searchable:
            continue

        inspected, _ = _inspect_container(
            docker_bin=docker_bin,
            container=container_id,
        )

        if inspected is not None:
            candidates.append(inspected)

    if not candidates:
        raise RuntimeError(
            "No Redis Docker container was found. Run "
            "'docker ps -a --format "
            "\"table {{.Names}}\\t{{.Image}}\\t{{.State}}\"' "
            "and pass the exact name with --redis-container."
        )

    if len(candidates) > 1:
        choices = ", ".join(
            f"{item.name} ({item.image}, {item.state})"
            for item in candidates
        )
        raise RuntimeError(
            "Multiple Redis containers were found. Pass one exact name "
            f"with --redis-container. Candidates: {choices}"
        )

    return candidates[0], result


def _resolve_redis_container(
    *,
    docker_bin: str,
    requested_container: str | None,
) -> tuple[DockerContainer, dict[str, Any]]:
    if requested_container is None:
        container, discovery_result = _discover_redis_container(
            docker_bin=docker_bin
        )
        return container, {
            "mode": "auto_discovery",
            "command": asdict(discovery_result),
        }

    container, inspect_result = _inspect_container(
        docker_bin=docker_bin,
        container=requested_container,
    )

    if container is None:
        raise RuntimeError(
            "The requested Redis container does not exist: "
            f"{requested_container!r}. Docker error: "
            f"{inspect_result.stderr or inspect_result.error_message}"
        )

    searchable = f"{container.name} {container.image}".lower()

    if "redis" not in searchable:
        raise RuntimeError(
            "The requested container does not look like Redis: "
            f"name={container.name!r}, image={container.image!r}"
        )

    return container, {
        "mode": "explicit",
        "command": asdict(inspect_result),
    }


async def _wait_for_container_state(
    *,
    docker_bin: str,
    container: str,
    expected_state: str,
    timeout_s: float,
    poll_interval_s: float,
) -> dict[str, Any]:
    deadline = time.perf_counter() + timeout_s
    samples: list[dict[str, Any]] = []

    while True:
        inspected, command_result = await asyncio.to_thread(
            _inspect_container,
            docker_bin=docker_bin,
            container=container,
        )

        sample = {
            "captured_at_utc": utc_now_iso(),
            "container": (
                None if inspected is None else asdict(inspected)
            ),
            "command": asdict(command_result),
        }
        samples.append(sample)

        state_matches = (
            inspected is not None
            and inspected.state == expected_state
        )
        health_matches = (
            expected_state != "running"
            or inspected is None
            or inspected.health in {None, "healthy"}
        )

        if state_matches and health_matches:
            return {
                "reached": True,
                "timed_out": False,
                "samples": samples,
                "final_container": asdict(inspected),
            }

        if time.perf_counter() >= deadline:
            return {
                "reached": False,
                "timed_out": True,
                "samples": samples,
                "final_container": (
                    None if inspected is None else asdict(inspected)
                ),
            }

        await asyncio.sleep(poll_interval_s)


def _parse_prometheus(text: str | None) -> dict[str, float]:
    if not text:
        return {}

    values: dict[str, float] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        sample_name, separator, raw_value = line.rpartition(" ")

        if not separator:
            continue

        metric_name = sample_name.split("{", 1)[0]

        try:
            value = float(raw_value)
        except ValueError:
            continue

        values[metric_name] = values.get(metric_name, 0.0) + value

    return values


async def _get(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    path: str,
) -> dict[str, Any]:
    started = time.perf_counter()

    try:
        response = await client.get(f"{base_url}{path}")
    except Exception as exc:
        return {
            "path": path,
            "status_code": None,
            "elapsed_ms": (time.perf_counter() - started) * 1000.0,
            "response_json": None,
            "response_text": None,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }

    try:
        response_json: Any | None = response.json()
    except ValueError:
        response_json = None

    return {
        "path": path,
        "status_code": response.status_code,
        "elapsed_ms": (time.perf_counter() - started) * 1000.0,
        "response_json": response_json,
        "response_text": response.text,
        "error_type": None,
        "error_message": None,
    }


async def _collect_state(
    client: httpx.AsyncClient,
    *,
    base_url: str,
) -> dict[str, Any]:
    liveness = await _get(
        client,
        base_url=base_url,
        path="/health/live",
    )
    readiness = await _get(
        client,
        base_url=base_url,
        path="/health/ready",
    )
    health = await _get(
        client,
        base_url=base_url,
        path="/health",
    )
    metrics_response = await _get(
        client,
        base_url=base_url,
        path="/metrics",
    )
    metrics = _parse_prometheus(
        metrics_response["response_text"]
    )

    return {
        "captured_at_utc": utc_now_iso(),
        "liveness": liveness,
        "readiness": readiness,
        "health": health,
        "metrics_status_code": metrics_response["status_code"],
        "metrics": {
            REDIS_AVAILABLE_METRIC: metrics.get(
                REDIS_AVAILABLE_METRIC
            ),
            REDIS_FAILURES_METRIC: metrics.get(
                REDIS_FAILURES_METRIC
            ),
            REDIS_RECOVERIES_METRIC: metrics.get(
                REDIS_RECOVERIES_METRIC
            ),
            PROCESS_START_METRIC: metrics.get(
                PROCESS_START_METRIC
            ),
        },
    }


def _state_view(state: dict[str, Any]) -> dict[str, Any]:
    liveness = state["liveness"]["response_json"]
    readiness = state["readiness"]["response_json"]
    health = state["health"]["response_json"]

    liveness = liveness if isinstance(liveness, dict) else {}
    readiness = readiness if isinstance(readiness, dict) else {}
    health = health if isinstance(health, dict) else {}

    components = readiness.get("components")
    components = components if isinstance(components, dict) else {}

    return {
        "liveness_http": state["liveness"]["status_code"],
        "liveness_status": liveness.get("status"),
        "liveness_uptime_s": liveness.get("uptime_s"),
        "readiness_http": state["readiness"]["status_code"],
        "readiness_status": readiness.get("status"),
        "ready": readiness.get("ready"),
        "accepting_requests": readiness.get(
            "accepting_requests"
        ),
        "shutting_down": readiness.get("shutting_down"),
        "redis_component": components.get("redis"),
        "degraded_dependencies": readiness.get(
            "degraded_dependencies"
        ),
        "failure_reasons": readiness.get("failure_reasons"),
        "health_http": state["health"]["status_code"],
        "health_status": health.get("status"),
        "redis_available": state["metrics"].get(
            REDIS_AVAILABLE_METRIC
        ),
        "redis_failures_total": state["metrics"].get(
            REDIS_FAILURES_METRIC
        ),
        "redis_recoveries_total": state["metrics"].get(
            REDIS_RECOVERIES_METRIC
        ),
        "process_start_time_seconds": state["metrics"].get(
            PROCESS_START_METRIC
        ),
    }


def _is_healthy(state: dict[str, Any]) -> bool:
    view = _state_view(state)

    return (
        view["liveness_http"] == 200
        and view["liveness_status"] == "alive"
        and view["readiness_http"] == 200
        and view["readiness_status"] == "ready"
        and view["ready"] is True
        and view["accepting_requests"] is True
        and view["shutting_down"] is False
        and view["redis_component"] == "ready"
        and view["health_http"] == 200
        and view["health_status"] == "ok"
        and view["redis_available"] == 1.0
    )


def _is_degraded_fail_open(state: dict[str, Any]) -> bool:
    view = _state_view(state)

    return (
        view["liveness_http"] == 200
        and view["liveness_status"] == "alive"
        and view["readiness_http"] == 200
        and view["readiness_status"] == "degraded"
        and view["ready"] is True
        and view["accepting_requests"] is True
        and view["shutting_down"] is False
        and view["redis_component"] in {"degraded", "unavailable"}
        and view["health_http"] == 200
        and view["health_status"] == "degraded"
        and view["redis_available"] == 0.0
    )


async def _poll_api_state(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    predicate: Any,
    timeout_s: float,
    poll_interval_s: float,
    trigger: Any | None = None,
) -> dict[str, Any]:
    deadline = time.perf_counter() + timeout_s
    samples: list[dict[str, Any]] = []
    trigger_results: list[dict[str, Any]] = []

    while True:
        if trigger is not None:
            trigger_result = await trigger()
            trigger_results.append(asdict(trigger_result))

        state = await _collect_state(
            client,
            base_url=base_url,
        )
        samples.append(state)

        if predicate(state):
            return {
                "reached": True,
                "timed_out": False,
                "samples": samples,
                "trigger_results": trigger_results,
                "final_state": state,
                "final_view": _state_view(state),
            }

        if time.perf_counter() >= deadline:
            return {
                "reached": False,
                "timed_out": True,
                "samples": samples,
                "trigger_results": trigger_results,
                "final_state": state,
                "final_view": _state_view(state),
            }

        await asyncio.sleep(poll_interval_s)


def _locations(
    *,
    matrix_size: int,
    variant: int,
) -> list[dict[str, Any]]:
    center_lat = 26.4499
    center_lon = 80.3319
    spacing = 0.0016
    shift = (variant % 8) * 0.00022

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


async def _matrix_probe(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    stage: str,
    attempt_index: int,
    matrix_size: int,
    algorithm: str,
    variant: int,
) -> MatrixResult:
    payload = {
        "locations": _locations(
            matrix_size=matrix_size,
            variant=variant,
        ),
        "algorithm": algorithm,
        "use_cache": True,
    }

    started_at_utc = utc_now_iso()
    started = time.perf_counter()

    status_code: int | None = None
    response_summary: Any | None = None
    cache_enabled: bool | None = None
    cache_hit: bool | None = None
    cache_error: str | None = None
    cache_key: str | None = None
    error_type: str | None = None
    error_message: str | None = None

    try:
        response = await client.post(
            f"{base_url}/matrix",
            json=payload,
        )
        status_code = response.status_code

        try:
            response_json: Any | None = response.json()
        except ValueError:
            response_json = None

        if isinstance(response_json, dict):
            cache = response_json.get("cache")
            cache = cache if isinstance(cache, dict) else {}

            cache_enabled = cache.get("enabled")
            cache_hit = cache.get("hit")
            cache_error_value = cache.get("error")
            cache_key_value = cache.get("key")

            cache_error = (
                cache_error_value
                if isinstance(cache_error_value, str)
                else None
            )
            cache_key = (
                cache_key_value
                if isinstance(cache_key_value, str)
                else None
            )

            response_summary = {
                "status": response_json.get("status"),
                "n": response_json.get("n"),
                "algorithm": response_json.get("algorithm"),
                "pair_count": response_json.get("pair_count"),
                "computed_pairs": response_json.get(
                    "computed_pairs"
                ),
                "failed_pairs": response_json.get(
                    "failed_pairs"
                ),
                "generation_time_ms": response_json.get(
                    "generation_time_ms"
                ),
                "cache": cache,
            }
        else:
            response_summary = {
                "body_preview": response.text[:2000]
            }
    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    return MatrixResult(
        stage=stage,
        attempt_index=attempt_index,
        status_code=status_code,
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
        cache_enabled=cache_enabled,
        cache_hit=cache_hit,
        cache_error=cache_error,
        cache_key=cache_key,
        response_summary=response_summary,
        error_type=error_type,
        error_message=error_message,
        started_at_utc=started_at_utc,
        finished_at_utc=utc_now_iso(),
    )


def _latency_summary(
    probes: list[MatrixResult],
) -> dict[str, float | int | None]:
    values = [probe.elapsed_ms for probe in probes]

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


def _counter_delta(
    before: float | None,
    after: float | None,
) -> float | None:
    if before is None or after is None:
        return None

    return after - before


def _validate(
    *,
    baseline_state: dict[str, Any],
    baseline_probes: list[MatrixResult],
    stop_result: CommandResult,
    stopped_state: dict[str, Any],
    degraded_probe: MatrixResult,
    degraded_poll: dict[str, Any],
    start_result: CommandResult,
    running_state: dict[str, Any],
    recovery_poll: dict[str, Any],
    recovery_probes: list[MatrixResult],
    final_state: dict[str, Any],
    require_recovery_counter: bool,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not _is_healthy(baseline_state):
        errors.append("Baseline Redis state was not healthy")

    if baseline_probes[0].status_code != 200:
        errors.append("Baseline cache-miss request failed")

    if baseline_probes[1].status_code != 200:
        errors.append("Baseline cache-hit request failed")

    if baseline_probes[1].cache_hit is not True:
        errors.append("Baseline second request was not a cache hit")

    if not stop_result.ok:
        errors.append("Docker failed to stop the Redis container")

    if stopped_state.get("reached") is not True:
        errors.append("Redis container did not reach exited state")

    if degraded_probe.status_code != 200:
        errors.append(
            "Matrix endpoint did not fail open during Redis outage"
        )

    if degraded_probe.cache_hit is True:
        errors.append(
            "Outage matrix request unexpectedly reported a cache hit"
        )

    if degraded_poll.get("reached") is not True:
        errors.append(
            "CityRoute did not expose degraded-but-ready Redis state"
        )

    if not start_result.ok:
        errors.append("Docker failed to start the Redis container")

    if running_state.get("reached") is not True:
        errors.append(
            "Redis container did not return to running/healthy state"
        )

    if recovery_poll.get("reached") is not True:
        errors.append(
            "CityRoute did not automatically return Redis to ready state"
        )

    if recovery_probes[0].status_code != 200:
        errors.append("First post-recovery matrix request failed")

    if recovery_probes[1].status_code != 200:
        errors.append("Second post-recovery matrix request failed")

    if recovery_probes[1].cache_hit is not True:
        errors.append(
            "Second post-recovery request was not a Redis cache hit"
        )

    if not _is_healthy(final_state):
        errors.append("Final Redis state was not healthy")

    baseline_view = _state_view(baseline_state)
    final_view = _state_view(final_state)

    before_process_start = baseline_view[
        "process_start_time_seconds"
    ]
    after_process_start = final_view[
        "process_start_time_seconds"
    ]

    if (
        before_process_start is not None
        and after_process_start is not None
        and before_process_start != after_process_start
    ):
        errors.append(
            "CityRoute API process restarted during Redis recovery"
        )

    before_uptime = baseline_view["liveness_uptime_s"]
    after_uptime = final_view["liveness_uptime_s"]

    if (
        isinstance(before_uptime, int | float)
        and isinstance(after_uptime, int | float)
        and after_uptime < before_uptime
    ):
        errors.append(
            "CityRoute liveness uptime decreased during recovery"
        )

    recovery_delta = _counter_delta(
        baseline_view["redis_recoveries_total"],
        final_view["redis_recoveries_total"],
    )

    if recovery_delta is None:
        message = (
            "Redis recovery counter was not available in both baseline "
            "and final metrics."
        )

        if require_recovery_counter:
            errors.append(message)
        else:
            warnings.append(message)
    elif recovery_delta < 1.0:
        message = (
            "Redis recovered functionally, but "
            "cityroute_redis_recoveries_total did not increase."
        )

        if require_recovery_counter:
            errors.append(message)
        else:
            warnings.append(message)

    return errors, warnings


async def async_main(args: argparse.Namespace) -> int:
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
        allow_degraded=False,
    )

    container, container_resolution = await asyncio.to_thread(
        _resolve_redis_container,
        docker_bin=args.docker_bin,
        requested_container=args.redis_container,
    )

    async with httpx.AsyncClient(
        timeout=args.timeout_s,
        limits=httpx.Limits(
            max_connections=20,
            max_keepalive_connections=20,
        ),
    ) as client:
        baseline_state = await _collect_state(
            client,
            base_url=base_url,
        )

        baseline_probes = [
            await _matrix_probe(
                client,
                base_url=base_url,
                stage="baseline",
                attempt_index=attempt_index,
                matrix_size=args.matrix_size,
                algorithm=args.algorithm,
                variant=0,
            )
            for attempt_index in range(2)
        ]

        stop_result = await asyncio.to_thread(
            _run_command,
            [args.docker_bin, "stop", container.container_id],
        )

        stopped_state: dict[str, Any] = {
            "reached": False,
            "timed_out": False,
            "samples": [],
            "final_container": None,
        }
        degraded_probe = MatrixResult(
            stage="redis_stopped",
            attempt_index=0,
            status_code=None,
            elapsed_ms=0.0,
            cache_enabled=None,
            cache_hit=None,
            cache_error=None,
            cache_key=None,
            response_summary=None,
            error_type="NotExecuted",
            error_message="Redis outage probe did not execute",
            started_at_utc=utc_now_iso(),
            finished_at_utc=utc_now_iso(),
        )
        degraded_poll: dict[str, Any] = {
            "reached": False,
            "timed_out": False,
            "samples": [],
            "trigger_results": [],
            "final_state": None,
            "final_view": None,
        }

        try:
            stopped_state = await _wait_for_container_state(
                docker_bin=args.docker_bin,
                container=container.container_id,
                expected_state="exited",
                timeout_s=args.state_timeout_s,
                poll_interval_s=args.poll_interval_s,
            )

            degraded_probe = await _matrix_probe(
                client,
                base_url=base_url,
                stage="redis_stopped",
                attempt_index=0,
                matrix_size=args.matrix_size,
                algorithm=args.algorithm,
                variant=1,
            )

            async def degraded_trigger() -> MatrixResult:
                return await _matrix_probe(
                    client,
                    base_url=base_url,
                    stage="degraded_detection",
                    attempt_index=0,
                    matrix_size=min(args.matrix_size, 5),
                    algorithm=args.algorithm,
                    variant=1,
                )

            degraded_poll = await _poll_api_state(
                client,
                base_url=base_url,
                predicate=_is_degraded_fail_open,
                timeout_s=args.state_timeout_s,
                poll_interval_s=args.poll_interval_s,
                trigger=degraded_trigger,
            )
        finally:
            # Never leave Redis stopped because an assertion or HTTP probe
            # raised unexpectedly.
            start_result = await asyncio.to_thread(
                _run_command,
                [args.docker_bin, "start", container.container_id],
            )

        running_state = await _wait_for_container_state(
            docker_bin=args.docker_bin,
            container=container.container_id,
            expected_state="running",
            timeout_s=args.state_timeout_s,
            poll_interval_s=args.poll_interval_s,
        )

        async def recovery_trigger() -> MatrixResult:
            return await _matrix_probe(
                client,
                base_url=base_url,
                stage="recovery_detection",
                attempt_index=0,
                matrix_size=min(args.matrix_size, 5),
                algorithm=args.algorithm,
                variant=2,
            )

        recovery_poll = await _poll_api_state(
            client,
            base_url=base_url,
            predicate=_is_healthy,
            timeout_s=args.state_timeout_s,
            poll_interval_s=args.poll_interval_s,
            trigger=recovery_trigger,
        )

        recovery_probes = [
            await _matrix_probe(
                client,
                base_url=base_url,
                stage="recovered",
                attempt_index=attempt_index,
                matrix_size=args.matrix_size,
                algorithm=args.algorithm,
                variant=3,
            )
            for attempt_index in range(2)
        ]

        final_state = await _collect_state(
            client,
            base_url=base_url,
        )

    validation_errors, warnings = _validate(
        baseline_state=baseline_state,
        baseline_probes=baseline_probes,
        stop_result=stop_result,
        stopped_state=stopped_state,
        degraded_probe=degraded_probe,
        degraded_poll=degraded_poll,
        start_result=start_result,
        running_state=running_state,
        recovery_poll=recovery_poll,
        recovery_probes=recovery_probes,
        final_state=final_state,
        require_recovery_counter=args.require_recovery_counter,
    )

    baseline_view = _state_view(baseline_state)
    final_view = _state_view(final_state)

    recovery_counter_delta = _counter_delta(
        baseline_view["redis_recoveries_total"],
        final_view["redis_recoveries_total"],
    )
    failure_counter_delta = _counter_delta(
        baseline_view["redis_failures_total"],
        final_view["redis_failures_total"],
    )

    overall_ok = not validation_errors
    timestamp = timestamp_slug()

    raw_path = build_result_path(
        "phase11_redis_recovery_probe_raw",
        results_dir=args.results_dir,
        target=args.target,
        timestamp=timestamp,
    )
    summary_path = build_result_path(
        "phase11_redis_recovery_probe_summary",
        results_dir=args.results_dir,
        target=args.target,
        timestamp=timestamp,
    )

    raw_payload: dict[str, Any] = {
        "phase_code": PROJECT_PHASE_CODE,
        "phase_name": PROJECT_PHASE_NAME,
        "benchmark": "phase11_redis_recovery_probe",
        "started_at_utc": started_at_utc,
        "finished_at_utc": utc_now_iso(),
        "base_url": base_url,
        "target": args.target,
        "configuration": {
            "requested_redis_container": args.redis_container,
            "resolved_redis_container": asdict(container),
            "docker_bin": args.docker_bin,
            "matrix_size": args.matrix_size,
            "algorithm": args.algorithm,
            "state_timeout_s": args.state_timeout_s,
            "poll_interval_s": args.poll_interval_s,
            "http_timeout_s": args.timeout_s,
            "require_recovery_counter": (
                args.require_recovery_counter
            ),
        },
        "runtime_metadata": asdict(
            collect_runtime_metadata(base_url=base_url)
        ),
        "startup_probes": {
            "liveness": asdict(startup_liveness),
            "readiness": asdict(startup_readiness),
        },
        "container_resolution": container_resolution,
        "baseline_state": baseline_state,
        "baseline_view": baseline_view,
        "baseline_probes": [
            asdict(probe)
            for probe in baseline_probes
        ],
        "stop_result": asdict(stop_result),
        "stopped_container_state": stopped_state,
        "degraded_probe": asdict(degraded_probe),
        "degraded_poll": degraded_poll,
        "start_result": asdict(start_result),
        "running_container_state": running_state,
        "recovery_poll": recovery_poll,
        "recovery_probes": [
            asdict(probe)
            for probe in recovery_probes
        ],
        "final_state": final_state,
        "final_view": final_view,
        "baseline_latency": _latency_summary(
            baseline_probes
        ),
        "recovery_latency": _latency_summary(
            recovery_probes
        ),
        "redis_failure_counter_delta": failure_counter_delta,
        "redis_recovery_counter_delta": (
            recovery_counter_delta
        ),
        "validation_errors": validation_errors,
        "warnings": warnings,
        "overall_ok": overall_ok,
    }

    summary_payload: dict[str, Any] = {
        "phase_code": PROJECT_PHASE_CODE,
        "phase_name": PROJECT_PHASE_NAME,
        "benchmark": "phase11_redis_recovery_probe",
        "base_url": base_url,
        "target": args.target,
        "overall_ok": overall_ok,
        "resolved_redis_container": {
            "name": container.name,
            "id": container.container_id,
            "image": container.image,
        },
        "baseline_healthy": _is_healthy(
            baseline_state
        ),
        "baseline_second_cache_hit": (
            baseline_probes[1].cache_hit
        ),
        "redis_stop_ok": stop_result.ok,
        "container_stopped": stopped_state["reached"],
        "degraded_state_reached": degraded_poll["reached"],
        "fail_open_matrix_status_code": (
            degraded_probe.status_code
        ),
        "redis_start_ok": start_result.ok,
        "container_running": running_state["reached"],
        "healthy_state_recovered": recovery_poll[
            "reached"
        ],
        "recovery_second_cache_hit": (
            recovery_probes[1].cache_hit
        ),
        "api_process_start_unchanged": (
            baseline_view["process_start_time_seconds"]
            == final_view["process_start_time_seconds"]
        ),
        "redis_failure_counter_delta": (
            failure_counter_delta
        ),
        "redis_recovery_counter_delta": (
            recovery_counter_delta
        ),
        "baseline_latency": raw_payload[
            "baseline_latency"
        ],
        "recovery_latency": raw_payload[
            "recovery_latency"
        ],
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
            "Phase 11 Redis recovery probe interrupted",
            file=sys.stderr,
        )
        raise SystemExit(130) from None