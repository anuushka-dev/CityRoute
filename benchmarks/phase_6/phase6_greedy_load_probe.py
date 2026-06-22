# benchmarks/phase_6/phase6_greedy_load_probe.py

from __future__ import annotations

import argparse
import json
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def check_health(base_url: str, timeout_s: int) -> None:
    health_url = f"{base_url}/health"

    print(f"Checking health: {health_url}")

    response = requests.get(health_url, timeout=timeout_s)

    print(f"Health status code: {response.status_code}")
    print(f"Health body: {response.text}")

    response.raise_for_status()

    body = response.json()

    if not body.get("graph_loaded"):
        raise RuntimeError("Graph is not loaded. Load probe cannot run.")


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


def run_one_request(
    *,
    base_url: str,
    payload: dict[str, Any],
    timeout_s: int,
    request_index: int,
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
            "request_index": request_index,
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
            "request_index": request_index,
            "ok": False,
            "status_code": None,
            "api_elapsed_ms": api_elapsed_ms,
            "response": None,
            "error": str(exc),
        }


def run_invalid_limit_probe(
    *,
    base_url: str,
    matrix_algorithm: str,
    use_cache: bool,
    timeout_s: int,
) -> dict[str, Any]:
    invalid_stops = STOPS + [{"lat": 26.4680, "lon": 80.3800}]

    payload = {
        "start": START,
        "stops": invalid_stops,
        "return_to_start": False,
        "matrix_algorithm": matrix_algorithm,
        "use_cache": use_cache,
    }

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

    return {
        "case": "invalid_25_stops",
        "stop_count": len(invalid_stops),
        "expected_status_code": 422,
        "actual_status_code": response.status_code,
        "passed": response.status_code == 422,
        "api_elapsed_ms": api_elapsed_ms,
        "response": body,
    }


def summarize_load_probe(
    *,
    records: list[dict[str, Any]],
    mode: str,
    base_url: str,
    stop_count: int,
    total_requests: int,
    workers: int,
    matrix_algorithm: str,
    use_cache: bool,
    return_to_start: bool,
    invalid_limit_probe: dict[str, Any],
) -> dict[str, Any]:
    successful = [record for record in records if record.get("ok")]
    failed = [record for record in records if not record.get("ok")]

    expected_leg_count = stop_count + 1 if return_to_start else stop_count

    all_orders_valid = all(
        record.get("optimized_order_valid") is True for record in successful
    )

    all_leg_counts_valid = all(
        record.get("leg_count") == expected_leg_count for record in successful
    )

    cache_hit_count = sum(
        1 for record in successful if record.get("cache_used") is True
    )

    cache_miss_count = sum(
        1 for record in successful if record.get("cache_used") is False
    )

    load_probe_passed = (
        len(successful) == total_requests
        and len(failed) == 0
        and all_orders_valid
        and all_leg_counts_valid
        and invalid_limit_probe["passed"]
    )

    return {
        "benchmark": "phase6_greedy_load_probe",
        "phase": "tier2_phase6_1",
        "mode": mode,
        "base_url": base_url,
        "endpoint": "/vrp/greedy",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "stop_count": stop_count,
        "return_to_start": return_to_start,
        "total_requests": total_requests,
        "workers": workers,
        "matrix_algorithm": matrix_algorithm,
        "use_cache": use_cache,
        "expected_leg_count": expected_leg_count,
        "success_count": len(successful),
        "failure_count": len(failed),
        "success_rate_pct": round((len(successful) / total_requests) * 100, 3),
        "all_orders_valid": all_orders_valid,
        "all_leg_counts_valid": all_leg_counts_valid,
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
        "invalid_limit_probe": invalid_limit_probe,
        "load_probe_passed": load_probe_passed,
        "first_failure": failed[0] if failed else None,
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tier 2 Phase 6 greedy VRP load and limit probe.",
    )

    parser.add_argument("--mode", choices=["local", "docker"], required=True)
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--stop-count", type=int, default=24)

    parser.add_argument(
        "--matrix-algorithm",
        choices=["bidirectional_astar", "source_dijkstra"],
        default="bidirectional_astar",
    )

    parser.add_argument("--use-cache", action="store_true")
    parser.add_argument("--return-to-start", action="store_true")
    parser.add_argument("--timeout", type=int, default=180)

    args = parser.parse_args()

    if args.requests < 1:
        raise ValueError("requests must be at least 1.")

    if args.workers < 1:
        raise ValueError("workers must be at least 1.")

    if args.stop_count < 1:
        raise ValueError("stop-count must be at least 1.")

    if args.stop_count > len(STOPS):
        raise ValueError(
            f"stop-count cannot exceed {len(STOPS)} for valid load probe."
        )

    base_url = base_url_for_mode(args.mode)
    results_dir = results_dir_for_mode(args.mode)
    results_dir.mkdir(parents=True, exist_ok=True)

    check_health(base_url=base_url, timeout_s=args.timeout)

    payload = build_payload(
        stop_count=args.stop_count,
        matrix_algorithm=args.matrix_algorithm,
        use_cache=args.use_cache,
        return_to_start=args.return_to_start,
    )

    print(
        "Running Phase 6 load probe | "
        f"mode={args.mode} | "
        f"stop_count={args.stop_count} | "
        f"requests={args.requests} | "
        f"workers={args.workers} | "
        f"return_to_start={args.return_to_start}"
    )

    records: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(
                run_one_request,
                base_url=base_url,
                payload=payload,
                timeout_s=args.timeout,
                request_index=index,
            )
            for index in range(args.requests)
        ]

        for future in as_completed(futures):
            records.append(future.result())

    records.sort(key=lambda record: int(record["request_index"]))

    invalid_limit_probe = run_invalid_limit_probe(
        base_url=base_url,
        matrix_algorithm=args.matrix_algorithm,
        use_cache=args.use_cache,
        timeout_s=args.timeout,
    )

    summary = summarize_load_probe(
        records=records,
        mode=args.mode,
        base_url=base_url,
        stop_count=args.stop_count,
        total_requests=args.requests,
        workers=args.workers,
        matrix_algorithm=args.matrix_algorithm,
        use_cache=args.use_cache,
        return_to_start=args.return_to_start,
        invalid_limit_probe=invalid_limit_probe,
    )

    route_mode = "return_to_start" if args.return_to_start else "open"

    output_path = results_dir / (
        f"phase6_greedy_load_probe_{args.stop_count}_stops_"
        f"{route_mode}_{args.mode}.json"
    )

    output_path.write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    print(
        f"saved={output_path} | "
        f"success={summary['success_count']}/{summary['total_requests']} | "
        f"orders_valid={summary['all_orders_valid']} | "
        f"legs_valid={summary['all_leg_counts_valid']} | "
        f"invalid_25_passed={summary['invalid_limit_probe']['passed']} | "
        f"cache_hits={summary['cache_hit_count']} | "
        f"cache_misses={summary['cache_miss_count']} | "
        f"api_median={summary['api_elapsed_ms']['median']} ms | "
        f"api_p95={summary['api_elapsed_ms']['p95']} ms | "
        f"matrix_median={summary['matrix_generation_time_ms']['median']} ms | "
        f"greedy_median={summary['optimization_time_ms']['median']} ms | "
        f"load_probe_passed={summary['load_probe_passed']}"
    )

    if summary["first_failure"] is not None:
        print("FIRST FAILURE:")
        print(json.dumps(summary["first_failure"], indent=2))

    if not summary["load_probe_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()