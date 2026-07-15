# benchmarks/phase_10/phase10_haversine_vs_road_probe.py

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

PHASE = "tier3_phase10"
BENCHMARK = "haversine_vs_road"
ENDPOINT = "/dispatch/compare"

DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_DOCKER_BASE_URL = "http://127.0.0.1:8001"

DEFAULT_SIZES = (
    5,
    10,
    25,
    50,
)

DEFAULT_ITERATIONS = 10
DEFAULT_WARMUP = 2
DEFAULT_TIMEOUT_SECONDS = 180.0

KANPUR_CENTER_LAT = 26.4499
KANPUR_CENTER_LON = 80.3319


def parse_sizes(
    raw_value: str,
) -> tuple[int, ...]:
    sizes: list[int] = []

    for item in raw_value.split(","):
        item = item.strip()

        if not item:
            continue

        size = int(item)

        if size < 1:
            raise argparse.ArgumentTypeError(
                "Every benchmark size must be >= 1."
            )

        sizes.append(size)

    if not sizes:
        raise argparse.ArgumentTypeError(
            "At least one benchmark size is required."
        )

    return tuple(sizes)


def percentile(
    values: list[float],
    percentile_value: float,
) -> float:
    if not values:
        return 0.0

    ordered = sorted(values)

    if len(ordered) == 1:
        return ordered[0]

    position = (
        percentile_value
        / 100.0
        * (
            len(ordered)
            - 1
        )
    )

    lower_index = math.floor(position)
    upper_index = math.ceil(position)

    if lower_index == upper_index:
        return ordered[lower_index]

    fraction = position - lower_index

    return (
        ordered[lower_index]
        * (
            1.0
            - fraction
        )
        + ordered[upper_index]
        * fraction
    )


def summarize_values(
    values: list[float],
) -> dict[str, float | int]:
    if not values:
        return {
            "count": 0,
            "min": 0.0,
            "median": 0.0,
            "mean": 0.0,
            "p95": 0.0,
            "max": 0.0,
        }

    return {
        "count": len(values),
        "min": round(
            min(values),
            6,
        ),
        "median": round(
            statistics.median(values),
            6,
        ),
        "mean": round(
            statistics.fmean(values),
            6,
        ),
        "p95": round(
            percentile(
                values,
                95.0,
            ),
            6,
        ),
        "max": round(
            max(values),
            6,
        ),
    }


def safe_ratio(
    numerator: float,
    denominator: float,
) -> float | None:
    if denominator == 0.0:
        return None

    return numerator / denominator


def build_coordinate(
    index: int,
    *,
    latitude_offset: float,
    longitude_offset: float,
) -> tuple[float, float]:
    row = index // 10
    column = index % 10

    lat = (
        KANPUR_CENTER_LAT
        + latitude_offset
        + row * 0.00115
        + column * 0.00017
    )

    lon = (
        KANPUR_CENTER_LON
        + longitude_offset
        + column * 0.00105
        + row * 0.00019
    )

    return (
        round(
            lat,
            7,
        ),
        round(
            lon,
            7,
        ),
    )


def build_payload(
    *,
    size: int,
    matrix_algorithm: str,
) -> dict[str, Any]:
    drivers: list[dict[str, Any]] = []
    orders: list[dict[str, Any]] = []

    for index in range(size):
        driver_lat, driver_lon = build_coordinate(
            index,
            latitude_offset=0.0,
            longitude_offset=0.0,
        )

        order_lat, order_lon = build_coordinate(
            index,
            latitude_offset=0.00043,
            longitude_offset=0.00061,
        )

        drivers.append(
            {
                "driver_id": f"driver_{index + 1}",
                "lat": driver_lat,
                "lon": driver_lon,
                "current_load": 0,
                "max_capacity": 1,
            }
        )

        orders.append(
            {
                "order_id": f"order_{index + 1}",
                "pickup_lat": order_lat,
                "pickup_lon": order_lon,
            }
        )

    return {
        "drivers": drivers,
        "orders": orders,
        "matrix_algorithm": matrix_algorithm,
        "use_cache": False,
        "load_penalty_m": 0.0,
        "slot_penalty_m": 0.0,
        "return_cost_breakdown": False,
    }


