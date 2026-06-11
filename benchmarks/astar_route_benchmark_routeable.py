# benchmarks/astar_route_benchmark_routeable.py

from __future__ import annotations
import os

import json
import os
import random
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter


BASE_URL = os.getenv("CITYROUTE_BASE_URL", "http://127.0.0.1:8001")
RESULTS_DIR = Path("benchmarks/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

BBOX = {
    "south": 26.43,
    "north": 26.50,
    "west": 80.28,
    "east": 80.38,
}


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0

    sorted_values = sorted(values)
    index = int(round((pct / 100) * (len(sorted_values) - 1)))
    return round(sorted_values[index], 3)


def summarize(values: list[float]) -> dict[str, float]:
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
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "max": round(max(values), 3),
    }


def random_coordinate() -> tuple[float, float]:
    lat = random.uniform(BBOX["south"], BBOX["north"])
    lon = random.uniform(BBOX["west"], BBOX["east"])

    return round(lat, 6), round(lon, 6)


def call_route(start_lat: float, start_lon: float, end_lat: float, end_lon: float) -> dict:
    query = urllib.parse.urlencode(
        {
            "start_lat": start_lat,
            "start_lon": start_lon,
            "end_lat": end_lat,
            "end_lon": end_lon,
        }
    )
    url = f"{BASE_URL}/route?{query}"

    request_start = perf_counter()

    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            body = response.read().decode("utf-8")
            api_elapsed_ms = round((perf_counter() - request_start) * 1000, 3)
            data = json.loads(body)

            return {
                "kind": "success",
                "status_code": response.status,
                "api_elapsed_ms": api_elapsed_ms,
                "route_time_ms": float(data["route_time_ms"]),
                "total_time_ms": float(data["total_time_ms"]),
                "nodes_expanded": int(data["nodes_expanded"]),
                "distance_m": float(data["distance_m"]),
                "path_node_count": int(data["path_node_count"]),
                "start_snap_time_ms": float(data["start"]["snap_time_ms"]),
                "end_snap_time_ms": float(data["end"]["snap_time_ms"]),
                "algorithm": data["algorithm"],
                "start_snap_method": data["start"]["snap_method"],
                "end_snap_method": data["end"]["snap_method"],
            }

    except urllib.error.HTTPError as exc:
        elapsed_ms = round((perf_counter() - request_start) * 1000, 3)
        body = exc.read().decode("utf-8", errors="replace")

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"raw": body}

        detail = parsed.get("detail", {}) if isinstance(parsed, dict) else {}
        error_name = detail.get("error") if isinstance(detail, dict) else None

        if exc.code == 404 and error_name == "No path found":
            return {
                "kind": "no_path",
                "status_code": exc.code,
                "api_elapsed_ms": elapsed_ms,
                "error": parsed,
            }

        return {
            "kind": "real_failure",
            "status_code": exc.code,
            "api_elapsed_ms": elapsed_ms,
            "error": parsed,
        }

    except Exception as exc:
        elapsed_ms = round((perf_counter() - request_start) * 1000, 3)
        return {
            "kind": "real_failure",
            "status_code": None,
            "api_elapsed_ms": elapsed_ms,
            "error": repr(exc),
        }


def main() -> None:
    random.seed(42)

    target_successes = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    warmup = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    max_attempts = int(sys.argv[3]) if len(sys.argv) > 3 else target_successes * 3

    print(f"Base URL: {BASE_URL}")
    print(f"Warmup: {warmup}")
    print(f"Target successful route measurements: {target_successes}")
    print(f"Max attempts: {max_attempts}")

    for _ in range(warmup):
        start_lat, start_lon = random_coordinate()
        end_lat, end_lon = random_coordinate()
        call_route(start_lat, start_lon, end_lat, end_lon)

    successes = []
    no_path_skipped = []
    real_failures = []

    benchmark_start = perf_counter()
    attempts = 0

    while len(successes) < target_successes and attempts < max_attempts:
        start_lat, start_lon = random_coordinate()
        end_lat, end_lon = random_coordinate()

        result = call_route(start_lat, start_lon, end_lat, end_lon)
        result["attempt"] = attempts
        result["start"] = {"lat": start_lat, "lon": start_lon}
        result["end"] = {"lat": end_lat, "lon": end_lon}

        if result["kind"] == "success":
            successes.append(result)
        elif result["kind"] == "no_path":
            no_path_skipped.append(result)
        else:
            real_failures.append(result)

        attempts += 1

        if attempts % 100 == 0:
            print(
                f"Attempts={attempts} | successes={len(successes)} | "
                f"no_path={len(no_path_skipped)} | real_failures={len(real_failures)}"
            )

    elapsed_s = round(perf_counter() - benchmark_start, 3)

    route_times = [row["route_time_ms"] for row in successes]
    total_times = [row["total_time_ms"] for row in successes]
    api_times = [row["api_elapsed_ms"] for row in successes]
    nodes_expanded = [row["nodes_expanded"] for row in successes]
    distances = [row["distance_m"] for row in successes]
    path_node_counts = [row["path_node_count"] for row in successes]
    snap_times = [
        row["start_snap_time_ms"] + row["end_snap_time_ms"]
        for row in successes
    ]
    zero_distance_routes = [
        row for row in successes
        if row["distance_m"] == 0.0 or row["path_node_count"] == 1
    ]

    output = {
        "benchmark": "phase3_astar_route_benchmark_routeable",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": BASE_URL,
        "target_successful_route_measurements": target_successes,
        "attempted_requests": attempts,
        "successful_route_measurements": len(successes),
        "no_path_404_skipped": len(no_path_skipped),
        "real_failures": len(real_failures),
        "real_failure_rate_pct": round((len(real_failures) / attempts) * 100, 3) if attempts else 0,
        "no_path_rate_pct": round((len(no_path_skipped) / attempts) * 100, 3) if attempts else 0,
        "zero_distance_successes": len(zero_distance_routes),
        "elapsed_s": elapsed_s,
        "route_time_ms": summarize(route_times),
        "total_time_ms": summarize(total_times),
        "api_elapsed_ms": summarize(api_times),
        "two_snap_time_ms": summarize(snap_times),
        "nodes_expanded": summarize(nodes_expanded),
        "distance_m": summarize(distances),
        "path_node_count": summarize(path_node_counts),
        "targets": {
            "successful_route_measurements": "1000",
            "real_failures": "0",
            "route_time_p50_ms": "10-25 ms",
            "route_time_p95_ms": "< 60 ms",
            "route_time_p99_ms": "< 120 ms",
            "two_snap_p50_ms": "< 1 ms",
            "memory": "record separately with docker stats",
        },
        "sample_no_path": no_path_skipped[:10],
        "sample_real_failures": real_failures[:10],
    }

    output_path = RESULTS_DIR / "phase3_astar_route_benchmark_routeable.json"
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")

    print(json.dumps(output, indent=2))

    if len(successes) < target_successes:
        raise SystemExit(
            f"Only collected {len(successes)}/{target_successes} successful route measurements."
        )

    if real_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
