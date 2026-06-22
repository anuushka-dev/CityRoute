# benchmarks/phase5_1_algorithm_comparison.py

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any
from urllib import error, request


LOCAL_BASE_URL = "http://127.0.0.1:8000"
DOCKER_BASE_URL = "http://127.0.0.1:8001"

ALGORITHMS_TO_COMPARE = [
    "bidirectional_astar",
    "source_dijkstra",
]

KANPUR_TEST_LOCATIONS = [
    {"id": "p01", "lat": 26.4400, "lon": 80.3000},
    {"id": "p02", "lat": 26.4420, "lon": 80.3050},
    {"id": "p03", "lat": 26.4450, "lon": 80.3100},
    {"id": "p04", "lat": 26.4480, "lon": 80.3150},
    {"id": "p05", "lat": 26.4500, "lon": 80.3200},
    {"id": "p06", "lat": 26.4520, "lon": 80.3250},
    {"id": "p07", "lat": 26.4550, "lon": 80.3300},
    {"id": "p08", "lat": 26.4580, "lon": 80.3350},
    {"id": "p09", "lat": 26.4600, "lon": 80.3400},
    {"id": "p10", "lat": 26.4620, "lon": 80.3450},
    {"id": "p11", "lat": 26.4650, "lon": 80.3500},
    {"id": "p12", "lat": 26.4680, "lon": 80.3550},
    {"id": "p13", "lat": 26.4700, "lon": 80.3600},
    {"id": "p14", "lat": 26.4720, "lon": 80.3650},
    {"id": "p15", "lat": 26.4750, "lon": 80.3700},
    {"id": "p16", "lat": 26.4415, "lon": 80.3120},
    {"id": "p17", "lat": 26.4445, "lon": 80.3180},
    {"id": "p18", "lat": 26.4495, "lon": 80.3220},
    {"id": "p19", "lat": 26.4535, "lon": 80.3280},
    {"id": "p20", "lat": 26.4575, "lon": 80.3320},
    {"id": "p21", "lat": 26.4615, "lon": 80.3380},
    {"id": "p22", "lat": 26.4665, "lon": 80.3420},
    {"id": "p23", "lat": 26.4715, "lon": 80.3480},
    {"id": "p24", "lat": 26.4765, "lon": 80.3520},
    {"id": "p25", "lat": 26.4790, "lon": 80.3580},
]


