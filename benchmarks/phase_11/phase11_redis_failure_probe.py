# benchmarks/phase_11/phase11_redis_failure_probe.py

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

# Support both:
#   python benchmarks/phase_11/phase11_redis_failure_probe.py
#   python -m benchmarks.phase_11.phase11_redis_failure_probe
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


@dataclass(frozen=True)
class ActionResult:
    action: str
    command: str
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
class EndpointResult:
    path: str
    status_code: int | None
    elapsed_ms: float
    response_json: Any | None
    response_text: str | None
    error_type: str | None
    error_message: str | None
    started_at_utc: str
    finished_at_utc: str


@dataclass(frozen=True)
class MatrixProbeResult:
    stage: str
    attempt_index: int
    status_code: int | None
    elapsed_ms: float
    response_summary: Any | None
    cache_enabled: bool | None
    cache_hit: bool | None
    cache_error: str | None
    cache_key: str | None
    validation_errors: tuple[str, ...]
    error_type: str | None
    error_message: str | None
    started_at_utc: str
    finished_at_utc: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prove Phase 11 Redis fail-open behavior and recovery. The "
            "probe verifies healthy cache hits, injects a Redis outage, "
            "proves degraded-but-ready operation, restores Redis, and "
            "proves cache recovery."
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

    injection_group = parser.add_mutually_exclusive_group(
        required=True
    )
    injection_group.add_argument(
        "--redis-container",
        help=(
            "Docker container name or ID for Redis. The probe runs "
            "'docker stop' and 'docker start' for this container."
        ),
    )
    injection_group.add_argument(
        "--failure-command",
        help=(
            "Explicit shell command that makes Redis unavailable. "
            "Requires --recovery-command."
        ),
    )
    injection_group.add_argument(
        "--manual",
        action="store_true",
        help=(
            "Pause for manual Redis stop/start actions. Intended for "
            "interactive local runs."
        ),
    )

    parser.add_argument(
        "--recovery-command",
        help=(
            "Explicit shell command that restores Redis. Required with "
            "--failure-command."
        ),
    )
    parser.add_argument(
        "--matrix-size",
        type=int,
        default=DEFAULT_MATRIX_SIZE,
        help=(
            "Locations in each cache-enabled matrix probe. "
            f"Default: {DEFAULT_MATRIX_SIZE}"
        ),
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
            "Maximum wait for degraded and recovered Redis states. "
            f"Default: {DEFAULT_STATE_TIMEOUT_S}"
        ),
    )
    parser.add_argument(
        "--poll-interval-s",
        type=float,
        default=DEFAULT_POLL_INTERVAL_S,
        help=(
            "State polling interval. "
            f"Default: {DEFAULT_POLL_INTERVAL_S}"
        ),
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
        "--require-cache-hit-before",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Require the second baseline request to be a Redis cache hit. "
            "Default: enabled."
        ),
    )
    parser.add_argument(
        "--require-cache-hit-after",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Require the second post-recovery request to be a cache hit. "
            "Default: enabled."
        ),
    )
    parser.add_argument(
        "--require-cache-error-during-failure",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Require the degraded matrix response to include cache.error. "
            "Disabled by default because an already-open recovery circuit "
            "may fail open without repeating the low-level error string."
        ),
    )
    parser.add_argument(
        "--fail-on-validation-error",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Exit non-zero when Redis fail-open or recovery validation "
            "fails. Default: enabled."
        ),
    )

    args = parser.parse_args()

    if args.failure_command and not args.recovery_command:
        parser.error(
            "--recovery-command is required with --failure-command"
        )

    if (
        args.recovery_command
        and not args.failure_command
        and not args.redis_container
    ):
        parser.error(
            "--recovery-command requires --failure-command unless "
            "--redis-container is used"
        )

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


def _resolve_commands(
    args: argparse.Namespace,
) -> tuple[str | None, str | None]:
    if args.redis_container:
        container = args.redis_container
        return (
            f'docker stop "{container}"',
            f'docker start "{container}"',
        )

    if args.failure_command:
        return args.failure_command, args.recovery_command

    return None, None


