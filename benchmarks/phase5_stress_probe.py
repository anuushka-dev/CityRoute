# benchmarks/phase5_stress_probe.py

from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib import error, request

from phase5_1_algorithm_comparison import KANPUR_TEST_LOCATIONS


LOCAL_BASE_URL = "http://127.0.0.1:8000"
DOCKER_BASE_URL = "http://127.0.0.1:8001"


def _http_json(
    *,
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    timeout_s: int = 600,
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


def _post_matrix(
    *,
    base_url: str,
    locations: list[dict[str, Any]],
    algorithm: str,
    use_cache: bool,
    request_index: int,
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
        timeout_s=600,
    )

    api_elapsed_ms = round((time.perf_counter() - started_at) * 1000, 3)

    generation_time_ms = None
    failed_pairs = None
    computed_pairs = None
    pair_count = None
    cache_hit = None
    cache_enabled = use_cache

    if status_code == 200 and isinstance(response_payload, dict):
        generation_time_ms = response_payload.get("generation_time_ms")
        failed_pairs = response_payload.get("failed_pairs")
        computed_pairs = response_payload.get("computed_pairs")
        pair_count = response_payload.get("pair_count")

        cache_payload = response_payload.get("cache", {})
        if isinstance(cache_payload, dict):
            cache_hit = cache_payload.get("hit")
            cache_enabled = cache_payload.get("enabled", use_cache)

    return {
        "request_index": request_index,
        "status_code": status_code,
        "api_elapsed_ms": api_elapsed_ms,
        "generation_time_ms": generation_time_ms,
        "failed_pairs": failed_pairs,
        "computed_pairs": computed_pairs,
        "pair_count": pair_count,
        "cache_enabled": cache_enabled,
        "cache_hit": cache_hit,
        "response_type": type(response_payload).__name__,
        "error": response_payload if status_code != 200 else None,
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None

    ordered = sorted(values)
    index = int(round((percentile / 100) * (len(ordered) - 1)))

    return round(ordered[index], 3)


def _summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [
        run
        for run in runs
        if run["status_code"] == 200
    ]

    api_values = [
        float(run["api_elapsed_ms"])
        for run in successful
        if run["api_elapsed_ms"] is not None
    ]

    generation_values = [
        float(run["generation_time_ms"])
        for run in successful
        if run["generation_time_ms"] is not None
    ]

    failed_pair_values = [
        int(run["failed_pairs"])
        for run in successful
        if run["failed_pairs"] is not None
    ]

    cache_hit_values = [
        bool(run["cache_hit"])
        for run in successful
        if run["cache_hit"] is not None
    ]

    return {
        "request_count": len(runs),
        "success_count": len(successful),
        "failure_count": len(runs) - len(successful),
        "success_rate_percent": round((len(successful) / len(runs)) * 100, 3)
        if runs
        else 0.0,
        "api_elapsed_ms": {
            "min": round(min(api_values), 3) if api_values else None,
            "mean": round(statistics.mean(api_values), 3) if api_values else None,
            "median": round(statistics.median(api_values), 3) if api_values else None,
            "p95": _percentile(api_values, 95),
            "p99": _percentile(api_values, 99),
            "max": round(max(api_values), 3) if api_values else None,
        },
        "generation_time_ms": {
            "min": round(min(generation_values), 3) if generation_values else None,
            "mean": round(statistics.mean(generation_values), 3)
            if generation_values
            else None,
            "median": round(statistics.median(generation_values), 3)
            if generation_values
            else None,
            "p95": _percentile(generation_values, 95),
            "p99": _percentile(generation_values, 99),
            "max": round(max(generation_values), 3) if generation_values else None,
        },
        "failed_pairs": {
            "values": failed_pair_values,
            "all_zero": all(value == 0 for value in failed_pair_values)
            if failed_pair_values
            else False,
        },
        "cache": {
            "hit_values": cache_hit_values,
            "all_hits": all(cache_hit_values) if cache_hit_values else False,
            "any_hit": any(cache_hit_values) if cache_hit_values else False,
        },
    }


def _run_concurrency_level(
    *,
    base_url: str,
    locations: list[dict[str, Any]],
    algorithm: str,
    use_cache: bool,
    concurrency: int,
    requests_per_level: int,
) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []

    started_at = time.perf_counter()

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                _post_matrix,
                base_url=base_url,
                locations=locations,
                algorithm=algorithm,
                use_cache=use_cache,
                request_index=request_index + 1,
            )
            for request_index in range(requests_per_level)
        ]

        for future in as_completed(futures):
            runs.append(future.result())

    elapsed_s = round(time.perf_counter() - started_at, 3)

    return {
        "concurrency": concurrency,
        "requests_per_level": requests_per_level,
        "elapsed_s": elapsed_s,
        "summary": _summary(runs),
        "runs": sorted(runs, key=lambda item: item["request_index"]),
    }


