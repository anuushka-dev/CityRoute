from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

KANPUR_START = {"lat": 26.4549, "lon": 80.3506}

KANPUR_STOPS = [
    {"lat": 26.4558, "lon": 80.3520},
    {"lat": 26.4570, "lon": 80.3492},
    {"lat": 26.4525, "lon": 80.3480},
    {"lat": 26.4512, "lon": 80.3518},
    {"lat": 26.4595, "lon": 80.3535},
    {"lat": 26.4610, "lon": 80.3478},
    {"lat": 26.4489, "lon": 80.3470},
    {"lat": 26.4475, "lon": 80.3528},
]


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _safe_round(value: Any) -> float | None:
    if value is None:
        return None

    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _http_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout_s: float = 180.0,
) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}

    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url=url, data=body, headers=headers, method=method)

    try:
        with urlopen(request, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8")
            return {
                "ok": True,
                "status_code": response.status,
                "body": json.loads(raw) if raw else None,
            }

    except HTTPError as exc:
        raw = exc.read().decode("utf-8")

        try:
            body_json: Any = json.loads(raw)
        except json.JSONDecodeError:
            body_json = raw

        return {
            "ok": False,
            "status_code": exc.code,
            "body": body_json,
        }

    except URLError as exc:
        return {
            "ok": False,
            "status_code": None,
            "body": {
                "error": "URL error",
                "message": str(exc),
            },
        }


def _distance_value(cell: Any) -> float:
    if isinstance(cell, (int, float)):
        return float(cell)

    if cell is None:
        return -1.0

    if isinstance(cell, dict):
        for key in (
            "distance_m",
            "distance_meters",
            "route_distance_m",
            "total_distance_m",
            "value",
        ):
            value = cell.get(key)
            if value is not None:
                return float(value)

    for attr in (
        "distance_m",
        "distance_meters",
        "route_distance_m",
        "total_distance_m",
        "value",
    ):
        if hasattr(cell, attr):
            return float(getattr(cell, attr))

    raise ValueError(f"Unsupported matrix cell format: {type(cell).__name__}")


def _normalize_matrix(raw_matrix: Any) -> list[list[float]]:
    if not isinstance(raw_matrix, list) or not raw_matrix:
        raise ValueError("matrix must be a non-empty list")

    matrix: list[list[float]] = []

    for row in raw_matrix:
        if not isinstance(row, list):
            raise ValueError("matrix rows must be lists")

        matrix.append([_distance_value(cell) for cell in row])

    size = len(matrix)

    if any(len(row) != size for row in matrix):
        raise ValueError("matrix must be square")

    return matrix


def _extract_matrix(matrix_response_body: dict[str, Any]) -> list[list[float]]:
    for field_name in (
        "matrix_distance_m",
        "matrix",
        "distance_matrix",
        "distances",
        "distances_m",
        "distance_matrix_m",
        "distance_matrix_meters",
    ):
        raw_matrix = matrix_response_body.get(field_name)

        if raw_matrix is not None:
            return _normalize_matrix(raw_matrix)

    raise ValueError("matrix response body does not contain distance matrix")

def _route_distance(
    order: tuple[int, ...],
    matrix: list[list[float]],
    *,
    return_to_start: bool,
) -> float:
    total = 0.0
    current_matrix_index = 0

    for stop_index in order:
        next_matrix_index = stop_index + 1
        distance = matrix[current_matrix_index][next_matrix_index]

        if distance < 0:
            return -1.0

        total += distance
        current_matrix_index = next_matrix_index

    if return_to_start:
        distance = matrix[current_matrix_index][0]

        if distance < 0:
            return -1.0

        total += distance

    return round(total, 3)


def _exact_optimum(
    matrix: list[list[float]],
    *,
    stop_count: int,
    return_to_start: bool,
) -> dict[str, Any]:
    best_order: tuple[int, ...] | None = None
    best_distance = float("inf")
    evaluated = 0
    reachable = 0

    for order in itertools.permutations(range(stop_count)):
        evaluated += 1

        distance = _route_distance(
            order,
            matrix,
            return_to_start=return_to_start,
        )

        if distance < 0:
            continue

        reachable += 1

        if distance < best_distance:
            best_distance = distance
            best_order = order

    if best_order is None:
        raise ValueError("no reachable exact route found")

    return {
        "exact_order": list(best_order),
        "exact_distance_m": round(best_distance, 3),
        "permutations_evaluated": evaluated,
        "reachable_permutations": reachable,
    }


def _build_matrix_payload(
    *,
    stop_count: int,
    matrix_algorithm: str,
    use_cache: bool,
) -> dict[str, Any]:
    locations: list[dict[str, Any]] = [
        {
            "id": "start",
            "lat": KANPUR_START["lat"],
            "lon": KANPUR_START["lon"],
        }
    ]

    for index, stop in enumerate(KANPUR_STOPS[:stop_count]):
        locations.append(
            {
                "id": f"stop_{index}",
                "lat": stop["lat"],
                "lon": stop["lon"],
            }
        )

    return {
        "locations": locations,
        "algorithm": matrix_algorithm,
        "use_cache": use_cache,
    }


def _build_advanced_payload(
    *,
    stop_count: int,
    return_to_start: bool,
    matrix_algorithm: str,
    use_cache: bool,
    two_opt_max_iterations: int,
    lns_max_iterations: int,
    lns_destroy_fraction: float,
    lns_no_improvement_limit: int,
    seed: int,
    keep_trace: bool,
) -> dict[str, Any]:
    return {
        "start": KANPUR_START,
        "stops": KANPUR_STOPS[:stop_count],
        "return_to_start": return_to_start,
        "matrix_algorithm": matrix_algorithm,
        "use_cache": use_cache,
        "two_opt_max_iterations": two_opt_max_iterations,
        "two_opt_improvement_tolerance_m": 0.001,
        "lns_max_iterations": lns_max_iterations,
        "lns_destroy_fraction": lns_destroy_fraction,
        "lns_no_improvement_limit": lns_no_improvement_limit,
        "lns_random_seed": seed,
        "keep_trace": keep_trace,
    }


def _gap_pct(candidate_distance_m: float, exact_distance_m: float) -> float:
    if exact_distance_m <= 0:
        return 0.0

    return round(((candidate_distance_m - exact_distance_m) / exact_distance_m) * 100.0, 3)


def _run_case(
    *,
    base_url: str,
    stop_count: int,
    return_to_start: bool,
    matrix_algorithm: str,
    use_cache: bool,
    two_opt_max_iterations: int,
    lns_max_iterations: int,
    lns_destroy_fraction: float,
    lns_no_improvement_limit: int,
    seed: int,
    keep_trace: bool,
    timeout_s: float,
) -> dict[str, Any]:
    matrix_payload = _build_matrix_payload(
        stop_count=stop_count,
        matrix_algorithm=matrix_algorithm,
        use_cache=use_cache,
    )

    matrix_start = time.perf_counter()
    matrix_response = _http_json(
        "POST",
        f"{base_url}/matrix",
        payload=matrix_payload,
        timeout_s=timeout_s,
    )
    matrix_elapsed_ms = round((time.perf_counter() - matrix_start) * 1000.0, 3)

    if not matrix_response.get("ok") or not isinstance(matrix_response.get("body"), dict):
        return {
            "success": False,
            "stage": "matrix",
            "stop_count": stop_count,
            "return_to_start": return_to_start,
            "seed": seed,
            "matrix_elapsed_ms": matrix_elapsed_ms,
            "matrix_response": matrix_response,
        }

    matrix = _extract_matrix(matrix_response["body"])

    exact_start = time.perf_counter()
    exact = _exact_optimum(
        matrix,
        stop_count=stop_count,
        return_to_start=return_to_start,
    )
    exact_elapsed_ms = round((time.perf_counter() - exact_start) * 1000.0, 3)

    advanced_payload = _build_advanced_payload(
        stop_count=stop_count,
        return_to_start=return_to_start,
        matrix_algorithm=matrix_algorithm,
        use_cache=use_cache,
        two_opt_max_iterations=two_opt_max_iterations,
        lns_max_iterations=lns_max_iterations,
        lns_destroy_fraction=lns_destroy_fraction,
        lns_no_improvement_limit=lns_no_improvement_limit,
        seed=seed,
        keep_trace=keep_trace,
    )

    advanced_start = time.perf_counter()
    advanced_response = _http_json(
        "POST",
        f"{base_url}/vrp/compare/advanced",
        payload=advanced_payload,
        timeout_s=timeout_s,
    )
    advanced_elapsed_ms = round((time.perf_counter() - advanced_start) * 1000.0, 3)

    if not advanced_response.get("ok") or not isinstance(advanced_response.get("body"), dict):
        return {
            "success": False,
            "stage": "advanced_compare",
            "stop_count": stop_count,
            "return_to_start": return_to_start,
            "seed": seed,
            "matrix_elapsed_ms": matrix_elapsed_ms,
            "exact_elapsed_ms": exact_elapsed_ms,
            "advanced_elapsed_ms": advanced_elapsed_ms,
            "exact": exact,
            "advanced_response": advanced_response,
        }

    body = advanced_response["body"]

    greedy_distance = _safe_round(body.get("greedy", {}).get("total_distance_m"))
    two_opt_distance = _safe_round(body.get("two_opt", {}).get("total_distance_m"))
    lns_distance = _safe_round(body.get("lns", {}).get("total_distance_m"))
    exact_distance = float(exact["exact_distance_m"])

    if greedy_distance is None or two_opt_distance is None or lns_distance is None:
        raise ValueError("advanced response missing algorithm distances")

    return {
        "success": True,
        "stage": "complete",
        "stop_count": stop_count,
        "return_to_start": return_to_start,
        "seed": seed,
        "matrix_algorithm": matrix_algorithm,
        "use_cache": use_cache,
        "exact": exact,
        "greedy": {
            "order": body.get("greedy", {}).get("optimized_order"),
            "distance_m": greedy_distance,
            "gap_to_exact_pct": _gap_pct(greedy_distance, exact_distance),
        },
        "two_opt": {
            "order": body.get("two_opt", {}).get("optimized_order"),
            "distance_m": two_opt_distance,
            "gap_to_exact_pct": _gap_pct(two_opt_distance, exact_distance),
        },
        "lns": {
            "order": body.get("lns", {}).get("optimized_order"),
            "distance_m": lns_distance,
            "gap_to_exact_pct": _gap_pct(lns_distance, exact_distance),
            "iterations_run": body.get("lns", {}).get("iterations_run"),
            "improvements_applied": body.get("lns", {}).get("improvements_applied"),
            "converged": body.get("lns", {}).get("converged"),
            "trace_length": len(body.get("lns", {}).get("trace", [])),
        },
        "comparison": body.get("comparison", {}),
        "timings_ms": {
            "matrix_elapsed_ms": matrix_elapsed_ms,
            "exact_elapsed_ms": exact_elapsed_ms,
            "advanced_elapsed_ms": advanced_elapsed_ms,
            "api_total_time_ms": _safe_round(body.get("total_time_ms")),
            "matrix_generation_time_ms": _safe_round(body.get("matrix_generation_time_ms")),
            "lns_optimization_time_ms": _safe_round(
                body.get("lns", {}).get("optimization_time_ms")
            ),
        },
        "cache": {
            "cache_used": body.get("cache_used"),
            "cache_status": body.get("cache_status"),
            "cache_hits": body.get("cache_hits"),
            "cache_misses": body.get("cache_misses"),
        },
        "non_regression": {
            "two_opt_non_regression": body.get("comparison", {}).get(
                "two_opt_non_regression"
            ),
            "lns_non_regression": body.get("comparison", {}).get("lns_non_regression"),
            "greedy_ge_exact": greedy_distance >= exact_distance,
            "two_opt_ge_exact": two_opt_distance >= exact_distance,
            "lns_ge_exact": lns_distance >= exact_distance,
        },
    }


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    base_url = args.base_url.rstrip("/")
    output_dir = Path(args.output_dir)

    health = _http_json("GET", f"{base_url}/health", timeout_s=args.timeout_s)
    graph_stats = _http_json("GET", f"{base_url}/graph/stats", timeout_s=args.timeout_s)
    openapi = _http_json("GET", f"{base_url}/openapi.json", timeout_s=args.timeout_s)

    endpoint_available = False
    matrix_available = False

    if openapi.get("ok") and isinstance(openapi.get("body"), dict):
        paths = openapi["body"].get("paths", {})
        endpoint_available = "/vrp/compare/advanced" in paths
        matrix_available = "/matrix" in paths

    raw_cases: list[dict[str, Any]] = []

    for stop_count in args.sizes:
        for return_to_start in args.return_modes:
            seed = args.seed + stop_count * 100 + int(return_to_start)

            print(
                f"[gap-probe] stop_count={stop_count} "
                f"return_to_start={return_to_start} seed={seed}"
            )

            case = _run_case(
                base_url=base_url,
                stop_count=stop_count,
                return_to_start=return_to_start,
                matrix_algorithm=args.matrix_algorithm,
                use_cache=args.use_cache,
                two_opt_max_iterations=args.two_opt_max_iterations,
                lns_max_iterations=args.lns_max_iterations,
                lns_destroy_fraction=args.lns_destroy_fraction,
                lns_no_improvement_limit=args.lns_no_improvement_limit,
                seed=seed,
                keep_trace=args.keep_trace,
                timeout_s=args.timeout_s,
            )

            raw_cases.append(case)

            print(
                f"  success={case.get('success')} "
                f"exact={case.get('exact', {}).get('exact_distance_m')} "
                f"lns={case.get('lns', {}).get('distance_m')} "
                f"lns_gap_pct={case.get('lns', {}).get('gap_to_exact_pct')}"
            )

    successes = [case for case in raw_cases if case.get("success")]
    failures = [case for case in raw_cases if not case.get("success")]

    lns_gaps = [
        float(case["lns"]["gap_to_exact_pct"])
        for case in successes
        if case.get("lns", {}).get("gap_to_exact_pct") is not None
    ]

    two_opt_gaps = [
        float(case["two_opt"]["gap_to_exact_pct"])
        for case in successes
        if case.get("two_opt", {}).get("gap_to_exact_pct") is not None
    ]

    greedy_gaps = [
        float(case["greedy"]["gap_to_exact_pct"])
        for case in successes
        if case.get("greedy", {}).get("gap_to_exact_pct") is not None
    ]

    summary = {
        "phase": "tier3_phase8",
        "probe": "lns_optimality_gap",
        "created_at_utc": _utc_now_iso(),
        "mode": args.mode,
        "base_url": base_url,
        "sizes": args.sizes,
        "return_modes": args.return_modes,
        "matrix_algorithm": args.matrix_algorithm,
        "use_cache": args.use_cache,
        "keep_trace": args.keep_trace,
        "settings": {
            "two_opt_max_iterations": args.two_opt_max_iterations,
            "lns_max_iterations": args.lns_max_iterations,
            "lns_destroy_fraction": args.lns_destroy_fraction,
            "lns_no_improvement_limit": args.lns_no_improvement_limit,
            "seed_base": args.seed,
        },
        "preflight": {
            "health_ok": bool(health.get("ok")),
            "health": health.get("body"),
            "graph_stats_ok": bool(graph_stats.get("ok")),
            "graph_stats": graph_stats.get("body"),
            "openapi_ok": bool(openapi.get("ok")),
            "matrix_endpoint_available": matrix_available,
            "advanced_endpoint_available": endpoint_available,
        },
        "case_count": len(raw_cases),
        "success_count": len(successes),
        "failure_count": len(failures),
        "success_rate_pct": round((len(successes) / len(raw_cases)) * 100.0, 3)
        if raw_cases
        else 0.0,
        "gap_summary_pct": {
            "greedy_best": round(min(greedy_gaps), 3) if greedy_gaps else None,
            "greedy_worst": round(max(greedy_gaps), 3) if greedy_gaps else None,
            "two_opt_best": round(min(two_opt_gaps), 3) if two_opt_gaps else None,
            "two_opt_worst": round(max(two_opt_gaps), 3) if two_opt_gaps else None,
            "lns_best": round(min(lns_gaps), 3) if lns_gaps else None,
            "lns_worst": round(max(lns_gaps), 3) if lns_gaps else None,
        },
        "quality_flags": {
            "all_cases_successful": len(successes) == len(raw_cases),
            "all_lns_non_regression": all(
                bool(case.get("non_regression", {}).get("lns_non_regression"))
                for case in successes
            )
            if successes
            else False,
            "all_two_opt_non_regression": all(
                bool(case.get("non_regression", {}).get("two_opt_non_regression"))
                for case in successes
            )
            if successes
            else False,
            "all_lns_at_or_above_exact": all(
                bool(case.get("non_regression", {}).get("lns_ge_exact"))
                for case in successes
            )
            if successes
            else False,
        },
        "cases": raw_cases,
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = output_dir / f"phase8_lns_optimality_gap_summary_{args.mode}_{timestamp}.json"
    raw_path = output_dir / f"phase8_lns_optimality_gap_raw_{args.mode}_{timestamp}.json"

    _write_json(summary_path, summary)
    _write_json(raw_path, raw_cases)

    print()
    print(f"Summary saved: {summary_path}")
    print(f"Raw cases saved: {raw_path}")

    return summary


def _parse_return_modes(values: list[str]) -> list[bool]:
    modes: list[bool] = []

    for value in values:
        normalized = value.lower().strip()

        if normalized in {"open", "false", "0", "no"}:
            modes.append(False)
        elif normalized in {"return", "true", "1", "yes"}:
            modes.append(True)
        else:
            raise argparse.ArgumentTypeError(
                "return modes must be one of: open, return, true, false"
            )

    return modes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 8 exact optimality-gap probe for small LNS VRP cases"
    )

    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--mode", choices=["docker", "local"], default="docker")
    parser.add_argument("--output-dir", default="benchmarks/phase_8/docker_results")

    parser.add_argument(
        "--sizes",
        nargs="+",
        type=int,
        default=[5, 6, 7],
        help="Small exact sizes only. 8 is already 40320 permutations.",
    )
    parser.add_argument(
        "--return-modes",
        nargs="+",
        type=str,
        default=["open", "return"],
    )

    parser.add_argument("--matrix-algorithm", default="source_dijkstra")
    parser.add_argument("--use-cache", action=argparse.BooleanOptionalAction, default=True)

    parser.add_argument("--two-opt-max-iterations", type=int, default=100)
    parser.add_argument("--lns-max-iterations", type=int, default=500)
    parser.add_argument("--lns-destroy-fraction", type=float, default=0.30)
    parser.add_argument("--lns-no-improvement-limit", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)

    parser.add_argument("--keep-trace", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout-s", type=float, default=180.0)

    args = parser.parse_args()

    args.return_modes = _parse_return_modes(args.return_modes)

    if any(size < 1 or size > len(KANPUR_STOPS) for size in args.sizes):
        parser.error(f"all sizes must be between 1 and {len(KANPUR_STOPS)}")

    if any(size > 8 for size in args.sizes):
        parser.error("exact optimality probe should not exceed 8 stops")

    if args.mode == "local" and args.output_dir == "benchmarks/phase_8/docker_results":
        args.output_dir = "benchmarks/phase_8/local_results"

    return args


def main() -> int:
    args = parse_args()

    try:
        summary = run_probe(args)
    except KeyboardInterrupt:
        print("Optimality-gap probe interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Optimality-gap probe failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    flags = summary["quality_flags"]

    if not flags["all_cases_successful"]:
        return 2

    if not flags["all_two_opt_non_regression"]:
        return 3

    if not flags["all_lns_non_regression"]:
        return 4

    if not flags["all_lns_at_or_above_exact"]:
        return 5

    return 0


if __name__ == "__main__":
    raise SystemExit(main())