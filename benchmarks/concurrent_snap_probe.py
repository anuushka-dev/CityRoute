# benchmarks/concurrent_snap_probe.py

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import mean, median
from time import perf_counter

import requests


def call_snap(index: int, url: str) -> tuple[int, int, float, float, str]:
    start = perf_counter()
    response = requests.get(url, timeout=30)
    elapsed_ms = round((perf_counter() - start) * 1000, 3)

    data = response.json()

    return (
        index,
        response.status_code,
        elapsed_ms,
        float(data.get("snap_time_ms", -1)),
        str(data.get("snap_method")),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--requests", type=int, default=10)
    args = parser.parse_args()

    api_times: list[float] = []
    internal_snap_times: list[float] = []
    status_codes: list[int] = []
    snap_methods: set[str] = set()

    start = perf_counter()

    with ThreadPoolExecutor(max_workers=args.requests) as executor:
        futures = [executor.submit(call_snap, i, args.url) for i in range(args.requests)]

        for future in as_completed(futures):
            index, status_code, elapsed_ms, snap_time_ms, snap_method = future.result()

            api_times.append(elapsed_ms)
            internal_snap_times.append(snap_time_ms)
            status_codes.append(status_code)
            snap_methods.add(snap_method)

            print(
                f"request={index} "
                f"status_code={status_code} "
                f"api_elapsed_ms={elapsed_ms} "
                f"internal_snap_time_ms={snap_time_ms} "
                f"snap_method={snap_method}"
            )

    total_ms = round((perf_counter() - start) * 1000, 3)

    print("summary")
    print(f"total_requests={args.requests}")
    print(f"total_elapsed_ms={total_ms}")
    print(f"status_codes={sorted(set(status_codes))}")
    print(f"snap_methods={sorted(snap_methods)}")

    print(f"api_min_ms={min(api_times):.3f}")
    print(f"api_mean_ms={mean(api_times):.3f}")
    print(f"api_median_ms={median(api_times):.3f}")
    print(f"api_max_ms={max(api_times):.3f}")

    print(f"internal_snap_min_ms={min(internal_snap_times):.3f}")
    print(f"internal_snap_mean_ms={mean(internal_snap_times):.3f}")
    print(f"internal_snap_median_ms={median(internal_snap_times):.3f}")
    print(f"internal_snap_max_ms={max(internal_snap_times):.3f}")


if __name__ == "__main__":
    main()