# benchmarks/phase_6/phase6_greedy_edge_cases.py

from __future__ import annotations

import argparse
import json
import random
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

SAFE_STOPS = [
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


NEAR_DUPLICATE_STOPS = [
    {"lat": 26.45000, "lon": 80.35000},
    {"lat": 26.45002, "lon": 80.35002},
    {"lat": 26.45004, "lon": 80.35004},
    {"lat": 26.45500, "lon": 80.34500},
    {"lat": 26.45502, "lon": 80.34502},
    {"lat": 26.46000, "lon": 80.34000},
    {"lat": 26.46003, "lon": 80.34003},
    {"lat": 26.46500, "lon": 80.33500},
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


def seeded_sample(seed: int, count: int) -> list[dict[str, float]]:
    rng = random.Random(seed)
    return rng.sample(SAFE_STOPS, count)


def build_cases() -> list[dict[str, Any]]:
    return [
        {
            "case_name": "clustered_8",
            "description": "Eight stops in a compact nearby cluster.",
            "seed": None,
            "return_to_start": False,
            "stops": SAFE_STOPS[0:8],
        },
        {
            "case_name": "spread_out_10",
            "description": "Ten stops selected from wider ends of the known benchmark area.",
            "seed": None,
            "return_to_start": False,
            "stops": [
                SAFE_STOPS[0],
                SAFE_STOPS[4],
                SAFE_STOPS[9],
                SAFE_STOPS[10],
                SAFE_STOPS[14],
                SAFE_STOPS[19],
                SAFE_STOPS[20],
                SAFE_STOPS[21],
                SAFE_STOPS[22],
                SAFE_STOPS[23],
            ],
        },
        {
            "case_name": "near_duplicate_8",
            "description": "Near-duplicate coordinates to test snapping and valid route construction.",
            "seed": None,
            "return_to_start": False,
            "stops": NEAR_DUPLICATE_STOPS,
        },
        {
            "case_name": "seeded_random_42_12",
            "description": "Seeded random 12-stop sample from safe benchmark points.",
            "seed": 42,
            "return_to_start": False,
            "stops": seeded_sample(seed=42, count=12),
        },
        {
            "case_name": "seeded_random_123_12",
            "description": "Second deterministic random 12-stop sample from safe benchmark points.",
            "seed": 123,
            "return_to_start": False,
            "stops": seeded_sample(seed=123, count=12),
        },
        {
            "case_name": "zigzag_order_16",
            "description": "Alternating near/far input order to show greedy remains valid even with awkward ordering.",
            "seed": None,
            "return_to_start": False,
            "stops": [
                SAFE_STOPS[0],
                SAFE_STOPS[23],
                SAFE_STOPS[1],
                SAFE_STOPS[22],
                SAFE_STOPS[2],
                SAFE_STOPS[21],
                SAFE_STOPS[3],
                SAFE_STOPS[20],
                SAFE_STOPS[4],
                SAFE_STOPS[19],
                SAFE_STOPS[5],
                SAFE_STOPS[18],
                SAFE_STOPS[6],
                SAFE_STOPS[17],
                SAFE_STOPS[7],
                SAFE_STOPS[16],
            ],
        },
        {
            "case_name": "return_to_start_seeded_42_12",
            "description": "Seeded random 12-stop sample with depot return enabled.",
            "seed": 42,
            "return_to_start": True,
            "stops": seeded_sample(seed=42, count=12),
        },
    ]


def check_health(base_url: str, timeout_s: int) -> None:
    health_url = f"{base_url}/health"

    print(f"Checking health: {health_url}")

    response = requests.get(health_url, timeout=timeout_s)

    print(f"Health status code: {response.status_code}")
    print(f"Health body: {response.text}")

    response.raise_for_status()

    body = response.json()

    if not body.get("graph_loaded"):
        raise RuntimeError("Graph is not loaded. Benchmark cannot run.")


def build_payload(
    *,
    stops: list[dict[str, float]],
    matrix_algorithm: str,
    use_cache: bool,
    return_to_start: bool,
) -> dict[str, Any]:
    return {
        "start": START,
        "stops": stops,
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

    try:
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
            stop_count = len(payload["stops"])
            expected_leg_count = (
                stop_count + 1 if payload["return_to_start"] else stop_count
            )

            optimized_order = body.get("optimized_order", [])
            legs = body.get("legs", [])

            record.update(
                {
                    "stop_count": stop_count,
                    "expected_leg_count": expected_leg_count,
                    "optimized_order_valid": sorted(optimized_order)
                    == list(range(stop_count)),
                    "leg_count": len(legs),
                    "leg_count_valid": len(legs) == expected_leg_count,
                    "last_leg_returns_to_start": (
                        legs[-1].get("to_type") == "start"
                        if payload["return_to_start"] and legs
                        else None
                    ),
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

    except Exception as exc:
        api_elapsed_ms = round((perf_counter() - started_at) * 1000, 3)

        return {
            "ok": False,
            "status_code": None,
            "api_elapsed_ms": api_elapsed_ms,
            "response": None,
            "error": str(exc),
        }


def summarize_case(
    *,
    case: dict[str, Any],
    records: list[dict[str, Any]],
    iterations: int,
) -> dict[str, Any]:
    successful = [record for record in records if record.get("ok")]
    failed = [record for record in records if not record.get("ok")]

    stop_count = len(case["stops"])
    expected_leg_count = stop_count + 1 if case["return_to_start"] else stop_count

    cache_hit_count = sum(
        1 for record in successful if record.get("cache_used") is True
    )

    cache_miss_count = sum(
        1 for record in successful if record.get("cache_used") is False
    )

    all_orders_valid = all(
        record.get("optimized_order_valid") is True for record in successful
    )

    all_leg_counts_valid = all(
        record.get("leg_count") == expected_leg_count for record in successful
    )

    if case["return_to_start"]:
        all_return_legs_valid = all(
            record.get("last_leg_returns_to_start") is True for record in successful
        )
    else:
        all_return_legs_valid = None

    return {
        "case_name": case["case_name"],
        "description": case["description"],
        "seed": case["seed"],
        "stop_count": stop_count,
        "return_to_start": case["return_to_start"],
        "expected_leg_count": expected_leg_count,
        "success_count": len(successful),
        "failure_count": len(failed),
        "success_rate_pct": round((len(successful) / iterations) * 100, 3),
        "all_orders_valid": all_orders_valid,
        "all_leg_counts_valid": all_leg_counts_valid,
        "all_return_legs_valid": all_return_legs_valid,
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tier 2 Phase 6 greedy VRP edge-case benchmark.",
    )

    parser.add_argument("--mode", choices=["local", "docker"], required=True)
    parser.add_argument("--iterations", type=int, default=5)

    parser.add_argument(
        "--matrix-algorithm",
        choices=["bidirectional_astar", "source_dijkstra"],
        default="bidirectional_astar",
    )

    parser.add_argument("--use-cache", action="store_true")
    parser.add_argument("--timeout", type=int, default=180)

    args = parser.parse_args()

    if args.iterations < 1:
        raise ValueError("Iterations must be at least 1.")

    base_url = base_url_for_mode(args.mode)
    results_dir = results_dir_for_mode(args.mode)
    results_dir.mkdir(parents=True, exist_ok=True)

    check_health(base_url=base_url, timeout_s=args.timeout)

    cases = build_cases()
    case_summaries = []

    for case in cases:
        print(
            f"Running edge case | mode={args.mode} | "
            f"case={case['case_name']} | "
            f"stops={len(case['stops'])} | "
            f"return_to_start={case['return_to_start']} | "
            f"iterations={args.iterations}"
        )

        payload = build_payload(
            stops=case["stops"],
            matrix_algorithm=args.matrix_algorithm,
            use_cache=args.use_cache,
            return_to_start=case["return_to_start"],
        )

        records = [
            run_one(
                base_url=base_url,
                payload=payload,
                timeout_s=args.timeout,
            )
            for _ in range(args.iterations)
        ]

        case_summary = summarize_case(
            case=case,
            records=records,
            iterations=args.iterations,
        )

        case_summaries.append(case_summary)

        print(
            f"case={case_summary['case_name']} | "
            f"success={case_summary['success_count']}/{args.iterations} | "
            f"orders_valid={case_summary['all_orders_valid']} | "
            f"legs_valid={case_summary['all_leg_counts_valid']} | "
            f"return_leg_valid={case_summary['all_return_legs_valid']} | "
            f"cache_hits={case_summary['cache_hit_count']} | "
            f"cache_misses={case_summary['cache_miss_count']} | "
            f"api_median={case_summary['api_elapsed_ms']['median']} ms | "
            f"matrix_median={case_summary['matrix_generation_time_ms']['median']} ms | "
            f"greedy_median={case_summary['optimization_time_ms']['median']} ms"
        )

        if case_summary["first_failure"] is not None:
            print("FIRST FAILURE:")
            print(json.dumps(case_summary["first_failure"], indent=2))

    all_cases_passed = all(
        case["success_count"] == args.iterations
        and case["all_orders_valid"]
        and case["all_leg_counts_valid"]
        and (
            case["all_return_legs_valid"] is True
            if case["return_to_start"]
            else True
        )
        for case in case_summaries
    )

    output = {
        "benchmark": "phase6_greedy_edge_cases",
        "phase": "tier2_phase6_1",
        "mode": args.mode,
        "base_url": base_url,
        "endpoint": "/vrp/greedy",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "iterations_per_case": args.iterations,
        "matrix_algorithm": args.matrix_algorithm,
        "use_cache": args.use_cache,
        "case_count": len(case_summaries),
        "all_cases_passed": all_cases_passed,
        "cases": case_summaries,
    }

    output_path = results_dir / f"phase6_greedy_edge_cases_{args.mode}.json"

    output_path.write_text(
        json.dumps(output, indent=2),
        encoding="utf-8",
    )

    print(f"saved={output_path}")
    print(f"all_cases_passed={all_cases_passed}")

    if not all_cases_passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()