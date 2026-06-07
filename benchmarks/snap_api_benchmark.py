# benchmarks/snap_api_benchmark.py

from __future__ import annotations

import argparse
from statistics import mean, median
from time import perf_counter

import requests


def run_benchmark(url: str, iterations: int) -> None:
    timings_ms: list[float] = []
    status_codes: list[int] = []
    snap_times_ms: list[float] = []
    snap_methods: set[str] = set()

    # Warm-up request
    warmup = requests.get(url, timeout=30)
    warmup.raise_for_status()

    for _ in range(iterations):
        start = perf_counter()
        response = requests.get(url, timeout=30)
        elapsed_ms = (perf_counter() - start) * 1000

        status_codes.append(response.status_code)
        timings_ms.append(elapsed_ms)

        data = response.json()
        snap_times_ms.append(float(data["snap_time_ms"]))
        snap_methods.add(str(data.get("snap_method")))

    print("snap_api_benchmark")
    print(f"url={url}")
    print(f"iterations={iterations}")
    print(f"status_codes={sorted(set(status_codes))}")
    print(f"snap_methods={sorted(snap_methods)}")

    print(f"api_min_ms={min(timings_ms):.3f}")
    print(f"api_mean_ms={mean(timings_ms):.3f}")
    print(f"api_median_ms={median(timings_ms):.3f}")
    print(f"api_max_ms={max(timings_ms):.3f}")

    print(f"internal_snap_min_ms={min(snap_times_ms):.3f}")
    print(f"internal_snap_mean_ms={mean(snap_times_ms):.3f}")
    print(f"internal_snap_median_ms={median(snap_times_ms):.3f}")
    print(f"internal_snap_max_ms={max(snap_times_ms):.3f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--iterations", type=int, default=100)
    args = parser.parse_args()

    run_benchmark(url=args.url, iterations=args.iterations)


if __name__ == "__main__":
    main()