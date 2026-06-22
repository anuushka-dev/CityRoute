# benchmarks/phase_7_1/phase7_1_cache_observability_benchmark.py

from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URLS = {
    "local": "http://127.0.0.1:8000",
    "docker": "http://127.0.0.1:8001",
}


BASE_START = {
    "lat": 26.4499,
    "lon": 80.3319,
}

BASE_STOPS = [
    {"lat": 26.4600, "lon": 80.3400},
    {"lat": 26.4550, "lon": 80.3250},
    {"lat": 26.4700, "lon": 80.3350},
    {"lat": 26.4420, "lon": 80.3450},
    {"lat": 26.4650, "lon": 80.3150},
]


def _post_json(url: str, payload: dict[str, Any]) -> tuple[dict[str, Any], float]:
    request = Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    started_at = time.perf_counter()

    try:
        with urlopen(request, timeout=120) as response:
            elapsed_ms = round((time.perf_counter() - started_at) * 1000.0, 3)
            raw = response.read().decode("utf-8")
            return json.loads(raw), elapsed_ms

    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {error_body}") from exc

    except URLError as exc:
        raise RuntimeError(f"Could not connect to {url}: {exc}") from exc


def _build_payloads(run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Build matching /matrix and /vrp/compare payloads.

    Important:
    The matrix payload must use the same IDs that /vrp/compare internally
    generates through _build_matrix_locations():
        depot, stop_0, stop_1, ...

    The cache-key freshness comes from tiny coordinate jitter, not unique IDs.
    """
    jitter_units = (int(run_id[:2], 16) % 8) + 1
    jitter = jitter_units * 0.000001

    start = {
        "id": "depot",
        "lat": round(BASE_START["lat"] + jitter, 6),
        "lon": round(BASE_START["lon"], 6),
    }

    stops = []

    for index, stop in enumerate(BASE_STOPS):
        stops.append(
            {
                "id": f"stop_{index}",
                "lat": round(stop["lat"] + jitter, 6),
                "lon": round(stop["lon"], 6),
            }
        )

    matrix_payload = {
        "locations": [start, *stops],
        "algorithm": "source_dijkstra",
        "use_cache": True,
    }

    vrp_payload = {
        "start": start,
        "stops": stops,
        "matrix_algorithm": "source_dijkstra",
        "use_cache": True,
        "return_to_start": False,
        "two_opt_max_iterations": 100,
        "improvement_tolerance_m": 0.001,
        "keep_trace": True,
    }

    return matrix_payload, vrp_payload


def _matrix_cache_status(matrix_response: dict[str, Any]) -> dict[str, Any]:
    cache = matrix_response.get("cache") or {}

    return {
        "enabled": cache.get("enabled"),
        "hit": cache.get("hit"),
        "key": cache.get("key"),
        "ttl_seconds": cache.get("ttl_seconds"),
        "error": cache.get("error"),
    }


def _safe_speedup(before_ms: Any, after_ms: Any) -> float | None:
    if not isinstance(before_ms, (int, float)):
        return None

    if not isinstance(after_ms, (int, float)):
        return None

    if after_ms <= 0:
        return None

    return round(before_ms / after_ms, 3)


def run_benchmark(*, mode: str, base_url: str, output_dir: Path) -> dict[str, Any]:
    run_id = uuid.uuid4().hex[:8]

    matrix_payload, vrp_payload = _build_payloads(run_id=run_id)

    matrix_url = f"{base_url.rstrip('/')}/matrix"
    vrp_url = f"{base_url.rstrip('/')}/vrp/compare"

    cold_matrix_response, cold_http_ms = _post_json(matrix_url, matrix_payload)
    warm_matrix_response, warm_http_ms = _post_json(matrix_url, matrix_payload)
    vrp_response, vrp_http_ms = _post_json(vrp_url, vrp_payload)

    cold_cache = _matrix_cache_status(cold_matrix_response)
    warm_cache = _matrix_cache_status(warm_matrix_response)

    cold_generation_ms = cold_matrix_response.get("generation_time_ms")
    warm_generation_ms = warm_matrix_response.get("generation_time_ms")
    vrp_matrix_ms = vrp_response.get("matrix_generation_time_ms")

    validations = {
        "cold_matrix_cache_miss": cold_cache["enabled"] is True
        and cold_cache["hit"] is False,
        "warm_matrix_cache_hit": warm_cache["enabled"] is True
        and warm_cache["hit"] is True,
        "vrp_compare_cache_hit": vrp_response.get("cache_status") == "hit",
        "vrp_compare_cache_hits_positive": vrp_response.get("cache_hits") == 1,
        "vrp_compare_cache_misses_zero": vrp_response.get("cache_misses") == 0,
        "vrp_non_regression": (
            vrp_response.get("improvement", {}).get("non_regression") is True
        ),
    }

    result = {
        "phase": "tier2_phase7_1",
        "benchmark": "cache_observability_cold_warm_vrp",
        "mode": mode,
        "base_url": base_url,
        "run_id": run_id,
        "location_count": len(matrix_payload["locations"]),
        "stop_count": len(vrp_payload["stops"]),
        "algorithm": "source_dijkstra",
        "all_validations_passed": all(validations.values()),
        "validations": validations,
        "cold_matrix": {
            "http_elapsed_ms": cold_http_ms,
            "generation_time_ms": cold_generation_ms,
            "cache": cold_cache,
        },
        "warm_matrix": {
            "http_elapsed_ms": warm_http_ms,
            "generation_time_ms": warm_generation_ms,
            "cache": warm_cache,
        },
        "vrp_compare": {
            "http_elapsed_ms": vrp_http_ms,
            "matrix_generation_time_ms": vrp_matrix_ms,
            "total_time_ms": vrp_response.get("total_time_ms"),
            "cache_used": vrp_response.get("cache_used"),
            "cache_status": vrp_response.get("cache_status"),
            "cache_hits": vrp_response.get("cache_hits"),
            "cache_misses": vrp_response.get("cache_misses"),
            "greedy_distance_m": vrp_response.get("greedy", {}).get(
                "total_distance_m"
            ),
            "two_opt_distance_m": vrp_response.get("two_opt", {}).get(
                "total_distance_m"
            ),
            "distance_saved_m": vrp_response.get("improvement", {}).get(
                "distance_saved_m"
            ),
            "improvement_pct": vrp_response.get("improvement", {}).get(
                "improvement_pct"
            ),
            "non_regression": vrp_response.get("improvement", {}).get(
                "non_regression"
            ),
        },
        "speedups": {
            "cold_matrix_to_warm_matrix_generation": _safe_speedup(
                cold_generation_ms,
                warm_generation_ms,
            ),
            "cold_matrix_to_vrp_matrix_generation": _safe_speedup(
                cold_generation_ms,
                vrp_matrix_ms,
            ),
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"phase7_1_cache_observability_{mode}_{run_id}.json"
    latest_path = output_dir / f"phase7_1_cache_observability_{mode}_latest.json"

    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    latest_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 7.1 cache observability benchmark."
    )

    parser.add_argument(
        "--mode",
        choices=("local", "docker"),
        default="docker",
    )

    parser.add_argument(
        "--base-url",
        default=None,
        help="Override API base URL. Default is based on --mode.",
    )

    parser.add_argument(
        "--output-dir",
        default=None,
    )

    args = parser.parse_args()

    base_url = args.base_url or DEFAULT_BASE_URLS[args.mode]

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path("benchmarks") / "phase_7_1" / f"{args.mode}_results"

    result = run_benchmark(
        mode=args.mode,
        base_url=base_url,
        output_dir=output_dir,
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()