def assignment_signature(
    body: dict[str, Any],
    algorithm_name: str,
) -> set[tuple[str, str]]:
    algorithm_result = body.get(
        algorithm_name
    )

    if not isinstance(
        algorithm_result,
        dict,
    ):
        return set()

    assignments = algorithm_result.get(
        "assignments"
    )

    if not isinstance(
        assignments,
        list,
    ):
        return set()

    result: set[
        tuple[str, str]
    ] = set()

    for assignment in assignments:
        if not isinstance(
            assignment,
            dict,
        ):
            continue

        driver_id = assignment.get(
            "driver_id"
        )

        order_id = assignment.get(
            "order_id"
        )

        if (
            isinstance(
                driver_id,
                str,
            )
            and isinstance(
                order_id,
                str,
            )
        ):
            result.add(
                (
                    driver_id,
                    order_id,
                )
            )

    return result


def jaccard_similarity(
    left: set[tuple[str, str]],
    right: set[tuple[str, str]],
) -> float:
    union = left | right

    if not union:
        return 1.0

    return len(
        left & right
    ) / len(union)


def validate_response(
    *,
    body: dict[str, Any],
    size: int,
    matrix_algorithm: str,
) -> list[str]:
    errors: list[str] = []

    if body.get("status") != "ok":
        errors.append(
            "response status is not 'ok'"
        )

    if body.get("phase") != PHASE:
        errors.append(
            "unexpected phase: "
            f"{body.get('phase')!r}"
        )

    if (
        body.get(
            "matrix_algorithm"
        )
        != matrix_algorithm
    ):
        errors.append(
            "unexpected matrix_algorithm: "
            f"{body.get('matrix_algorithm')!r}"
        )

    if body.get("driver_count") != size:
        errors.append(
            "driver_count mismatch"
        )

    if body.get("order_count") != size:
        errors.append(
            "order_count mismatch"
        )

    comparison = body.get(
        "comparison"
    )

    if not isinstance(
        comparison,
        dict,
    ):
        errors.append(
            "comparison section missing"
        )

    elif (
        comparison.get(
            "hungarian_non_regression"
        )
        is not True
    ):
        errors.append(
            "Hungarian non-regression failed"
        )

    if (
        matrix_algorithm
        == "source_dijkstra"
    ):
        road_network = body.get(
            "road_network"
        )

        if not isinstance(
            road_network,
            dict,
        ):
            errors.append(
                "road_network telemetry missing"
            )

        else:
            expected_pair_count = (
                size
                * size
            )

            if (
                road_network.get(
                    "pair_count"
                )
                != expected_pair_count
            ):
                errors.append(
                    "road pair_count mismatch"
                )

    return errors


