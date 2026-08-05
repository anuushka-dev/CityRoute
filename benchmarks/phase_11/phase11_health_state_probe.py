# benchmarks/phase_11/phase11_health_state_probe.py

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx

# Support both direct execution and module execution:
#   python benchmarks/phase_11/phase11_health_state_probe.py
#   python -m benchmarks.phase_11.phase11_health_state_probe
PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.phase_11.phase11_common import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT_S,
    PROJECT_PHASE_CODE,
    PROJECT_PHASE_NAME,
    HttpProbeResult,
    build_result_path,
    collect_runtime_metadata,
    extract_prometheus_sample,
    print_json,
    probes_to_dicts,
    request_probe,
    summarize_latencies,
    timestamp_slug,
    utc_now_iso,
    wait_for_liveness,
    wait_for_readiness,
    write_json,
)


DEFAULT_SAMPLES = 30
DEFAULT_INTERVAL_S = 0.5

PROBE_ENDPOINTS: tuple[tuple[str, str, tuple[int, ...]], ...] = (
    ("GET", "/health/live", (200,)),
    ("GET", "/health/ready", (200,)),
    ("GET", "/health", (200,)),
    ("GET", "/graph/stats", (200,)),
    ("GET", "/metrics", (200,)),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Collect repeated Phase 11 health-state snapshots and verify "
            "cross-endpoint lifecycle, readiness, dependency, and metrics "
            "consistency."
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
        "--samples",
        type=int,
        default=DEFAULT_SAMPLES,
        help=(
            "Number of repeated health-state snapshots. "
            f"Default: {DEFAULT_SAMPLES}"
        ),
    )
    parser.add_argument(
        "--interval-s",
        type=float,
        default=DEFAULT_INTERVAL_S,
        help=(
            "Delay between snapshots in seconds. "
            f"Default: {DEFAULT_INTERVAL_S}"
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
            "Accept degraded readiness and health when Redis fails open. "
            "Default: enabled."
        ),
    )
    parser.add_argument(
        "--max-uptime-skew-s",
        type=float,
        default=2.0,
        help=(
            "Maximum accepted uptime difference between liveness, "
            "readiness, and legacy health within one snapshot. "
            "Default: 2.0"
        ),
    )
    parser.add_argument(
        "--fail-on-validation-error",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Exit non-zero when any probe or state validation fails. "
            "Default: enabled."
        ),
    )

    args = parser.parse_args()

    if args.samples <= 0:
        parser.error("--samples must be greater than zero")

    if args.interval_s < 0:
        parser.error("--interval-s must be zero or greater")

    if args.timeout_s <= 0:
        parser.error("--timeout-s must be greater than zero")

    if args.startup_timeout_s <= 0:
        parser.error("--startup-timeout-s must be greater than zero")

    if args.max_uptime_skew_s < 0:
        parser.error("--max-uptime-skew-s must be zero or greater")

    return args


def _payload(
    probes: dict[str, HttpProbeResult],
    path: str,
) -> dict[str, Any] | None:
    value = probes[path].response_json
    return value if isinstance(value, dict) else None


def _numeric_value(
    payload: dict[str, Any] | None,
    key: str,
) -> float | None:
    if payload is None:
        return None

    value = payload.get(key)

    if isinstance(value, bool):
        return None

    if isinstance(value, int | float):
        return float(value)

    return None


def _validate_http_probes(
    probes: dict[str, HttpProbeResult],
) -> list[str]:
    errors: list[str] = []

    for path, probe in probes.items():
        if probe.ok:
            continue

        errors.append(
            f"{path} probe failed: "
            f"status={probe.status_code}, "
            f"error={probe.error_type}: {probe.error_message}"
        )

    return errors


def _validate_liveness(
    payload: dict[str, Any] | None,
) -> list[str]:
    if payload is None:
        return ["liveness response must be a JSON object"]

    errors: list[str] = []

    if payload.get("status") != "alive":
        errors.append("liveness status must be 'alive'")

    if payload.get("phase") != PROJECT_PHASE_CODE:
        errors.append(
            "liveness phase mismatch: "
            f"{payload.get('phase')!r}"
        )

    uptime = _numeric_value(payload, "uptime_s")
    if uptime is None or uptime < 0:
        errors.append(
            "liveness uptime_s must be a non-negative number"
        )

    return errors