def _run_command(
    *,
    action: str,
    command: str,
) -> ActionResult:
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
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return_code = completed.returncode
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    return ActionResult(
        action=action,
        command=command,
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


async def _manual_action(
    *,
    action: str,
    instruction: str,
) -> ActionResult:
    started_at_utc = utc_now_iso()
    started = time.perf_counter()

    await asyncio.to_thread(
        input,
        f"{instruction}\nPress Enter when complete: ",
    )

    return ActionResult(
        action=action,
        command="manual",
        return_code=0,
        ok=True,
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
        stdout="Manual action acknowledged",
        stderr="",
        error_type=None,
        error_message=None,
        started_at_utc=started_at_utc,
        finished_at_utc=utc_now_iso(),
    )


async def _perform_action(
    *,
    action: str,
    command: str | None,
    manual: bool,
) -> ActionResult:
    if manual:
        instruction = (
            "Stop Redis now."
            if action == "inject_failure"
            else "Start Redis now."
        )
        return await _manual_action(
            action=action,
            instruction=instruction,
        )

    if command is None:
        raise RuntimeError(
            f"No command configured for action {action!r}"
        )

    return await asyncio.to_thread(
        _run_command,
        action=action,
        command=command,
    )


async def _get_endpoint(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    path: str,
) -> EndpointResult:
    started_at_utc = utc_now_iso()
    started = time.perf_counter()

    status_code: int | None = None
    response_json: Any | None = None
    response_text: str | None = None
    error_type: str | None = None
    error_message: str | None = None

    try:
        response = await client.get(f"{base_url}{path}")
        status_code = response.status_code
        response_text = response.text

        try:
            response_json = response.json()
        except ValueError:
            response_json = None
    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    return EndpointResult(
        path=path,
        status_code=status_code,
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
        response_json=response_json,
        response_text=response_text,
        error_type=error_type,
        error_message=error_message,
        started_at_utc=started_at_utc,
        finished_at_utc=utc_now_iso(),
    )


def _prometheus_metric(
    text: str | None,
    metric_name: str,
) -> float | None:
    if not text:
        return None

    values: list[float] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if (
            not line
            or line.startswith("#")
            or not line.startswith(metric_name)
        ):
            continue

        sample_name, separator, raw_value = line.rpartition(" ")

        if not separator:
            continue

        if sample_name.split("{", 1)[0] != metric_name:
            continue

        try:
            values.append(float(raw_value))
        except ValueError:
            continue

    return sum(values) if values else None


def _redis_metric_snapshot(
    text: str | None,
) -> dict[str, float]:
    if not text:
        return {}

    metrics: dict[str, float] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        sample_name, separator, raw_value = line.rpartition(" ")

        if not separator:
            continue

        metric_name = sample_name.split("{", 1)[0]

        if "redis" not in metric_name.lower():
            continue

        try:
            value = float(raw_value)
        except ValueError:
            continue

        metrics[metric_name] = (
            metrics.get(metric_name, 0.0) + value
        )

    return dict(sorted(metrics.items()))


async def _collect_state(
    client: httpx.AsyncClient,
    *,
    base_url: str,
) -> dict[str, Any]:
    liveness = await _get_endpoint(
        client,
        base_url=base_url,
        path="/health/live",
    )
    readiness = await _get_endpoint(
        client,
        base_url=base_url,
        path="/health/ready",
    )
    health = await _get_endpoint(
        client,
        base_url=base_url,
        path="/health",
    )
    metrics = await _get_endpoint(
        client,
        base_url=base_url,
        path="/metrics",
    )

    return {
        "captured_at_utc": utc_now_iso(),
        "liveness": asdict(liveness),
        "readiness": asdict(readiness),
        "health": asdict(health),
        "metrics": {
            **asdict(metrics),
            "redis_available": _prometheus_metric(
                metrics.response_text,
                REDIS_AVAILABLE_METRIC,
            ),
            "redis_metrics": _redis_metric_snapshot(
                metrics.response_text
            ),
        },
    }


def _generated_locations(
    *,
    matrix_size: int,
    variant: int,
) -> list[dict[str, Any]]:
    center_lat = 26.4499
    center_lon = 80.3319
    spacing = 0.0016

    # Five safely bounded variants around Kanpur Central. The shift is large
    # enough to reduce accidental cache-key reuse while remaining local.
    shift = (variant % 5) * 0.00035

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
    variant: int,
) -> dict[str, Any]:
    return {
        "locations": _generated_locations(
            matrix_size=matrix_size,
            variant=variant,
        ),
        "algorithm": algorithm,
        "use_cache": True,
    }


