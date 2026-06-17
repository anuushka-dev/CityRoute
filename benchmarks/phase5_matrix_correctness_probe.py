# benchmarks/phase5_matrix_correctness_probe.py

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


def _build_locations(n: int, run_id: str) -> list[dict[str, Any]]:
    if n < 2:
        raise ValueError("Correctness probe requires n >= 2.")

    if n > len(KANPUR_POINTS):
        raise ValueError(
            f"Only {len(KANPUR_POINTS)} fixed Kanpur points are available. "
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
        timeout=180.0,
    )

    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)

    try:
        data = response.json()
    except Exception:
        data = {"raw_text": response.text}

    return data, elapsed_ms, response.status_code


def _extract_route_distance_m(data: dict[str, Any]) -> float | None:
    for key in ("distance_m", "total_distance_m", "route_distance_m"):
        value = data.get(key)

        if isinstance(value, int | float):
            return float(value)

    if isinstance(data.get("distance_km"), int | float):
        return float(data["distance_km"]) * 1000

    return None


def _get_route_distance(
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


def _validate_shape_and_diagonal(
    *,
    matrix_response: dict[str, Any],
    n: int,
) -> dict[str, Any]:
    distance_matrix = matrix_response.get("matrix_distance_m")
    eta_matrix = matrix_response.get("matrix_eta_s")

    distance_shape_ok = (
        isinstance(distance_matrix, list)
        and len(distance_matrix) == n
        and all(isinstance(row, list) and len(row) == n for row in distance_matrix)
    )

    eta_shape_ok = (
        isinstance(eta_matrix, list)
        and len(eta_matrix) == n
        and all(isinstance(row, list) and len(row) == n for row in eta_matrix)
    )

    diagonal_zero = False

    if distance_shape_ok and eta_shape_ok:
        diagonal_zero = all(
            distance_matrix[index][index] == 0.0
            and eta_matrix[index][index] == 0.0
            for index in range(n)
        )

    return {
        "distance_shape_ok": distance_shape_ok,
        "eta_shape_ok": eta_shape_ok,
        "diagonal_zero": diagonal_zero,
        "n_field_correct": matrix_response.get("n") == n,
        "pair_count_correct": matrix_response.get("pair_count") == n * n,
    }


def _selected_pairs(n: int, max_pairs: int) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []

    for i in range(n):
        for j in range(n):
            if i == j:
                continue

            pairs.append((i, j))

    # Deterministic coverage: first, middle-ish, and later pairs.
    if len(pairs) <= max_pairs:
        return pairs

    step = max(1, len(pairs) // max_pairs)
    selected = pairs[::step][:max_pairs]

    return selected


def _compare_selected_pairs_to_route(
    *,
    client: httpx.Client,
    base_url: str,
    locations: list[dict[str, Any]],
    matrix_distance_m: list[list[float | None]],
    max_pairs: int,
    tolerance_m: float,
) -> dict[str, Any]:
    n = len(locations)
    selected = _selected_pairs(n=n, max_pairs=max_pairs)

    comparisons: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    route_times_ms: list[float] = []

    for from_index, to_index in selected:
        route_result = _get_route_distance(
            client=client,
            base_url=base_url,
            from_location=locations[from_index],
            to_location=locations[to_index],
        )

        route_times_ms.append(route_result["elapsed_ms"])

        matrix_value = matrix_distance_m[from_index][to_index]
        route_value = route_result["distance_m"]

        diff_m = None
        within_tolerance = False

        if matrix_value is not None and route_value is not None:
            diff_m = round(abs(float(matrix_value) - float(route_value)), 3)
            within_tolerance = diff_m <= tolerance_m

        comparison = {
            "from_index": from_index,
            "to_index": to_index,
            "from_id": locations[from_index]["id"],
            "to_id": locations[to_index]["id"],
            "route_status_code": route_result["status_code"],
            "matrix_distance_m": matrix_value,
            "route_distance_m": route_value,
            "diff_m": diff_m,
            "within_tolerance": within_tolerance,
        }

        comparisons.append(comparison)

        if not within_tolerance:
            mismatches.append(comparison)

    return {
        "selected_pair_count": len(selected),
        "tolerance_m": tolerance_m,
        "route_elapsed_ms": {
            "min_ms": round(min(route_times_ms), 3) if route_times_ms else None,
            "mean_ms": round(statistics.mean(route_times_ms), 3) if route_times_ms else None,
            "median_ms": round(statistics.median(route_times_ms), 3) if route_times_ms else None,
            "max_ms": round(max(route_times_ms), 3) if route_times_ms else None,
        },
        "comparison_count": len(comparisons),
        "mismatch_count": len(mismatches),
        "all_compared_pairs_match": len(mismatches) == 0,
        "comparisons": comparisons,
        "mismatches": mismatches,
    }


def _check_directionality(matrix_distance_m: list[list[float | None]]) -> dict[str, Any]:
    """
    Directed road graphs may produce asymmetric distances.

    This check does not require asymmetry.
    It records whether asymmetry exists, and confirms we did not incorrectly
    force matrix[i][j] == matrix[j][i].
    """

    n = len(matrix_distance_m)
    asymmetric_pairs: list[dict[str, Any]] = []

    for i in range(n):
        for j in range(i + 1, n):
            a_to_b = matrix_distance_m[i][j]
            b_to_a = matrix_distance_m[j][i]

            if a_to_b is None or b_to_a is None:
                continue

            diff = abs(float(a_to_b) - float(b_to_a))

            if diff > 1.0:
                asymmetric_pairs.append(
                    {
                        "i": i,
                        "j": j,
                        "distance_i_to_j_m": a_to_b,
                        "distance_j_to_i_m": b_to_a,
                        "diff_m": round(diff, 3),
                    }
                )

    return {
        "asymmetry_detected": len(asymmetric_pairs) > 0,
        "asymmetric_pair_count": len(asymmetric_pairs),
        "sample_asymmetric_pairs": asymmetric_pairs[:10],
    }


def run_correctness_probe(
    *,
    mode: str,
    base_url: str,
    n: int,
    algorithm: str,
    max_route_compare_pairs: int,
    tolerance_m: float,
) -> dict[str, Any]:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    locations = _build_locations(n=n, run_id=run_id)

    with httpx.Client() as client:
        health = _check_health(client, base_url)
        graph_stats = _check_graph_stats(client, base_url)

        matrix_response, matrix_elapsed_ms, matrix_status_code = _post_matrix(
            client=client,
            base_url=base_url,
            locations=locations,
            algorithm=algorithm,
            use_cache=False,
        )

        if matrix_status_code != 200:
            return {
                "artifact": "phase5_matrix_correctness_probe",
                "created_at": _now_iso(),
                "mode": mode,
                "base_url": base_url,
                "n": n,
                "algorithm": algorithm,
                "matrix_status_code": matrix_status_code,
                "matrix_response": matrix_response,
                "error": "POST /matrix did not return 200.",
            }

        shape_checks = _validate_shape_and_diagonal(
            matrix_response=matrix_response,
            n=n,
        )

        matrix_distance_m = matrix_response.get("matrix_distance_m")

        route_comparison = _compare_selected_pairs_to_route(
            client=client,
            base_url=base_url,
            locations=locations,
            matrix_distance_m=matrix_distance_m,
            max_pairs=max_route_compare_pairs,
            tolerance_m=tolerance_m,
        )

    directionality = _check_directionality(matrix_distance_m)

    failed_pairs = matrix_response.get("failed_pairs")
    computed_pairs = matrix_response.get("computed_pairs")
    pair_count = matrix_response.get("pair_count")

    return {
        "artifact": "phase5_matrix_correctness_probe",
        "created_at": _now_iso(),
        "mode": mode,
        "base_url": base_url,
        "matrix_size": f"{n}x{n}",
        "n": n,
        "pairs": n * n,
        "algorithm": algorithm,
        "health": health,
        "graph_stats": graph_stats,
        "matrix_request": {
            "status_code": matrix_status_code,
            "api_elapsed_ms": matrix_elapsed_ms,
            "service_generation_time_ms": matrix_response.get("generation_time_ms"),
            "parallel_workers": matrix_response.get("parallel_workers"),
            "cache": matrix_response.get("cache"),
        },
        "matrix_counts": {
            "pair_count": pair_count,
            "computed_pairs": computed_pairs,
            "failed_pairs": failed_pairs,
            "failures": matrix_response.get("failures", [])[:20],
        },
        "shape_checks": shape_checks,
        "directionality": directionality,
        "route_comparison": route_comparison,
        "acceptance_checks": {
            "matrix_status_200": matrix_status_code == 200,
            "distance_shape_ok": shape_checks["distance_shape_ok"],
            "eta_shape_ok": shape_checks["eta_shape_ok"],
            "diagonal_zero": shape_checks["diagonal_zero"],
            "n_field_correct": shape_checks["n_field_correct"],
            "pair_count_correct": shape_checks["pair_count_correct"],
            "failed_pairs_zero": failed_pairs == 0,
            "selected_route_pairs_match": route_comparison["all_compared_pairs_match"],
            "route_mismatch_count": route_comparison["mismatch_count"],
        },
    }


def save_result(result: dict[str, Any], *, mode: str, n: int) -> Path:
    output_dir = _results_dir_for_mode(mode)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"phase5_matrix_correctness_{n}x{n}.json"

    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 5 matrix correctness probe."
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
        "--max-route-compare-pairs",
        type=int,
        default=20,
        help="How many matrix cells to compare against direct /route calls.",
    )
    parser.add_argument(
        "--tolerance-m",
        type=float,
        default=1.0,
        help="Allowed distance difference between matrix cell and /route result.",
    )

    args = parser.parse_args()
    base_url = args.base_url or _default_base_url_for_mode(args.mode)

    try:
        result = run_correctness_probe(
            mode=args.mode,
            base_url=base_url,
            n=args.n,
            algorithm=args.algorithm,
            max_route_compare_pairs=args.max_route_compare_pairs,
            tolerance_m=args.tolerance_m,
        )

        output_path = save_result(result, mode=args.mode, n=args.n)

    except Exception as exc:
        output_dir = _results_dir_for_mode(args.mode)
        output_dir.mkdir(parents=True, exist_ok=True)

        error_path = output_dir / f"phase5_matrix_correctness_{args.n}x{args.n}_ERROR.json"

        error_payload = {
            "artifact": "phase5_matrix_correctness_probe_error",
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

        print(f"ERROR: correctness probe failed. Error artifact saved to {error_path}")
        print(repr(exc))
        return 1

    print("Phase 5 matrix correctness probe complete")
    print(f"Mode: {args.mode}")
    print(f"Base URL: {base_url}")
    print(f"Matrix size: {args.n}x{args.n}")
    print(f"Output: {output_path}")
    print(
        "Shape OK:",
        result["acceptance_checks"]["distance_shape_ok"]
        and result["acceptance_checks"]["eta_shape_ok"],
    )
    print("Diagonal zero:", result["acceptance_checks"]["diagonal_zero"])
    print("Failed pairs zero:", result["acceptance_checks"]["failed_pairs_zero"])
    print("Selected route pairs match:", result["acceptance_checks"]["selected_route_pairs_match"])
    print("Route mismatch count:", result["acceptance_checks"]["route_mismatch_count"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())