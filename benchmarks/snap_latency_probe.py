# benchmarks/snap_latency_probe.py

from __future__ import annotations

import sys
from pathlib import Path
from statistics import mean, median
from time import perf_counter

# Allow this script to be run directly:
# python benchmarks\snap_latency_probe.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import osmnx as ox  # noqa: E402

from app.config import settings  # noqa: E402


def benchmark_single_snap(graph, *, lat: float, lon: float, iterations: int) -> list[float]:
    """
    Benchmark repeated single nearest-node lookups.

    This matches how /graph/snap is used: one GPS coordinate comes in,
    one nearest road node is found.
    """
    timings_ms: list[float] = []

    # Warm-up so first-call setup is not counted.
    ox.distance.nearest_nodes(graph, X=lon, Y=lat)

    for _ in range(iterations):
        start = perf_counter()
        ox.distance.nearest_nodes(graph, X=lon, Y=lat)
        timings_ms.append((perf_counter() - start) * 1000)

    return timings_ms


def main() -> None:
    graph_path = settings.graph_path

    if not graph_path.exists():
        raise FileNotFoundError(
            f"GraphML file not found: {graph_path}. "
            "Run the app once first so Phase 2 can create/load the graph."
        )

    load_start = perf_counter()
    graph = ox.load_graphml(graph_path)
    graph_load_time_s = round(perf_counter() - load_start, 3)

    lat = 26.44
    lon = 80.30
    iterations = 100

    timings_ms = benchmark_single_snap(
        graph,
        lat=lat,
        lon=lon,
        iterations=iterations,
    )

    print("snap_latency_probe")
    print(f"graph_path={graph_path}")
    print(f"graph_load_time_s={graph_load_time_s}")
    print(f"iterations={len(timings_ms)}")
    print(f"input_lat={lat}")
    print(f"input_lon={lon}")
    print(f"min_ms={min(timings_ms):.3f}")
    print(f"mean_ms={mean(timings_ms):.3f}")
    print(f"median_ms={median(timings_ms):.3f}")
    print(f"max_ms={max(timings_ms):.3f}")


if __name__ == "__main__":
    main()