def _summarize_matrix_response(
    response_json: Any,
) -> tuple[
    Any | None,
    bool | None,
    bool | None,
    str | None,
    str | None,
]:
    if not isinstance(response_json, dict):
        return response_json, None, None, None, None

    cache = response_json.get("cache")
    cache = cache if isinstance(cache, dict) else {}

    summary = {
        "status": response_json.get("status"),
        "n": response_json.get("n"),
        "algorithm": response_json.get("algorithm"),
        "pair_count": response_json.get("pair_count"),
        "computed_pairs": response_json.get("computed_pairs"),
        "failed_pairs": response_json.get("failed_pairs"),
        "generation_time_ms": response_json.get(
            "generation_time_ms"
        ),
        "cache": cache,
    }

    cache_error = cache.get("error")

    return (
        summary,
        cache.get("enabled"),
        cache.get("hit"),
        (
            cache_error
            if isinstance(cache_error, str)
            else None
        ),
        (
            cache.get("key")
            if isinstance(cache.get("key"), str)
            else None
        ),
    )


async def _matrix_probe(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    stage: str,
    attempt_index: int,
    matrix_size: int,
    algorithm: str,
    variant: int,
) -> MatrixProbeResult:
    payload = _build_matrix_payload(
        matrix_size=matrix_size,
        algorithm=algorithm,
        variant=variant,
    )

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
    validation_errors: list[str] = []

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

        (
            response_summary,
            cache_enabled,
            cache_hit,
            cache_error,
            cache_key,
        ) = _summarize_matrix_response(response_json)
    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    if status_code != 200:
        validation_errors.append(
            f"matrix probe must return HTTP 200, got {status_code}"
        )

    if cache_enabled is not True:
        validation_errors.append(
            "matrix response must report cache.enabled=true"
        )

    if (
        isinstance(response_summary, dict)
        and response_summary.get("failed_pairs") not in {0, None}
    ):
        validation_errors.append(
            "matrix response contains failed pairs"
        )

    return MatrixProbeResult(
        stage=stage,
        attempt_index=attempt_index,
        status_code=status_code,
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
        response_summary=response_summary,
        cache_enabled=cache_enabled,
        cache_hit=cache_hit,
        cache_error=cache_error,
        cache_key=cache_key,
        validation_errors=tuple(validation_errors),
        error_type=error_type,
        error_message=error_message,
        started_at_utc=started_at_utc,
        finished_at_utc=utc_now_iso(),
    )


def _state_values(
    state: dict[str, Any],
) -> dict[str, Any]:
    readiness = state["readiness"]["response_json"]
    health = state["health"]["response_json"]
    liveness = state["liveness"]["response_json"]

    readiness = (
        readiness if isinstance(readiness, dict) else {}
    )
    health = health if isinstance(health, dict) else {}
    liveness = liveness if isinstance(liveness, dict) else {}

    components = readiness.get("components")
    components = components if isinstance(components, dict) else {}

    return {
        "liveness_status_code": state["liveness"][
            "status_code"
        ],
        "liveness_status": liveness.get("status"),
        "readiness_status_code": state["readiness"][
            "status_code"
        ],
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
        "failure_reasons": readiness.get(
            "failure_reasons"
        ),
        "health_status_code": state["health"]["status_code"],
        "health_status": health.get("status"),
        "redis_available_metric": state["metrics"][
            "redis_available"
        ],
    }