def run_stress_probe(
    *,
    mode: str,
    base_url: str,
    n: int,
    algorithm: str,
    use_cache: bool,
    prewarm_cache: bool,
    concurrency_levels: list[int],
    requests_per_level: int,
) -> dict[str, Any]:
    if n < 2:
        raise ValueError("n must be at least 2.")

    if n > len(KANPUR_TEST_LOCATIONS):
        raise ValueError(f"n must be <= {len(KANPUR_TEST_LOCATIONS)}.")

    locations = KANPUR_TEST_LOCATIONS[:n]

    result: dict[str, Any] = {
        "benchmark": "phase5_stress_probe",
        "mode": mode,
        "base_url": base_url,
        "matrix_size": n,
        "algorithm": algorithm,
        "use_cache": use_cache,
        "prewarm_cache": prewarm_cache,
        "concurrency_levels": concurrency_levels,
        "requests_per_level": requests_per_level,
        "locations": locations,
        "levels": [],
    }

    if use_cache and prewarm_cache:
        result["prewarm_request"] = _post_matrix(
            base_url=base_url,
            locations=locations,
            algorithm=algorithm,
            use_cache=True,
            request_index=0,
        )

    for concurrency in concurrency_levels:
        result["levels"].append(
            _run_concurrency_level(
                base_url=base_url,
                locations=locations,
                algorithm=algorithm,
                use_cache=use_cache,
                concurrency=concurrency,
                requests_per_level=requests_per_level,
            )
        )

    return result


def _output_path(
    *,
    mode: str,
    n: int,
    algorithm: str,
    use_cache: bool,
) -> Path:
    output_dir = Path("benchmarks") / "phase5" / f"{mode}_results"
    output_dir.mkdir(parents=True, exist_ok=True)

    cache_label = "cache_on" if use_cache else "cache_off"

    return output_dir / f"phase5_stress_{algorithm}_{cache_label}_{n}x{n}.json"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 5 stress probe for matrix endpoint."
    )

    parser.add_argument("--mode", choices=["local", "docker"], required=True)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--n", type=int, default=25)
    parser.add_argument("--algorithm", default="source_dijkstra")
    parser.add_argument("--use-cache", action="store_true")
    parser.add_argument("--prewarm-cache", action="store_true")
    parser.add_argument(
        "--concurrency-levels",
        default="1,2,4",
        help="Comma-separated concurrency levels, for example: 1,2,4",
    )
    parser.add_argument("--requests-per-level", type=int, default=4)

    args = parser.parse_args()

    base_url = args.base_url

    if base_url is None:
        base_url = LOCAL_BASE_URL if args.mode == "local" else DOCKER_BASE_URL

    concurrency_levels = [
        int(value.strip())
        for value in args.concurrency_levels.split(",")
        if value.strip()
    ]

    output_path = _output_path(
        mode=args.mode,
        n=args.n,
        algorithm=args.algorithm,
        use_cache=args.use_cache,
    )

    try:
        result = run_stress_probe(
            mode=args.mode,
            base_url=base_url,
            n=args.n,
            algorithm=args.algorithm,
            use_cache=args.use_cache,
            prewarm_cache=args.prewarm_cache,
            concurrency_levels=concurrency_levels,
            requests_per_level=args.requests_per_level,
        )

    except Exception as exc:
        result = {
            "benchmark": "phase5_stress_probe",
            "mode": args.mode,
            "base_url": base_url,
            "matrix_size": args.n,
            "algorithm": args.algorithm,
            "use_cache": args.use_cache,
            "error": type(exc).__name__,
            "message": str(exc),
        }

    output_path.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print("Phase 5 stress probe complete")
    print(f"Mode: {args.mode}")
    print(f"Base URL: {base_url}")
    print(f"Matrix size: {args.n}x{args.n}")
    print(f"Algorithm: {args.algorithm}")
    print(f"Use cache: {args.use_cache}")
    print(f"Output: {output_path}")

    for level in result.get("levels", []):
        summary = level["summary"]

        print("")
        print(f"Concurrency: {level['concurrency']}")
        print("Success rate %:", summary["success_rate_percent"])
        print("API median ms:", summary["api_elapsed_ms"]["median"])
        print("API p95 ms:", summary["api_elapsed_ms"]["p95"])
        print("Generation median ms:", summary["generation_time_ms"]["median"])
        print("Generation p95 ms:", summary["generation_time_ms"]["p95"])
        print("Failed pairs all zero:", summary["failed_pairs"]["all_zero"])
        print("Cache all hits:", summary["cache"]["all_hits"])


if __name__ == "__main__":
    main()