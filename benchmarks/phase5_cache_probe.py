# benchmarks/phase5_cache_probe.py

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


KANPUR_CACHE_PROBE_POINTS = [
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
        raise ValueError("Cache probe requires n >= 2.")

    if n > len(KANPUR_CACHE_PROBE_POINTS):
        raise ValueError(
            f"Only {len(KANPUR_CACHE_PROBE_POINTS)} cache probe points are available. "
            f"Received n={n}."
        )

    locations: list[dict[str, Any]] = []

    for point in KANPUR_CACHE_PROBE_POINTS[:n]:
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
) -> tuple[dict[str, Any], float, int]:
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
        data = {"raw_text": response.text}

    return data, elapsed_ms, response.status_code


def _check_health(client: httpx.Client, base_url: str) -> dict[str, Any]:
    response = client.get(f"{base_url.rstrip('/')}/health", timeout=30.0)
    response.raise_for_status()
    return response.json()


def _check_graph_stats(client: httpx.Client, base_url: str) -> dict[str, Any]:
    response = client.get(f"{base_url.rstrip('/')}/graph/stats", timeout=30.0)
    response.raise_for_status()
    return response.json()


def run_cache_probe(
    *,
    mode: str,
    base_url: str,
    n: int,
    algorithm: str,
    hit_repeats: int,
) -> dict[str, Any]:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    locations = _build_locations(n=n, run_id=run_id)

    hit_times_ms: list[float] = []
    hit_status_codes: list[int] = []
    hit_flags: list[bool | None] = []

    with httpx.Client() as client:
        health = _check_health(client, base_url)
        graph_stats = _check_graph_stats(client, base_url)

        miss_response, miss_elapsed_ms, miss_status = _post_matrix(
            client=client,
            base_url=base_url,
            locations=locations,
            algorithm=algorithm,
            use_cache=True,
        )

        for _ in range(hit_repeats):
            hit_response, hit_elapsed_ms, hit_status = _post_matrix(
                client=client,
                base_url=base_url,
                locations=locations,
                algorithm=algorithm,
                use_cache=True,
            )

            hit_times_ms.append(hit_elapsed_ms)
            hit_status_codes.append(hit_status)
            hit_flags.append(hit_response.get("cache", {}).get("hit"))

    miss_cache = miss_response.get("cache", {})
    final_hit_confirmed_count = sum(hit is True for hit in hit_flags)

    return {
        "artifact": "phase5_cache_probe",
        "created_at": _now_iso(),
        "mode": mode,
        "base_url": base_url,
        "matrix_size": f"{n}x{n}",
        "n": n,
        "pairs": n * n,
        "algorithm": algorithm,
        "hit_repeats": hit_repeats,
        "health": health,
        "graph_stats": graph_stats,
        "cache_miss_request": {
            "status_code": miss_status,
            "api_elapsed_ms": miss_elapsed_ms,
            "cache_enabled": miss_cache.get("enabled"),
            "cache_hit": miss_cache.get("hit"),
            "cache_key": miss_cache.get("key"),
            "cache_error": miss_cache.get("error"),
            "generation_time_ms": miss_response.get("generation_time_ms"),
            "pair_count": miss_response.get("pair_count"),
            "computed_pairs": miss_response.get("computed_pairs"),
            "failed_pairs": miss_response.get("failed_pairs"),
        },
        "cache_hit_requests": {
            "status_codes": hit_status_codes,
            "cache_hit_flags": hit_flags,
            "confirmed_hit_count": final_hit_confirmed_count,
            "api_elapsed_ms": _summary(hit_times_ms),
        },
        "acceptance_checks": {
            "miss_status_200": miss_status == 200,
            "miss_confirmed": miss_cache.get("hit") is False,
            "all_hit_status_200": all(code == 200 for code in hit_status_codes),
            "all_hits_confirmed": final_hit_confirmed_count == hit_repeats,
            "hit_median_under_20ms": (
                bool(hit_times_ms) and statistics.median(hit_times_ms) < 20.0
            ),
            "cache_key_present": bool(miss_cache.get("key")),
            "failed_pairs": miss_response.get("failed_pairs"),
        },
    }


def save_result(result: dict[str, Any], *, mode: str, n: int) -> Path:
    output_dir = _results_dir_for_mode(mode)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"phase5_cache_probe_{n}x{n}.json"

    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 5 Redis cache probe. Saves local/Docker evidence separately."
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
    )
    parser.add_argument(
        "--hit-repeats",
        type=int,
        default=5,
        help="Number of repeated cache-hit calls after first miss.",
    )

    args = parser.parse_args()

    base_url = args.base_url or _default_base_url_for_mode(args.mode)

    try:
        result = run_cache_probe(
            mode=args.mode,
            base_url=base_url,
            n=args.n,
            algorithm=args.algorithm,
            hit_repeats=args.hit_repeats,
        )

        output_path = save_result(result, mode=args.mode, n=args.n)

    except Exception as exc:
        output_dir = _results_dir_for_mode(args.mode)
        output_dir.mkdir(parents=True, exist_ok=True)

        error_path = output_dir / f"phase5_cache_probe_{args.n}x{args.n}_ERROR.json"
        error_payload = {
            "artifact": "phase5_cache_probe_error",
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

        print(f"ERROR: cache probe failed. Error artifact saved to {error_path}")
        print(repr(exc))
        return 1

    print("Phase 5 cache probe complete")
    print(f"Mode: {args.mode}")
    print(f"Base URL: {base_url}")
    print(f"Matrix size: {args.n}x{args.n}")
    print(f"Output: {output_path}")
    print(
        "Miss confirmed:",
        result["acceptance_checks"]["miss_confirmed"],
    )
    print(
        "All hits confirmed:",
        result["acceptance_checks"]["all_hits_confirmed"],
    )
    print(
        "Hit median under 20ms:",
        result["acceptance_checks"]["hit_median_under_20ms"],
    )
    print(
        "Hit median ms:",
        result["cache_hit_requests"]["api_elapsed_ms"]["median_ms"],
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())