def _http_json(
    *,
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    timeout_s: int = 240,
) -> tuple[int, dict[str, Any] | list[Any] | str]:
    body: bytes | None = None
    headers = {"Accept": "application/json"}

    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(
        url=url,
        data=body,
        headers=headers,
        method=method,
    )

    try:
        with request.urlopen(req, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8")

            if not raw:
                return response.status, ""

            return response.status, json.loads(raw)

    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")

        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw

    except Exception as exc:
        return 0, {
            "error": type(exc).__name__,
            "message": str(exc),
            "url": url,
        }


def _get_json(base_url: str, path: str) -> dict[str, Any]:
    status_code, payload = _http_json(
        method="GET",
        url=f"{base_url}{path}",
        timeout_s=60,
    )

    return {
        "status_code": status_code,
        "payload": payload,
    }


def _post_matrix(
    *,
    base_url: str,
    locations: list[dict[str, Any]],
    algorithm: str,
    use_cache: bool,
) -> dict[str, Any]:
    payload = {
        "locations": locations,
        "algorithm": algorithm,
        "use_cache": use_cache,
    }

    started_at = time.perf_counter()

    status_code, response_payload = _http_json(
        method="POST",
        url=f"{base_url}/matrix",
        payload=payload,
        timeout_s=300,
    )

    api_elapsed_ms = round((time.perf_counter() - started_at) * 1000, 3)

    return {
        "status_code": status_code,
        "api_elapsed_ms": api_elapsed_ms,
        "response": response_payload,
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None

    return round(statistics.median(values), 3)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None

    return round(statistics.mean(values), 3)


def _compare_matrices(
    matrix_a: list[list[float | None]],
    matrix_b: list[list[float | None]],
    tolerance_m: float,
) -> dict[str, Any]:
    mismatch_count = 0
    checked_cells = 0
    max_abs_difference_m = 0.0
    samples: list[dict[str, Any]] = []

    if len(matrix_a) != len(matrix_b):
        return {
            "shape_match": False,
            "checked_cells": 0,
            "mismatch_count": None,
            "max_abs_difference_m": None,
            "samples": [
                {
                    "error": "Matrix row count differs.",
                    "matrix_a_rows": len(matrix_a),
                    "matrix_b_rows": len(matrix_b),
                }
            ],
        }

    for row_index, row_a in enumerate(matrix_a):
        row_b = matrix_b[row_index]

        if len(row_a) != len(row_b):
            return {
                "shape_match": False,
                "checked_cells": checked_cells,
                "mismatch_count": None,
                "max_abs_difference_m": None,
                "samples": [
                    {
                        "error": "Matrix column count differs.",
                        "row_index": row_index,
                        "matrix_a_cols": len(row_a),
                        "matrix_b_cols": len(row_b),
                    }
                ],
            }

        for col_index, value_a in enumerate(row_a):
            value_b = row_b[col_index]
            checked_cells += 1

            if value_a is None and value_b is None:
                continue

            if value_a is None or value_b is None:
                mismatch_count += 1

                if len(samples) < 10:
                    samples.append(
                        {
                            "row": row_index,
                            "col": col_index,
                            "value_a": value_a,
                            "value_b": value_b,
                            "reason": "One value is null and the other is not.",
                        }
                    )

                continue

            difference = abs(float(value_a) - float(value_b))
            max_abs_difference_m = max(max_abs_difference_m, difference)

            if difference > tolerance_m:
                mismatch_count += 1

                if len(samples) < 10:
                    samples.append(
                        {
                            "row": row_index,
                            "col": col_index,
                            "value_a": value_a,
                            "value_b": value_b,
                            "difference_m": round(difference, 6),
                        }
                    )

    return {
        "shape_match": True,
        "checked_cells": checked_cells,
        "mismatch_count": mismatch_count,
        "max_abs_difference_m": round(max_abs_difference_m, 6),
        "samples": samples,
    }


def _summarize_algorithm_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    successful_runs = [
        run
        for run in runs
        if run["status_code"] == 200 and isinstance(run["response"], dict)
    ]

    api_elapsed_values = [
        float(run["api_elapsed_ms"])
        for run in successful_runs
    ]

    generation_values = [
        float(run["response"].get("generation_time_ms", 0))
        for run in successful_runs
    ]

    failed_pairs_values = [
        int(run["response"].get("failed_pairs", -1))
        for run in successful_runs
    ]

    return {
        "run_count": len(runs),
        "successful_run_count": len(successful_runs),
        "failed_run_count": len(runs) - len(successful_runs),
        "api_elapsed_ms": {
            "min": round(min(api_elapsed_values), 3) if api_elapsed_values else None,
            "mean": _mean(api_elapsed_values),
            "median": _median(api_elapsed_values),
            "max": round(max(api_elapsed_values), 3) if api_elapsed_values else None,
        },
        "generation_time_ms": {
            "min": round(min(generation_values), 3) if generation_values else None,
            "mean": _mean(generation_values),
            "median": _median(generation_values),
            "max": round(max(generation_values), 3) if generation_values else None,
        },
        "failed_pairs": {
            "values": failed_pairs_values,
            "all_zero": (
                all(value == 0 for value in failed_pairs_values)
                if failed_pairs_values
                else False
            ),
        },
    }


def run_comparison(
    *,
    mode: str,
    base_url: str,
    n: int,
    repeats: int,
    tolerance_m: float,
) -> dict[str, Any]:
    if n < 2:
        raise ValueError("n must be at least 2 for /matrix service validation.")

    if n > len(KANPUR_TEST_LOCATIONS):
        raise ValueError(f"n must be <= {len(KANPUR_TEST_LOCATIONS)}.")

    locations = KANPUR_TEST_LOCATIONS[:n]

    result: dict[str, Any] = {
        "benchmark": "phase5_1_algorithm_comparison",
        "mode": mode,
        "base_url": base_url,
        "matrix_size": n,
        "repeats": repeats,
        "tolerance_m": tolerance_m,
        "locations": locations,
        "health": _get_json(base_url, "/health"),
        "graph_stats": _get_json(base_url, "/graph/stats"),
        "algorithms": {},
        "comparison": {},
    }

    successful_responses: dict[str, dict[str, Any]] = {}

    for algorithm in ALGORITHMS_TO_COMPARE:
        runs: list[dict[str, Any]] = []

        for run_index in range(repeats):
            run = _post_matrix(
                base_url=base_url,
                locations=locations,
                algorithm=algorithm,
                use_cache=False,
            )

            run["run_index"] = run_index + 1
            runs.append(run)

            if (
                algorithm not in successful_responses
                and run["status_code"] == 200
                and isinstance(run["response"], dict)
            ):
                successful_responses[algorithm] = run["response"]

        result["algorithms"][algorithm] = {
            "runs": runs,
            "summary": _summarize_algorithm_runs(runs),
        }

    bidirectional_response = successful_responses.get("bidirectional_astar")
    source_response = successful_responses.get("source_dijkstra")

    if bidirectional_response is not None and source_response is not None:
        result["comparison"]["matrix_distance_match"] = _compare_matrices(
            bidirectional_response["matrix_distance_m"],
            source_response["matrix_distance_m"],
            tolerance_m=tolerance_m,
        )

    bidirectional_median = result["algorithms"]["bidirectional_astar"]["summary"][
        "generation_time_ms"
    ]["median"]

    source_median = result["algorithms"]["source_dijkstra"]["summary"][
        "generation_time_ms"
    ]["median"]

    if bidirectional_median and source_median and source_median > 0:
        speedup = round(float(bidirectional_median) / float(source_median), 3)

        result["comparison"]["source_dijkstra_vs_bidirectional_astar"] = {
            "bidirectional_generation_median_ms": bidirectional_median,
            "source_dijkstra_generation_median_ms": source_median,
            "speedup": speedup,
            "source_dijkstra_faster": speedup > 1.0,
            "speedup_target_4x_met": speedup >= 4.0,
        }
    else:
        result["comparison"]["source_dijkstra_vs_bidirectional_astar"] = {
            "bidirectional_generation_median_ms": bidirectional_median,
            "source_dijkstra_generation_median_ms": source_median,
            "speedup": None,
            "source_dijkstra_faster": False,
            "speedup_target_4x_met": False,
        }

    return result


def _output_path(mode: str, n: int) -> Path:
    output_dir = Path("benchmarks") / "phase5_1" / f"{mode}_results"
    output_dir.mkdir(parents=True, exist_ok=True)

    return output_dir / f"phase5_1_algorithm_comparison_{n}x{n}.json"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compare Phase 5 pairwise Bidirectional A* matrix "
            "against Phase 5.1 source-wise Dijkstra matrix."
        )
    )

    parser.add_argument("--mode", choices=["local", "docker"], required=True)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--n", type=int, default=15)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--tolerance-m", type=float, default=0.01)

    args = parser.parse_args()

    base_url = args.base_url

    if base_url is None:
        base_url = LOCAL_BASE_URL if args.mode == "local" else DOCKER_BASE_URL

    output_path = _output_path(args.mode, args.n)

    try:
        result = run_comparison(
            mode=args.mode,
            base_url=base_url,
            n=args.n,
            repeats=args.repeats,
            tolerance_m=args.tolerance_m,
        )

    except Exception as exc:
        result = {
            "benchmark": "phase5_1_algorithm_comparison",
            "mode": args.mode,
            "base_url": base_url,
            "matrix_size": args.n,
            "error": type(exc).__name__,
            "message": str(exc),
        }

    output_path.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print("Phase 5.1 algorithm comparison complete")
    print(f"Mode: {args.mode}")
    print(f"Base URL: {base_url}")
    print(f"Matrix size: {args.n}x{args.n}")
    print(f"Output: {output_path}")

    comparison = result.get("comparison", {})
    speedup_summary = comparison.get("source_dijkstra_vs_bidirectional_astar", {})

    print(
        "Bidirectional median ms:",
        speedup_summary.get("bidirectional_generation_median_ms"),
    )
    print(
        "Source Dijkstra median ms:",
        speedup_summary.get("source_dijkstra_generation_median_ms"),
    )
    print("Speedup:", speedup_summary.get("speedup"))
    print("Source Dijkstra faster:", speedup_summary.get("source_dijkstra_faster"))
    print("4x target met:", speedup_summary.get("speedup_target_4x_met"))

    matrix_match = comparison.get("matrix_distance_match", {})
    print("Matrix mismatch count:", matrix_match.get("mismatch_count"))


if __name__ == "__main__":
    main()