def run_request(
    *,
    client: httpx.Client,
    endpoint_url: str,
    payload: dict[str, Any],
    size: int,
    matrix_algorithm: str,
) -> dict[str, Any]:
    started = time.perf_counter()

    try:
        response = client.post(
            endpoint_url,
            json=payload,
        )

        elapsed_ms = (
            (
                time.perf_counter()
                - started
            )
            * 1000.0
        )

        try:
            decoded = response.json()

        except ValueError as exc:
            return {
                "success": False,
                "status_code": response.status_code,
                "elapsed_ms": round(
                    elapsed_ms,
                    6,
                ),
                "error": (
                    "Invalid JSON response: "
                    f"{exc}"
                ),
                "validation_errors": [],
                "body": None,
            }

        if not isinstance(
            decoded,
            dict,
        ):
            return {
                "success": False,
                "status_code": response.status_code,
                "elapsed_ms": round(
                    elapsed_ms,
                    6,
                ),
                "error": (
                    "Response JSON is not "
                    "an object."
                ),
                "validation_errors": [],
                "body": None,
            }

        validation_errors = (
            validate_response(
                body=decoded,
                size=size,
                matrix_algorithm=(
                    matrix_algorithm
                ),
            )
        )

        success = (
            response.status_code
            == 200
            and not validation_errors
        )

        return {
            "success": success,
            "status_code": response.status_code,
            "elapsed_ms": round(
                elapsed_ms,
                6,
            ),
            "error": (
                None
                if response.status_code
                == 200
                else response.text[
                    :500
                ]
            ),
            "validation_errors": (
                validation_errors
            ),
            "body": decoded,
        }

    except Exception as exc:
        elapsed_ms = (
            (
                time.perf_counter()
                - started
            )
            * 1000.0
        )

        return {
            "success": False,
            "status_code": 0,
            "elapsed_ms": round(
                elapsed_ms,
                6,
            ),
            "error": (
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
            "validation_errors": [],
            "body": None,
        }


def extract_algorithm_result(
    body: dict[str, Any],
    algorithm_name: str,
) -> dict[str, Any]:
    result = body.get(
        algorithm_name
    )

    if not isinstance(
        result,
        dict,
    ):
        return {
            "assigned_count": None,
            "total_cost": None,
        }

    return {
        "assigned_count": result.get(
            "assigned_count"
        ),
        "total_cost": result.get(
            "total_cost"
        ),
    }


def extract_road_telemetry(
    body: dict[str, Any],
) -> dict[str, Any]:
    road_network = body.get(
        "road_network"
    )

    if not isinstance(
        road_network,
        dict,
    ):
        return {}

    return {
        "matrix_source": road_network.get(
            "matrix_source"
        ),
        "snapped_driver_count": (
            road_network.get(
                "snapped_driver_count"
            )
        ),
        "snapped_order_count": (
            road_network.get(
                "snapped_order_count"
            )
        ),
        "unique_driver_node_count": (
            road_network.get(
                "unique_driver_node_count"
            )
        ),
        "unique_order_node_count": (
            road_network.get(
                "unique_order_node_count"
            )
        ),
        "source_search_count": (
            road_network.get(
                "source_search_count"
            )
        ),
        "pair_count": road_network.get(
            "pair_count"
        ),
        "reachable_pair_count": (
            road_network.get(
                "reachable_pair_count"
            )
        ),
        "unreachable_pair_count": (
            road_network.get(
                "unreachable_pair_count"
            )
        ),
        "all_pairs_reachable": (
            road_network.get(
                "all_pairs_reachable"
            )
        ),
        "snap_time_ms": road_network.get(
            "snap_time_ms"
        ),
        "matrix_build_time_ms": (
            road_network.get(
                "matrix_build_time_ms"
            )
        ),
        "total_time_ms": road_network.get(
            "total_time_ms"
        ),
    }


def build_pair_record(
    *,
    mode: str,
    size: int,
    iteration: int,
    haversine_result: dict[str, Any],
    road_result: dict[str, Any],
) -> dict[str, Any]:
    haversine_body = (
        haversine_result.get(
            "body"
        )
    )

    road_body = road_result.get(
        "body"
    )

    if not isinstance(
        haversine_body,
        dict,
    ):
        haversine_body = {}

    if not isinstance(
        road_body,
        dict,
    ):
        road_body = {}

    haversine_hungarian = (
        extract_algorithm_result(
            haversine_body,
            "hungarian",
        )
    )

    road_hungarian = (
        extract_algorithm_result(
            road_body,
            "hungarian",
        )
    )

    haversine_greedy = (
        extract_algorithm_result(
            haversine_body,
            "greedy",
        )
    )

    road_greedy = (
        extract_algorithm_result(
            road_body,
            "greedy",
        )
    )

    haversine_hungarian_assignments = (
        assignment_signature(
            haversine_body,
            "hungarian",
        )
    )

    road_hungarian_assignments = (
        assignment_signature(
            road_body,
            "hungarian",
        )
    )

    haversine_greedy_assignments = (
        assignment_signature(
            haversine_body,
            "greedy",
        )
    )

    road_greedy_assignments = (
        assignment_signature(
            road_body,
            "greedy",
        )
    )

    haversine_elapsed_ms = float(
        haversine_result[
            "elapsed_ms"
        ]
    )

    road_elapsed_ms = float(
        road_result[
            "elapsed_ms"
        ]
    )

    road_vs_haversine_latency_ratio = (
        safe_ratio(
            road_elapsed_ms,
            haversine_elapsed_ms,
        )
    )

    haversine_hungarian_cost = (
        haversine_hungarian[
            "total_cost"
        ]
    )

    road_hungarian_cost = (
        road_hungarian[
            "total_cost"
        ]
    )

    road_vs_haversine_cost_ratio = None

    if (
        isinstance(
            haversine_hungarian_cost,
            (
                int,
                float,
            ),
        )
        and isinstance(
            road_hungarian_cost,
            (
                int,
                float,
            ),
        )
    ):
        road_vs_haversine_cost_ratio = (
            safe_ratio(
                float(
                    road_hungarian_cost
                ),
                float(
                    haversine_hungarian_cost
                ),
            )
        )

    return {
        "phase": PHASE,
        "benchmark": BENCHMARK,
        "mode": mode,
        "size": size,
        "iteration": iteration,
        "success": (
            haversine_result[
                "success"
            ]
            and road_result[
                "success"
            ]
        ),
        "haversine": {
            "status_code": (
                haversine_result[
                    "status_code"
                ]
            ),
            "elapsed_ms": (
                haversine_elapsed_ms
            ),
            "error": (
                haversine_result[
                    "error"
                ]
            ),
            "validation_errors": (
                haversine_result[
                    "validation_errors"
                ]
            ),
            "assigned_order_count": (
                haversine_body.get(
                    "assigned_order_count"
                )
            ),
            "greedy": (
                haversine_greedy
            ),
            "hungarian": (
                haversine_hungarian
            ),
        },
        "road": {
            "status_code": (
                road_result[
                    "status_code"
                ]
            ),
            "elapsed_ms": (
                road_elapsed_ms
            ),
            "error": road_result[
                "error"
            ],
            "validation_errors": (
                road_result[
                    "validation_errors"
                ]
            ),
            "assigned_order_count": (
                road_body.get(
                    "assigned_order_count"
                )
            ),
            "greedy": road_greedy,
            "hungarian": road_hungarian,
            "road_network": (
                extract_road_telemetry(
                    road_body
                )
            ),
        },
        "comparison": {
            "road_minus_haversine_elapsed_ms": (
                round(
                    road_elapsed_ms
                    - haversine_elapsed_ms,
                    6,
                )
            ),
            "road_vs_haversine_latency_ratio": (
                round(
                    road_vs_haversine_latency_ratio,
                    6,
                )
                if (
                    road_vs_haversine_latency_ratio
                    is not None
                )
                else None
            ),
            "road_vs_haversine_hungarian_cost_ratio": (
                round(
                    road_vs_haversine_cost_ratio,
                    6,
                )
                if (
                    road_vs_haversine_cost_ratio
                    is not None
                )
                else None
            ),
            "hungarian_assignment_jaccard": (
                round(
                    jaccard_similarity(
                        haversine_hungarian_assignments,
                        road_hungarian_assignments,
                    ),
                    6,
                )
            ),
            "hungarian_exact_assignment_match": (
                haversine_hungarian_assignments
                == road_hungarian_assignments
            ),
            "greedy_assignment_jaccard": (
                round(
                    jaccard_similarity(
                        haversine_greedy_assignments,
                        road_greedy_assignments,
                    ),
                    6,
                )
            ),
            "greedy_exact_assignment_match": (
                haversine_greedy_assignments
                == road_greedy_assignments
            ),
        },
    }


def build_size_summary(
    *,
    size: int,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    successful = [
        record
        for record in records
        if record["success"]
    ]

    haversine_times = [
        float(
            record[
                "haversine"
            ][
                "elapsed_ms"
            ]
        )
        for record in successful
    ]

    road_times = [
        float(
            record[
                "road"
            ][
                "elapsed_ms"
            ]
        )
        for record in successful
    ]

    latency_ratios = [
        float(
            record[
                "comparison"
            ][
                "road_vs_haversine_latency_ratio"
            ]
        )
        for record in successful
        if (
            record[
                "comparison"
            ][
                "road_vs_haversine_latency_ratio"
            ]
            is not None
        )
    ]

    cost_ratios = [
        float(
            record[
                "comparison"
            ][
                "road_vs_haversine_hungarian_cost_ratio"
            ]
        )
        for record in successful
        if (
            record[
                "comparison"
            ][
                "road_vs_haversine_hungarian_cost_ratio"
            ]
            is not None
        )
    ]

    hungarian_jaccard = [
        float(
            record[
                "comparison"
            ][
                "hungarian_assignment_jaccard"
            ]
        )
        for record in successful
    ]

    greedy_jaccard = [
        float(
            record[
                "comparison"
            ][
                "greedy_assignment_jaccard"
            ]
        )
        for record in successful
    ]

    exact_hungarian_matches = sum(
        1
        for record in successful
        if (
            record[
                "comparison"
            ][
                "hungarian_exact_assignment_match"
            ]
        )
    )

    exact_greedy_matches = sum(
        1
        for record in successful
        if (
            record[
                "comparison"
            ][
                "greedy_exact_assignment_match"
            ]
        )
    )

    return {
        "size": size,
        "case_count": len(records),
        "success_count": len(
            successful
        ),
        "failure_count": (
            len(records)
            - len(successful)
        ),
        "success_rate_pct": round(
            (
                len(successful)
                / len(records)
                * 100.0
            )
            if records
            else 0.0,
            3,
        ),
        "haversine_request_elapsed_ms": (
            summarize_values(
                haversine_times
            )
        ),
        "road_request_elapsed_ms": (
            summarize_values(
                road_times
            )
        ),
        "road_vs_haversine_latency_ratio": (
            summarize_values(
                latency_ratios
            )
        ),
        "road_vs_haversine_hungarian_cost_ratio": (
            summarize_values(
                cost_ratios
            )
        ),
        "hungarian_assignment_jaccard": (
            summarize_values(
                hungarian_jaccard
            )
        ),
        "greedy_assignment_jaccard": (
            summarize_values(
                greedy_jaccard
            )
        ),
        "hungarian_exact_assignment_match_count": (
            exact_hungarian_matches
        ),
        "greedy_exact_assignment_match_count": (
            exact_greedy_matches
        ),
    }


def preflight(
    *,
    client: httpx.Client,
    base_url: str,
) -> dict[str, Any]:
    started = time.perf_counter()

    try:
        response = client.get(
            f"{base_url}/health"
        )

        elapsed_ms = (
            (
                time.perf_counter()
                - started
            )
            * 1000.0
        )

        try:
            payload: Any = response.json()

        except ValueError:
            payload = response.text

        return {
            "success": (
                response.status_code
                == 200
            ),
            "status_code": (
                response.status_code
            ),
            "elapsed_ms": round(
                elapsed_ms,
                6,
            ),
            "payload": payload,
        }

    except Exception as exc:
        return {
            "success": False,
            "status_code": 0,
            "elapsed_ms": 0.0,
            "error": (
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
        }


def save_json(
    *,
    path: Path,
    payload: Any,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare Phase 10 Haversine dispatch "
            "against real road-network source-Dijkstra dispatch."
        )
    )

    parser.add_argument(
        "--mode",
        choices=(
            "local",
            "docker",
        ),
        default="docker",
    )

    parser.add_argument(
        "--base-url",
        default=None,
    )

    parser.add_argument(
        "--sizes",
        type=parse_sizes,
        default=DEFAULT_SIZES,
    )

    parser.add_argument(
        "--iterations",
        type=int,
        default=DEFAULT_ITERATIONS,
    )

    parser.add_argument(
        "--warmup",
        type=int,
        default=DEFAULT_WARMUP,
    )

    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
    )

    args = parser.parse_args()

    if args.iterations < 1:
        parser.error(
            "--iterations must be >= 1"
        )

    if args.warmup < 0:
        parser.error(
            "--warmup must be >= 0"
        )

    if (
        not math.isfinite(
            args.timeout_seconds
        )
        or args.timeout_seconds
        <= 0.0
    ):
        parser.error(
            "--timeout-seconds must be finite and > 0"
        )

    base_url = (
        args.base_url
        or (
            DEFAULT_DOCKER_BASE_URL
            if args.mode
            == "docker"
            else DEFAULT_LOCAL_BASE_URL
        )
    ).rstrip("/")

    endpoint_url = (
        f"{base_url}"
        f"{ENDPOINT}"
    )

    timestamp = datetime.now(
        UTC
    ).strftime(
        "%Y%m%d_%H%M%S"
    )

    result_directory = (
        Path("benchmarks")
        / "phase_10"
        / f"{args.mode}_results"
    )

    raw_path = (
        result_directory
        / (
            "phase10_haversine_vs_road_raw_"
            f"{args.mode}_"
            f"{timestamp}.json"
        )
    )

    summary_path = (
        result_directory
        / (
            "phase10_haversine_vs_road_summary_"
            f"{args.mode}_"
            f"{timestamp}.json"
        )
    )

    print(
        "="
        * 80
    )

    print(
        "CityRoute Phase 10 "
        "Haversine vs Road-Network Probe"
    )

    print(
        "="
        * 80
    )

    print(
        f"mode={args.mode}"
    )

    print(
        f"base_url={base_url}"
    )

    print(
        f"sizes={args.sizes}"
    )

    print(
        f"iterations={args.iterations}"
    )

    print(
        f"warmup={args.warmup}"
    )

    print(
        "cache=False for both algorithms"
    )

    print(
        "="
        * 80
    )

    timeout = httpx.Timeout(
        args.timeout_seconds
    )

    records: list[
        dict[str, Any]
    ] = []

    with httpx.Client(
        timeout=timeout
    ) as client:
        health = preflight(
            client=client,
            base_url=base_url,
        )

        print(
            f"health_preflight={health}"
        )

        if not health.get(
            "success",
            False,
        ):
            print(
                "ERROR: health preflight failed."
            )

            return 1

        for size in args.sizes:
            haversine_payload = (
                build_payload(
                    size=size,
                    matrix_algorithm=(
                        "haversine"
                    ),
                )
            )

            road_payload = (
                build_payload(
                    size=size,
                    matrix_algorithm=(
                        "source_dijkstra"
                    ),
                )
            )

            print()
            print(
                "-"
                * 80
            )

            print(
                f"size={size}"
            )

            print(
                "-"
                * 80
            )

            for warmup_index in range(
                args.warmup
            ):
                run_request(
                    client=client,
                    endpoint_url=(
                        endpoint_url
                    ),
                    payload=(
                        haversine_payload
                    ),
                    size=size,
                    matrix_algorithm=(
                        "haversine"
                    ),
                )

                run_request(
                    client=client,
                    endpoint_url=(
                        endpoint_url
                    ),
                    payload=road_payload,
                    size=size,
                    matrix_algorithm=(
                        "source_dijkstra"
                    ),
                )

                print(
                    "warmup="
                    f"{warmup_index + 1}/"
                    f"{args.warmup}"
                )

            for iteration in range(
                1,
                args.iterations
                + 1,
            ):
                # Alternate execution order to reduce systematic
                # first-request / second-request ordering bias.
                if (
                    iteration
                    % 2
                    == 1
                ):
                    haversine_result = (
                        run_request(
                            client=client,
                            endpoint_url=(
                                endpoint_url
                            ),
                            payload=(
                                haversine_payload
                            ),
                            size=size,
                            matrix_algorithm=(
                                "haversine"
                            ),
                        )
                    )

                    road_result = (
                        run_request(
                            client=client,
                            endpoint_url=(
                                endpoint_url
                            ),
                            payload=(
                                road_payload
                            ),
                            size=size,
                            matrix_algorithm=(
                                "source_dijkstra"
                            ),
                        )
                    )

                else:
                    road_result = (
                        run_request(
                            client=client,
                            endpoint_url=(
                                endpoint_url
                            ),
                            payload=(
                                road_payload
                            ),
                            size=size,
                            matrix_algorithm=(
                                "source_dijkstra"
                            ),
                        )
                    )

                    haversine_result = (
                        run_request(
                            client=client,
                            endpoint_url=(
                                endpoint_url
                            ),
                            payload=(
                                haversine_payload
                            ),
                            size=size,
                            matrix_algorithm=(
                                "haversine"
                            ),
                        )
                    )

                record = build_pair_record(
                    mode=args.mode,
                    size=size,
                    iteration=iteration,
                    haversine_result=(
                        haversine_result
                    ),
                    road_result=road_result,
                )

                records.append(record)

                print(
                    f"iteration={iteration}/"
                    f"{args.iterations} "
                    f"success={record['success']} "
                    "haversine_ms="
                    f"{record['haversine']['elapsed_ms']} "
                    "road_ms="
                    f"{record['road']['elapsed_ms']} "
                    "latency_ratio="
                    f"{record['comparison']['road_vs_haversine_latency_ratio']} "
                    "hungarian_jaccard="
                    f"{record['comparison']['hungarian_assignment_jaccard']}"
                )

    successful = [
        record
        for record in records
        if record["success"]
    ]

    failures = [
        record
        for record in records
        if not record["success"]
    ]

    size_summaries = [
        build_size_summary(
            size=size,
            records=[
                record
                for record in records
                if (
                    record[
                        "size"
                    ]
                    == size
                )
            ],
        )
        for size in args.sizes
    ]

    raw_payload = {
        "phase": PHASE,
        "benchmark": BENCHMARK,
        "created_at_utc": (
            datetime.now(
                UTC
            ).isoformat()
        ),
        "configuration": {
            "mode": args.mode,
            "base_url": base_url,
            "endpoint": ENDPOINT,
            "sizes": list(
                args.sizes
            ),
            "iterations": (
                args.iterations
            ),
            "warmup": args.warmup,
            "use_cache": False,
            "timeout_seconds": (
                args.timeout_seconds
            ),
        },
        "health_preflight": health,
        "records": records,
    }

    summary_payload = {
        "phase": PHASE,
        "benchmark": BENCHMARK,
        "created_at_utc": (
            datetime.now(
                UTC
            ).isoformat()
        ),
        "configuration": {
            "mode": args.mode,
            "base_url": base_url,
            "endpoint": ENDPOINT,
            "sizes": list(
                args.sizes
            ),
            "iterations": (
                args.iterations
            ),
            "warmup": args.warmup,
            "use_cache": False,
        },
        "case_count": len(records),
        "success_count": len(
            successful
        ),
        "failure_count": len(
            failures
        ),
        "success_rate_pct": round(
            (
                len(successful)
                / len(records)
                * 100.0
            )
            if records
            else 0.0,
            3,
        ),
        "size_summaries": (
            size_summaries
        ),
        "failed_cases": [
            {
                "size": record[
                    "size"
                ],
                "iteration": (
                    record[
                        "iteration"
                    ]
                ),
                "haversine_error": (
                    record[
                        "haversine"
                    ][
                        "error"
                    ]
                ),
                "road_error": (
                    record[
                        "road"
                    ][
                        "error"
                    ]
                ),
                "haversine_validation_errors": (
                    record[
                        "haversine"
                    ][
                        "validation_errors"
                    ]
                ),
                "road_validation_errors": (
                    record[
                        "road"
                    ][
                        "validation_errors"
                    ]
                ),
            }
            for record in failures
        ],
        "interpretation_note": (
            "Haversine and source_dijkstra optimize different cost "
            "matrices. A lower total cost from one model must not be "
            "interpreted as proof that it is globally better under the "
            "other model. Assignment agreement and latency are reported "
            "as comparative evidence."
        ),
    }

    save_json(
        path=raw_path,
        payload=raw_payload,
    )

    save_json(
        path=summary_path,
        payload=summary_payload,
    )

    print()
    print(
        "="
        * 80
    )

    print(
        "FINAL SUMMARY"
    )

    print(
        "="
        * 80
    )

    print(
        json.dumps(
            summary_payload,
            indent=2,
        )
    )

    print()
    print(
        f"raw_output={raw_path}"
    )

    print(
        f"summary_output={summary_path}"
    )

    return (
        0
        if not failures
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )