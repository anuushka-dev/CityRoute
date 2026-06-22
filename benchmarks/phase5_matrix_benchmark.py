# benchmarks/phase5_matrix_benchmark.py

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


LOCAL_RESULTS_DIR = Path("benchmarks/phase5/local_results")
DOCKER_RESULTS_DIR = Path("benchmarks/phase5/docker_results")

DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_DOCKER_BASE_URL = "http://127.0.0.1:8001"


KANPUR_TEST_POINTS = [
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
    {"id": "stop_15", "lat": 26.4680, "lon": 80.3750},
    {"id": "stop_16", "lat": 26.4740, "lon": 80.3720},
    {"id": "stop_17", "lat": 26.4820, "lon": 80.3680},
    {"id": "stop_18", "lat": 26.4880, "lon": 80.3620},
    {"id": "stop_19", "lat": 26.4940, "lon": 80.3580},
    {"id": "stop_20", "lat": 26.4360, "lon": 80.3080},
    {"id": "stop_21", "lat": 26.4380, "lon": 80.3180},
    {"id": "stop_22", "lat": 26.4440, "lon": 80.3280},
    {"id": "stop_23", "lat": 26.4520, "lon": 80.3380},
    {"id": "stop_24", "lat": 26.4580, "lon": 80.3480},
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None

    ordered = sorted(values)

    if len(ordered) == 1:
        return round(ordered[0], 3)

    index = (len(ordered) - 1) * percentile
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower

    result = ordered[lower] * (1 - weight) + ordered[upper] * weight
    return round(result, 3)


def _summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {
            "min_ms": None,
            "mean_ms": None,
            "median_ms": None,
            "p95_ms": None,
            "p99_ms": None,
            "max_ms": None,
        }

    return {
        "min_ms": round(min(values), 3),
        "mean_ms": round(statistics.mean(values), 3),
        "median_ms": round(statistics.median(values), 3),
        "p95_ms": _percentile(values, 0.95),
        "p99_ms": _percentile(values, 0.99),
        "max_ms": round(max(values), 3),
    }


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


def _build_locations(n: int, run_id: str) -> list[dict[str, Any]]:
    if n < 2:
        raise ValueError("Matrix benchmark requires n >= 2.")

    if n > len(KANPUR_TEST_POINTS):
        raise ValueError(
            f"Only {len(KANPUR_TEST_POINTS)} fixed Kanpur test points are available. "
            f"Received n={n}."
        )

    # Add run_id into IDs to force a fresh Redis key for the cache-miss measurement.
    # Coordinates stay identical, only cache key changes.
    locations = []

    for point in KANPUR_TEST_POINTS[:n]:
        locations.append(
            {
                "id": f"{point['id']}_{run_id}",
                "lat": point["lat"],
                "lon": point["lon"],
            }
        )

    return locations


def _post_matrix(
    *,
    client: httpx.Client,
    base_url: str,
    locations: list[dict[str, Any]],
    algorithm: str,
    use_cache: bool,
) -> tuple[dict[str, Any], float]:
    payload = {
        "locations": locations,
        "algorithm": algorithm,
        "use_cache": use_cache,
    }

    started = time.perf_counter()

    response = client.post(
        f"{base_url.rstrip('/')}/matrix",
        json=payload,
        timeout=120.0,
    )

    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)

    try:
        data = response.json()
    except Exception:
        data = {
            "raw_text": response.text,
        }

    if response.status_code != 200:
        raise RuntimeError(
            f"POST /matrix failed | status={response.status_code} | body={data}"
        )

    return data, elapsed_ms


def _check_health(client: httpx.Client, base_url: str) -> dict[str, Any]:
    response = client.get(f"{base_url.rstrip('/')}/health", timeout=30.0)
    response.raise_for_status()
    return response.json()


def _check_graph_stats(client: httpx.Client, base_url: str) -> dict[str, Any]:
    response = client.get(f"{base_url.rstrip('/')}/graph/stats", timeout=30.0)
    response.raise_for_status()
    return response.json()


def _validate_matrix_response(data: dict[str, Any], n: int) -> dict[str, Any]:
    distance_matrix = data.get("matrix_distance_m")
    eta_matrix = data.get("matrix_eta_s")

    shape_ok = (
        isinstance(distance_matrix, list)
        and len(distance_matrix) == n
        and all(isinstance(row, list) and len(row) == n for row in distance_matrix)
        and isinstance(eta_matrix, list)
        and len(eta_matrix) == n
        and all(isinstance(row, list) and len(row) == n for row in eta_matrix)
    )

    diagonal_zero = False

    if shape_ok:
        diagonal_zero = all(
            distance_matrix[index][index] == 0.0
            and eta_matrix[index][index] == 0.0
            for index in range(n)
        )

    return {
        "shape_ok": shape_ok,
        "diagonal_zero": diagonal_zero,
        "n": data.get("n"),
        "pair_count": data.get("pair_count"),
        "computed_pairs": data.get("computed_pairs"),
        "failed_pairs": data.get("failed_pairs"),
        "cache_enabled": data.get("cache", {}).get("enabled"),
        "cache_hit": data.get("cache", {}).get("hit"),
        "service_generation_time_ms": data.get("generation_time_ms"),
        "parallel_workers": data.get("parallel_workers"),
    }


def run_benchmark(
    *,
    mode: str,
    base_url: str,
    n: int,
    algorithm: str,
    repeats: int,
) -> dict[str, Any]:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    locations = _build_locations(n=n, run_id=run_id)

    cold_no_cache_times: list[float] = []
    cache_miss_times: list[float] = []
    cache_hit_times: list[float] = []

    cold_no_cache_response: dict[str, Any] | None = None
    cache_miss_response: dict[str, Any] | None = None
    cache_hit_response: dict[str, Any] | None = None

    with httpx.Client() as client:
        health = _check_health(client, base_url)
        graph_stats = _check_graph_stats(client, base_url)

        for iteration in range(repeats):
            cold_data, cold_elapsed_ms = _post_matrix(
                client=client,
                base_url=base_url,
                locations=locations,
                algorithm=algorithm,
                use_cache=False,
            )
            cold_no_cache_times.append(cold_elapsed_ms)
            cold_no_cache_response = cold_data

        # First cached call should be miss because run_id makes a fresh cache key.
        cache_miss_data, cache_miss_elapsed_ms = _post_matrix(
            client=client,
            base_url=base_url,
            locations=locations,
            algorithm=algorithm,
            use_cache=True,
        )
        cache_miss_times.append(cache_miss_elapsed_ms)
        cache_miss_response = cache_miss_data

        # Repeated cached calls should hit Redis.
        for _ in range(repeats):
            cache_hit_data, cache_hit_elapsed_ms = _post_matrix(
                client=client,
                base_url=base_url,
                locations=locations,
                algorithm=algorithm,
                use_cache=True,
            )
            cache_hit_times.append(cache_hit_elapsed_ms)
            cache_hit_response = cache_hit_data

    cold_validation = _validate_matrix_response(cold_no_cache_response or {}, n)
    cache_miss_validation = _validate_matrix_response(cache_miss_response or {}, n)
    cache_hit_validation = _validate_matrix_response(cache_hit_response or {}, n)

    cache_miss_is_real_miss = cache_miss_response.get("cache", {}).get("hit") is False
    cache_hit_is_real_hit = cache_hit_response.get("cache", {}).get("hit") is True

    result = {
        "artifact": "phase5_matrix_benchmark",
        "created_at": _now_iso(),
        "mode": mode,
        "base_url": base_url,
        "matrix_size": f"{n}x{n}",
        "n": n,
        "pairs": n * n,
        "algorithm": algorithm,
        "repeats": repeats,
        "health": health,
        "graph_stats": graph_stats,
        "cold_no_cache": {
            "use_cache": False,
            "api_elapsed_ms": _summary(cold_no_cache_times),
            "validation": cold_validation,
        },
        "cache_miss": {
            "use_cache": True,
            "expected_hit": False,
            "actual_hit": cache_miss_response.get("cache", {}).get("hit"),
            "actual_miss_confirmed": cache_miss_is_real_miss,
            "api_elapsed_ms": _summary(cache_miss_times),
            "validation": cache_miss_validation,
        },
        "cache_hit": {
            "use_cache": True,
            "expected_hit": True,
            "actual_hit": cache_hit_response.get("cache", {}).get("hit"),
            "actual_hit_confirmed": cache_hit_is_real_hit,
            "api_elapsed_ms": _summary(cache_hit_times),
            "validation": cache_hit_validation,
        },
        "acceptance_checks": {
            "cold_shape_ok": cold_validation["shape_ok"],
            "cold_diagonal_zero": cold_validation["diagonal_zero"],
            "cache_miss_confirmed": cache_miss_is_real_miss,
            "cache_hit_confirmed": cache_hit_is_real_hit,
            "cache_hit_under_20ms": (
                cache_hit_times
                and statistics.median(cache_hit_times) < 20.0
            ),
            "failed_pairs": cache_hit_validation["failed_pairs"],
        },
        "sample_response_fields": {
            "cold_no_cache": {
                "n": cold_no_cache_response.get("n"),
                "pair_count": cold_no_cache_response.get("pair_count"),
                "computed_pairs": cold_no_cache_response.get("computed_pairs"),
                "failed_pairs": cold_no_cache_response.get("failed_pairs"),
                "generation_time_ms": cold_no_cache_response.get("generation_time_ms"),
                "parallel_workers": cold_no_cache_response.get("parallel_workers"),
            },
            "cache_miss": {
                "cache": cache_miss_response.get("cache"),
                "generation_time_ms": cache_miss_response.get("generation_time_ms"),
            },
            "cache_hit": {
                "cache": cache_hit_response.get("cache"),
                "generation_time_ms": cache_hit_response.get("generation_time_ms"),
            },
        },
    }

    return result


