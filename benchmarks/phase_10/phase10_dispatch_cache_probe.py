# benchmarks/phase_10/phase10_dispatch_cache_probe.py

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
BENCHMARK = "dispatch_cache"
ENDPOINT = "/dispatch/compare"

DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_DOCKER_BASE_URL = "http://127.0.0.1:8001"

DEFAULT_SIZES = (5, 10, 25, 50)
DEFAULT_ITERATIONS = 10
DEFAULT_WARM_HITS = 2
DEFAULT_WARMUP = 1
DEFAULT_TIMEOUT_SECONDS = 180.0

KANPUR_CENTER_LAT = 26.4499
KANPUR_CENTER_LON = 80.3319


def parse_sizes(raw_value: str) -> tuple[int, ...]:
    sizes: list[int] = []

    for item in raw_value.split(","):
        stripped = item.strip()

        if not stripped:
            continue

        size = int(stripped)

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
        * (len(ordered) - 1)
    )

    lower_index = math.floor(position)
    upper_index = math.ceil(position)

    if lower_index == upper_index:
        return ordered[lower_index]

    fraction = position - lower_index

    return (
        ordered[lower_index]
        * (1.0 - fraction)
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
        "min": round(min(values), 6),
        "median": round(
            statistics.median(values),
            6,
        ),
        "mean": round(
            statistics.fmean(values),
            6,
        ),
        "p95": round(
            percentile(values, 95.0),
            6,
        ),
        "max": round(max(values), 6),
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
        round(lat, 7),
        round(lon, 7),
    )


def rotate_items(
    items: list[dict[str, Any]],
    shift: int,
) -> list[dict[str, Any]]:
    if not items:
        return []

    normalized_shift = (
        shift
        % len(items)
    )

    return (
        items[normalized_shift:]
        + items[:normalized_shift]
    )


def build_base_payload_components(
    size: int,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
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

    return drivers, orders


def build_payload(
    *,
    size: int,
    scenario_index: int,
) -> dict[str, Any]:
    drivers, orders = (
        build_base_payload_components(size)
    )

    driver_shift = (
        scenario_index
        % size
    )

    order_shift = (
        scenario_index
        // size
    ) % size

    rotated_drivers = rotate_items(
        drivers,
        driver_shift,
    )

    rotated_orders = rotate_items(
        orders,
        order_shift,
    )

    return {
        "drivers": rotated_drivers,
        "orders": rotated_orders,
        "matrix_algorithm": "source_dijkstra",
        "use_cache": True,
        "load_penalty_m": 0.0,
        "slot_penalty_m": 0.0,
        "return_cost_breakdown": False,
    }


def assignment_signature(
    body: dict[str, Any],
    algorithm_name: str,
) -> tuple[tuple[str, str], ...]:
    algorithm_result = body.get(
        algorithm_name
    )

    if not isinstance(
        algorithm_result,
        dict,
    ):
        return ()

    assignments = algorithm_result.get(
        "assignments"
    )

    if not isinstance(
        assignments,
        list,
    ):
        return ()

    pairs: list[tuple[str, str]] = []

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
            isinstance(driver_id, str)
            and isinstance(order_id, str)
        ):
            pairs.append(
                (
                    driver_id,
                    order_id,
                )
            )

    return tuple(
        sorted(pairs)
    )


def extract_cache_status(
    body: dict[str, Any],
) -> str | None:
    top_level_status = body.get(
        "cache_status"
    )

    if isinstance(
        top_level_status,
        str,
    ):
        return top_level_status

    road_network = body.get(
        "road_network"
    )

    if isinstance(
        road_network,
        dict,
    ):
        nested_status = (
            road_network.get(
                "cache_status"
            )
        )

        if isinstance(
            nested_status,
            str,
        ):
            return nested_status

    return None


def extract_matrix_source(
    body: dict[str, Any],
) -> str | None:
    road_network = body.get(
        "road_network"
    )

    if not isinstance(
        road_network,
        dict,
    ):
        return None

    matrix_source = (
        road_network.get(
            "matrix_source"
        )
    )

    if isinstance(
        matrix_source,
        str,
    ):
        return matrix_source

    return None