def _healthy_redis_state(state: dict[str, Any]) -> bool:
    values = _state_values(state)

    return (
        values["liveness_status_code"] == 200
        and values["liveness_status"] == "alive"
        and values["readiness_status_code"] == 200
        and values["readiness_status"] == "ready"
        and values["ready"] is True
        and values["accepting_requests"] is True
        and values["shutting_down"] is False
        and values["redis_component"] == "ready"
        and values["health_status_code"] == 200
        and values["health_status"] == "ok"
        and values["redis_available_metric"] == 1.0
    )


def _degraded_redis_state(state: dict[str, Any]) -> bool:
    values = _state_values(state)

    return (
        values["liveness_status_code"] == 200
        and values["liveness_status"] == "alive"
        and values["readiness_status_code"] == 200
        and values["readiness_status"] == "degraded"
        and values["ready"] is True
        and values["accepting_requests"] is True
        and values["shutting_down"] is False
        and values["redis_component"]
        in {"degraded", "unavailable"}
        and values["health_status_code"] == 200
        and values["health_status"] == "degraded"
        and values["redis_available_metric"] == 0.0
    )


async def _poll_state(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    predicate: Any,
    timeout_s: float,
    poll_interval_s: float,
    trigger_matrix: bool,
    matrix_size: int,
    algorithm: str,
    trigger_variant: int,
) -> dict[str, Any]:
    deadline = time.perf_counter() + timeout_s
    samples: list[dict[str, Any]] = []
    trigger_results: list[MatrixProbeResult] = []

    while True:
        if trigger_matrix:
            trigger_results.append(
                await _matrix_probe(
                    client,
                    base_url=base_url,
                    stage="state_trigger",
                    attempt_index=len(trigger_results),
                    matrix_size=min(matrix_size, 5),
                    algorithm=algorithm,
                    variant=trigger_variant,
                )
            )

        state = await _collect_state(
            client,
            base_url=base_url,
        )
        samples.append(state)

        if predicate(state):
            return {
                "reached": True,
                "timed_out": False,
                "elapsed_ms": (
                    timeout_s
                    - max(
                        0.0,
                        deadline - time.perf_counter(),
                    )
                )
                * 1000.0,
                "samples": samples,
                "trigger_matrix_results": [
                    asdict(result)
                    for result in trigger_results
                ],
                "final_state": state,
                "final_values": _state_values(state),
            }

        if time.perf_counter() >= deadline:
            return {
                "reached": False,
                "timed_out": True,
                "elapsed_ms": timeout_s * 1000.0,
                "samples": samples,
                "trigger_matrix_results": [
                    asdict(result)
                    for result in trigger_results
                ],
                "final_state": state,
                "final_values": _state_values(state),
            }

        await asyncio.sleep(poll_interval_s)


