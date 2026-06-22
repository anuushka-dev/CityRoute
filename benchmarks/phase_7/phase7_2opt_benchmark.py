# benchmarks/phase_7/phase7_2opt_benchmark.py

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URLS = {
    "local": "http://127.0.0.1:8000",
    "docker": "http://127.0.0.1:8001",
}

PHASE_DIR = Path("benchmarks") / "phase_7"
RESULT_DIRS = {
    "local": PHASE_DIR / "local_results",
    "docker": PHASE_DIR / "docker_results",
}

START_COORD = {
    "id": "depot",
    "lat": 26.4499,
    "lon": 80.3319,
}

STOP_COORDS = [
    {"id": "stop_00", "lat": 26.4600, "lon": 80.3400},
    {"id": "stop_01", "lat": 26.4550, "lon": 80.3250},
    {"id": "stop_02", "lat": 26.4650, "lon": 80.3500},
    {"id": "stop_03", "lat": 26.4700, "lon": 80.3600},
    {"id": "stop_04", "lat": 26.4750, "lon": 80.3450},
    {"id": "stop_05", "lat": 26.4400, "lon": 80.3200},
    {"id": "stop_06", "lat": 26.4350, "lon": 80.3350},
    {"id": "stop_07", "lat": 26.4305, "lon": 80.3500},
    {"id": "stop_08", "lat": 26.4450, "lon": 80.3600},
    {"id": "stop_09", "lat": 26.4550, "lon": 80.3700},
    {"id": "stop_10", "lat": 26.4620, "lon": 80.3220},
    {"id": "stop_11", "lat": 26.4680, "lon": 80.3150},
    {"id": "stop_12", "lat": 26.4780, "lon": 80.3280},
    {"id": "stop_13", "lat": 26.4820, "lon": 80.3380},
    {"id": "stop_14", "lat": 26.4880, "lon": 80.3520},
    {"id": "stop_15", "lat": 26.4920, "lon": 80.3650},
    {"id": "stop_16", "lat": 26.4380, "lon": 80.3650},

    # Corrected Phase 7 safe points.
    # All are inside bbox:
    # south=26.43, north=26.50, west=80.28, east=80.38
    {"id": "stop_17", "lat": 26.4320, "lon": 80.3420},
    {"id": "stop_18", "lat": 26.4340, "lon": 80.3300},
    {"id": "stop_19", "lat": 26.4360, "lon": 80.3150},

    {"id": "stop_20", "lat": 26.4420, "lon": 80.3050},
    {"id": "stop_21", "lat": 26.4560, "lon": 80.3000},
    {"id": "stop_22", "lat": 26.4720, "lon": 80.3050},
    {"id": "stop_23", "lat": 26.4860, "lon": 80.3180},
]


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def result_dir_for_mode(mode: str) -> Path:
    if mode not in RESULT_DIRS:
        raise ValueError(f"Unsupported mode: {mode}")

    output_dir = RESULT_DIRS[mode]
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None

    sorted_values = sorted(values)

    if len(sorted_values) == 1:
        return round(sorted_values[0], 3)

    rank = (len(sorted_values) - 1) * (pct / 100.0)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = rank - lower

    value = sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight
    return round(value, 3)


def summary_stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {
            "min": None,
            "mean": None,
            "median": None,
            "p95": None,
            "p99": None,
            "max": None,
        }

    return {
        "min": round(min(values), 3),
        "mean": round(statistics.mean(values), 3),
        "median": round(statistics.median(values), 3),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "max": round(max(values), 3),
    }


def request_json(
    *,
    url: str,
    method: str,
    payload: dict[str, Any] | None = None,
    timeout_s: int,
) -> tuple[int, dict[str, Any]]:
    data = None

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    request = Request(
        url=url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method=method,
    )

    try:
        with urlopen(request, timeout=timeout_s) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body)

    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"raw_body": body}

        return exc.code, parsed

    except URLError as exc:
        return 0, {
            "error": "URL error",
            "message": str(exc),
        }


def build_payload(
    *,
    stop_count: int,
    matrix_algorithm: str,
    use_cache: bool,
    return_to_start: bool,
    two_opt_max_iterations: int,
    improvement_tolerance_m: float,
    keep_trace: bool,
) -> dict[str, Any]:
    if stop_count < 1 or stop_count > 24:
        raise ValueError("stop_count must be between 1 and 24")

    return {
        "start": START_COORD,
        "stops": STOP_COORDS[:stop_count],
        "return_to_start": return_to_start,
        "matrix_algorithm": matrix_algorithm,
        "use_cache": use_cache,
        "two_opt_max_iterations": two_opt_max_iterations,
        "improvement_tolerance_m": improvement_tolerance_m,
        "keep_trace": keep_trace,
    }


def is_order_valid(order: Any, stop_count: int) -> bool:
    return isinstance(order, list) and sorted(order) == list(range(stop_count))


def expected_leg_count(stop_count: int, return_to_start: bool) -> int:
    return stop_count + 1 if return_to_start else stop_count


def record_from_response(
    *,
    status_code: int,
    body: dict[str, Any],
    api_elapsed_ms: float,
    stop_count: int,
    return_to_start: bool,
    iteration: int,
) -> dict[str, Any]:
    base_record = {
        "iteration": iteration,
        "status_code": status_code,
        "api_elapsed_ms": round(api_elapsed_ms, 3),
    }

    if status_code != 200:
        return {
            **base_record,
            "ok": False,
            "error_body": body,
        }

    greedy = body.get("greedy", {})
    two_opt = body.get("two_opt", {})
    improvement = body.get("improvement", {})

    greedy_order = greedy.get("optimized_order")
    two_opt_order = two_opt.get("optimized_order")

    greedy_legs = greedy.get("legs", [])
    two_opt_legs = two_opt.get("legs", [])

    expected_legs = expected_leg_count(stop_count, return_to_start)

    return {
        **base_record,
        "ok": True,
        "response": body,
        "stop_count": stop_count,
        "return_to_start": return_to_start,
        "expected_leg_count": expected_legs,
        "greedy_order_valid": is_order_valid(greedy_order, stop_count),
        "two_opt_order_valid": is_order_valid(two_opt_order, stop_count),
        "greedy_leg_count_valid": len(greedy_legs) == expected_legs,
        "two_opt_leg_count_valid": len(two_opt_legs) == expected_legs,
        "non_regression": bool(improvement.get("non_regression", False)),
        "greedy_distance_m": greedy.get("total_distance_m"),
        "two_opt_distance_m": two_opt.get("total_distance_m"),
        "distance_saved_m": improvement.get("distance_saved_m"),
        "improvement_pct": improvement.get("improvement_pct"),
        "greedy_optimization_time_ms": greedy.get("optimization_time_ms"),
        "two_opt_optimization_time_ms": two_opt.get("optimization_time_ms"),
        "two_opt_iterations": two_opt.get("iterations"),
        "two_opt_swaps_applied": two_opt.get("swaps_applied"),
        "two_opt_converged": two_opt.get("converged"),
        "matrix_generation_time_ms": body.get("matrix_generation_time_ms"),
        "response_total_time_ms": body.get("total_time_ms"),
        "cache_used": body.get("cache_used"),
        "cache_hits": body.get("cache_hits"),
        "cache_misses": body.get("cache_misses"),
    }


