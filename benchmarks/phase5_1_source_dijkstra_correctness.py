# benchmarks/phase5_1_source_dijkstra_correctness.py

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any
from urllib import parse

from phase5_1_algorithm_comparison import (
    DOCKER_BASE_URL,
    KANPUR_TEST_LOCATIONS,
    LOCAL_BASE_URL,
    _compare_matrices,
    _get_json,
    _http_json,
    _post_matrix,
)


def _is_square_matrix(matrix: Any, n: int) -> bool:
    if not isinstance(matrix, list):
        return False

    if len(matrix) != n:
        return False

    return all(isinstance(row, list) and len(row) == n for row in matrix)


def _diagonal_zero(matrix: list[list[float | None]]) -> bool:
    for index, row in enumerate(matrix):
        if row[index] != 0.0:
            return False

    return True


def _selected_pairs(n: int) -> list[tuple[int, int]]:
    candidate_pairs = [
        (0, 1),
        (1, 0),
        (0, n - 1),
        (n - 1, 0),
        (n // 2, n - 1),
        (n - 1, n // 2),
        (1, n // 2),
        (n // 2, 1),
    ]

    clean_pairs: list[tuple[int, int]] = []

    for from_index, to_index in candidate_pairs:
        if from_index == to_index:
            continue

        if 0 <= from_index < n and 0 <= to_index < n:
            pair = (from_index, to_index)

            if pair not in clean_pairs:
                clean_pairs.append(pair)

    return clean_pairs


def _get_route(
    *,
    base_url: str,
    start: dict[str, Any],
    end: dict[str, Any],
) -> dict[str, Any]:
    query = parse.urlencode(
        {
            "start_lat": start["lat"],
            "start_lon": start["lon"],
            "end_lat": end["lat"],
            "end_lon": end["lon"],
        }
    )

    started_at = time.perf_counter()

    status_code, response_payload = _http_json(
        method="GET",
        url=f"{base_url}/route?{query}",
        timeout_s=120,
    )

    api_elapsed_ms = round((time.perf_counter() - started_at) * 1000, 3)

    return {
        "status_code": status_code,
        "api_elapsed_ms": api_elapsed_ms,
        "response": response_payload,
    }


def _extract_route_distance_m(route_response: dict[str, Any]) -> float | None:
    if not isinstance(route_response, dict):
        return None

    value = route_response.get("distance_m")

    if value is None:
        return None

    return round(float(value), 3)


def _compare_selected_matrix_cells_to_route(
    *,
    base_url: str,
    locations: list[dict[str, Any]],
    matrix_distance_m: list[list[float | None]],
    tolerance_m: float,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []

    for from_index, to_index in _selected_pairs(len(locations)):
        start = locations[from_index]
        end = locations[to_index]

        route_result = _get_route(
            base_url=base_url,
            start=start,
            end=end,
        )

        route_distance_m = None

        if route_result["status_code"] == 200:
            route_distance_m = _extract_route_distance_m(route_result["response"])

        matrix_distance_m_value = matrix_distance_m[from_index][to_index]

        check = {
            "from_index": from_index,
            "to_index": to_index,
            "from_id": start["id"],
            "to_id": end["id"],
            "route_status_code": route_result["status_code"],
            "route_distance_m": route_distance_m,
            "matrix_distance_m": matrix_distance_m_value,
            "match": False,
        }

        if route_distance_m is not None and matrix_distance_m_value is not None:
            difference_m = abs(float(route_distance_m) - float(matrix_distance_m_value))

            check["difference_m"] = round(difference_m, 6)
            check["match"] = difference_m <= tolerance_m

        if not check["match"]:
            mismatches.append(check)

        checks.append(check)

    return {
        "checked_pair_count": len(checks),
        "mismatch_count": len(mismatches),
        "all_selected_pairs_match": len(mismatches) == 0,
        "checks": checks,
        "mismatches": mismatches,
    }


def run_correctness_probe(
    *,
    mode: str,
    base_url: str,
    n: int,
    tolerance_m: float,
    compare_bidirectional: bool,
) -> dict[str, Any]:
    if n < 2:
        raise ValueError("n must be at least 2 for /matrix service validation.")

    if n > len(KANPUR_TEST_LOCATIONS):
        raise ValueError(f"n must be <= {len(KANPUR_TEST_LOCATIONS)}.")

    locations = KANPUR_TEST_LOCATIONS[:n]

    result: dict[str, Any] = {
        "benchmark": "phase5_1_source_dijkstra_correctness",
        "mode": mode,
        "base_url": base_url,
        "matrix_size": n,
        "tolerance_m": tolerance_m,
        "compare_bidirectional": compare_bidirectional,
        "locations": locations,
        "health": _get_json(base_url, "/health"),
        "graph_stats": _get_json(base_url, "/graph/stats"),
    }

    source_result = _post_matrix(
        base_url=base_url,
        locations=locations,
        algorithm="source_dijkstra",
        use_cache=False,
    )

    result["source_dijkstra_matrix_request"] = source_result

    if source_result["status_code"] != 200 or not isinstance(
        source_result["response"],
        dict,
    ):
        result["acceptance_checks"] = {
            "matrix_request_200": False,
            "distance_shape_ok": False,
            "eta_shape_ok": False,
            "diagonal_zero": False,
            "failed_pairs_zero": False,
            "computed_pairs_equals_pair_count": False,
            "selected_route_pairs_match": False,
            "route_mismatch_count": None,
            "bidirectional_matrix_match": None,
        }

        return result

    response = source_result["response"]

    matrix_distance_m = response["matrix_distance_m"]
    matrix_eta_s = response["matrix_eta_s"]

    distance_shape_ok = _is_square_matrix(matrix_distance_m, n)
    eta_shape_ok = _is_square_matrix(matrix_eta_s, n)

    diagonal_zero = False

    if distance_shape_ok and eta_shape_ok:
        diagonal_zero = _diagonal_zero(matrix_distance_m) and _diagonal_zero(
            matrix_eta_s
        )

    selected_route_comparison = _compare_selected_matrix_cells_to_route(
        base_url=base_url,
        locations=locations,
        matrix_distance_m=matrix_distance_m,
        tolerance_m=tolerance_m,
    )

    result["selected_route_comparison"] = selected_route_comparison

    bidirectional_matrix_comparison: dict[str, Any] | None = None

    if compare_bidirectional:
        bidirectional_result = _post_matrix(
            base_url=base_url,
            locations=locations,
            algorithm="bidirectional_astar",
            use_cache=False,
        )

        result["bidirectional_astar_matrix_request"] = bidirectional_result

        if (
            bidirectional_result["status_code"] == 200
            and isinstance(bidirectional_result["response"], dict)
        ):
            bidirectional_matrix_comparison = _compare_matrices(
                bidirectional_result["response"]["matrix_distance_m"],
                matrix_distance_m,
                tolerance_m=tolerance_m,
            )

            result["bidirectional_matrix_comparison"] = (
                bidirectional_matrix_comparison
            )

    result["acceptance_checks"] = {
        "matrix_request_200": True,
        "distance_shape_ok": distance_shape_ok,
        "eta_shape_ok": eta_shape_ok,
        "diagonal_zero": diagonal_zero,
        "failed_pairs_zero": int(response.get("failed_pairs", -1)) == 0,
        "computed_pairs_equals_pair_count": response.get("computed_pairs")
        == response.get("pair_count"),
        "selected_route_pairs_match": selected_route_comparison[
            "all_selected_pairs_match"
        ],
        "route_mismatch_count": selected_route_comparison["mismatch_count"],
        "bidirectional_matrix_match": (
            bidirectional_matrix_comparison["mismatch_count"] == 0
            if bidirectional_matrix_comparison is not None
            else None
        ),
    }

    return result


def _output_path(mode: str, n: int) -> Path:
    output_dir = Path("benchmarks") / "phase5_1" / f"{mode}_results"
    output_dir.mkdir(parents=True, exist_ok=True)

    return output_dir / f"phase5_1_source_dijkstra_correctness_{n}x{n}.json"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate Phase 5.1 source_dijkstra matrix correctness."
    )

    parser.add_argument("--mode", choices=["local", "docker"], required=True)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--n", type=int, default=15)
    parser.add_argument("--tolerance-m", type=float, default=0.01)
    parser.add_argument(
        "--compare-bidirectional",
        action="store_true",
        help="Also compare source_dijkstra matrix against bidirectional_astar matrix.",
    )

    args = parser.parse_args()

    base_url = args.base_url

    if base_url is None:
        base_url = LOCAL_BASE_URL if args.mode == "local" else DOCKER_BASE_URL

    output_path = _output_path(args.mode, args.n)

    try:
        result = run_correctness_probe(
            mode=args.mode,
            base_url=base_url,
            n=args.n,
            tolerance_m=args.tolerance_m,
            compare_bidirectional=args.compare_bidirectional,
        )

    except Exception as exc:
        result = {
            "benchmark": "phase5_1_source_dijkstra_correctness",
            "mode": args.mode,
            "base_url": base_url,
            "matrix_size": args.n,
            "tolerance_m": args.tolerance_m,
            "error": type(exc).__name__,
            "message": str(exc),
        }

    output_path.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print("Phase 5.1 source_dijkstra correctness probe complete")
    print(f"Mode: {args.mode}")
    print(f"Base URL: {base_url}")
    print(f"Matrix size: {args.n}x{args.n}")
    print(f"Tolerance m: {args.tolerance_m}")
    print(f"Output: {output_path}")

    checks = result.get("acceptance_checks")

    if checks is None:
        print("Probe failed before acceptance checks were produced.")
        print("Error:", result.get("message"))
        return

    print("Matrix request 200:", checks["matrix_request_200"])
    print("Shape OK:", checks["distance_shape_ok"] and checks["eta_shape_ok"])
    print("Diagonal zero:", checks["diagonal_zero"])
    print("Failed pairs zero:", checks["failed_pairs_zero"])
    print("Computed pairs equals pair count:", checks["computed_pairs_equals_pair_count"])
    print("Selected route pairs match:", checks["selected_route_pairs_match"])
    print("Route mismatch count:", checks["route_mismatch_count"])
    print("Bidirectional matrix match:", checks["bidirectional_matrix_match"])


if __name__ == "__main__":
    main()