def _latency_summary(
    probes: list[MatrixProbeResult],
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


def _metric_deltas(
    before: dict[str, float],
    after: dict[str, float],
) -> dict[str, float | None]:
    names = sorted(set(before) | set(after))

    return {
        name: (
            None
            if name not in before or name not in after
            else after[name] - before[name]
        )
        for name in names
    }


def _validate_evidence(
    *,
    baseline_state: dict[str, Any],
    baseline_probes: list[MatrixProbeResult],
    failure_action: ActionResult,
    degraded_poll: dict[str, Any],
    degraded_probe: MatrixProbeResult,
    recovery_action: ActionResult,
    recovery_poll: dict[str, Any],
    recovery_probes: list[MatrixProbeResult],
    require_cache_hit_before: bool,
    require_cache_hit_after: bool,
    require_cache_error_during_failure: bool,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not _healthy_redis_state(baseline_state):
        errors.append(
            "Baseline Redis state was not fully healthy"
        )

    for probe in [
        *baseline_probes,
        degraded_probe,
        *recovery_probes,
    ]:
        errors.extend(probe.validation_errors)

    if (
        require_cache_hit_before
        and baseline_probes[-1].cache_hit is not True
    ):
        errors.append(
            "Second baseline request was not a Redis cache hit"
        )

    if not failure_action.ok:
        errors.append(
            "Redis failure-injection action did not succeed"
        )

    if degraded_poll.get("reached") is not True:
        errors.append(
            "CityRoute did not enter degraded Redis fail-open state"
        )

    if degraded_probe.status_code != 200:
        errors.append(
            "Matrix request failed instead of failing open during "
            "Redis outage"
        )

    if degraded_probe.cache_hit is True:
        errors.append(
            "Degraded matrix request unexpectedly reported a cache hit"
        )

    if (
        require_cache_error_during_failure
        and not degraded_probe.cache_error
    ):
        errors.append(
            "Degraded matrix response did not expose cache.error"
        )

    if (
        not require_cache_error_during_failure
        and not degraded_probe.cache_error
    ):
        warnings.append(
            "Degraded matrix response did not include cache.error. "
            "The readiness state and redis_available gauge still prove "
            "the fail-open outage."
        )

    if not recovery_action.ok:
        errors.append(
            "Redis recovery action did not succeed"
        )

    if recovery_poll.get("reached") is not True:
        errors.append(
            "CityRoute did not return to healthy Redis state"
        )

    if (
        require_cache_hit_after
        and recovery_probes[-1].cache_hit is not True
    ):
        errors.append(
            "Second post-recovery request was not a Redis cache hit"
        )

    if recovery_probes[-1].status_code != 200:
        errors.append(
            "Post-recovery matrix request did not return HTTP 200"
        )

    return errors, warnings


async def async_main(args: argparse.Namespace) -> int:
    base_url = args.base_url.rstrip("/")
    started_at_utc = utc_now_iso()
    failure_command, recovery_command = _resolve_commands(
        args
    )

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
                variant=1,
            )
            for attempt_index in range(2)
        ]

        baseline_redis_metrics = baseline_state[
            "metrics"
        ]["redis_metrics"]

        failure_action = await _perform_action(
            action="inject_failure",
            command=failure_command,
            manual=args.manual,
        )

        # Force one cache operation immediately so Redis failure is observed
        # even when recovery checks are request-driven rather than background.
        degraded_probe = await _matrix_probe(
            client,
            base_url=base_url,
            stage="redis_unavailable",
            attempt_index=0,
            matrix_size=args.matrix_size,
            algorithm=args.algorithm,
            variant=2,
        )

        degraded_poll = await _poll_state(
            client,
            base_url=base_url,
            predicate=_degraded_redis_state,
            timeout_s=args.state_timeout_s,
            poll_interval_s=args.poll_interval_s,
            trigger_matrix=True,
            matrix_size=args.matrix_size,
            algorithm=args.algorithm,
            trigger_variant=2,
        )

        # Recovery is attempted unconditionally after fault injection so a
        # failed assertion cannot leave the developer's Redis stopped.
        recovery_action = await _perform_action(
            action="restore_redis",
            command=recovery_command,
            manual=args.manual,
        )

        recovery_poll = await _poll_state(
            client,
            base_url=base_url,
            predicate=_healthy_redis_state,
            timeout_s=args.state_timeout_s,
            poll_interval_s=args.poll_interval_s,
            trigger_matrix=True,
            matrix_size=args.matrix_size,
            algorithm=args.algorithm,
            trigger_variant=3,
        )

        recovery_probes = [
            await _matrix_probe(
                client,
                base_url=base_url,
                stage="recovered",
                attempt_index=attempt_index,
                matrix_size=args.matrix_size,
                algorithm=args.algorithm,
                variant=4,
            )
            for attempt_index in range(2)
        ]

        final_state = await _collect_state(
            client,
            base_url=base_url,
        )

    validation_errors, warnings = _validate_evidence(
        baseline_state=baseline_state,
        baseline_probes=baseline_probes,
        failure_action=failure_action,
        degraded_poll=degraded_poll,
        degraded_probe=degraded_probe,
        recovery_action=recovery_action,
        recovery_poll=recovery_poll,
        recovery_probes=recovery_probes,
        require_cache_hit_before=(
            args.require_cache_hit_before
        ),
        require_cache_hit_after=(
            args.require_cache_hit_after
        ),
        require_cache_error_during_failure=(
            args.require_cache_error_during_failure
        ),
    )

    final_redis_metrics = final_state["metrics"][
        "redis_metrics"
    ]
    redis_metric_deltas = _metric_deltas(
        baseline_redis_metrics,
        final_redis_metrics,
    )

    overall_ok = not validation_errors
    timestamp = timestamp_slug()

    raw_path = build_result_path(
        "phase11_redis_failure_probe_raw",
        results_dir=args.results_dir,
        target=args.target,
        timestamp=timestamp,
    )
    summary_path = build_result_path(
        "phase11_redis_failure_probe_summary",
        results_dir=args.results_dir,
        target=args.target,
        timestamp=timestamp,
    )

    raw_payload: dict[str, Any] = {
        "phase_code": PROJECT_PHASE_CODE,
        "phase_name": PROJECT_PHASE_NAME,
        "benchmark": "phase11_redis_failure_probe",
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
            "redis_container": args.redis_container,
            "failure_command": failure_command,
            "recovery_command": recovery_command,
            "manual": args.manual,
            "matrix_size": args.matrix_size,
            "algorithm": args.algorithm,
            "state_timeout_s": args.state_timeout_s,
            "poll_interval_s": args.poll_interval_s,
            "http_timeout_s": args.timeout_s,
            "startup_timeout_s": args.startup_timeout_s,
            "require_cache_hit_before": (
                args.require_cache_hit_before
            ),
            "require_cache_hit_after": (
                args.require_cache_hit_after
            ),
            "require_cache_error_during_failure": (
                args.require_cache_error_during_failure
            ),
        },
        "runtime_metadata": asdict(
            collect_runtime_metadata(base_url=base_url)
        ),
        "startup_probes": {
            "liveness": asdict(startup_liveness),
            "readiness": asdict(startup_readiness),
        },
        "baseline_state": baseline_state,
        "baseline_probes": [
            asdict(probe)
            for probe in baseline_probes
        ],
        "failure_action": asdict(failure_action),
        "degraded_probe": asdict(degraded_probe),
        "degraded_poll": degraded_poll,
        "recovery_action": asdict(recovery_action),
        "recovery_poll": recovery_poll,
        "recovery_probes": [
            asdict(probe)
            for probe in recovery_probes
        ],
        "final_state": final_state,
        "redis_metric_deltas": redis_metric_deltas,
        "baseline_latency": _latency_summary(
            baseline_probes
        ),
        "recovery_latency": _latency_summary(
            recovery_probes
        ),
        "validation_errors": validation_errors,
        "warnings": warnings,
        "overall_ok": overall_ok,
    }

    summary_payload: dict[str, Any] = {
        "phase_code": PROJECT_PHASE_CODE,
        "phase_name": PROJECT_PHASE_NAME,
        "benchmark": "phase11_redis_failure_probe",
        "base_url": base_url,
        "target": args.target,
        "overall_ok": overall_ok,
        "baseline_redis_healthy": _healthy_redis_state(
            baseline_state
        ),
        "baseline_first_cache_hit": (
            baseline_probes[0].cache_hit
        ),
        "baseline_second_cache_hit": (
            baseline_probes[1].cache_hit
        ),
        "failure_action_ok": failure_action.ok,
        "degraded_state_reached": degraded_poll["reached"],
        "degraded_detection_ms": degraded_poll[
            "elapsed_ms"
        ],
        "fail_open_matrix_status_code": (
            degraded_probe.status_code
        ),
        "fail_open_cache_hit": degraded_probe.cache_hit,
        "fail_open_cache_error": (
            degraded_probe.cache_error
        ),
        "recovery_action_ok": recovery_action.ok,
        "healthy_state_recovered": recovery_poll["reached"],
        "recovery_detection_ms": recovery_poll[
            "elapsed_ms"
        ],
        "recovery_first_cache_hit": (
            recovery_probes[0].cache_hit
        ),
        "recovery_second_cache_hit": (
            recovery_probes[1].cache_hit
        ),
        "final_redis_healthy": _healthy_redis_state(
            final_state
        ),
        "baseline_latency": raw_payload[
            "baseline_latency"
        ],
        "recovery_latency": raw_payload[
            "recovery_latency"
        ],
        "redis_metric_deltas": redis_metric_deltas,
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
            "Phase 11 Redis failure probe interrupted",
            file=sys.stderr,
        )
        raise SystemExit(130) from None