# benchmarks/phase_6/phase6_greedy_benchmark.py

from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import requests


LOCAL_BASE_URL = "http://127.0.0.1:8000"
DOCKER_BASE_URL = "http://127.0.0.1:8001"

RESULTS_ROOT = Path("benchmarks") / "phase_6"
LOCAL_RESULTS_DIR = RESULTS_ROOT / "local_results"
DOCKER_RESULTS_DIR = RESULTS_ROOT / "docker_results"


START = {"lat": 26.44, "lon": 80.30}

STOPS = [
    {"lat": 26.4500, "lon": 80.3500},
    {"lat": 26.4550, "lon": 80.3450},
    {"lat": 26.4600, "lon": 80.3400},
    {"lat": 26.4650, "lon": 80.3350},
    {"lat": 26.4700, "lon": 80.3300},
    {"lat": 26.4750, "lon": 80.3250},
    {"lat": 26.4800, "lon": 80.3200},
    {"lat": 26.4850, "lon": 80.3150},
    {"lat": 26.4900, "lon": 80.3100},
    {"lat": 26.4950, "lon": 80.3050},
    {"lat": 26.4520, "lon": 80.3550},
    {"lat": 26.4570, "lon": 80.3520},
    {"lat": 26.4620, "lon": 80.3480},
    {"lat": 26.4670, "lon": 80.3440},
    {"lat": 26.4720, "lon": 80.3380},
    {"lat": 26.4770, "lon": 80.3320},
    {"lat": 26.4820, "lon": 80.3260},
    {"lat": 26.4870, "lon": 80.3180},
    {"lat": 26.4920, "lon": 80.3120},
    {"lat": 26.4970, "lon": 80.3060},
    {"lat": 26.4480, "lon": 80.3600},
    {"lat": 26.4530, "lon": 80.3650},
    {"lat": 26.4580, "lon": 80.3700},
    {"lat": 26.4630, "lon": 80.3750},
]


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0

    values = sorted(values)
    index = (len(values) - 1) * pct
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)

    if lower == upper:
        return round(values[lower], 3)

    weight = index - lower
    return round(values[lower] * (1 - weight) + values[upper] * weight, 3)


def summarize(values: list[float]) -> dict[str, float]:
    if not values:
        return {
            "min": 0.0,
            "mean": 0.0,
            "median": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "max": 0.0,
        }

    return {
        "min": round(min(values), 3),
        "mean": round(statistics.mean(values), 3),
        "median": round(statistics.median(values), 3),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": round(max(values), 3),
    }


def parse_sizes(raw: str) -> list[int]:
    sizes = [int(item.strip()) for item in raw.split(",") if item.strip()]

    if not sizes:
        raise ValueError("At least one stop count is required.")

    for size in sizes:
        if size < 1:
            raise ValueError("Stop count must be at least 1.")

        if size > len(STOPS):
            raise ValueError(
                f"Stop count {size} exceeds available benchmark stops {len(STOPS)}."
            )

    return sizes


def base_url_for_mode(mode: str) -> str:
    if mode == "local":
        return LOCAL_BASE_URL

    if mode == "docker":
        return DOCKER_BASE_URL

    raise ValueError(f"Unsupported mode: {mode}")


def results_dir_for_mode(mode: str) -> Path:
    if mode == "local":
        return LOCAL_RESULTS_DIR

    if mode == "docker":
        return DOCKER_RESULTS_DIR

    raise ValueError(f"Unsupported mode: {mode}")


def build_payload(
    *,
    stop_count: int,
    matrix_algorithm: str,
    use_cache: bool,
    return_to_start: bool,
) -> dict[str, Any]:
    return {
        "start": START,
        "stops": STOPS[:stop_count],
        "return_to_start": return_to_start,
        "matrix_algorithm": matrix_algorithm,
        "use_cache": use_cache,
    }


def run_one(
    *,
    base_url: str,
    payload: dict[str, Any],
    timeout_s: int,
) -> dict[str, Any]:
    started_at = perf_counter()

    response = requests.post(
        f"{base_url}/vrp/greedy",
        json=payload,
        timeout=timeout_s,
    )

    api_elapsed_ms = round((perf_counter() - started_at) * 1000, 3)

    try:
        body = response.json()
    except Exception:
        body = {"raw_text": response.text[:1000]}

    record: dict[str, Any] = {
        "ok": response.status_code == 200,
        "status_code": response.status_code,
        "api_elapsed_ms": api_elapsed_ms,
        "response": body,
    }

    if response.status_code == 200:
        optimized_order = body.get("optimized_order", [])
        stop_count = body.get("stop_count", 0)
        return_to_start = body.get("return_to_start", False)
        expected_leg_count = stop_count + 1 if return_to_start else stop_count

        record.update(
            {
                "stop_count": stop_count,
                "expected_leg_count": expected_leg_count,
                "optimized_order_valid": sorted(optimized_order) == list(range(stop_count)),
                "leg_count": len(body.get("legs", [])),
                "leg_count_valid": len(body.get("legs", [])) == expected_leg_count,
                "total_distance_m": body.get("total_distance_m"),
                "matrix_generation_time_ms": body.get("matrix_generation_time_ms"),
                "optimization_time_ms": body.get("optimization_time_ms"),
                "total_time_ms": body.get("total_time_ms"),
                "cache_used": body.get("cache_used"),
            }
        )
    else:
        record["error"] = body

    return record


