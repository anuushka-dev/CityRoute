# benchmarks/phase_11/phase11_baseline_probe.py

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx

# Allow this benchmark to run both as:
#   python benchmarks/phase_11/phase11_baseline_probe.py
# and:
#   python -m benchmarks.phase_11.phase11_baseline_probe
PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.phase_11.phase11_common import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT_S,
    PROJECT_PHASE_CODE,
    PROJECT_PHASE_NAME,
    assert_probe_success,
    build_result_path,
    collect_runtime_metadata,
    print_json,
    probes_to_dicts,
    request_probe,
    summarize_latencies,
    utc_now_iso,
    wait_for_liveness,
    wait_for_readiness,
    write_json,
)

DEFAULT_ITERATIONS = 20
DEFAULT_WARMUP_ITERATIONS = 3

BASELINE_ENDPOINTS: tuple[tuple[str, str, tuple[int, ...]], ...] = (
    ("GET", "/", (200,)),
    ("GET", "/health/live", (200,)),
    ("GET", "/health/ready", (200,)),
    ("GET", "/health", (200,)),
    ("GET", "/graph/stats", (200,)),
    ("GET", "/metrics", (200,)),
)

LATENCY_ENDPOINTS: tuple[tuple[str, str, tuple[int, ...]], ...] = (
    ("GET", "/", (200,)),
    ("GET", "/health/live", (200,)),
    ("GET", "/health/ready", (200,)),
    ("GET", "/health", (200,)),
    ("GET", "/graph/stats", (200,)),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Collect the Phase 11 baseline health, readiness, graph, "
            "metrics, and latency evidence."
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
        "--iterations",
        type=int,
        default=DEFAULT_ITERATIONS,
        help=(
            "Measured latency probes per endpoint. "
            f"Default: {DEFAULT_ITERATIONS}"
        ),
    )
    parser.add_argument(
        "--warmup-iterations",
        type=int,
        default=DEFAULT_WARMUP_ITERATIONS,
        help=(
            "Unrecorded warmup probes per endpoint. "
            f"Default: {DEFAULT_WARMUP_ITERATIONS}"
        ),
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        help=(
            "Per-request timeout in seconds. "
            f"Default: {DEFAULT_TIMEOUT_S}"
        ),
    )
    parser.add_argument(
        "--startup-timeout-s",
        type=float,
        default=180.0,
        help="Maximum wait for liveness/readiness. Default: 180",
    )
    parser.add_argument(
        "--allow-degraded",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Accept degraded readiness, for example Redis fail-open mode. "
            "Default: enabled."
        ),
    )
    parser.add_argument(
        "--fail-on-probe-error",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Exit non-zero when a required baseline probe fails. "
            "Default: enabled."
        ),
    )

    args = parser.parse_args()

    if args.iterations <= 0:
        parser.error("--iterations must be greater than zero")

    if args.warmup_iterations < 0:
        parser.error("--warmup-iterations must be zero or greater")

    if args.timeout_s <= 0:
        parser.error("--timeout-s must be greater than zero")

    if args.startup_timeout_s <= 0:
        parser.error("--startup-timeout-s must be greater than zero")

    return args


def _validate_root_payload(
    payload: Any,
) -> list[str]:
    errors: list[str] = []

    if not isinstance(payload, dict):
        return ["root response must be a JSON object"]

    if payload.get("status") != "ok":
        errors.append("root status must be 'ok'")

    if payload.get("service") != "cityroute":
        errors.append("root service must be 'cityroute'")

    if payload.get("phase_code") != PROJECT_PHASE_CODE:
        errors.append(
            "root phase_code mismatch: "
            f"{payload.get('phase_code')!r}"
        )

    if payload.get("phase") != PROJECT_PHASE_NAME:
        errors.append(
            "root phase mismatch: "
            f"{payload.get('phase')!r}"
        )

    required_links = {
        "health": "/health",
        "liveness": "/health/live",
        "readiness": "/health/ready",
        "metrics": "/metrics",
        "graph_stats": "/graph/stats",
        "route": "/route",
        "route_compare": "/route/compare",
        "matrix": "/matrix",
        "vrp_greedy": "/vrp/greedy",
        "vrp_compare": "/vrp/compare",
        "vrp_advanced_compare": "/vrp/compare/advanced",
        "dispatch_compare": "/dispatch/compare",
    }

    for key, expected_value in required_links.items():
        if payload.get(key) != expected_value:
            errors.append(
                f"root link {key!r} expected "
                f"{expected_value!r}, got {payload.get(key)!r}"
            )

    return errors


def _validate_liveness_payload(
    payload: Any,
) -> list[str]:
    errors: list[str] = []

    if not isinstance(payload, dict):
        return ["liveness response must be a JSON object"]

    if payload.get("status") != "alive":
        errors.append("liveness status must be 'alive'")

    if payload.get("phase") != PROJECT_PHASE_CODE:
        errors.append(
            "liveness phase mismatch: "
            f"{payload.get('phase')!r}"
        )

    uptime = payload.get("uptime_s")
    if not isinstance(uptime, int | float) or uptime < 0:
        errors.append("liveness uptime_s must be a non-negative number")

    return errors


def _validate_readiness_payload(
    payload: Any,
    *,
    allow_degraded: bool,
) -> list[str]:
    errors: list[str] = []

    if not isinstance(payload, dict):
        return ["readiness response must be a JSON object"]

    expected_statuses = {"ready"}
    if allow_degraded:
        expected_statuses.add("degraded")

    if payload.get("ready") is not True:
        errors.append("readiness ready must be true")

    if payload.get("status") not in expected_statuses:
        errors.append(
            "readiness status must be one of "
            f"{sorted(expected_statuses)}, got "
            f"{payload.get('status')!r}"
        )

    if payload.get("phase") != PROJECT_PHASE_CODE:
        errors.append(
            "readiness phase mismatch: "
            f"{payload.get('phase')!r}"
        )

    if payload.get("startup_complete") is not True:
        errors.append("readiness startup_complete must be true")

    if payload.get("accepting_requests") is not True:
        errors.append("readiness accepting_requests must be true")

    if payload.get("shutting_down") is not False:
        errors.append("readiness shutting_down must be false")

    components = payload.get("components")
    if not isinstance(components, dict):
        errors.append("readiness components must be an object")
    else:
        for required_component in (
            "graph",
            "snap_index",
            "dispatch_adjacency",
            "redis",
        ):
            if required_component not in components:
                errors.append(
                    "readiness components missing "
                    f"{required_component!r}"
                )

    return errors


def _validate_health_payload(
    payload: Any,
) -> list[str]:
    errors: list[str] = []

    if not isinstance(payload, dict):
        return ["health response must be a JSON object"]

    if payload.get("status") not in {"ok", "degraded"}:
        errors.append(
            "health status must be 'ok' or 'degraded'"
        )

    if payload.get("graph_loaded") is not True:
        errors.append("health graph_loaded must be true")

    uptime = payload.get("uptime_s")
    if not isinstance(uptime, int | float) or uptime < 0:
        errors.append("health uptime_s must be a non-negative number")

    return errors


def _validate_graph_stats_payload(
    payload: Any,
) -> list[str]:
    errors: list[str] = []

    if not isinstance(payload, dict):
        return ["graph stats response must be a JSON object"]

    if payload.get("graph_loaded") is not True:
        errors.append("graph stats graph_loaded must be true")

    for key in ("nodes", "edges"):
        value = payload.get(key)
        if not isinstance(value, int) or value <= 0:
            errors.append(
                f"graph stats {key} must be a positive integer"
            )

    if payload.get("snap_index_loaded") is not True:
        errors.append("graph stats snap_index_loaded must be true")

    if payload.get("dispatch_adjacency_loaded") is not True:
        errors.append(
            "graph stats dispatch_adjacency_loaded must be true"
        )

    if payload.get("dispatch_road_matrix_ready") is not True:
        errors.append(
            "graph stats dispatch_road_matrix_ready must be true"
        )

    if payload.get("phase11_reliability_enabled") is not True:
        errors.append(
            "graph stats phase11_reliability_enabled must be true"
        )

    if payload.get("phase11_accepting_requests") is not True:
        errors.append(
            "graph stats phase11_accepting_requests must be true"
        )

    return errors


def _validate_metrics_text(
    body: str | None,
) -> list[str]:
    errors: list[str] = []

    if not body:
        return ["metrics response body must not be empty"]

    if "# HELP" not in body:
        errors.append("metrics output is missing '# HELP'")

    if "# TYPE" not in body:
        errors.append("metrics output is missing '# TYPE'")

    required_metrics = (
        "cityroute_active_requests",
        "cityroute_waiting_requests",
        "cityroute_readiness",
        "cityroute_redis_available",
        "cityroute_graceful_shutdown_inflight",
    )

    for metric_name in required_metrics:
        if metric_name not in body:
            errors.append(
                f"metrics output is missing {metric_name!r}"
            )

    return errors


def _validate_probe_payload(
    *,
    path: str,
    response_json: Any,
    response_text: str | None,
    allow_degraded: bool,
) -> list[str]:
    if path == "/":
        return _validate_root_payload(response_json)

    if path == "/health/live":
        return _validate_liveness_payload(response_json)

    if path == "/health/ready":
        return _validate_readiness_payload(
            response_json,
            allow_degraded=allow_degraded,
        )

    if path == "/health":
        return _validate_health_payload(response_json)

    if path == "/graph/stats":
        return _validate_graph_stats_payload(response_json)

    if path == "/metrics":
        return _validate_metrics_text(response_text)

    return []


def _run_warmups(
    *,
    client: httpx.Client,
    base_url: str,
    warmup_iterations: int,
    timeout_s: float,
) -> None:
    for method, path, expected_status_codes in LATENCY_ENDPOINTS:
        for _ in range(warmup_iterations):
            request_probe(
                method=method,
                path=path,
                base_url=base_url,
                expected_status_codes=expected_status_codes,
                timeout_s=timeout_s,
                client=client,
            )