def _validate_readiness(
    payload: dict[str, Any] | None,
    *,
    allow_degraded: bool,
) -> list[str]:
    if payload is None:
        return ["readiness response must be a JSON object"]

    errors: list[str] = []

    accepted_statuses = {"ready"}
    if allow_degraded:
        accepted_statuses.add("degraded")

    if payload.get("status") not in accepted_statuses:
        errors.append(
            "readiness status must be one of "
            f"{sorted(accepted_statuses)}, got "
            f"{payload.get('status')!r}"
        )

    if payload.get("ready") is not True:
        errors.append("readiness ready must be true")

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
        return errors

    for component in (
        "graph",
        "snap_index",
        "dispatch_adjacency",
        "redis",
    ):
        if component not in components:
            errors.append(
                f"readiness components missing {component!r}"
            )

    for required_component in (
        "graph",
        "snap_index",
        "dispatch_adjacency",
    ):
        if components.get(required_component) != "ready":
            errors.append(
                f"required component {required_component!r} "
                f"must be 'ready', got "
                f"{components.get(required_component)!r}"
            )

    redis_state = components.get("redis")

    if allow_degraded:
        accepted_redis_states = {
            "ready",
            "degraded",
            "unavailable",
            "not_initialized",
        }
    else:
        accepted_redis_states = {"ready"}

    if redis_state not in accepted_redis_states:
        errors.append(
            "Redis component state must be one of "
            f"{sorted(accepted_redis_states)}, got "
            f"{redis_state!r}"
        )

    degraded_dependencies = payload.get("degraded_dependencies")
    failure_reasons = payload.get("failure_reasons")

    if not isinstance(degraded_dependencies, list):
        errors.append(
            "readiness degraded_dependencies must be a list"
        )

    if not isinstance(failure_reasons, list):
        errors.append("readiness failure_reasons must be a list")

    return errors


def _validate_legacy_health(
    payload: dict[str, Any] | None,
    *,
    allow_degraded: bool,
) -> list[str]:
    if payload is None:
        return ["legacy health response must be a JSON object"]

    errors: list[str] = []

    accepted_statuses = {"ok"}
    if allow_degraded:
        accepted_statuses.add("degraded")

    if payload.get("status") not in accepted_statuses:
        errors.append(
            "legacy health status must be one of "
            f"{sorted(accepted_statuses)}, got "
            f"{payload.get('status')!r}"
        )

    if payload.get("graph_loaded") is not True:
        errors.append("legacy health graph_loaded must be true")

    uptime = _numeric_value(payload, "uptime_s")
    if uptime is None or uptime < 0:
        errors.append(
            "legacy health uptime_s must be a non-negative number"
        )

    return errors


def _validate_graph_stats(
    payload: dict[str, Any] | None,
) -> list[str]:
    if payload is None:
        return ["graph stats response must be a JSON object"]

    errors: list[str] = []

    boolean_requirements = {
        "graph_loaded": True,
        "snap_index_loaded": True,
        "dispatch_adjacency_loaded": True,
        "dispatch_road_matrix_ready": True,
        "phase11_reliability_enabled": True,
        "phase11_accepting_requests": True,
    }

    for key, expected in boolean_requirements.items():
        if payload.get(key) is not expected:
            errors.append(
                f"graph stats {key} must be {expected!r}, "
                f"got {payload.get(key)!r}"
            )

    for key in (
        "nodes",
        "edges",
        "dispatch_adjacency_node_count",
        "dispatch_adjacency_edge_count",
    ):
        value = payload.get(key)

        if not isinstance(value, int) or value <= 0:
            errors.append(
                f"graph stats {key} must be a positive integer"
            )

    return errors


def _metric_values(
    metrics_text: str | None,
) -> dict[str, float | None]:
    body = metrics_text or ""

    metric_names = (
        "cityroute_active_requests",
        "cityroute_waiting_requests",
        "cityroute_max_active_requests",
        "cityroute_max_waiting_requests",
        "cityroute_readiness",
        "cityroute_accepting_requests",
        "cityroute_redis_available",
        "cityroute_graceful_shutdown_inflight",
    )

    return {
        metric_name: extract_prometheus_sample(
            body,
            metric_name,
        )
        for metric_name in metric_names
    }


def _validate_metrics(
    metrics_text: str | None,
    *,
    readiness_payload: dict[str, Any] | None,
) -> tuple[list[str], dict[str, float | None]]:
    values = _metric_values(metrics_text)
    errors: list[str] = []

    for metric_name, value in values.items():
        if value is None:
            errors.append(
                f"metrics output missing sample {metric_name!r}"
            )

    non_negative_metrics = (
        "cityroute_active_requests",
        "cityroute_waiting_requests",
        "cityroute_max_active_requests",
        "cityroute_max_waiting_requests",
        "cityroute_graceful_shutdown_inflight",
    )

    for metric_name in non_negative_metrics:
        value = values.get(metric_name)

        if value is not None and value < 0:
            errors.append(
                f"{metric_name} must be non-negative, got {value}"
            )

    for metric_name in (
        "cityroute_max_active_requests",
        "cityroute_max_waiting_requests",
    ):
        value = values.get(metric_name)

        if value is not None and value <= 0:
            errors.append(
                f"{metric_name} must be greater than zero"
            )

    if values.get("cityroute_readiness") not in {1.0}:
        errors.append(
            "cityroute_readiness must be 1 while ready"
        )

    if values.get("cityroute_accepting_requests") not in {1.0}:
        errors.append(
            "cityroute_accepting_requests must be 1 "
            "while admission is enabled"
        )

    if values.get("cityroute_graceful_shutdown_inflight") not in {
        0.0
    }:
        errors.append(
            "cityroute_graceful_shutdown_inflight must be 0 "
            "during steady-state probing"
        )

    components = (
        readiness_payload.get("components")
        if readiness_payload is not None
        else None
    )
    redis_state = (
        components.get("redis")
        if isinstance(components, dict)
        else None
    )

    redis_metric = values.get("cityroute_redis_available")

    if redis_state == "ready" and redis_metric != 1.0:
        errors.append(
            "Redis readiness component is ready but "
            "cityroute_redis_available is not 1"
        )

    if (
        redis_state is not None
        and redis_state != "ready"
        and redis_metric != 0.0
    ):
        errors.append(
            "Redis readiness component is not ready but "
            "cityroute_redis_available is not 0"
        )

    return errors, values


def _validate_uptime_consistency(
    *,
    liveness_payload: dict[str, Any] | None,
    readiness_payload: dict[str, Any] | None,
    health_payload: dict[str, Any] | None,
    previous_uptimes: dict[str, float] | None,
    max_uptime_skew_s: float,
) -> tuple[list[str], dict[str, float]]:
    errors: list[str] = []

    uptimes = {
        "liveness": _numeric_value(
            liveness_payload,
            "uptime_s",
        ),
        "readiness": _numeric_value(
            readiness_payload,
            "uptime_s",
        ),
        "health": _numeric_value(
            health_payload,
            "uptime_s",
        ),
    }

    resolved_uptimes = {
        key: value
        for key, value in uptimes.items()
        if value is not None
    }

    if len(resolved_uptimes) == len(uptimes):
        skew_s = (
            max(resolved_uptimes.values())
            - min(resolved_uptimes.values())
        )

        if skew_s > max_uptime_skew_s:
            errors.append(
                "uptime skew exceeded threshold: "
                f"{skew_s:.6f}s > {max_uptime_skew_s:.6f}s"
            )

    if previous_uptimes is not None:
        for key, value in resolved_uptimes.items():
            previous_value = previous_uptimes.get(key)

            if (
                previous_value is not None
                and value < previous_value
            ):
                errors.append(
                    f"{key} uptime decreased from "
                    f"{previous_value} to {value}"
                )

    return errors, resolved_uptimes


def _validate_cross_endpoint_state(
    *,
    readiness_payload: dict[str, Any] | None,
    health_payload: dict[str, Any] | None,
    graph_stats_payload: dict[str, Any] | None,
) -> list[str]:
    errors: list[str] = []

    if (
        readiness_payload is None
        or health_payload is None
        or graph_stats_payload is None
    ):
        return errors

    components = readiness_payload.get("components")
    components = (
        components
        if isinstance(components, dict)
        else {}
    )

    if (
        components.get("graph") == "ready"
        and health_payload.get("graph_loaded") is not True
    ):
        errors.append(
            "readiness reports graph ready but legacy health "
            "reports graph_loaded=false"
        )

    if (
        components.get("graph") == "ready"
        and graph_stats_payload.get("graph_loaded") is not True
    ):
        errors.append(
            "readiness reports graph ready but graph stats "
            "reports graph_loaded=false"
        )

    if (
        components.get("snap_index") == "ready"
        and graph_stats_payload.get("snap_index_loaded") is not True
    ):
        errors.append(
            "readiness reports snap index ready but graph stats "
            "reports snap_index_loaded=false"
        )

    if (
        components.get("dispatch_adjacency") == "ready"
        and graph_stats_payload.get(
            "dispatch_road_matrix_ready"
        )
        is not True
    ):
        errors.append(
            "readiness reports dispatch adjacency ready but graph "
            "stats reports dispatch_road_matrix_ready=false"
        )

    if (
        readiness_payload.get("accepting_requests") is True
        and graph_stats_payload.get(
            "phase11_accepting_requests"
        )
        is not True
    ):
        errors.append(
            "readiness reports accepting_requests=true but graph "
            "stats reports phase11_accepting_requests=false"
        )

    return errors


def _collect_snapshot(
    *,
    client: httpx.Client,
    base_url: str,
    timeout_s: float,
) -> dict[str, HttpProbeResult]:
    probes: dict[str, HttpProbeResult] = {}

    for method, path, expected_status_codes in PROBE_ENDPOINTS:
        probes[path] = request_probe(
            method=method,
            path=path,
            base_url=base_url,
            expected_status_codes=expected_status_codes,
            timeout_s=timeout_s,
            client=client,
        )

    return probes


def _status_distribution(
    snapshots: list[dict[str, Any]],
    *,
    section: str,
    key: str,
) -> dict[str, int]:
    counts: Counter[str] = Counter()

    for snapshot in snapshots:
        payload = snapshot.get(section)

        if isinstance(payload, dict):
            counts[str(payload.get(key))] += 1

    return dict(sorted(counts.items()))


def main() -> int:
    args = parse_args()
    base_url = args.base_url.rstrip("/")

    started_at_utc = utc_now_iso()

    startup_liveness = wait_for_liveness(
        base_url=base_url,
        startup_timeout_s=args.startup_timeout_s,
    )
    startup_readiness = wait_for_readiness(
        base_url=base_url,
        startup_timeout_s=args.startup_timeout_s,
        allow_degraded=args.allow_degraded,
    )

    snapshots: list[dict[str, Any]] = []
    endpoint_probes: dict[str, list[HttpProbeResult]] = {
        path: []
        for _, path, _ in PROBE_ENDPOINTS
    }
    previous_uptimes: dict[str, float] | None = None

    with httpx.Client(timeout=args.timeout_s) as client:
        for sample_index in range(args.samples):
            captured_at_utc = utc_now_iso()

            probes = _collect_snapshot(
                client=client,
                base_url=base_url,
                timeout_s=args.timeout_s,
            )

            for path, probe in probes.items():
                endpoint_probes[path].append(probe)

            liveness_payload = _payload(
                probes,
                "/health/live",
            )
            readiness_payload = _payload(
                probes,
                "/health/ready",
            )
            health_payload = _payload(
                probes,
                "/health",
            )
            graph_stats_payload = _payload(
                probes,
                "/graph/stats",
            )
            metrics_probe = probes["/metrics"]

            validation_errors: list[str] = []

            validation_errors.extend(
                _validate_http_probes(probes)
            )
            validation_errors.extend(
                _validate_liveness(liveness_payload)
            )
            validation_errors.extend(
                _validate_readiness(
                    readiness_payload,
                    allow_degraded=args.allow_degraded,
                )
            )
            validation_errors.extend(
                _validate_legacy_health(
                    health_payload,
                    allow_degraded=args.allow_degraded,
                )
            )
            validation_errors.extend(
                _validate_graph_stats(graph_stats_payload)
            )

            metrics_errors, metric_values = _validate_metrics(
                metrics_probe.response_text,
                readiness_payload=readiness_payload,
            )
            validation_errors.extend(metrics_errors)

            uptime_errors, current_uptimes = (
                _validate_uptime_consistency(
                    liveness_payload=liveness_payload,
                    readiness_payload=readiness_payload,
                    health_payload=health_payload,
                    previous_uptimes=previous_uptimes,
                    max_uptime_skew_s=args.max_uptime_skew_s,
                )
            )
            validation_errors.extend(uptime_errors)

            validation_errors.extend(
                _validate_cross_endpoint_state(
                    readiness_payload=readiness_payload,
                    health_payload=health_payload,
                    graph_stats_payload=graph_stats_payload,
                )
            )

            previous_uptimes = current_uptimes

            snapshots.append(
                {
                    "sample_index": sample_index,
                    "captured_at_utc": captured_at_utc,
                    "ok": not validation_errors,
                    "validation_errors": validation_errors,
                    "liveness": liveness_payload,
                    "readiness": readiness_payload,
                    "health": health_payload,
                    "graph_stats": graph_stats_payload,
                    "metric_values": metric_values,
                    "probes": {
                        path: asdict(probe)
                        for path, probe in probes.items()
                    },
                }
            )

            if (
                sample_index < args.samples - 1
                and args.interval_s > 0
            ):
                time.sleep(args.interval_s)

    failed_snapshots = [
        snapshot
        for snapshot in snapshots
        if not snapshot["ok"]
    ]

    latency_summaries = {
        f"GET {path}": asdict(
            summarize_latencies(probes)
        )
        for path, probes in endpoint_probes.items()
    }

    readiness_status_distribution = _status_distribution(
        snapshots,
        section="readiness",
        key="status",
    )
    health_status_distribution = _status_distribution(
        snapshots,
        section="health",
        key="status",
    )

    component_state_distributions: dict[str, dict[str, int]] = {}

    for component in (
        "graph",
        "snap_index",
        "dispatch_adjacency",
        "redis",
    ):
        counts: Counter[str] = Counter()

        for snapshot in snapshots:
            readiness_payload = snapshot.get("readiness")
            components = (
                readiness_payload.get("components")
                if isinstance(readiness_payload, dict)
                else None
            )

            if isinstance(components, dict):
                counts[str(components.get(component))] += 1

        component_state_distributions[component] = dict(
            sorted(counts.items())
        )

    overall_ok = (
        startup_liveness.ok
        and startup_readiness.ok
        and not failed_snapshots
    )

    timestamp = timestamp_slug()

    raw_path = build_result_path(
        "phase11_health_state_probe_raw",
        results_dir=args.results_dir,
        target=args.target,
        timestamp=timestamp,
    )
    summary_path = build_result_path(
        "phase11_health_state_probe_summary",
        results_dir=args.results_dir,
        target=args.target,
        timestamp=timestamp,
    )

    raw_payload: dict[str, Any] = {
        "phase_code": PROJECT_PHASE_CODE,
        "phase_name": PROJECT_PHASE_NAME,
        "benchmark": "phase11_health_state_probe",
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
            "samples": args.samples,
            "interval_s": args.interval_s,
            "timeout_s": args.timeout_s,
            "startup_timeout_s": args.startup_timeout_s,
            "allow_degraded": args.allow_degraded,
            "max_uptime_skew_s": args.max_uptime_skew_s,
            "fail_on_validation_error": (
                args.fail_on_validation_error
            ),
        },
        "runtime_metadata": asdict(
            collect_runtime_metadata(base_url=base_url)
        ),
        "startup_probes": {
            "liveness": asdict(startup_liveness),
            "readiness": asdict(startup_readiness),
        },
        "snapshots": snapshots,
        "endpoint_probes": {
            path: probes_to_dicts(probes)
            for path, probes in endpoint_probes.items()
        },
        "latency_summaries": latency_summaries,
        "readiness_status_distribution": (
            readiness_status_distribution
        ),
        "health_status_distribution": (
            health_status_distribution
        ),
        "component_state_distributions": (
            component_state_distributions
        ),
        "failed_snapshot_count": len(failed_snapshots),
        "overall_ok": overall_ok,
    }

    summary_payload: dict[str, Any] = {
        "phase_code": PROJECT_PHASE_CODE,
        "phase_name": PROJECT_PHASE_NAME,
        "benchmark": "phase11_health_state_probe",
        "base_url": base_url,
        "target": args.target,
        "sample_count": args.samples,
        "failed_snapshot_count": len(failed_snapshots),
        "success_rate": (
            (args.samples - len(failed_snapshots))
            / args.samples
        ),
        "overall_ok": overall_ok,
        "readiness_status_distribution": (
            readiness_status_distribution
        ),
        "health_status_distribution": (
            health_status_distribution
        ),
        "component_state_distributions": (
            component_state_distributions
        ),
        "latency_summaries": latency_summaries,
        "raw_result_path": str(raw_path),
        "summary_result_path": str(summary_path),
    }

    write_json(raw_path, raw_payload)
    write_json(summary_path, summary_payload)
    print_json(summary_payload)

    if args.fail_on_validation_error and not overall_ok:
        print(
            "Phase 11 health-state validation failed",
            file=sys.stderr,
        )
        return 1

    return 0 if overall_ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print(
            "Phase 11 health-state probe interrupted",
            file=sys.stderr,
        )
        raise SystemExit(130) from None