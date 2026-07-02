from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

KANPUR_START = {"lat": 26.4549, "lon": 80.3506}

KANPUR_STOPS = [
    {"lat": 26.4558, "lon": 80.3520},
    {"lat": 26.4570, "lon": 80.3492},
    {"lat": 26.4525, "lon": 80.3480},
    {"lat": 26.4512, "lon": 80.3518},
    {"lat": 26.4595, "lon": 80.3535},
    {"lat": 26.4610, "lon": 80.3478},
    {"lat": 26.4489, "lon": 80.3470},
    {"lat": 26.4475, "lon": 80.3528},
    {"lat": 26.4630, "lon": 80.3555},
    {"lat": 26.4645, "lon": 80.3445},
    {"lat": 26.4458, "lon": 80.3440},
    {"lat": 26.4440, "lon": 80.3545},
    {"lat": 26.4660, "lon": 80.3580},
    {"lat": 26.4680, "lon": 80.3420},
    {"lat": 26.4420, "lon": 80.3415},
    {"lat": 26.4400, "lon": 80.3570},
    {"lat": 26.4700, "lon": 80.3600},
    {"lat": 26.4720, "lon": 80.3395},
    {"lat": 26.4385, "lon": 80.3390},
    {"lat": 26.4365, "lon": 80.3595},
    {"lat": 26.4740, "lon": 80.3620},
    {"lat": 26.4760, "lon": 80.3375},
    {"lat": 26.4350, "lon": 80.3370},
    {"lat": 26.4330, "lon": 80.3615},
]


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None

    sorted_values = sorted(values)

    if len(sorted_values) == 1:
        return round(sorted_values[0], 3)

    rank = (len(sorted_values) - 1) * pct
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = rank - lower

    value = sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight
    return round(value, 3)


def _safe_round(value: Any) -> float | None:
    if value is None:
        return None

    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _http_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout_s: float = 120.0,
) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}

    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url=url, data=body, headers=headers, method=method)

    try:
        with urlopen(request, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8")
            return {
                "ok": True,
                "status_code": response.status,
                "body": json.loads(raw) if raw else None,
            }

    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            body_json: Any = json.loads(raw)
        except json.JSONDecodeError:
            body_json = raw

        return {
            "ok": False,
            "status_code": exc.code,
            "body": body_json,
        }

    except URLError as exc:
        return {
            "ok": False,
            "status_code": None,
            "body": {"error": "URL error", "message": str(exc)},
        }


def _build_payload(
    *,
    stop_count: int,
    return_to_start: bool,
    matrix_algorithm: str,
    use_cache: bool,
    two_opt_max_iterations: int,
    two_opt_improvement_tolerance_m: float,
    lns_max_iterations: int,
    lns_destroy_fraction: float,
    lns_no_improvement_limit: int,
    lns_random_seed: int,
    keep_trace: bool,
) -> dict[str, Any]:
    if stop_count < 1 or stop_count > 24:
        raise ValueError("stop_count must be between 1 and 24")

    return {
        "start": KANPUR_START,
        "stops": KANPUR_STOPS[:stop_count],
        "return_to_start": return_to_start,
        "matrix_algorithm": matrix_algorithm,
        "use_cache": use_cache,
        "two_opt_max_iterations": two_opt_max_iterations,
        "two_opt_improvement_tolerance_m": two_opt_improvement_tolerance_m,
        "lns_max_iterations": lns_max_iterations,
        "lns_destroy_fraction": lns_destroy_fraction,
        "lns_no_improvement_limit": lns_no_improvement_limit,
        "lns_random_seed": lns_random_seed,
        "keep_trace": keep_trace,
    }


def _extract_success_metrics(
    *,
    body: dict[str, Any],
    response_elapsed_ms: float,
    stop_count: int,
    iteration: int,
    return_to_start: bool,
    seed: int,
) -> dict[str, Any]:
    greedy = body.get("greedy", {})
    two_opt = body.get("two_opt", {})
    lns = body.get("lns", {})
    comparison = body.get("comparison", {})

    greedy_distance = _safe_round(greedy.get("total_distance_m"))
    two_opt_distance = _safe_round(two_opt.get("total_distance_m"))
    lns_distance = _safe_round(lns.get("total_distance_m"))

    return {
        "success": True,
        "stop_count": stop_count,
        "iteration": iteration,
        "return_to_start": return_to_start,
        "seed": seed,
        "response_elapsed_ms": round(response_elapsed_ms, 3),
        "api_total_time_ms": _safe_round(body.get("total_time_ms")),
        "matrix_generation_time_ms": _safe_round(body.get("matrix_generation_time_ms")),
        "greedy_optimization_time_ms": _safe_round(greedy.get("optimization_time_ms")),
        "two_opt_optimization_time_ms": _safe_round(two_opt.get("optimization_time_ms")),
        "lns_optimization_time_ms": _safe_round(lns.get("optimization_time_ms")),
        "greedy_distance_m": greedy_distance,
        "two_opt_distance_m": two_opt_distance,
        "lns_distance_m": lns_distance,
        "two_opt_vs_greedy_saved_m": _safe_round(
            comparison.get("two_opt_vs_greedy_distance_saved_m")
        ),
        "two_opt_vs_greedy_improvement_pct": _safe_round(
            comparison.get("two_opt_vs_greedy_improvement_pct")
        ),
        "lns_vs_two_opt_saved_m": _safe_round(
            comparison.get("lns_vs_two_opt_distance_saved_m")
        ),
        "lns_vs_two_opt_improvement_pct": _safe_round(
            comparison.get("lns_vs_two_opt_improvement_pct")
        ),
        "lns_vs_greedy_saved_m": _safe_round(
            comparison.get("lns_vs_greedy_distance_saved_m")
        ),
        "lns_vs_greedy_improvement_pct": _safe_round(
            comparison.get("lns_vs_greedy_improvement_pct")
        ),
        "two_opt_non_regression": bool(comparison.get("two_opt_non_regression")),
        "lns_non_regression": bool(comparison.get("lns_non_regression")),
        "lns_iterations_run": lns.get("iterations_run"),
        "lns_improvements_applied": lns.get("improvements_applied"),
        "lns_converged": lns.get("converged"),
        "lns_trace_length": len(lns.get("trace", [])),
        "cache_used": body.get("cache_used"),
        "cache_status": body.get("cache_status"),
        "cache_hits": body.get("cache_hits"),
        "cache_misses": body.get("cache_misses"),
    }


def _summarize_group(results: list[dict[str, Any]]) -> dict[str, Any]:
    successes = [item for item in results if item.get("success")]
    failures = [item for item in results if not item.get("success")]

    response_times = [
        float(item["response_elapsed_ms"])
        for item in successes
        if item.get("response_elapsed_ms") is not None
    ]
    api_times = [
        float(item["api_total_time_ms"])
        for item in successes
        if item.get("api_total_time_ms") is not None
    ]
    lns_times = [
        float(item["lns_optimization_time_ms"])
        for item in successes
        if item.get("lns_optimization_time_ms") is not None
    ]
    lns_vs_two_opt_improvements = [
        float(item["lns_vs_two_opt_improvement_pct"])
        for item in successes
        if item.get("lns_vs_two_opt_improvement_pct") is not None
    ]
    lns_vs_greedy_improvements = [
        float(item["lns_vs_greedy_improvement_pct"])
        for item in successes
        if item.get("lns_vs_greedy_improvement_pct") is not None
    ]

    return {
        "attempt_count": len(results),
        "success_count": len(successes),
        "failure_count": len(failures),
        "success_rate_pct": round((len(successes) / len(results)) * 100.0, 3)
        if results
        else 0.0,
        "all_two_opt_non_regression": all(
            bool(item.get("two_opt_non_regression")) for item in successes
        )
        if successes
        else False,
        "all_lns_non_regression": all(
            bool(item.get("lns_non_regression")) for item in successes
        )
        if successes
        else False,
        "response_elapsed_ms": {
            "median": _percentile(response_times, 0.50),
            "p95": _percentile(response_times, 0.95),
            "max": _percentile(response_times, 1.00),
        },
        "api_total_time_ms": {
            "median": _percentile(api_times, 0.50),
            "p95": _percentile(api_times, 0.95),
            "max": _percentile(api_times, 1.00),
        },
        "lns_optimization_time_ms": {
            "median": _percentile(lns_times, 0.50),
            "p95": _percentile(lns_times, 0.95),
            "max": _percentile(lns_times, 1.00),
        },
        "lns_vs_two_opt_improvement_pct": {
            "median": _percentile(lns_vs_two_opt_improvements, 0.50),
            "best": _percentile(lns_vs_two_opt_improvements, 1.00),
        },
        "lns_vs_greedy_improvement_pct": {
            "median": _percentile(lns_vs_greedy_improvements, 0.50),
            "best": _percentile(lns_vs_greedy_improvements, 1.00),
        },
        "failures": failures,
    }


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    base_url = args.base_url.rstrip("/")
    output_dir = Path(args.output_dir)

    health = _http_json("GET", f"{base_url}/health", timeout_s=args.timeout_s)
    graph_stats = _http_json("GET", f"{base_url}/graph/stats", timeout_s=args.timeout_s)
    openapi = _http_json("GET", f"{base_url}/openapi.json", timeout_s=args.timeout_s)

    endpoint_available = False
    if openapi.get("ok") and isinstance(openapi.get("body"), dict):
        endpoint_available = "/vrp/compare/advanced" in openapi["body"].get("paths", {})

    raw_runs: list[dict[str, Any]] = []
    result_groups: dict[str, list[dict[str, Any]]] = {}

    for stop_count in args.sizes:
        group_key = f"{stop_count}_stops_{'return' if args.return_to_start else 'open'}"
        result_groups[group_key] = []

        for iteration in range(1, args.iterations + 1):
            seed = args.seed + stop_count * 100 + iteration

            payload = _build_payload(
                stop_count=stop_count,
                return_to_start=args.return_to_start,
                matrix_algorithm=args.matrix_algorithm,
                use_cache=args.use_cache,
                two_opt_max_iterations=args.two_opt_max_iterations,
                two_opt_improvement_tolerance_m=args.two_opt_improvement_tolerance_m,
                lns_max_iterations=args.lns_max_iterations,
                lns_destroy_fraction=args.lns_destroy_fraction,
                lns_no_improvement_limit=args.lns_no_improvement_limit,
                lns_random_seed=seed,
                keep_trace=args.keep_trace,
            )

            start = time.perf_counter()
            response = _http_json(
                "POST",
                f"{base_url}/vrp/compare/advanced",
                payload=payload,
                timeout_s=args.timeout_s,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000.0

            raw_record = {
                "stop_count": stop_count,
                "iteration": iteration,
                "seed": seed,
                "payload": payload,
                "response": response,
                "response_elapsed_ms": round(elapsed_ms, 3),
            }
            raw_runs.append(raw_record)

            if response.get("ok") and isinstance(response.get("body"), dict):
                metric = _extract_success_metrics(
                    body=response["body"],
                    response_elapsed_ms=elapsed_ms,
                    stop_count=stop_count,
                    iteration=iteration,
                    return_to_start=args.return_to_start,
                    seed=seed,
                )
            else:
                metric = {
                    "success": False,
                    "stop_count": stop_count,
                    "iteration": iteration,
                    "return_to_start": args.return_to_start,
                    "seed": seed,
                    "status_code": response.get("status_code"),
                    "error_body": response.get("body"),
                    "response_elapsed_ms": round(elapsed_ms, 3),
                }

            result_groups[group_key].append(metric)

            print(
                f"[{group_key}] iteration={iteration} "
                f"success={metric.get('success')} "
                f"elapsed_ms={metric.get('response_elapsed_ms')} "
                f"lns_non_regression={metric.get('lns_non_regression')}"
            )

    group_summaries = {
        group_key: _summarize_group(group_results)
        for group_key, group_results in result_groups.items()
    }

    successful_groups = [
        summary
        for summary in group_summaries.values()
        if summary["success_count"] > 0
    ]

    final_summary = {
        "phase": "tier3_phase8",
        "benchmark": "lns_advanced_compare",
        "created_at_utc": _utc_now_iso(),
        "mode": args.mode,
        "base_url": base_url,
        "endpoint": "/vrp/compare/advanced",
        "return_to_start": args.return_to_start,
        "matrix_algorithm": args.matrix_algorithm,
        "use_cache": args.use_cache,
        "keep_trace": args.keep_trace,
        "iterations_per_size": args.iterations,
        "sizes": args.sizes,
        "lns_settings": {
            "lns_max_iterations": args.lns_max_iterations,
            "lns_destroy_fraction": args.lns_destroy_fraction,
            "lns_no_improvement_limit": args.lns_no_improvement_limit,
            "seed_base": args.seed,
        },
        "two_opt_settings": {
            "two_opt_max_iterations": args.two_opt_max_iterations,
            "two_opt_improvement_tolerance_m": args.two_opt_improvement_tolerance_m,
        },
        "preflight": {
            "health_ok": bool(health.get("ok")),
            "health": health.get("body"),
            "graph_stats_ok": bool(graph_stats.get("ok")),
            "graph_stats": graph_stats.get("body"),
            "openapi_ok": bool(openapi.get("ok")),
            "advanced_endpoint_available": endpoint_available,
        },
        "group_summaries": group_summaries,
        "overall": {
            "group_count": len(group_summaries),
            "successful_group_count": len(successful_groups),
            "all_groups_have_success": len(successful_groups) == len(group_summaries),
            "all_successes_two_opt_non_regression": all(
                summary["all_two_opt_non_regression"] for summary in successful_groups
            )
            if successful_groups
            else False,
            "all_successes_lns_non_regression": all(
                summary["all_lns_non_regression"] for summary in successful_groups
            )
            if successful_groups
            else False,
        },
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "return" if args.return_to_start else "open"

    summary_path = output_dir / f"phase8_lns_benchmark_summary_{args.mode}_{suffix}_{timestamp}.json"
    raw_path = output_dir / f"phase8_lns_benchmark_raw_{args.mode}_{suffix}_{timestamp}.json"

    _write_json(summary_path, final_summary)
    _write_json(raw_path, raw_runs)

    print()
    print(f"Summary saved: {summary_path}")
    print(f"Raw runs saved: {raw_path}")

    return final_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 8 LNS benchmark for /vrp/compare/advanced"
    )

    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--mode", choices=["docker", "local"], default="docker")
    parser.add_argument("--output-dir", default="benchmarks/phase_8/docker_results")

    parser.add_argument("--sizes", nargs="+", type=int, default=[5, 10, 15, 24])
    parser.add_argument("--iterations", type=int, default=5)

    parser.add_argument("--matrix-algorithm", default="source_dijkstra")
    parser.add_argument("--use-cache", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--return-to-start",
        action=argparse.BooleanOptionalAction,
        default=False,
    )

    parser.add_argument("--two-opt-max-iterations", type=int, default=100)
    parser.add_argument("--two-opt-improvement-tolerance-m", type=float, default=0.001)

    parser.add_argument("--lns-max-iterations", type=int, default=500)
    parser.add_argument("--lns-destroy-fraction", type=float, default=0.30)
    parser.add_argument("--lns-no-improvement-limit", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)

    parser.add_argument("--keep-trace", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout-s", type=float, default=180.0)

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.mode == "local" and args.output_dir == "benchmarks/phase_8/docker_results":
        args.output_dir = "benchmarks/phase_8/local_results"

    try:
        summary = run_benchmark(args)
    except KeyboardInterrupt:
        print("Benchmark interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Benchmark failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    overall = summary["overall"]

    if not overall["all_groups_have_success"]:
        return 2

    if not overall["all_successes_two_opt_non_regression"]:
        return 3

    if not overall["all_successes_lns_non_regression"]:
        return 4

    return 0


if __name__ == "__main__":
    raise SystemExit(main())