def _collect_latency_probes(
    *,
    client: httpx.Client,
    base_url: str,
    iterations: int,
    timeout_s: float,
) -> dict[str, list[Any]]:
    endpoint_probes: dict[str, list[Any]] = {}

    for method, path, expected_status_codes in LATENCY_ENDPOINTS:
        probes = []

        for _ in range(iterations):
            probes.append(
                request_probe(
                    method=method,
                    path=path,
                    base_url=base_url,
                    expected_status_codes=expected_status_codes,
                    timeout_s=timeout_s,
                    client=client,
                )
            )

        endpoint_probes[f"{method} {path}"] = probes

    return endpoint_probes


def main() -> int:
    args = parse_args()
    base_url = args.base_url.rstrip("/")

    started_at_utc = utc_now_iso()

    liveness_probe = wait_for_liveness(
        base_url=base_url,
        startup_timeout_s=args.startup_timeout_s,
    )
    readiness_probe = wait_for_readiness(
        base_url=base_url,
        startup_timeout_s=args.startup_timeout_s,
        allow_degraded=args.allow_degraded,
    )

    baseline_probes = []

    with httpx.Client(timeout=args.timeout_s) as client:
        for method, path, expected_status_codes in BASELINE_ENDPOINTS:
            baseline_probes.append(
                request_probe(
                    method=method,
                    path=path,
                    base_url=base_url,
                    expected_status_codes=expected_status_codes,
                    timeout_s=args.timeout_s,
                    client=client,
                )
            )

        _run_warmups(
            client=client,
            base_url=base_url,
            warmup_iterations=args.warmup_iterations,
            timeout_s=args.timeout_s,
        )

        latency_probes = _collect_latency_probes(
            client=client,
            base_url=base_url,
            iterations=args.iterations,
            timeout_s=args.timeout_s,
        )

    validation_errors: dict[str, list[str]] = {}

    for probe in baseline_probes:
        errors = _validate_probe_payload(
            path=probe.path,
            response_json=probe.response_json,
            response_text=probe.response_text,
            allow_degraded=args.allow_degraded,
        )

        if errors:
            validation_errors[
                f"{probe.method} {probe.path}"
            ] = errors

    latency_summaries = {
        endpoint: asdict(summarize_latencies(probes))
        for endpoint, probes in latency_probes.items()
    }

    failed_baseline_probes = [
        probe
        for probe in baseline_probes
        if not probe.ok
    ]

    failed_latency_probes = {
        endpoint: [
            probe
            for probe in probes
            if not probe.ok
        ]
        for endpoint, probes in latency_probes.items()
    }
    failed_latency_probes = {
        endpoint: probes
        for endpoint, probes in failed_latency_probes.items()
        if probes
    }

    overall_ok = (
        liveness_probe.ok
        and readiness_probe.ok
        and not failed_baseline_probes
        and not failed_latency_probes
        and not validation_errors
    )

    result_payload: dict[str, Any] = {
        "phase_code": PROJECT_PHASE_CODE,
        "phase_name": PROJECT_PHASE_NAME,
        "benchmark": "phase11_baseline_probe",
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
            "iterations": args.iterations,
            "warmup_iterations": args.warmup_iterations,
            "timeout_s": args.timeout_s,
            "startup_timeout_s": args.startup_timeout_s,
            "allow_degraded": args.allow_degraded,
            "fail_on_probe_error": args.fail_on_probe_error,
        },
        "runtime_metadata": asdict(
            collect_runtime_metadata(base_url=base_url)
        ),
        "startup_probes": {
            "liveness": asdict(liveness_probe),
            "readiness": asdict(readiness_probe),
        },
        "baseline_probes": probes_to_dicts(baseline_probes),
        "baseline_validation_errors": validation_errors,
        "latency_summaries": latency_summaries,
        "latency_probes": {
            endpoint: probes_to_dicts(probes)
            for endpoint, probes in latency_probes.items()
        },
        "failed_baseline_probe_count": len(
            failed_baseline_probes
        ),
        "failed_latency_probe_count": sum(
            len(probes)
            for probes in failed_latency_probes.values()
        ),
        "overall_ok": overall_ok,
    }

    result_path = build_result_path(
        "phase11_baseline_probe_raw",
        results_dir=args.results_dir,
        target=args.target,
    )
    write_json(result_path, result_payload)

    summary = {
        "phase_code": PROJECT_PHASE_CODE,
        "benchmark": "phase11_baseline_probe",
        "overall_ok": overall_ok,
        "base_url": base_url,
        "result_path": str(result_path),
        "baseline_validation_errors": validation_errors,
        "latency_summaries": latency_summaries,
    }
    print_json(summary)

    if args.fail_on_probe_error:
        for probe in baseline_probes:
            assert_probe_success(
                probe,
                context="baseline probe",
            )

        if failed_latency_probes:
            raise AssertionError(
                "One or more latency probes failed: "
                f"{sorted(failed_latency_probes)}"
            )

        if validation_errors:
            raise AssertionError(
                "Baseline payload validation failed: "
                f"{validation_errors}"
            )

    return 0 if overall_ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print(
            "Phase 11 baseline probe interrupted",
            file=sys.stderr,
        )
        raise SystemExit(130) from None