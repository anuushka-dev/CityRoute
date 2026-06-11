# benchmarks/bidirectional_astar_benchmark.py

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:8001"

DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "phase4_results"
    / "phase4_bidirectional_astar_benchmark.json"
)

BBOX = {
    "south": 26.43,
    "north": 26.50,
    "west": 80.28,
    "east": 80.38,
}


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0

    sorted_values = sorted(values)
    index = (len(sorted_values) - 1) * percentile
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)

    if lower == upper:
        return sorted_values[lower]

    weight = index - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {
            "min": 0.0,
            "mean": 0.0,
            "median": 0.0,
            "p50": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "max": 0.0,
        }

    return {
        "min": round(min(values), 3),
        "mean": round(statistics.mean(values), 3),
        "median": round(statistics.median(values), 3),
        "p50": round(_percentile(values, 0.50), 3),
        "p95": round(_percentile(values, 0.95), 3),
        "p99": round(_percentile(values, 0.99), 3),
        "max": round(max(values), 3),
    }


def _int_stats(values: list[int]) -> dict[str, float | int]:
    raw_stats = _stats([float(value) for value in values])

    return {
        "min": int(raw_stats["min"]),
        "mean": raw_stats["mean"],
        "median": raw_stats["median"],
        "p50": int(round(raw_stats["p50"])),
        "p95": int(round(raw_stats["p95"])),
        "p99": int(round(raw_stats["p99"])),
        "max": int(raw_stats["max"]),
    }


def _random_coordinate() -> tuple[float, float]:
    lat = random.uniform(BBOX["south"], BBOX["north"])
    lon = random.uniform(BBOX["west"], BBOX["east"])

    return round(lat, 6), round(lon, 6)


def _fetch_route_compare(
    *,
    base_url: str,
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    timeout_s: float,
) -> tuple[int, dict[str, Any], float]:
    query = urlencode(
        {
            "start_lat": start_lat,
            "start_lon": start_lon,
            "end_lat": end_lat,
            "end_lon": end_lon,
        }
    )

    url = f"{base_url.rstrip('/')}/route/compare?{query}"
    request = Request(url, headers={"Accept": "application/json"})

    started_at = time.perf_counter()

    try:
        with urlopen(request, timeout=timeout_s) as response:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            body = response.read().decode("utf-8")
            return response.status, json.loads(body), round(elapsed_ms, 3)

    except HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        body = exc.read().decode("utf-8", errors="replace")

        try:
            parsed_body = json.loads(body)
        except json.JSONDecodeError:
            parsed_body = {"raw_body": body}

        return exc.code, parsed_body, round(elapsed_ms, 3)

    except URLError as exc:
        raise RuntimeError(
            f"Could not connect to {url}. Make sure the Docker API is running."
        ) from exc


def _is_no_path_response(status_code: int, body: dict[str, Any]) -> bool:
    if status_code != 404:
        return False

    detail = body.get("detail")

    if isinstance(detail, dict):
        return detail.get("error") == "No path found"

    return False


def _validate_success_response(body: dict[str, Any]) -> None:
    if body.get("status") != "ok":
        raise ValueError("Response status must be ok.")

    if "astar" not in body:
        raise ValueError("Response missing astar section.")

    if "bidirectional_astar" not in body:
        raise ValueError("Response missing bidirectional_astar section.")

    if "comparison" not in body:
        raise ValueError("Response missing comparison section.")

    if body["astar"].get("algorithm") != "astar":
        raise ValueError("A* section algorithm must be astar.")

    if body["bidirectional_astar"].get("algorithm") != "bidirectional_astar":
        raise ValueError("Bidirectional section algorithm must be bidirectional_astar.")

    comparison = body["comparison"]

    if comparison.get("same_distance") is not True:
        raise ValueError(
            f"Algorithm distances do not match. Delta: "
            f"{comparison.get('distance_delta_m')}"
        )

    if float(comparison.get("distance_delta_m", 999999.0)) > 0.001:
        raise ValueError(
            f"Distance delta exceeds tolerance: {comparison.get('distance_delta_m')}"
        )


