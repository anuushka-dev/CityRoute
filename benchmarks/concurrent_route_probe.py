# benchmarks/concurrent_route_probe.py

from __future__ import annotations

import concurrent.futures
import json
import os
import statistics
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter


BASE_URL = os.getenv("CITYROUTE_BASE_URL", "http://127.0.0.1:8001")
RESULTS_DIR = Path("benchmarks/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


ROUTES = [
    (26.44, 80.30, 26.45, 80.35),
    (26.441, 80.301, 26.449, 80.349),
    (26.442, 80.302, 26.448, 80.348),
    (26.443, 80.303, 26.447, 80.347),
    (26.444, 80.304, 26.446, 80.346),
    (26.445, 80.305, 26.450, 80.345),
    (26.446, 80.306, 26.451, 80.344),
    (26.447, 80.307, 26.452, 80.343),
    (26.448, 80.308, 26.453, 80.342),
    (26.449, 80.309, 26.454, 80.341),
]


def summarize(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "mean": 0.0, "median": 0.0, "max": 0.0}

    return {
        "min": round(min(values), 3),
        "mean": round(statistics.mean(values), 3),
        "median": round(statistics.median(values), 3),
        "max": round(max(values), 3),
    }


def call_route(index: int, route: tuple[float, float, float, float]) -> dict:
    start_lat, start_lon, end_lat, end_lon = route

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

    with urllib.request.urlopen(url, timeout=30) as response:
        body = response.read().decode("utf-8")
        api_elapsed_ms = round((perf_counter() - request_start) * 1000, 3)
        data = json.loads(body)

    return {
        "request": index,
        "status_code": response.status,
        "api_elapsed_ms": api_elapsed_ms,
        "route_time_ms": float(data["route_time_ms"]),
        "total_time_ms": float(data["total_time_ms"]),
        "nodes_expanded": int(data["nodes_expanded"]),
        "distance_m": float(data["distance_m"]),
        "path_node_count": int(data["path_node_count"]),
        "algorithm": data["algorithm"],
        "start_snap_method": data["start"]["snap_method"],
        "end_snap_method": data["end"]["snap_method"],
    }


def main() -> None:
    workers = int(os.getenv("CITYROUTE_CONCURRENT_WORKERS", "10"))

    start = perf_counter()

    results = []
    errors = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(call_route, index, route)
            for index, route in enumerate(ROUTES[:workers])
        ]

        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                errors.append(repr(exc))

    total_elapsed_ms = round((perf_counter() - start) * 1000, 3)

    output = {
        "benchmark": "phase3_concurrent_route_probe",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": BASE_URL,
        "workers": workers,
        "total_requests": len(results) + len(errors),
        "successful_requests": len(results),
        "failed_requests": len(errors),
        "status_codes": sorted(set(row["status_code"] for row in results)),
        "algorithms": sorted(set(row["algorithm"] for row in results)),
        "snap_methods": sorted(
            set(
                [row["start_snap_method"] for row in results]
                + [row["end_snap_method"] for row in results]
            )
        ),
        "total_elapsed_ms": total_elapsed_ms,
        "api_elapsed_ms": summarize([row["api_elapsed_ms"] for row in results]),
        "route_time_ms": summarize([row["route_time_ms"] for row in results]),
        "total_time_ms": summarize([row["total_time_ms"] for row in results]),
        "nodes_expanded": summarize([row["nodes_expanded"] for row in results]),
        "errors": errors,
        "results": sorted(results, key=lambda row: row["request"]),
    }

    output_path = RESULTS_DIR / "phase3_concurrent_route_probe.json"
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")

    print(json.dumps(output, indent=2))

    if errors:
        raise SystemExit(1)

    if any(row["status_code"] != 200 for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
