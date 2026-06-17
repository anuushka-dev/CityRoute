# benchmarks/phase5_parallel_vs_serial_probe.py

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


LOCAL_RESULTS_DIR = Path("benchmarks/phase5/local_results")
DOCKER_RESULTS_DIR = Path("benchmarks/phase5/docker_results")

DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_DOCKER_BASE_URL = "http://127.0.0.1:8001"


KANPUR_POINTS = [
    {"id": "depot", "lat": 26.4400, "lon": 80.3000},
    {"id": "stop_01", "lat": 26.4450, "lon": 80.3050},
    {"id": "stop_02", "lat": 26.4500, "lon": 80.3100},
    {"id": "stop_03", "lat": 26.4550, "lon": 80.3150},
    {"id": "stop_04", "lat": 26.4600, "lon": 80.3200},
    {"id": "stop_05", "lat": 26.4650, "lon": 80.3250},
    {"id": "stop_06", "lat": 26.4700, "lon": 80.3300},
    {"id": "stop_07", "lat": 26.4750, "lon": 80.3350},
    {"id": "stop_08", "lat": 26.4800, "lon": 80.3400},
    {"id": "stop_09", "lat": 26.4850, "lon": 80.3450},
    {"id": "stop_10", "lat": 26.4900, "lon": 80.3500},
    {"id": "stop_11", "lat": 26.4420, "lon": 80.3550},
    {"id": "stop_12", "lat": 26.4480, "lon": 80.3600},
    {"id": "stop_13", "lat": 26.4540, "lon": 80.3650},
    {"id": "stop_14", "lat": 26.4620, "lon": 80.3700},
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _results_dir_for_mode(mode: str) -> Path:
    if mode == "local":
        return LOCAL_RESULTS_DIR

    if mode == "docker":
        return DOCKER_RESULTS_DIR

    raise ValueError(f"Unsupported mode: {mode}")


def _default_base_url_for_mode(mode: str) -> str:
    if mode == "local":
        return DEFAULT_LOCAL_BASE_URL

    if mode == "docker":
        return DEFAULT_DOCKER_BASE_URL

    raise ValueError(f"Unsupported mode: {mode}")


def _summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {
            "min_ms": None,
            "mean_ms": None,
            "median_ms": None,
            "max_ms": None,
        }

    return {
        "min_ms": round(min(values), 3),
        "mean_ms": round(statistics.mean(values), 3),
        "median_ms": round(statistics.median(values), 3),
        "max_ms": round(max(values), 3),
    }


def _build_locations(n: int, run_id: str) -> list[dict[str, Any]]:
    if n < 2:
        raise ValueError("Parallel vs serial probe requires n >= 2.")

    if n > len(KANPUR_POINTS):
        raise ValueError(
            f"Only {len(KANPUR_POINTS)} fixed Kanpur test points are available. "
            f"Received n={n}."
        )

    locations: list[dict[str, Any]] = []

    for point in KANPUR_POINTS[:n]:
        locations.append(
            {
                "id": f"{point['id']}_{run_id}",
                "lat": point["lat"],
                "lon": point["lon"],
            }
        )

    return locations


def _check_health(client: httpx.Client, base_url: str) -> dict[str, Any]:
    response = client.get(f"{base_url.rstrip('/')}/health", timeout=30.0)
    response.raise_for_status()
    return response.json()


def _check_graph_stats(client: httpx.Client, base_url: str) -> dict[str, Any]:
    response = client.get(f"{base_url.rstrip('/')}/graph/stats", timeout=30.0)
    response.raise_for_status()
    return response.json()


def _extract_route_distance_m(data: dict[str, Any]) -> float | None:
    for key in ("distance_m", "total_distance_m", "route_distance_m"):
        value = data.get(key)

        if isinstance(value, int | float):
            return float(value)

    if isinstance(data.get("distance_km"), int | float):
        return float(data["distance_km"]) * 1000

    return None


def _call_route_pair(
    *,
    client: httpx.Client,
    base_url: str,
    from_location: dict[str, Any],
    to_location: dict[str, Any],
) -> dict[str, Any]:
    params = {
        "start_lat": from_location["lat"],
        "start_lon": from_location["lon"],
        "end_lat": to_location["lat"],
        "end_lon": to_location["lon"],
    }

    started = time.perf_counter()

    response = client.get(
        f"{base_url.rstrip('/')}/route",
        params=params,
        timeout=120.0,
    )

    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)

    try:
        data = response.json()
    except Exception:
        data = {"raw_text": response.text}

    return {
        "status_code": response.status_code,
        "elapsed_ms": elapsed_ms,
        "distance_m": _extract_route_distance_m(data) if response.status_code == 200 else None,
        "body": data,
    }