def save_result(result: dict[str, Any], *, mode: str, n: int) -> Path:
    output_dir = _results_dir_for_mode(mode)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"phase5_matrix_benchmark_{n}x{n}.json"

    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 5 matrix benchmark. Saves evidence separately for local and Docker."
        )
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
        help="Routing algorithm for pair computation.",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="Repeat count for cold no-cache and cache-hit timing.",
    )

    args = parser.parse_args()

    base_url = args.base_url or _default_base_url_for_mode(args.mode)

    try:
        result = run_benchmark(
            mode=args.mode,
            base_url=base_url,
            n=args.n,
            algorithm=args.algorithm,
            repeats=args.repeats,
        )
        output_path = save_result(result, mode=args.mode, n=args.n)

    except Exception as exc:
        error_output_dir = _results_dir_for_mode(args.mode)
        error_output_dir.mkdir(parents=True, exist_ok=True)

        error_path = error_output_dir / f"phase5_matrix_benchmark_{args.n}x{args.n}_ERROR.json"
        error_payload = {
            "artifact": "phase5_matrix_benchmark_error",
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

        print(f"ERROR: benchmark failed. Error artifact saved to {error_path}")
        print(repr(exc))
        return 1

    print("Phase 5 matrix benchmark complete")
    print(f"Mode: {args.mode}")
    print(f"Base URL: {base_url}")
    print(f"Matrix size: {args.n}x{args.n}")
    print(f"Output: {output_path}")
    print(
        "Cache hit median ms:",
        result["cache_hit"]["api_elapsed_ms"]["median_ms"],
    )
    print(
        "Cache hit confirmed:",
        result["acceptance_checks"]["cache_hit_confirmed"],
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())