def stable_dispatch_result(
    body: dict[str, Any],
) -> dict[str, Any]:
    greedy = body.get(
        "greedy"
    )

    hungarian = body.get(
        "hungarian"
    )

    comparison = body.get(
        "comparison"
    )

    if not isinstance(
        greedy,
        dict,
    ):
        greedy = {}

    if not isinstance(
        hungarian,
        dict,
    ):
        hungarian = {}

    if not isinstance(
        comparison,
        dict,
    ):
        comparison = {}

    return {
        "driver_count": body.get(
            "driver_count"
        ),
        "order_count": body.get(
            "order_count"
        ),
        "available_slot_count": (
            body.get(
                "available_slot_count"
            )
        ),
        "assigned_order_count": (
            body.get(
                "assigned_order_count"
            )
        ),
        "unassigned_order_count": (
            body.get(
                "unassigned_order_count"
            )
        ),
        "greedy": {
            "assigned_count": (
                greedy.get(
                    "assigned_count"
                )
            ),
            "total_cost": (
                greedy.get(
                    "total_cost"
                )
            ),
            "assignments": (
                assignment_signature(
                    body,
                    "greedy",
                )
            ),
        },
        "hungarian": {
            "assigned_count": (
                hungarian.get(
                    "assigned_count"
                )
            ),
            "total_cost": (
                hungarian.get(
                    "total_cost"
                )
            ),
            "assignments": (
                assignment_signature(
                    body,
                    "hungarian",
                )
            ),
        },
        "hungarian_non_regression": (
            comparison.get(
                "hungarian_non_regression"
            )
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
        "matrix_source": (
            road_network.get(
                "matrix_source"
            )
        ),
        "cache_status": (
            road_network.get(
                "cache_status"
            )
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
        "pair_count": (
            road_network.get(
                "pair_count"
            )
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
        "snap_time_ms": (
            road_network.get(
                "snap_time_ms"
            )
        ),
        "cache_lookup_time_ms": (
            road_network.get(
                "cache_lookup_time_ms"
            )
        ),
        "matrix_build_time_ms": (
            road_network.get(
                "matrix_build_time_ms"
            )
        ),
        "cache_write_time_ms": (
            road_network.get(
                "cache_write_time_ms"
            )
        ),
        "total_time_ms": (
            road_network.get(
                "total_time_ms"
            )
        ),
    }


def validate_common_response(
    *,
    body: dict[str, Any],
    size: int,
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
        != "source_dijkstra"
    ):
        errors.append(
            "matrix_algorithm is not "
            "'source_dijkstra'"
        )

    if body.get("driver_count") != size:
        errors.append(
            "driver_count mismatch"
        )

    if body.get("order_count") != size:
        errors.append(
            "order_count mismatch"
        )

    if body.get("cache_used") is not True:
        errors.append(
            "cache_used is not true"
        )

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
                "road-network pair_count mismatch"
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

    return errors


def validate_cold_response(
    *,
    body: dict[str, Any],
    size: int,
) -> list[str]:
    errors = validate_common_response(
        body=body,
        size=size,
    )

    cache_status = (
        extract_cache_status(body)
    )

    if cache_status != "miss":
        errors.append(
            "expected cold request cache_status="
            f"'miss', got {cache_status!r}"
        )

    cache_hit = body.get(
        "cache_hit"
    )

    if cache_hit is not False:
        errors.append(
            "expected cold request cache_hit=false"
        )

    matrix_source = (
        extract_matrix_source(body)
    )

    if matrix_source != "computed":
        errors.append(
            "expected cold request "
            "matrix_source='computed', "
            f"got {matrix_source!r}"
        )

    return errors


def validate_warm_response(
    *,
    body: dict[str, Any],
    size: int,
) -> list[str]:
    errors = validate_common_response(
        body=body,
        size=size,
    )

    cache_status = (
        extract_cache_status(body)
    )

    if cache_status != "hit":
        errors.append(
            "expected warm request cache_status="
            f"'hit', got {cache_status!r}"
        )

    cache_hit = body.get(
        "cache_hit"
    )

    if cache_hit is not True:
        errors.append(
            "expected warm request cache_hit=true"
        )

    matrix_source = (
        extract_matrix_source(body)
    )

    if matrix_source != "cache":
        errors.append(
            "expected warm request "
            "matrix_source='cache', "
            f"got {matrix_source!r}"
        )

    return errors


def run_request(
    *,
    client: httpx.Client,
    endpoint_url: str,
    payload: dict[str, Any],
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
                "status_code": (
                    response.status_code
                ),
                "elapsed_ms": round(
                    elapsed_ms,
                    6,
                ),
                "error": (
                    "Invalid JSON response: "
                    f"{exc}"
                ),
                "body": None,
            }

        if not isinstance(
            decoded,
            dict,
        ):
            return {
                "success": False,
                "status_code": (
                    response.status_code
                ),
                "elapsed_ms": round(
                    elapsed_ms,
                    6,
                ),
                "error": (
                    "Response JSON is not "
                    "an object."
                ),
                "body": None,
            }

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
            "error": (
                None
                if response.status_code
                == 200
                else response.text[:500]
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
            "body": None,
        }


def run_cache_cycle(
    *,
    client: httpx.Client,
    endpoint_url: str,
    mode: str,
    size: int,
    iteration: int,
    scenario_index: int,
    warm_hits: int,
) -> dict[str, Any]:
    payload = build_payload(
        size=size,
        scenario_index=scenario_index,
    )

    cold_request = run_request(
        client=client,
        endpoint_url=endpoint_url,
        payload=payload,
    )

    cold_body = cold_request.get(
        "body"
    )

    cold_validation_errors: list[str] = []

    if isinstance(
        cold_body,
        dict,
    ):
        cold_validation_errors = (
            validate_cold_response(
                body=cold_body,
                size=size,
            )
        )

    elif cold_request["success"]:
        cold_validation_errors.append(
            "cold response body missing"
        )

    warm_records: list[
        dict[str, Any]
    ] = []

    for warm_index in range(
        1,
        warm_hits + 1,
    ):
        warm_request = run_request(
            client=client,
            endpoint_url=endpoint_url,
            payload=payload,
        )

        warm_body = warm_request.get(
            "body"
        )

        warm_validation_errors: list[
            str
        ] = []

        if isinstance(
            warm_body,
            dict,
        ):
            warm_validation_errors = (
                validate_warm_response(
                    body=warm_body,
                    size=size,
                )
            )

        elif warm_request["success"]:
            warm_validation_errors.append(
                "warm response body missing"
            )

        warm_records.append(
            {
                "warm_index": warm_index,
                "request": warm_request,
                "validation_errors": (
                    warm_validation_errors
                ),
            }
        )

    cold_stable_result = (
        stable_dispatch_result(
            cold_body
        )
        if isinstance(
            cold_body,
            dict,
        )
        else None
    )

    all_warm_outputs_identical = True

    for warm_record in warm_records:
        warm_body = (
            warm_record[
                "request"
            ].get(
                "body"
            )
        )

        if not isinstance(
            warm_body,
            dict,
        ):
            all_warm_outputs_identical = False
            continue

        warm_stable_result = (
            stable_dispatch_result(
                warm_body
            )
        )

        if (
            warm_stable_result
            != cold_stable_result
        ):
            all_warm_outputs_identical = False

    cold_success = (
        cold_request["success"]
        and not cold_validation_errors
    )

    warm_success = all(
        warm_record[
            "request"
        ][
            "success"
        ]
        and not warm_record[
            "validation_errors"
        ]
        for warm_record
        in warm_records
    )

    success = (
        cold_success
        and warm_success
        and all_warm_outputs_identical
    )

    cold_elapsed_ms = float(
        cold_request[
            "elapsed_ms"
        ]
    )

    warm_elapsed_values = [
        float(
            warm_record[
                "request"
            ][
                "elapsed_ms"
            ]
        )
        for warm_record
        in warm_records
    ]

    warm_median_ms = (
        statistics.median(
            warm_elapsed_values
        )
        if warm_elapsed_values
        else 0.0
    )

    speedup_ratio = safe_ratio(
        cold_elapsed_ms,
        warm_median_ms,
    )

    return {
        "phase": PHASE,
        "benchmark": BENCHMARK,
        "mode": mode,
        "size": size,
        "iteration": iteration,
        "scenario_index": (
            scenario_index
        ),
        "success": success,
        "cold": {
            "status_code": (
                cold_request[
                    "status_code"
                ]
            ),
            "elapsed_ms": (
                cold_elapsed_ms
            ),
            "error": cold_request[
                "error"
            ],
            "validation_errors": (
                cold_validation_errors
            ),
            "cache_status": (
                extract_cache_status(
                    cold_body
                )
                if isinstance(
                    cold_body,
                    dict,
                )
                else None
            ),
            "cache_hit": (
                cold_body.get(
                    "cache_hit"
                )
                if isinstance(
                    cold_body,
                    dict,
                )
                else None
            ),
            "matrix_source": (
                extract_matrix_source(
                    cold_body
                )
                if isinstance(
                    cold_body,
                    dict,
                )
                else None
            ),
            "road_network": (
                extract_road_telemetry(
                    cold_body
                )
                if isinstance(
                    cold_body,
                    dict,
                )
                else {}
            ),
            "stable_result": (
                cold_stable_result
            ),
        },
        "warm": [
            {
                "warm_index": (
                    warm_record[
                        "warm_index"
                    ]
                ),
                "status_code": (
                    warm_record[
                        "request"
                    ][
                        "status_code"
                    ]
                ),
                "elapsed_ms": (
                    warm_record[
                        "request"
                    ][
                        "elapsed_ms"
                    ]
                ),
                "error": (
                    warm_record[
                        "request"
                    ][
                        "error"
                    ]
                ),
                "validation_errors": (
                    warm_record[
                        "validation_errors"
                    ]
                ),
                "cache_status": (
                    extract_cache_status(
                        warm_record[
                            "request"
                        ][
                            "body"
                        ]
                    )
                    if isinstance(
                        warm_record[
                            "request"
                        ].get(
                            "body"
                        ),
                        dict,
                    )
                    else None
                ),
                "cache_hit": (
                    warm_record[
                        "request"
                    ][
                        "body"
                    ].get(
                        "cache_hit"
                    )
                    if isinstance(
                        warm_record[
                            "request"
                        ].get(
                            "body"
                        ),
                        dict,
                    )
                    else None
                ),
                "matrix_source": (
                    extract_matrix_source(
                        warm_record[
                            "request"
                        ][
                            "body"
                        ]
                    )
                    if isinstance(
                        warm_record[
                            "request"
                        ].get(
                            "body"
                        ),
                        dict,
                    )
                    else None
                ),
                "road_network": (
                    extract_road_telemetry(
                        warm_record[
                            "request"
                        ][
                            "body"
                        ]
                    )
                    if isinstance(
                        warm_record[
                            "request"
                        ].get(
                            "body"
                        ),
                        dict,
                    )
                    else {}
                ),
            }
            for warm_record
            in warm_records
        ],
        "comparison": {
            "all_warm_outputs_identical": (
                all_warm_outputs_identical
            ),
            "cold_elapsed_ms": round(
                cold_elapsed_ms,
                6,
            ),
            "warm_median_elapsed_ms": round(
                warm_median_ms,
                6,
            ),
            "cold_minus_warm_median_ms": round(
                cold_elapsed_ms
                - warm_median_ms,
                6,
            ),
            "cold_to_warm_speedup_ratio": (
                round(
                    speedup_ratio,
                    6,
                )
                if speedup_ratio
                is not None
                else None
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

    cold_times = [
        float(
            record[
                "cold"
            ][
                "elapsed_ms"
            ]
        )
        for record in successful
    ]

    warm_times = [
        float(
            warm_record[
                "elapsed_ms"
            ]
        )
        for record in successful
        for warm_record
        in record["warm"]
    ]

    per_cycle_warm_medians = [
        float(
            record[
                "comparison"
            ][
                "warm_median_elapsed_ms"
            ]
        )
        for record in successful
    ]

    speedup_ratios = [
        float(
            record[
                "comparison"
            ][
                "cold_to_warm_speedup_ratio"
            ]
        )
        for record in successful
        if (
            record[
                "comparison"
            ][
                "cold_to_warm_speedup_ratio"
            ]
            is not None
        )
    ]

    cold_miss_count = sum(
        1
        for record in records
        if (
            record[
                "cold"
            ][
                "cache_status"
            ]
            == "miss"
        )
    )

    warm_hit_count = sum(
        1
        for record in records
        for warm_record
        in record["warm"]
        if (
            warm_record[
                "cache_status"
            ]
            == "hit"
        )
    )

    total_warm_requests = sum(
        len(record["warm"])
        for record in records
    )

    identical_output_count = sum(
        1
        for record in records
        if (
            record[
                "comparison"
            ][
                "all_warm_outputs_identical"
            ]
        )
    )

    return {
        "size": size,
        "cycle_count": len(records),
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
        "cold_miss_count": (
            cold_miss_count
        ),
        "expected_cold_miss_count": (
            len(records)
        ),
        "warm_hit_count": (
            warm_hit_count
        ),
        "expected_warm_hit_count": (
            total_warm_requests
        ),
        "identical_output_count": (
            identical_output_count
        ),
        "expected_identical_output_count": (
            len(records)
        ),
        "cold_request_elapsed_ms": (
            summarize_values(
                cold_times
            )
        ),
        "warm_request_elapsed_ms": (
            summarize_values(
                warm_times
            )
        ),
        "per_cycle_warm_median_elapsed_ms": (
            summarize_values(
                per_cycle_warm_medians
            )
        ),
        "cold_to_warm_speedup_ratio": (
            summarize_values(
                speedup_ratios
            )
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
            payload: Any = (
                response.json()
            )

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
            "Probe Phase 10 Redis-backed "
            "road-dispatch matrix caching."
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
        "--warm-hits",
        type=int,
        default=DEFAULT_WARM_HITS,
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

    if args.warm_hits < 1:
        parser.error(
            "--warm-hits must be >= 1"
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
            "--timeout-seconds must be "
            "finite and > 0"
        )

    for size in args.sizes:
        required_scenarios = (
            args.warmup
            + args.iterations
        )

        maximum_rotation_scenarios = (
            size
            * size
        )

        if (
            required_scenarios
            > maximum_rotation_scenarios
        ):
            parser.error(
                "For size "
                f"{size}, warmup + iterations "
                "must be <= size² "
                f"({maximum_rotation_scenarios}) "
                "to preserve unique rotation scenarios."
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
            "phase10_dispatch_cache_raw_"
            f"{args.mode}_"
            f"{timestamp}.json"
        )
    )

    summary_path = (
        result_directory
        / (
            "phase10_dispatch_cache_summary_"
            f"{args.mode}_"
            f"{timestamp}.json"
        )
    )

    print("=" * 80)
    print(
        "CityRoute Phase 10 "
        "Dispatch Cache Probe"
    )
    print("=" * 80)
    print(f"mode={args.mode}")
    print(f"base_url={base_url}")
    print(f"endpoint={ENDPOINT}")
    print("matrix_algorithm=source_dijkstra")
    print("use_cache=True")
    print(f"sizes={args.sizes}")
    print(
        f"iterations={args.iterations}"
    )
    print(
        f"warm_hits={args.warm_hits}"
    )
    print(f"warmup={args.warmup}")
    print("=" * 80)

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
            print()
            print("-" * 80)
            print(f"size={size}")
            print("-" * 80)

            for warmup_index in range(
                args.warmup
            ):
                warmup_record = (
                    run_cache_cycle(
                        client=client,
                        endpoint_url=(
                            endpoint_url
                        ),
                        mode=args.mode,
                        size=size,
                        iteration=(
                            -(
                                warmup_index
                                + 1
                            )
                        ),
                        scenario_index=(
                            warmup_index
                        ),
                        warm_hits=(
                            args.warm_hits
                        ),
                    )
                )

                print(
                    "warmup="
                    f"{warmup_index + 1}/"
                    f"{args.warmup} "
                    "success="
                    f"{warmup_record['success']}"
                )

            for iteration in range(
                1,
                args.iterations
                + 1,
            ):
                scenario_index = (
                    args.warmup
                    + iteration
                    - 1
                )

                record = run_cache_cycle(
                    client=client,
                    endpoint_url=(
                        endpoint_url
                    ),
                    mode=args.mode,
                    size=size,
                    iteration=iteration,
                    scenario_index=(
                        scenario_index
                    ),
                    warm_hits=(
                        args.warm_hits
                    ),
                )

                records.append(record)

                print(
                    f"iteration={iteration}/"
                    f"{args.iterations} "
                    f"success={record['success']} "
                    "cold_status="
                    f"{record['cold']['cache_status']} "
                    "cold_ms="
                    f"{record['cold']['elapsed_ms']} "
                    "warm_median_ms="
                    f"{record['comparison']['warm_median_elapsed_ms']} "
                    "speedup="
                    f"{record['comparison']['cold_to_warm_speedup_ratio']} "
                    "identical="
                    f"{record['comparison']['all_warm_outputs_identical']}"
                )

                if not record[
                    "success"
                ]:
                    print(
                        "  cold_errors="
                        f"{record['cold']['validation_errors']}"
                    )

                    for warm_record in (
                        record["warm"]
                    ):
                        if (
                            warm_record[
                                "validation_errors"
                            ]
                        ):
                            print(
                                "  warm_errors="
                                f"{warm_record['validation_errors']}"
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

    total_cold_misses = sum(
        1
        for record in records
        if (
            record[
                "cold"
            ][
                "cache_status"
            ]
            == "miss"
        )
    )

    total_warm_hits = sum(
        1
        for record in records
        for warm_record
        in record["warm"]
        if (
            warm_record[
                "cache_status"
            ]
            == "hit"
        )
    )

    total_warm_requests = sum(
        len(record["warm"])
        for record in records
    )

    identical_output_count = sum(
        1
        for record in records
        if (
            record[
                "comparison"
            ][
                "all_warm_outputs_identical"
            ]
        )
    )

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
            "matrix_algorithm": (
                "source_dijkstra"
            ),
            "use_cache": True,
            "sizes": list(
                args.sizes
            ),
            "iterations": (
                args.iterations
            ),
            "warm_hits": (
                args.warm_hits
            ),
            "warmup": args.warmup,
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
            "matrix_algorithm": (
                "source_dijkstra"
            ),
            "use_cache": True,
            "sizes": list(
                args.sizes
            ),
            "iterations": (
                args.iterations
            ),
            "warm_hits": (
                args.warm_hits
            ),
            "warmup": args.warmup,
        },
        "cycle_count": len(records),
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
        "cold_miss_count": (
            total_cold_misses
        ),
        "expected_cold_miss_count": (
            len(records)
        ),
        "warm_hit_count": (
            total_warm_hits
        ),
        "expected_warm_hit_count": (
            total_warm_requests
        ),
        "identical_output_count": (
            identical_output_count
        ),
        "expected_identical_output_count": (
            len(records)
        ),
        "all_cold_requests_missed": (
            total_cold_misses
            == len(records)
        ),
        "all_warm_requests_hit": (
            total_warm_hits
            == total_warm_requests
        ),
        "all_warm_outputs_identical": (
            identical_output_count
            == len(records)
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
                "cold_validation_errors": (
                    record[
                        "cold"
                    ][
                        "validation_errors"
                    ]
                ),
                "warm_validation_errors": [
                    warm_record[
                        "validation_errors"
                    ]
                    for warm_record
                    in record["warm"]
                    if (
                        warm_record[
                            "validation_errors"
                        ]
                    )
                ],
                "identical": (
                    record[
                        "comparison"
                    ][
                        "all_warm_outputs_identical"
                    ]
                ),
            }
            for record in failures
        ],
        "interpretation_note": (
            "Each measured cache cycle uses a deterministic "
            "driver/order ordering intended to produce a fresh cache "
            "key. The first request is expected to compute and store "
            "the road matrix; repeated requests for the same payload "
            "must hit Redis and return identical dispatch results."
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
    print("=" * 80)
    print("FINAL SUMMARY")
    print("=" * 80)

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