def _serial_route_loop(
    *,
    client: httpx.Client,
    base_url: str,
    locations: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Naive serial baseline.

    This calls /route once per directed pair.
    It intentionally represents the slow/simple approach Phase 5 improves on.
    """

    n = len(locations)

    pair_times_ms: list[float] = []
    status_codes: list[int] = []
    failures: list[dict[str, Any]] = []
    matrix_distance_m: list[list[float | None]] = [
        [None for _ in range(n)] for _ in range(n)
    ]

    started = time.perf_counter()

    for from_index, from_location in enumerate(locations):
        for to_index, to_location in enumerate(locations):
            if from_index == to_index:
                matrix_distance_m[from_index][to_index] = 0.0
                status_codes.append(200)
                continue

            result = _call_route_pair(
                client=client,
                base_url=base_url,
                from_location=from_location,
                to_location=to_location,
            )

            pair_times_ms.append(result["elapsed_ms"])
            status_codes.append(result["status_code"])

            if result["status_code"] == 200:
                matrix_distance_m[from_index][to_index] = result["distance_m"]
            else:
                failures.append(
                    {
                        "from_index": from_index,
                        "to_index": to_index,
                        "from_id": from_location["id"],
                        "to_id": to_location["id"],
                        "status_code": result["status_code"],
                        "body": result["body"],
                    }
                )

    total_elapsed_ms = round((time.perf_counter() - started) * 1000, 3)

    return {
        "method": "serial_route_endpoint_pair_loop",
        "description": "Naive baseline: calls GET /route once per directed non-diagonal pair.",
        "total_elapsed_ms": total_elapsed_ms,
        "pair_elapsed_ms": _summary(pair_times_ms),
        "status_codes": sorted(set(status_codes)),
        "successful_pairs": sum(1 for code in status_codes if code == 200),
        "failed_pairs": len(failures),
        "failures": failures[:10],
        "matrix_distance_m": matrix_distance_m,
    }


def _parallel_matrix_call(
    *,
    client: httpx.Client,
    base_url: str,
    locations: list[dict[str, Any]],
    algorithm: str,
) -> dict[str, Any]:
    payload = {
        "locations": locations,
        "algorithm": algorithm,
        "use_cache": False,
    }

    started = time.perf_counter()

    response = client.post(
        f"{base_url.rstrip('/')}/matrix",
        json=payload,
        timeout=180.0,
    )

    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)

    try:
        data = response.json()
    except Exception:
        data = {"raw_text": response.text}

    if response.status_code != 200:
        return {
            "method": "parallel_matrix_endpoint",
            "status_code": response.status_code,
            "total_elapsed_ms": elapsed_ms,
            "error": data,
        }

    return {
        "method": "parallel_matrix_endpoint",
        "description": "Phase 5 path: calls POST /matrix once with use_cache=false.",
        "status_code": response.status_code,
        "total_elapsed_ms": elapsed_ms,
        "service_generation_time_ms": data.get("generation_time_ms"),
        "parallel_workers": data.get("parallel_workers"),
        "pair_count": data.get("pair_count"),
        "computed_pairs": data.get("computed_pairs"),
        "failed_pairs": data.get("failed_pairs"),
        "cache": data.get("cache"),
        "matrix_distance_m": data.get("matrix_distance_m"),
        "raw_response_summary": {
            "n": data.get("n"),
            "algorithm": data.get("algorithm"),
            "generation_time_ms": data.get("generation_time_ms"),
            "parallel_workers": data.get("parallel_workers"),
        },
    }


def _compare_matrices(
    *,
    serial_matrix: list[list[float | None]],
    parallel_matrix: list[list[float | None]] | None,
    tolerance_m: float,
) -> dict[str, Any]:
    if parallel_matrix is None:
        return {
            "compared": False,
            "reason": "parallel matrix missing",
            "mismatches": [],
        }

    n = len(serial_matrix)
    mismatches: list[dict[str, Any]] = []
    compared_pairs = 0

    for i in range(n):
        for j in range(n):
            serial_value = serial_matrix[i][j]
            parallel_value = parallel_matrix[i][j]

            if serial_value is None or parallel_value is None:
                continue

            compared_pairs += 1

            diff = abs(float(serial_value) - float(parallel_value))

            if diff > tolerance_m:
                mismatches.append(
                    {
                        "from_index": i,
                        "to_index": j,
                        "serial_distance_m": serial_value,
                        "parallel_distance_m": parallel_value,
                        "diff_m": round(diff, 3),
                    }
                )

    return {
        "compared": True,
        "tolerance_m": tolerance_m,
        "compared_pairs": compared_pairs,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:20],
    }


def run_probe(
    *,
    mode: str,
    base_url: str,
    n: int,
    algorithm: str,
    tolerance_m: float,
) -> dict[str, Any]:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    locations = _build_locations(n=n, run_id=run_id)

    with httpx.Client() as client:
        health = _check_health(client, base_url)
        graph_stats = _check_graph_stats(client, base_url)

        serial_result = _serial_route_loop(
            client=client,
            base_url=base_url,
            locations=locations,
        )

        parallel_result = _parallel_matrix_call(
            client=client,
            base_url=base_url,
            locations=locations,
            algorithm=algorithm,
        )

    serial_time_ms = float(serial_result["total_elapsed_ms"])
    parallel_time_ms = float(parallel_result["total_elapsed_ms"])

    speedup = None

    if parallel_time_ms > 0:
        speedup = round(serial_time_ms / parallel_time_ms, 3)

    matrix_comparison = _compare_matrices(
        serial_matrix=serial_result["matrix_distance_m"],
        parallel_matrix=parallel_result.get("matrix_distance_m"),
        tolerance_m=tolerance_m,
    )

    return {
        "artifact": "phase5_parallel_vs_serial_probe",
        "created_at": _now_iso(),
        "mode": mode,
        "base_url": base_url,
        "matrix_size": f"{n}x{n}",
        "n": n,
        "pairs": n * n,
        "non_diagonal_pairs": n * n - n,
        "algorithm": algorithm,
        "health": health,
        "graph_stats": graph_stats,
        "serial_baseline": serial_result,
        "parallel_matrix": parallel_result,
        "comparison": {
            "serial_total_elapsed_ms": serial_time_ms,
            "parallel_total_elapsed_ms": parallel_time_ms,
            "speedup_serial_over_parallel": speedup,
            "speedup_target_4x_met": speedup is not None and speedup >= 4.0,
            "matrix_distance_comparison": matrix_comparison,
        },
        "acceptance_checks": {
            "serial_completed": serial_result["failed_pairs"] == 0,
            "parallel_status_200": parallel_result.get("status_code") == 200,
            "parallel_failed_pairs": parallel_result.get("failed_pairs"),
            "matrix_mismatch_count": matrix_comparison.get("mismatch_count"),
            "speedup": speedup,
            "speedup_target_4x_met": speedup is not None and speedup >= 4.0,
        },
    }


def save_result(result: dict[str, Any], *, mode: str, n: int) -> Path:
    output_dir = _results_dir_for_mode(mode)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"phase5_parallel_vs_serial_{n}x{n}.json"

    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 5 parallel matrix vs serial /route pair-loop probe."
    )

    parser.add_argument(
        "--mode",
        choices=["local", "docker"],
        required=True,
        help="Evidence mode. Controls default base URL and output folder.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override base URL. Defaults: local=8000, docker=8001.",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=10,
        help="Matrix size. Example: 5, 10, 15.",
    )
    parser.add_argument(
        "--algorithm",
        choices=["astar", "bidirectional_astar"],
        default="bidirectional_astar",
        help="Algorithm used by POST /matrix.",
    )
    parser.add_argument(
        "--tolerance-m",
        type=float,
        default=1.0,
        help="Allowed distance mismatch between serial /route and matrix result.",
    )

    args = parser.parse_args()
    base_url = args.base_url or _default_base_url_for_mode(args.mode)

    try:
        result = run_probe(
            mode=args.mode,
            base_url=base_url,
            n=args.n,
            algorithm=args.algorithm,
            tolerance_m=args.tolerance_m,
        )

        output_path = save_result(result, mode=args.mode, n=args.n)

    except Exception as exc:
        output_dir = _results_dir_for_mode(args.mode)
        output_dir.mkdir(parents=True, exist_ok=True)

        error_path = output_dir / f"phase5_parallel_vs_serial_{args.n}x{args.n}_ERROR.json"

        error_payload = {
            "artifact": "phase5_parallel_vs_serial_probe_error",
            "created_at": _now_iso(),
            "mode": args.mode,
            "base_url": base_url,
            "n": args.n,
            "algorithm": args.algorithm,
            "error": repr(exc),
        }

        error_path.write_text(
            json.dumps(error_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        print(f"ERROR: probe failed. Error artifact saved to {error_path}")
        print(repr(exc))
        return 1

    print("Phase 5 parallel vs serial probe complete")
    print(f"Mode: {args.mode}")
    print(f"Base URL: {base_url}")
    print(f"Matrix size: {args.n}x{args.n}")
    print(f"Output: {output_path}")
    print(
        "Serial total ms:",
        result["comparison"]["serial_total_elapsed_ms"],
    )
    print(
        "Parallel total ms:",
        result["comparison"]["parallel_total_elapsed_ms"],
    )
    print(
        "Speedup:",
        result["comparison"]["speedup_serial_over_parallel"],
    )
    print(
        "Speedup target 4x met:",
        result["comparison"]["speedup_target_4x_met"],
    )
    print(
        "Matrix mismatch count:",
        result["comparison"]["matrix_distance_comparison"].get("mismatch_count"),
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())