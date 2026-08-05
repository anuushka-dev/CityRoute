# benchmarks/phase_11/phase11_corrupted_cache_probe.py

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

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

CORRUPTION_METRIC = "cityroute_corrupted_cache_payloads_total"
REDIS_AVAILABLE_METRIC = "cityroute_redis_available"
PROCESS_START_METRIC = "process_start_time_seconds"


@dataclass(frozen=True)
class ContainerInfo:
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
    stdout: str
    stderr: str
    elapsed_ms: float
    error_type: str | None
    error_message: str | None


@dataclass(frozen=True)
class MatrixResult:
    stage: str
    status_code: int | None
    elapsed_ms: float
    cache_enabled: bool | None
    cache_hit: bool | None
    cache_error: str | None
    cache_key: str | None
    response_summary: Any | None
    error_type: str | None
    error_message: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inject a malformed value into a real Redis matrix-cache key "
            "and prove that CityRoute rejects it, recomputes a correct "
            "matrix, repairs the key, stays healthy, and records telemetry."
        )
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--target", choices=("docker", "local"), default=None)
    parser.add_argument("--results-dir", type=Path, default=None)
    parser.add_argument("--redis-container", default=None)
    parser.add_argument("--docker-bin", default="docker")
    parser.add_argument("--redis-cli-bin", default="redis-cli")
    parser.add_argument("--redis-db", type=int, default=0)
    parser.add_argument("--matrix-size", type=int, default=10)
    parser.add_argument(
        "--algorithm",
        choices=("source_dijkstra", "bidirectional_astar"),
        default="source_dijkstra",
    )
    parser.add_argument(
        "--corruption-kind",
        choices=("invalid_json", "non_object_json"),
        default="invalid_json",
    )
    parser.add_argument("--variant", type=int, default=None)
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=max(DEFAULT_TIMEOUT_S, 30.0),
    )
    parser.add_argument("--startup-timeout-s", type=float, default=180.0)
    parser.add_argument(
        "--require-corruption-counter",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--fail-on-validation-error",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    args = parser.parse_args()

    if args.redis_db < 0:
        parser.error("--redis-db must be zero or greater")
    if not 2 <= args.matrix_size <= 25:
        parser.error("--matrix-size must be between 2 and 25")
    if args.timeout_s <= 0:
        parser.error("--timeout-s must be greater than zero")
    if args.startup_timeout_s <= 0:
        parser.error("--startup-timeout-s must be greater than zero")

    return args


def run_command(
    command: list[str],
    *,
    input_text: str | None = None,
    timeout_s: float = 60.0,
) -> CommandResult:
    started = time.perf_counter()
    return_code: int | None = None
    stdout = ""
    stderr = ""
    error_type: str | None = None
    error_message: str | None = None

    try:
        completed = subprocess.run(
            command,
            input=input_text,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_s,
        )
        return_code = completed.returncode
        stdout = completed.stdout.rstrip("\r\n")
        stderr = completed.stderr.rstrip("\r\n")
    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    return CommandResult(
        command=tuple(command),
        return_code=return_code,
        ok=return_code == 0 and error_type is None,
        stdout=stdout,
        stderr=stderr,
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
        error_type=error_type,
        error_message=error_message,
    )


def inspect_container(
    *, docker_bin: str, container: str
) -> tuple[ContainerInfo | None, CommandResult]:
    result = run_command(
        [
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
    )
    if not result.ok:
        return None, result

    parts = result.stdout.split("\t")
    if len(parts) != 5:
        return None, CommandResult(
            **{
                **asdict(result),
                "ok": False,
                "error_type": "ContainerParseError",
                "error_message": f"Unexpected inspect output: {result.stdout!r}",
            }
        )

    container_id, raw_name, image, state, raw_health = parts
    return (
        ContainerInfo(
            container_id=container_id,
            name=raw_name.lstrip("/"),
            image=image,
            state=state,
            health=None if raw_health == "none" else raw_health,
        ),
        result,
    )


def resolve_redis_container(
    *, docker_bin: str, requested: str | None
) -> tuple[ContainerInfo, dict[str, Any]]:
    if requested is not None:
        container, result = inspect_container(
            docker_bin=docker_bin,
            container=requested,
        )
        if container is None:
            raise RuntimeError(
                f"Redis container {requested!r} was not found: "
                f"{result.stderr or result.error_message}"
            )
        if "redis" not in f"{container.name} {container.image}".lower():
            raise RuntimeError(
                "Requested container does not look like Redis: "
                f"{container.name!r} ({container.image!r})"
            )
        if container.state != "running":
            raise RuntimeError(
                f"Redis container is not running: {container.state!r}"
            )
        return container, {"mode": "explicit", "command": asdict(result)}

    discovery = run_command(
        [
            docker_bin,
            "ps",
            "-a",
            "--format",
            "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.State}}",
        ]
    )
    if not discovery.ok:
        raise RuntimeError(
            f"Unable to list Docker containers: "
            f"{discovery.stderr or discovery.error_message}"
        )

    candidates: list[ContainerInfo] = []
    for line in discovery.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        container_id, name, image, _ = parts
        if "redis" not in f"{name} {image}".lower():
            continue
        inspected, _ = inspect_container(
            docker_bin=docker_bin,
            container=container_id,
        )
        if inspected is not None and inspected.state == "running":
            candidates.append(inspected)

    if not candidates:
        raise RuntimeError(
            "No running Redis container was found. Pass --redis-container."
        )
    if len(candidates) > 1:
        names = ", ".join(item.name for item in candidates)
        raise RuntimeError(
            "Multiple Redis containers were found. Pass one exact name: "
            f"{names}"
        )

    return candidates[0], {
        "mode": "auto_discovery",
        "command": asdict(discovery),
    }


def redis_command_base(
    *,
    args: argparse.Namespace,
    container: ContainerInfo,
    stdin: bool = False,
) -> list[str]:
    command = [args.docker_bin, "exec"]
    if stdin:
        command.append("-i")
    command.extend(
        [
            container.container_id,
            args.redis_cli_bin,
            "-n",
            str(args.redis_db),
        ]
    )
    return command


def redis_get(
    *, args: argparse.Namespace, container: ContainerInfo, key: str
) -> CommandResult:
    command = redis_command_base(args=args, container=container)
    command.extend(["--raw", "GET", key])
    return run_command(command)


def redis_pttl(
    *, args: argparse.Namespace, container: ContainerInfo, key: str
) -> CommandResult:
    command = redis_command_base(args=args, container=container)
    command.extend(["--raw", "PTTL", key])
    return run_command(command)


def redis_set(
    *,
    args: argparse.Namespace,
    container: ContainerInfo,
    key: str,
    value: str,
) -> CommandResult:
    command = redis_command_base(args=args, container=container, stdin=True)
    command.extend(["-x", "SET", key])
    return run_command(command, input_text=value)


def redis_pexpire(
    *,
    args: argparse.Namespace,
    container: ContainerInfo,
    key: str,
    ttl_ms: int,
) -> CommandResult:
    command = redis_command_base(args=args, container=container)
    command.extend(["PEXPIRE", key, str(ttl_ms)])
    return run_command(command)


def parse_prometheus(text: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for raw_line in text.splitlines():
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
        values[metric_name] = values.get(metric_name, 0.0) + value
    return values


async def collect_state(
    client: httpx.AsyncClient, *, base_url: str
) -> dict[str, Any]:
    async def get(path: str) -> dict[str, Any]:
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

    liveness = await get("/health/live")
    readiness = await get("/health/ready")
    health = await get("/health")
    metrics_response = await get("/metrics")
    metrics = parse_prometheus(metrics_response["response_text"] or "")

    return {
        "captured_at_utc": utc_now_iso(),
        "liveness": liveness,
        "readiness": readiness,
        "health": health,
        "metrics_status_code": metrics_response["status_code"],
        "metrics": {
            REDIS_AVAILABLE_METRIC: metrics.get(REDIS_AVAILABLE_METRIC),
            CORRUPTION_METRIC: metrics.get(CORRUPTION_METRIC),
            PROCESS_START_METRIC: metrics.get(PROCESS_START_METRIC),
        },
    }


def state_view(state: dict[str, Any]) -> dict[str, Any]:
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
        "accepting_requests": readiness.get("accepting_requests"),
        "shutting_down": readiness.get("shutting_down"),
        "redis_component": components.get("redis"),
        "health_http": state["health"]["status_code"],
        "health_status": health.get("status"),
        "redis_available": state["metrics"].get(REDIS_AVAILABLE_METRIC),
        "corrupted_payloads_total": state["metrics"].get(CORRUPTION_METRIC),
        "process_start_time_seconds": state["metrics"].get(
            PROCESS_START_METRIC
        ),
    }


def healthy(state: dict[str, Any]) -> bool:
    view = state_view(state)
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


def build_locations(
    *, matrix_size: int, variant: int
) -> list[dict[str, Any]]:
    center_lat = 26.4499
    center_lon = 80.3319
    spacing = 0.0016
    shift = (variant % 10_000) * 0.00000001
    locations: list[dict[str, Any]] = []

    for index in range(matrix_size):
        row, column = divmod(index, 5)
        locations.append(
            {
                "id": f"p{index:02d}",
                "lat": round(
                    center_lat + ((row - 2) * spacing) + shift,
                    8,
                ),
                "lon": round(
                    center_lon + ((column - 2) * spacing) - shift,
                    8,
                ),
            }
        )

    return locations


async def matrix_probe(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    stage: str,
    payload: dict[str, Any],
) -> MatrixResult:
    started = time.perf_counter()
    status_code: int | None = None
    cache_enabled: bool | None = None
    cache_hit: bool | None = None
    cache_error: str | None = None
    cache_key: str | None = None
    response_summary: Any | None = None
    error_type: str | None = None
    error_message: str | None = None

    try:
        response = await client.post(f"{base_url}/matrix", json=payload)
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
            cache_error = (
                cache.get("error")
                if isinstance(cache.get("error"), str)
                else None
            )
            cache_key = (
                cache.get("key")
                if isinstance(cache.get("key"), str)
                else None
            )
            response_summary = {
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
        else:
            response_summary = {"body_preview": response.text[:2000]}
    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    return MatrixResult(
        stage=stage,
        status_code=status_code,
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
        cache_enabled=cache_enabled,
        cache_hit=cache_hit,
        cache_error=cache_error,
        cache_key=cache_key,
        response_summary=response_summary,
        error_type=error_type,
        error_message=error_message,
    )


def valid_json_object(raw_value: str) -> bool:
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        return False
    return isinstance(value, dict)


def counter_delta(before: float | None, after: float | None) -> float | None:
    if after is None:
        return None
    if before is None:
        return after
    return after - before


def validate(
    *,
    matrix_size: int,
    baseline_state: dict[str, Any],
    baseline_hit: MatrixResult,
    original_value: CommandResult,
    corruption_write: CommandResult,
    corruption_verify: CommandResult,
    corruption_value: str,
    recovered_read: MatrixResult,
    repaired_hit: MatrixResult,
    repaired_value: CommandResult,
    final_state: dict[str, Any],
    metric_delta: float | None,
    require_counter: bool,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not healthy(baseline_state):
        errors.append("Baseline service state was not fully healthy")
    if baseline_hit.status_code != 200 or baseline_hit.cache_hit is not True:
        errors.append("Baseline repeated request was not a valid cache hit")
    if not original_value.ok or not valid_json_object(original_value.stdout):
        errors.append("Original Redis value was not a readable JSON object")
    if not corruption_write.ok:
        errors.append("Failed to inject corrupted Redis value")
    if not corruption_verify.ok or corruption_verify.stdout != corruption_value:
        errors.append("Injected corrupted Redis value was not verified")

    if recovered_read.status_code != 200:
        errors.append("Matrix endpoint failed on corrupted cache payload")
    if recovered_read.cache_hit is True:
        errors.append("Corrupted cache payload was accepted as a cache hit")

    summary = recovered_read.response_summary
    if not isinstance(summary, dict):
        errors.append("Recovery response was not a JSON object")
    else:
        if summary.get("status") != "ok":
            errors.append("Recovery response did not report status=ok")
        if summary.get("n") != matrix_size:
            errors.append("Recovery response matrix size was incorrect")
        if summary.get("failed_pairs") not in {0, None}:
            errors.append("Recovery response contained failed pairs")

    if repaired_hit.status_code != 200 or repaired_hit.cache_hit is not True:
        errors.append("Repeated request did not hit the repaired cache")
    if not repaired_value.ok or not valid_json_object(repaired_value.stdout):
        errors.append("Repaired Redis value was not a valid JSON object")
    if not healthy(final_state):
        errors.append("Service was not healthy after cache repair")

    baseline_view = state_view(baseline_state)
    final_view = state_view(final_state)
    if (
        baseline_view["process_start_time_seconds"]
        != final_view["process_start_time_seconds"]
    ):
        errors.append("CityRoute API process restarted during cache repair")

    if metric_delta is None:
        message = "Corrupted-cache counter was unavailable after injection"
        (errors if require_counter else warnings).append(message)
    elif metric_delta < 1.0:
        message = (
            "Cache recovered functionally, but "
            "cityroute_corrupted_cache_payloads_total did not increase"
        )
        (errors if require_counter else warnings).append(message)

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

    container, resolution = await asyncio.to_thread(
        resolve_redis_container,
        docker_bin=args.docker_bin,
        requested=args.redis_container,
    )

    variant = (
        args.variant
        if args.variant is not None
        else int(time.time_ns() % 9000) + 1000
    )
    payload = {
        "locations": build_locations(
            matrix_size=args.matrix_size,
            variant=variant,
        ),
        "algorithm": args.algorithm,
        "use_cache": True,
    }
    corruption_value = (
        '{"broken":'
        if args.corruption_kind == "invalid_json"
        else "[1,2,3]"
    )

    cleanup_actions: list[CommandResult] = []

    async with httpx.AsyncClient(timeout=args.timeout_s) as client:
        baseline_state = await collect_state(client, base_url=base_url)
        baseline_miss = await matrix_probe(
            client,
            base_url=base_url,
            stage="baseline_miss",
            payload=payload,
        )
        baseline_hit = await matrix_probe(
            client,
            base_url=base_url,
            stage="baseline_hit",
            payload=payload,
        )
        cache_key = baseline_hit.cache_key or baseline_miss.cache_key
        if not cache_key:
            raise RuntimeError("Matrix endpoint did not return a cache key")

        original_value = await asyncio.to_thread(
            redis_get,
            args=args,
            container=container,
            key=cache_key,
        )
        original_ttl = await asyncio.to_thread(
            redis_pttl,
            args=args,
            container=container,
            key=cache_key,
        )
        corruption_write = await asyncio.to_thread(
            redis_set,
            args=args,
            container=container,
            key=cache_key,
            value=corruption_value,
        )
        corruption_verify = await asyncio.to_thread(
            redis_get,
            args=args,
            container=container,
            key=cache_key,
        )

        recovered_read: MatrixResult | None = None
        repaired_hit: MatrixResult | None = None
        repaired_value: CommandResult | None = None
        final_state: dict[str, Any] | None = None

        try:
            recovered_read = await matrix_probe(
                client,
                base_url=base_url,
                stage="corrupted_payload_read",
                payload=payload,
            )
            repaired_hit = await matrix_probe(
                client,
                base_url=base_url,
                stage="repaired_cache_hit",
                payload=payload,
            )
            repaired_value = await asyncio.to_thread(
                redis_get,
                args=args,
                container=container,
                key=cache_key,
            )
            final_state = await collect_state(client, base_url=base_url)
        finally:
            current = await asyncio.to_thread(
                redis_get,
                args=args,
                container=container,
                key=cache_key,
            )
            if not current.ok or not valid_json_object(current.stdout):
                restore = await asyncio.to_thread(
                    redis_set,
                    args=args,
                    container=container,
                    key=cache_key,
                    value=original_value.stdout,
                )
                cleanup_actions.append(restore)
                try:
                    ttl_ms = int(original_ttl.stdout)
                except ValueError:
                    ttl_ms = -1
                if restore.ok and ttl_ms > 0:
                    cleanup_actions.append(
                        await asyncio.to_thread(
                            redis_pexpire,
                            args=args,
                            container=container,
                            key=cache_key,
                            ttl_ms=ttl_ms,
                        )
                    )

        if (
            recovered_read is None
            or repaired_hit is None
            or repaired_value is None
            or final_state is None
        ):
            raise RuntimeError("Corrupted-cache probe did not complete")

    assert recovered_read is not None
    assert repaired_hit is not None
    assert repaired_value is not None

    baseline_view = state_view(baseline_state)
    final_view = state_view(final_state)
    metric_delta = counter_delta(
        baseline_view["corrupted_payloads_total"],
        final_view["corrupted_payloads_total"],
    )

    validation_errors, warnings = validate(
        matrix_size=args.matrix_size,
        baseline_state=baseline_state,
        baseline_hit=baseline_hit,
        original_value=original_value,
        corruption_write=corruption_write,
        corruption_verify=corruption_verify,
        corruption_value=corruption_value,
        recovered_read=recovered_read,
        repaired_hit=repaired_hit,
        repaired_value=repaired_value,
        final_state=final_state,
        metric_delta=metric_delta,
        require_counter=args.require_corruption_counter,
    )

    overall_ok = not validation_errors
    timestamp = timestamp_slug()
    raw_path = build_result_path(
        "phase11_corrupted_cache_probe_raw",
        results_dir=args.results_dir,
        target=args.target,
        timestamp=timestamp,
    )
    summary_path = build_result_path(
        "phase11_corrupted_cache_probe_summary",
        results_dir=args.results_dir,
        target=args.target,
        timestamp=timestamp,
    )

    raw_payload = {
        "phase_code": PROJECT_PHASE_CODE,
        "phase_name": PROJECT_PHASE_NAME,
        "benchmark": "phase11_corrupted_cache_probe",
        "started_at_utc": started_at_utc,
        "finished_at_utc": utc_now_iso(),
        "base_url": base_url,
        "target": args.target,
        "configuration": {
            "matrix_size": args.matrix_size,
            "algorithm": args.algorithm,
            "variant": variant,
            "corruption_kind": args.corruption_kind,
            "redis_db": args.redis_db,
            "resolved_redis_container": asdict(container),
            "require_corruption_counter": args.require_corruption_counter,
        },
        "runtime_metadata": asdict(
            collect_runtime_metadata(base_url=base_url)
        ),
        "startup_probes": {
            "liveness": asdict(startup_liveness),
            "readiness": asdict(startup_readiness),
        },
        "container_resolution": resolution,
        "baseline_state": baseline_state,
        "baseline_miss": asdict(baseline_miss),
        "baseline_hit": asdict(baseline_hit),
        "cache_key": cache_key,
        "original_value": {
            "command": asdict(original_value),
            "valid_json_object": valid_json_object(original_value.stdout),
        },
        "original_ttl": asdict(original_ttl),
        "corruption_write": asdict(corruption_write),
        "corruption_verify": {
            "command": asdict(corruption_verify),
            "exact_value_observed": (
                corruption_verify.stdout == corruption_value
            ),
        },
        "recovered_read": asdict(recovered_read),
        "repaired_hit": asdict(repaired_hit),
        "repaired_value": {
            "command": asdict(repaired_value),
            "valid_json_object": valid_json_object(repaired_value.stdout),
        },
        "final_state": final_state,
        "cleanup_actions": [asdict(item) for item in cleanup_actions],
        "corruption_counter_delta": metric_delta,
        "validation_errors": validation_errors,
        "warnings": warnings,
        "overall_ok": overall_ok,
    }

    summary_payload = {
        "phase_code": PROJECT_PHASE_CODE,
        "phase_name": PROJECT_PHASE_NAME,
        "benchmark": "phase11_corrupted_cache_probe",
        "base_url": base_url,
        "target": args.target,
        "overall_ok": overall_ok,
        "resolved_redis_container": container.name,
        "baseline_healthy": healthy(baseline_state),
        "baseline_cache_hit": baseline_hit.cache_hit,
        "corruption_injected": (
            corruption_write.ok
            and corruption_verify.stdout == corruption_value
        ),
        "corrupted_payload_rejected": (
            recovered_read.status_code == 200
            and recovered_read.cache_hit is not True
        ),
        "matrix_recomputed_successfully": (
            recovered_read.status_code == 200
            and isinstance(recovered_read.response_summary, dict)
            and recovered_read.response_summary.get("status") == "ok"
            and recovered_read.response_summary.get("failed_pairs")
            in {0, None}
        ),
        "repaired_cache_hit": repaired_hit.cache_hit,
        "repaired_value_valid_json_object": valid_json_object(
            repaired_value.stdout
        ),
        "final_healthy": healthy(final_state),
        "api_process_start_unchanged": (
            baseline_view["process_start_time_seconds"]
            == final_view["process_start_time_seconds"]
        ),
        "corruption_counter_delta": metric_delta,
        "baseline_miss_ms": baseline_miss.elapsed_ms,
        "baseline_hit_ms": baseline_hit.elapsed_ms,
        "corruption_recovery_ms": recovered_read.elapsed_ms,
        "repaired_hit_ms": repaired_hit.elapsed_ms,
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
    return asyncio.run(async_main(parse_args()))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Phase 11 corrupted-cache probe interrupted", file=sys.stderr)
        raise SystemExit(130) from None