def extract_success_values(records: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []

    for record in records:
        if not record.get("ok"):
            continue

        value = record.get(key)

        if isinstance(value, (int, float)):
            values.append(float(value))

    return values


def run_size_benchmark(
    *,
    mode: str,
    base_url: str,
    output_dir: Path,
    stop_count: int,
    iterations: int,
    matrix_algorithm: str,
    use_cache: bool,
    return_to_start: bool,
    two_opt_max_iterations: int,
    improvement_tolerance_m: float,
    keep_trace: bool,
    timeout_s: int,
) -> dict[str, Any]:
    endpoint = "/vrp/compare"
    url = f"{base_url}{endpoint}"
    route_mode = "return_to_start" if return_to_start else "open"

    records: list[dict[str, Any]] = []

    for iteration in range(1, iterations + 1):
        payload = build_payload(
            stop_count=stop_count,
            matrix_algorithm=matrix_algorithm,
            use_cache=use_cache,
            return_to_start=return_to_start,
            two_opt_max_iterations=two_opt_max_iterations,
            improvement_tolerance_m=improvement_tolerance_m,
            keep_trace=keep_trace,
        )

        started_at = time.perf_counter()
        status_code, body = request_json(
            url=url,
            method="POST",
            payload=payload,
            timeout_s=timeout_s,
        )
        api_elapsed_ms = (time.perf_counter() - started_at) * 1000.0

        records.append(
            record_from_response(
                status_code=status_code,
                body=body,
                api_elapsed_ms=api_elapsed_ms,
                stop_count=stop_count,
                return_to_start=return_to_start,
                iteration=iteration,
            )
        )

    success_records = [record for record in records if record.get("ok")]
    failure_records = [record for record in records if not record.get("ok")]

    result = {
        "benchmark": "phase7_2opt_benchmark",
        "phase": "tier2_phase7",
        "mode": mode,
        "result_group": mode,
        "route_mode": route_mode,
        "base_url": base_url,
        "endpoint": endpoint,
        "created_at_utc": now_utc_iso(),
        "stop_count": stop_count,
        "iterations": iterations,
        "matrix_algorithm": matrix_algorithm,
        "use_cache": use_cache,
        "return_to_start": return_to_start,
        "two_opt_max_iterations": two_opt_max_iterations,
        "improvement_tolerance_m": improvement_tolerance_m,
        "keep_trace": keep_trace,
        "success_count": len(success_records),
        "failure_count": len(failure_records),
        "success_rate_pct": round((len(success_records) / iterations) * 100.0, 3),
        "expected_leg_count": expected_leg_count(stop_count, return_to_start),
        "all_greedy_orders_valid": all(
            record.get("greedy_order_valid") for record in success_records
        )
        if success_records
        else False,
        "all_two_opt_orders_valid": all(
            record.get("two_opt_order_valid") for record in success_records
        )
        if success_records
        else False,
        "all_greedy_leg_counts_valid": all(
            record.get("greedy_leg_count_valid") for record in success_records
        )
        if success_records
        else False,
        "all_two_opt_leg_counts_valid": all(
            record.get("two_opt_leg_count_valid") for record in success_records
        )
        if success_records
        else False,
        "all_non_regression": all(
            record.get("non_regression") for record in success_records
        )
        if success_records
        else False,
        "api_elapsed_ms": summary_stats(extract_success_values(records, "api_elapsed_ms")),
        "matrix_generation_time_ms": summary_stats(
            extract_success_values(records, "matrix_generation_time_ms")
        ),
        "greedy_optimization_time_ms": summary_stats(
            extract_success_values(records, "greedy_optimization_time_ms")
        ),
        "two_opt_optimization_time_ms": summary_stats(
            extract_success_values(records, "two_opt_optimization_time_ms")
        ),
        "response_total_time_ms": summary_stats(
            extract_success_values(records, "response_total_time_ms")
        ),
        "greedy_distance_m": summary_stats(
            extract_success_values(records, "greedy_distance_m")
        ),
        "two_opt_distance_m": summary_stats(
            extract_success_values(records, "two_opt_distance_m")
        ),
        "distance_saved_m": summary_stats(
            extract_success_values(records, "distance_saved_m")
        ),
        "improvement_pct": summary_stats(
            extract_success_values(records, "improvement_pct")
        ),
        "two_opt_iterations": summary_stats(
            extract_success_values(records, "two_opt_iterations")
        ),
        "two_opt_swaps_applied": summary_stats(
            extract_success_values(records, "two_opt_swaps_applied")
        ),
        "first_failure": failure_records[0] if failure_records else None,
        "records": records,
    }

    output_file = output_dir / f"phase7_2opt_benchmark_{stop_count}_stops_{route_mode}.json"

    output_file.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    result["saved_file"] = str(output_file)

    return result


def parse_sizes(raw: str) -> list[int]:
    sizes: list[int] = []

    for value in raw.split(","):
        value = value.strip()

        if not value:
            continue

        size = int(value)

        if size < 1 or size > 24:
            raise argparse.ArgumentTypeError("All sizes must be between 1 and 24")

        sizes.append(size)

    if not sizes:
        raise argparse.ArgumentTypeError("At least one size is required")

    return sizes


def save_summary(
    *,
    output_dir: Path,
    mode: str,
    base_url: str,
    sizes: list[int],
    iterations: int,
    matrix_algorithm: str,
    use_cache: bool,
    return_to_start: bool,
    results: list[dict[str, Any]],
) -> Path:
    route_mode = "return_to_start" if return_to_start else "open"

    summary = {
        "benchmark": "phase7_2opt_benchmark_summary",
        "phase": "tier2_phase7",
        "mode": mode,
        "result_group": mode,
        "route_mode": route_mode,
        "base_url": base_url,
        "created_at_utc": now_utc_iso(),
        "sizes": sizes,
        "iterations": iterations,
        "matrix_algorithm": matrix_algorithm,
        "use_cache": use_cache,
        "return_to_start": return_to_start,
        "output_directory": str(output_dir),
        "results": [
            {
                "stop_count": result["stop_count"],
                "success_count": result["success_count"],
                "failure_count": result["failure_count"],
                "success_rate_pct": result["success_rate_pct"],
                "all_greedy_orders_valid": result["all_greedy_orders_valid"],
                "all_two_opt_orders_valid": result["all_two_opt_orders_valid"],
                "all_greedy_leg_counts_valid": result["all_greedy_leg_counts_valid"],
                "all_two_opt_leg_counts_valid": result["all_two_opt_leg_counts_valid"],
                "all_non_regression": result["all_non_regression"],
                "api_median_ms": result["api_elapsed_ms"]["median"],
                "matrix_median_ms": result["matrix_generation_time_ms"]["median"],
                "greedy_median_ms": result["greedy_optimization_time_ms"]["median"],
                "two_opt_median_ms": result["two_opt_optimization_time_ms"]["median"],
                "greedy_distance_median_m": result["greedy_distance_m"]["median"],
                "two_opt_distance_median_m": result["two_opt_distance_m"]["median"],
                "distance_saved_median_m": result["distance_saved_m"]["median"],
                "improvement_pct_median": result["improvement_pct"]["median"],
            }
            for result in results
        ],
    }

    summary_file = output_dir / f"phase7_2opt_benchmark_{route_mode}_summary.json"

    summary_file.write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    return summary_file


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tier 2 Phase 7 benchmark for /vrp/compare Greedy vs 2-Opt."
    )

    parser.add_argument("--mode", choices=["local", "docker"], required=True)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--sizes", default="5,10,15,24")
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument(
        "--matrix-algorithm",
        choices=["source_dijkstra", "bidirectional_astar"],
        default="source_dijkstra",
    )
    parser.add_argument("--use-cache", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--return-to-start", action="store_true")
    parser.add_argument("--two-opt-max-iterations", type=int, default=100)
    parser.add_argument("--improvement-tolerance-m", type=float, default=0.001)
    parser.add_argument("--no-trace", action="store_true")
    parser.add_argument("--timeout-s", type=int, default=60)

    args = parser.parse_args()

    if args.iterations <= 0:
        raise SystemExit("--iterations must be greater than 0")

    if args.two_opt_max_iterations <= 0:
        raise SystemExit("--two-opt-max-iterations must be greater than 0")

    if args.improvement_tolerance_m < 0:
        raise SystemExit("--improvement-tolerance-m must be non-negative")

    mode = args.mode
    base_url = args.base_url or BASE_URLS[mode]
    output_dir = result_dir_for_mode(mode)
    sizes = parse_sizes(args.sizes)

    use_cache = args.use_cache and not args.no_cache

    print(f"Mode: {mode}")
    print(f"Base URL: {base_url}")
    print(f"Output directory: {output_dir}")

    health_status, health_body = request_json(
        url=f"{base_url}/health",
        method="GET",
        timeout_s=args.timeout_s,
    )

    print(f"Health status code: {health_status}")
    print(f"Health body: {json.dumps(health_body)}")

    if health_status != 200 or not health_body.get("graph_loaded", False):
        print("ERROR: API health check failed or graph_loaded is false.")
        return 1

    results: list[dict[str, Any]] = []

    for stop_count in sizes:
        print(
            "Running Phase 7 benchmark | "
            f"mode={mode} | stops={stop_count} | iterations={args.iterations} | "
            f"matrix_algorithm={args.matrix_algorithm} | cache={use_cache} | "
            f"return_to_start={args.return_to_start}"
        )

        result = run_size_benchmark(
            mode=mode,
            base_url=base_url,
            output_dir=output_dir,
            stop_count=stop_count,
            iterations=args.iterations,
            matrix_algorithm=args.matrix_algorithm,
            use_cache=use_cache,
            return_to_start=args.return_to_start,
            two_opt_max_iterations=args.two_opt_max_iterations,
            improvement_tolerance_m=args.improvement_tolerance_m,
            keep_trace=not args.no_trace,
            timeout_s=args.timeout_s,
        )

        results.append(result)

        print(
            f"saved={result['saved_file']} | "
            f"success={result['success_count']}/{result['iterations']} | "
            f"orders_valid={result['all_two_opt_orders_valid']} | "
            f"legs_valid={result['all_two_opt_leg_counts_valid']} | "
            f"non_regression={result['all_non_regression']} | "
            f"api_median={result['api_elapsed_ms']['median']} ms | "
            f"two_opt_median={result['two_opt_optimization_time_ms']['median']} ms | "
            f"improvement_pct_median={result['improvement_pct']['median']}"
        )

    summary_file = save_summary(
        output_dir=output_dir,
        mode=mode,
        base_url=base_url,
        sizes=sizes,
        iterations=args.iterations,
        matrix_algorithm=args.matrix_algorithm,
        use_cache=use_cache,
        return_to_start=args.return_to_start,
        results=results,
    )

    print(f"summary_saved={summary_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())