def run_size(
    *,
    base_url: str,
    mode: str,
    stop_count: int,
    iterations: int,
    matrix_algorithm: str,
    use_cache: bool,
    return_to_start: bool,
    timeout_s: int,
) -> dict[str, Any]:
    payload = build_payload(
        stop_count=stop_count,
        matrix_algorithm=matrix_algorithm,
        use_cache=use_cache,
        return_to_start=return_to_start,
    )

    records = [
        run_one(
            base_url=base_url,
            payload=payload,
            timeout_s=timeout_s,
        )
        for _ in range(iterations)
    ]

    successful = [record for record in records if record["ok"]]
    failed = [record for record in records if not record["ok"]]

    expected_leg_count = stop_count + 1 if return_to_start else stop_count
    route_mode = "return_to_start" if return_to_start else "open"

    cache_hit_count = sum(
        1 for record in successful if record.get("cache_used") is True
    )

    cache_miss_count = sum(
        1 for record in successful if record.get("cache_used") is False
    )

    result = {
        "benchmark": "phase6_greedy_benchmark",
        "phase": "tier2_phase6",
        "mode": mode,
        "route_mode": route_mode,
        "base_url": base_url,
        "endpoint": "/vrp/greedy",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "stop_count": stop_count,
        "iterations": iterations,
        "matrix_algorithm": matrix_algorithm,
        "use_cache": use_cache,
        "return_to_start": return_to_start,
        "success_count": len(successful),
        "failure_count": len(failed),
        "success_rate_pct": round((len(successful) / iterations) * 100, 3),
        "expected_leg_count": expected_leg_count,
        "all_orders_valid": all(
            record.get("optimized_order_valid") is True for record in successful
        ),
        "all_leg_counts_valid": all(
            record.get("leg_count") == expected_leg_count for record in successful
        ),
        "cache_hit_count": cache_hit_count,
        "cache_miss_count": cache_miss_count,
        "api_elapsed_ms": summarize(
            [float(record["api_elapsed_ms"]) for record in successful]
        ),
        "matrix_generation_time_ms": summarize(
            [
                float(record["matrix_generation_time_ms"])
                for record in successful
                if record.get("matrix_generation_time_ms") is not None
            ]
        ),
        "optimization_time_ms": summarize(
            [
                float(record["optimization_time_ms"])
                for record in successful
                if record.get("optimization_time_ms") is not None
            ]
        ),
        "response_total_time_ms": summarize(
            [
                float(record["total_time_ms"])
                for record in successful
                if record.get("total_time_ms") is not None
            ]
        ),
        "total_distance_m": summarize(
            [
                float(record["total_distance_m"])
                for record in successful
                if record.get("total_distance_m") is not None
            ]
        ),
        "first_failure": failed[0] if failed else None,
        "records": records,
    }

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Tier 2 Phase 6 greedy VRP benchmark.")

    parser.add_argument("--mode", choices=["local", "docker"], required=True)
    parser.add_argument("--sizes", default="5,10,15,24")
    parser.add_argument("--iterations", type=int, default=5)

    parser.add_argument(
        "--matrix-algorithm",
        choices=["bidirectional_astar", "source_dijkstra"],
        default="bidirectional_astar",
    )

    parser.add_argument("--use-cache", action="store_true")
    parser.add_argument("--return-to-start", action="store_true")
    parser.add_argument("--timeout", type=int, default=180)

    args = parser.parse_args()

    if args.iterations < 1:
        raise ValueError("Iterations must be at least 1.")

    base_url = base_url_for_mode(args.mode)
    results_dir = results_dir_for_mode(args.mode)
    results_dir.mkdir(parents=True, exist_ok=True)

    print(f"Checking health: {base_url}/health")
    health_response = requests.get(f"{base_url}/health", timeout=30)

    print(f"Health status code: {health_response.status_code}")
    print(f"Health body: {health_response.text}")

    health_response.raise_for_status()

    health_body = health_response.json()

    if not health_body.get("graph_loaded"):
        raise RuntimeError("Graph is not loaded. Benchmark cannot run.")

    sizes = parse_sizes(args.sizes)
    route_mode = "return_to_start" if args.return_to_start else "open"

    for stop_count in sizes:
        print(
            f"Running Phase 6 greedy | mode={args.mode} | "
            f"route_mode={route_mode} | "
            f"stops={stop_count} | iterations={args.iterations} | "
            f"algorithm={args.matrix_algorithm}"
        )

        result = run_size(
            base_url=base_url,
            mode=args.mode,
            stop_count=stop_count,
            iterations=args.iterations,
            matrix_algorithm=args.matrix_algorithm,
            use_cache=args.use_cache,
            return_to_start=args.return_to_start,
            timeout_s=args.timeout,
        )

        output_path = results_dir / (
            f"phase6_greedy_benchmark_{stop_count}_stops_{route_mode}.json"
        )

        output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

        print(
            f"saved={output_path} | "
            f"success={result['success_count']}/{result['iterations']} | "
            f"orders_valid={result['all_orders_valid']} | "
            f"legs_valid={result['all_leg_counts_valid']} | "
            f"cache_hits={result['cache_hit_count']} | "
            f"cache_misses={result['cache_miss_count']} | "
            f"api_median={result['api_elapsed_ms']['median']} ms | "
            f"matrix_median={result['matrix_generation_time_ms']['median']} ms | "
            f"greedy_median={result['optimization_time_ms']['median']} ms"
        )

        if result["failure_count"] > 0:
            print("FIRST FAILURE:")
            print(json.dumps(result["first_failure"], indent=2))


if __name__ == "__main__":
    main()