def run_benchmark(
    *,
    base_url: str,
    target_successful_route_measurements: int,
    warmup_requests: int,
    max_attempts: int,
    seed: int,
    timeout_s: float,
    output_path: Path,
) -> dict[str, Any]:
    random.seed(seed)

    print(f"Base URL: {base_url}")
    print(f"Warmup: {warmup_requests}")
    print(f"Target successful route measurements: {target_successful_route_measurements}")
    print(f"Max attempts: {max_attempts}")

    for _ in range(warmup_requests):
        start_lat, start_lon = _random_coordinate()
        end_lat, end_lon = _random_coordinate()

        _fetch_route_compare(
            base_url=base_url,
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
            timeout_s=timeout_s,
        )

    attempted_requests = 0
    successful_route_measurements = 0
    no_path_404_skipped = 0
    real_failures = 0
    zero_distance_successes = 0

    astar_route_times: list[float] = []
    bidirectional_route_times: list[float] = []

    astar_total_times: list[float] = []
    compare_total_times: list[float] = []
    api_elapsed_times: list[float] = []

    astar_nodes_expanded: list[int] = []
    bidirectional_nodes_expanded: list[int] = []

    astar_path_node_counts: list[int] = []
    bidirectional_path_node_counts: list[int] = []

    distance_deltas: list[float] = []
    route_time_deltas: list[float] = []
    nodes_expanded_deltas: list[int] = []
    nodes_expanded_reduction_pcts: list[float] = []
    route_time_reduction_pcts: list[float] = []

    distances_m: list[float] = []

    sample_no_path: list[dict[str, Any]] = []
    sample_real_failures: list[dict[str, Any]] = []

    started_at = time.perf_counter()

    while (
        successful_route_measurements < target_successful_route_measurements
        and attempted_requests < max_attempts
    ):
        attempted_requests += 1

        start_lat, start_lon = _random_coordinate()
        end_lat, end_lon = _random_coordinate()

        status_code, body, api_elapsed_ms = _fetch_route_compare(
            base_url=base_url,
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
            timeout_s=timeout_s,
        )

        if _is_no_path_response(status_code, body):
            no_path_404_skipped += 1

            if len(sample_no_path) < 10:
                sample_no_path.append(
                    {
                        "kind": "no_path",
                        "status_code": status_code,
                        "api_elapsed_ms": api_elapsed_ms,
                        "error": body,
                        "attempt": attempted_requests,
                        "start": {"lat": start_lat, "lon": start_lon},
                        "end": {"lat": end_lat, "lon": end_lon},
                    }
                )

            continue

        if status_code != 200:
            real_failures += 1

            if len(sample_real_failures) < 10:
                sample_real_failures.append(
                    {
                        "kind": "http_failure",
                        "status_code": status_code,
                        "api_elapsed_ms": api_elapsed_ms,
                        "body": body,
                        "attempt": attempted_requests,
                        "start": {"lat": start_lat, "lon": start_lon},
                        "end": {"lat": end_lat, "lon": end_lon},
                    }
                )

            continue

        try:
            _validate_success_response(body)

            astar = body["astar"]
            bidirectional = body["bidirectional_astar"]
            comparison = body["comparison"]

            astar_distance = float(astar["distance_m"])
            bidirectional_distance = float(bidirectional["distance_m"])

            if astar_distance == 0.0 and bidirectional_distance == 0.0:
                zero_distance_successes += 1

            astar_route_times.append(float(astar["route_time_ms"]))
            bidirectional_route_times.append(float(bidirectional["route_time_ms"]))

            astar_total_times.append(float(astar["total_time_ms"]))
            compare_total_times.append(float(body.get("compare_total_time_ms", 0.0)))
            api_elapsed_times.append(float(api_elapsed_ms))

            astar_nodes_expanded.append(int(astar["nodes_expanded"]))
            bidirectional_nodes_expanded.append(int(bidirectional["nodes_expanded"]))

            astar_path_node_counts.append(int(astar["path_node_count"]))
            bidirectional_path_node_counts.append(int(bidirectional["path_node_count"]))

            distance_deltas.append(float(comparison["distance_delta_m"]))
            route_time_deltas.append(float(comparison["route_time_delta_ms"]))
            nodes_expanded_deltas.append(int(comparison["nodes_expanded_delta"]))
            nodes_expanded_reduction_pcts.append(
                float(comparison["nodes_expanded_reduction_pct"])
            )
            route_time_reduction_pcts.append(
                float(comparison["route_time_reduction_pct"])
            )

            distances_m.append(astar_distance)

            successful_route_measurements += 1

        except Exception as exc:
            real_failures += 1

            if len(sample_real_failures) < 10:
                sample_real_failures.append(
                    {
                        "kind": "validation_failure",
                        "status_code": status_code,
                        "api_elapsed_ms": api_elapsed_ms,
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                        "attempt": attempted_requests,
                        "start": {"lat": start_lat, "lon": start_lon},
                        "end": {"lat": end_lat, "lon": end_lon},
                        "body": body,
                    }
                )

        if attempted_requests % 100 == 0:
            print(
                f"Attempts={attempted_requests} | "
                f"successes={successful_route_measurements} | "
                f"no_path={no_path_404_skipped} | "
                f"real_failures={real_failures}"
            )

    elapsed_s = round(time.perf_counter() - started_at, 3)

    result = {
        "benchmark": "phase4_bidirectional_astar_benchmark",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "target_successful_route_measurements": target_successful_route_measurements,
        "attempted_requests": attempted_requests,
        "successful_route_measurements": successful_route_measurements,
        "no_path_404_skipped": no_path_404_skipped,
        "real_failures": real_failures,
        "real_failure_rate_pct": (
            round((real_failures / attempted_requests) * 100, 3)
            if attempted_requests
            else 0.0
        ),
        "no_path_rate_pct": (
            round((no_path_404_skipped / attempted_requests) * 100, 3)
            if attempted_requests
            else 0.0
        ),
        "zero_distance_successes": zero_distance_successes,
        "elapsed_s": elapsed_s,
        "astar_route_time_ms": _stats(astar_route_times),
        "bidirectional_astar_route_time_ms": _stats(bidirectional_route_times),
        "astar_total_time_ms": _stats(astar_total_times),
        "compare_total_time_ms": _stats(compare_total_times),
        "api_elapsed_ms": _stats(api_elapsed_times),
        "astar_nodes_expanded": _int_stats(astar_nodes_expanded),
        "bidirectional_astar_nodes_expanded": _int_stats(
            bidirectional_nodes_expanded
        ),
        "astar_path_node_count": _int_stats(astar_path_node_counts),
        "bidirectional_astar_path_node_count": _int_stats(
            bidirectional_path_node_counts
        ),
        "distance_m": _stats(distances_m),
        "distance_delta_m": _stats(distance_deltas),
        "route_time_delta_ms": _stats(route_time_deltas),
        "nodes_expanded_delta": _int_stats(nodes_expanded_deltas),
        "nodes_expanded_reduction_pct": _stats(nodes_expanded_reduction_pcts),
        "route_time_reduction_pct": _stats(route_time_reduction_pcts),
        "targets": {
            "successful_route_measurements": str(
                target_successful_route_measurements
            ),
            "real_failures": "0",
            "distance_delta_m": "<= 0.001",
            "benchmark_goal": (
                "Compare A* vs Bidirectional A* timing and node expansion; "
                "do not assume Bidirectional A* is always faster."
            ),
        },
        "sample_no_path": sample_no_path,
        "sample_real_failures": sample_real_failures,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark Phase 4 A* vs Bidirectional A* through /route/compare."
    )

    parser.add_argument(
        "target_successful_route_measurements",
        nargs="?",
        type=int,
        default=1000,
    )
    parser.add_argument(
        "warmup_requests",
        nargs="?",
        type=int,
        default=5,
    )
    parser.add_argument(
        "max_attempts",
        nargs="?",
        type=int,
        default=3000,
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout-s", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    result = run_benchmark(
        base_url=args.base_url,
        target_successful_route_measurements=args.target_successful_route_measurements,
        warmup_requests=args.warmup_requests,
        max_attempts=args.max_attempts,
        seed=args.seed,
        timeout_s=args.timeout_s,
        output_path=args.output,
    )

    print(json.dumps(result, indent=2))

    if (
        result["successful_route_measurements"]
        != result["target_successful_route_measurements"]
    ):
        return 1

    if result["real_failures"] != 0:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())