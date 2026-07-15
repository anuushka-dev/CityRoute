# benchmarks/phase_10/phase10_road_dispatch_benchmark.py

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
ENDPOINT = "/dispatch/compare"

DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_DOCKER_BASE_URL = "http://127.0.0.1:8001"

DEFAULT_SIZES = (
    5,
    10,
    25,
)

DEFAULT_ITERATIONS = 10
DEFAULT_WARMUP = 2
DEFAULT_TIMEOUT_SECONDS = 120.0

KANPUR_CENTER_LAT = 26.4499
KANPUR_CENTER_LON = 80.3319


def parse_sizes(
    raw_value: str,
) -> tuple[int, ...]:
    values: list[int] = []

    for item in raw_value.split(","):
        stripped = item.strip()

        if not stripped:
            continue

        size = int(stripped)

        if size < 1:
            raise argparse.ArgumentTypeError(
                "Every benchmark size must be >= 1."
            )

        values.append(size)

    if not values:
        raise argparse.ArgumentTypeError(
            "At least one benchmark size is required."
        )

    return tuple(values)


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

    lower_index = math.floor(
        position
    )

    upper_index = math.ceil(
        position
    )

    if (
        lower_index
        == upper_index
    ):
        return ordered[
            lower_index
        ]

    fraction = (
        position
        - lower_index
    )

    return (
        ordered[
            lower_index
        ]
        * (
            1.0
            - fraction
        )
        + ordered[
            upper_index
        ]
        * fraction
    )


def summarize_numeric_values(
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
        "count": len(
            values
        ),
        "min": round(
            min(
                values
            ),
            6,
        ),
        "median": round(
            statistics.median(
                values
            ),
            6,
        ),
        "mean": round(
            statistics.fmean(
                values
            ),
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
            max(
                values
            ),
            6,
        ),
    }


def build_coordinate(
    index: int,
    *,
    latitude_offset: float,
    longitude_offset: float,
) -> tuple[float, float]:
    """
    Produce deterministic coordinates around central Kanpur.

    Coordinates remain close enough to the loaded Kanpur graph for snapping,
    while still creating distinct driver and order positions.
    """

    row = index // 10
    column = index % 10

    lat = (
        KANPUR_CENTER_LAT
        + latitude_offset
        + (
            row
            * 0.00115
        )
        + (
            column
            * 0.00017
        )
    )

    lon = (
        KANPUR_CENTER_LON
        + longitude_offset
        + (
            column
            * 0.00105
        )
        + (
            row
            * 0.00019
        )
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
    use_cache: bool,
) -> dict[str, Any]:
    drivers: list[
        dict[str, Any]
    ] = []

    orders: list[
        dict[str, Any]
    ] = []

    for index in range(
        size
    ):
        driver_lat, driver_lon = (
            build_coordinate(
                index,
                latitude_offset=0.0,
                longitude_offset=0.0,
            )
        )

        order_lat, order_lon = (
            build_coordinate(
                index,
                latitude_offset=0.00043,
                longitude_offset=0.00061,
            )
        )

        drivers.append(
            {
                "driver_id": (
                    f"driver_{index + 1}"
                ),
                "lat": driver_lat,
                "lon": driver_lon,
                "current_load": 0,
                "max_capacity": 1,
            }
        )

        orders.append(
            {
                "order_id": (
                    f"order_{index + 1}"
                ),
                "pickup_lat": (
                    order_lat
                ),
                "pickup_lon": (
                    order_lon
                ),
            }
        )

    return {
        "drivers": drivers,
        "orders": orders,
        "matrix_algorithm": (
            matrix_algorithm
        ),
        "use_cache": (
            use_cache
        ),
        "load_penalty_m": 0.0,
        "slot_penalty_m": 0.0,
        "return_cost_breakdown": False,
    }


def validate_response(
    *,
    body: dict[str, Any],
    size: int,
    matrix_algorithm: str,
) -> list[str]:
    errors: list[str] = []

    if (
        body.get(
            "status"
        )
        != "ok"
    ):
        errors.append(
            "response status is not 'ok'"
        )

    if (
        body.get(
            "phase"
        )
        != PHASE
    ):
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

    if (
        body.get(
            "driver_count"
        )
        != size
    ):
        errors.append(
            "driver_count does not match "
            f"requested size {size}"
        )

    if (
        body.get(
            "order_count"
        )
        != size
    ):
        errors.append(
            "order_count does not match "
            f"requested size {size}"
        )

    assigned_order_count = (
        body.get(
            "assigned_order_count"
        )
    )

    if not isinstance(
        assigned_order_count,
        int,
    ):
        errors.append(
            "assigned_order_count is missing "
            "or not an integer"
        )

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
        errors.append(
            "greedy result is missing"
        )

    if not isinstance(
        hungarian,
        dict,
    ):
        errors.append(
            "hungarian result is missing"
        )

    if not isinstance(
        comparison,
        dict,
    ):
        errors.append(
            "comparison result is missing"
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
        road_network = (
            body.get(
                "road_network"
            )
        )

        if not isinstance(
            road_network,
            dict,
        ):
            errors.append(
                "source_dijkstra response "
                "does not contain road_network telemetry"
            )

        else:
            expected_pair_count = (
                size
                * size
            )

            pair_count = (
                road_network.get(
                    "pair_count"
                )
            )

            if (
                pair_count
                != expected_pair_count
            ):
                errors.append(
                    "road-network pair_count mismatch: "
                    f"expected={expected_pair_count}, "
                    f"actual={pair_count}"
                )

            reachable_pair_count = (
                road_network.get(
                    "reachable_pair_count",
                    0,
                )
            )

            unreachable_pair_count = (
                road_network.get(
                    "unreachable_pair_count",
                    0,
                )
            )

            if (
                isinstance(
                    reachable_pair_count,
                    int,
                )
                and isinstance(
                    unreachable_pair_count,
                    int,
                )
                and (
                    reachable_pair_count
                    + unreachable_pair_count
                    != expected_pair_count
                )
            ):
                errors.append(
                    "reachable + unreachable "
                    "pair counts do not equal pair_count"
                )

    return errors


def extract_case_record(
    *,
    mode: str,
    size: int,
    iteration: int,
    request_elapsed_ms: float,
    status_code: int,
    body: dict[str, Any] | None,
    validation_errors: list[str],
    request_error: str | None,
) -> dict[str, Any]:
    body = (
        body
        if isinstance(
            body,
            dict,
        )
        else {}
    )

    road_network = (
        body.get(
            "road_network"
        )
    )

    if not isinstance(
        road_network,
        dict,
    ):
        road_network = {}

    greedy = (
        body.get(
            "greedy"
        )
    )

    if not isinstance(
        greedy,
        dict,
    ):
        greedy = {}

    hungarian = (
        body.get(
            "hungarian"
        )
    )

    if not isinstance(
        hungarian,
        dict,
    ):
        hungarian = {}

    comparison = (
        body.get(
            "comparison"
        )
    )

    if not isinstance(
        comparison,
        dict,
    ):
        comparison = {}

    success = (
        request_error
        is None
        and status_code
        == 200
        and not validation_errors
    )

    return {
        "phase": PHASE,
        "benchmark": (
            "road_dispatch"
        ),
        "mode": mode,
        "size": size,
        "iteration": iteration,
        "success": success,
        "status_code": (
            status_code
        ),
        "request_elapsed_ms": round(
            request_elapsed_ms,
            6,
        ),
        "request_error": (
            request_error
        ),
        "validation_errors": (
            validation_errors
        ),
        "response": {
            "status": body.get(
                "status"
            ),
            "phase": body.get(
                "phase"
            ),
            "matrix_algorithm": (
                body.get(
                    "matrix_algorithm"
                )
            ),
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
            "cache_used": body.get(
                "cache_used"
            ),
            "cache_hit": body.get(
                "cache_hit"
            ),
            "cache_status": body.get(
                "cache_status"
            ),
            "api_elapsed_ms": body.get(
                "api_elapsed_ms"
            ),
        },
        "road_network": {
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
        },
        "greedy": {
            "assigned_count": (
                greedy.get(
                    "assigned_count"
                )
            ),
            "total_cost": greedy.get(
                "total_cost"
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
        },
        "comparison": {
            "hungarian_non_regression": (
                comparison.get(
                    "hungarian_non_regression"
                )
            ),
        },
    }


def run_single_request(
    *,
    client: httpx.Client,
    endpoint_url: str,
    payload: dict[str, Any],
    mode: str,
    size: int,
    iteration: int,
    matrix_algorithm: str,
) -> dict[str, Any]:
    started = (
        time.perf_counter()
    )

    status_code = 0
    body: dict[
        str,
        Any
    ] | None = None

    request_error: (
        str
        | None
    ) = None

    validation_errors: list[
        str
    ] = []

    try:
        response = client.post(
            endpoint_url,
            json=payload,
        )

        status_code = (
            response.status_code
        )

        try:
            decoded = (
                response.json()
            )

            if isinstance(
                decoded,
                dict,
            ):
                body = decoded

            else:
                request_error = (
                    "Response JSON is not "
                    "an object."
                )

        except ValueError as exc:
            request_error = (
                "Response was not valid JSON: "
                f"{exc}"
            )

        if (
            status_code
            == 200
            and body
            is not None
        ):
            validation_errors = (
                validate_response(
                    body=body,
                    size=size,
                    matrix_algorithm=(
                        matrix_algorithm
                    ),
                )
            )

        elif (
            request_error
            is None
        ):
            request_error = (
                "Unexpected HTTP status "
                f"{status_code}: "
                f"{response.text[:500]}"
            )

    except Exception as exc:
        request_error = (
            f"{type(exc).__name__}: "
            f"{exc}"
        )

    request_elapsed_ms = (
        (
            time.perf_counter()
            - started
        )
        * 1000.0
    )

    return extract_case_record(
        mode=mode,
        size=size,
        iteration=iteration,
        request_elapsed_ms=(
            request_elapsed_ms
        ),
        status_code=status_code,
        body=body,
        validation_errors=(
            validation_errors
        ),
        request_error=request_error,
    )


def preflight(
    *,
    client: httpx.Client,
    base_url: str,
) -> dict[str, Any]:
    health_url = (
        f"{base_url.rstrip('/')}"
        "/health"
    )

    started = (
        time.perf_counter()
    )

    try:
        response = client.get(
            health_url
        )

        elapsed_ms = (
            (
                time.perf_counter()
                - started
            )
            * 1000.0
        )

        payload: Any

        try:
            payload = (
                response.json()
            )

        except ValueError:
            payload = (
                response.text
            )

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


def build_size_summary(
    *,
    size: int,
    records: list[
        dict[str, Any]
    ],
) -> dict[str, Any]:
    successful = [
        record
        for record
        in records
        if record[
            "success"
        ]
    ]

    failed = [
        record
        for record
        in records
        if not record[
            "success"
        ]
    ]

    request_times = [
        float(
            record[
                "request_elapsed_ms"
            ]
        )
        for record
        in successful
    ]

    road_total_times = [
        float(
            record[
                "road_network"
            ][
                "total_time_ms"
            ]
        )
        for record
        in successful
        if isinstance(
            record[
                "road_network"
            ][
                "total_time_ms"
            ],
            (
                int,
                float,
            ),
        )
    ]

    matrix_build_times = [
        float(
            record[
                "road_network"
            ][
                "matrix_build_time_ms"
            ]
        )
        for record
        in successful
        if isinstance(
            record[
                "road_network"
            ][
                "matrix_build_time_ms"
            ],
            (
                int,
                float,
            ),
        )
    ]

    unreachable_pair_counts = [
        int(
            record[
                "road_network"
            ][
                "unreachable_pair_count"
            ]
        )
        for record
        in successful
        if isinstance(
            record[
                "road_network"
            ][
                "unreachable_pair_count"
            ],
            int,
        )
    ]

    all_non_regression = all(
        record[
            "comparison"
        ][
            "hungarian_non_regression"
        ]
        is True
        for record
        in successful
    )

    all_assignment_counts_valid = all(
        (
            record[
                "hungarian"
            ][
                "assigned_count"
            ]
            is not None
        )
        and (
            record[
                "response"
            ][
                "assigned_order_count"
            ]
            is not None
        )
        for record
        in successful
    )

    return {
        "size": size,
        "case_count": len(
            records
        ),
        "success_count": len(
            successful
        ),
        "failure_count": len(
            failed
        ),
        "success_rate_pct": round(
            (
                len(
                    successful
                )
                / len(
                    records
                )
                * 100.0
            )
            if records
            else 0.0,
            3,
        ),
        "request_elapsed_ms": (
            summarize_numeric_values(
                request_times
            )
        ),
        "road_total_time_ms": (
            summarize_numeric_values(
                road_total_times
            )
        ),
        "matrix_build_time_ms": (
            summarize_numeric_values(
                matrix_build_times
            )
        ),
        "unreachable_pair_count": (
            summarize_numeric_values(
                [
                    float(
                        value
                    )
                    for value
                    in unreachable_pair_counts
                ]
            )
        ),
        "all_non_regression": (
            all_non_regression
        ),
        "all_assignment_counts_valid": (
            all_assignment_counts_valid
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
    parser = (
        argparse.ArgumentParser(
            description=(
                "Benchmark the Phase 10 live "
                "road-network dispatch endpoint."
            )
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
        default=(
            DEFAULT_ITERATIONS
        ),
    )

    parser.add_argument(
        "--warmup",
        type=int,
        default=(
            DEFAULT_WARMUP
        ),
    )

    parser.add_argument(
        "--matrix-algorithm",
        choices=(
            "source_dijkstra",
            "haversine",
        ),
        default=(
            "source_dijkstra"
        ),
    )

    parser.add_argument(
        "--use-cache",
        action="store_true",
    )

    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=(
            DEFAULT_TIMEOUT_SECONDS
        ),
    )

    args = parser.parse_args()

    if (
        args.iterations
        < 1
    ):
        parser.error(
            "--iterations must be >= 1"
        )

    if (
        args.warmup
        < 0
    ):
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

    base_url = (
        args.base_url
        or (
            DEFAULT_DOCKER_BASE_URL
            if args.mode
            == "docker"
            else DEFAULT_LOCAL_BASE_URL
        )
    ).rstrip(
        "/"
    )

    endpoint_url = (
        f"{base_url}"
        f"{ENDPOINT}"
    )

    timestamp = (
        datetime.now(
            UTC
        )
        .strftime(
            "%Y%m%d_%H%M%S"
        )
    )

    results_directory = (
        Path(
            "benchmarks"
        )
        / "phase_10"
        / (
            f"{args.mode}_results"
        )
    )

    raw_path = (
        results_directory
        / (
            "phase10_road_dispatch_raw_"
            f"{args.mode}_"
            f"{timestamp}.json"
        )
    )

    summary_path = (
        results_directory
        / (
            "phase10_road_dispatch_summary_"
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
        "Road Dispatch Benchmark"
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
        f"endpoint={ENDPOINT}"
    )

    print(
        "matrix_algorithm="
        f"{args.matrix_algorithm}"
    )

    print(
        f"use_cache={args.use_cache}"
    )

    print(
        f"sizes={args.sizes}"
    )

    print(
        "iterations="
        f"{args.iterations}"
    )

    print(
        f"warmup={args.warmup}"
    )

    print(
        "="
        * 80
    )

    timeout = httpx.Timeout(
        args.timeout_seconds
    )

    all_records: list[
        dict[str, Any]
    ] = []

    with httpx.Client(
        timeout=timeout
    ) as client:
        preflight_result = (
            preflight(
                client=client,
                base_url=base_url,
            )
        )

        print(
            "health_preflight="
            f"{preflight_result}"
        )

        if not preflight_result.get(
            "success",
            False,
        ):
            print(
                "ERROR: health preflight "
                "failed."
            )

            return 1

        for size in args.sizes:
            payload = build_payload(
                size=size,
                matrix_algorithm=(
                    args.matrix_algorithm
                ),
                use_cache=(
                    args.use_cache
                ),
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
                warmup_record = (
                    run_single_request(
                        client=client,
                        endpoint_url=(
                            endpoint_url
                        ),
                        payload=payload,
                        mode=args.mode,
                        size=size,
                        iteration=(
                            -(
                                warmup_index
                                + 1
                            )
                        ),
                        matrix_algorithm=(
                            args.matrix_algorithm
                        ),
                    )
                )

                print(
                    "warmup "
                    f"{warmup_index + 1}/"
                    f"{args.warmup} "
                    "success="
                    f"{warmup_record['success']} "
                    "elapsed_ms="
                    f"{warmup_record['request_elapsed_ms']}"
                )

            for iteration in range(
                1,
                args.iterations
                + 1,
            ):
                record = (
                    run_single_request(
                        client=client,
                        endpoint_url=(
                            endpoint_url
                        ),
                        payload=payload,
                        mode=args.mode,
                        size=size,
                        iteration=(
                            iteration
                        ),
                        matrix_algorithm=(
                            args.matrix_algorithm
                        ),
                    )
                )

                all_records.append(
                    record
                )

                print(
                    f"iteration={iteration}/"
                    f"{args.iterations} "
                    "success="
                    f"{record['success']} "
                    "request_elapsed_ms="
                    f"{record['request_elapsed_ms']} "
                    "assigned="
                    f"{record['response']['assigned_order_count']} "
                    "unreachable_pairs="
                    f"{record['road_network']['unreachable_pair_count']}"
                )

                if not record[
                    "success"
                ]:
                    print(
                        "  request_error="
                        f"{record['request_error']}"
                    )

                    print(
                        "  validation_errors="
                        f"{record['validation_errors']}"
                    )

    size_summaries = [
        build_size_summary(
            size=size,
            records=[
                record
                for record
                in all_records
                if (
                    record[
                        "size"
                    ]
                    == size
                )
            ],
        )
        for size
        in args.sizes
    ]

    successful_records = [
        record
        for record
        in all_records
        if record[
            "success"
        ]
    ]

    failure_records = [
        record
        for record
        in all_records
        if not record[
            "success"
        ]
    ]

    all_non_regression = all(
        record[
            "comparison"
        ][
            "hungarian_non_regression"
        ]
        is True
        for record
        in successful_records
    )

    source_dijkstra_road_telemetry_present = all(
        (
            record[
                "road_network"
            ][
                "pair_count"
            ]
            is not None
        )
        for record
        in successful_records
    ) if (
        args.matrix_algorithm
        == "source_dijkstra"
    ) else True

    raw_payload = {
        "phase": PHASE,
        "benchmark": (
            "road_dispatch"
        ),
        "created_at_utc": (
            datetime.now(
                UTC
            ).isoformat()
        ),
        "configuration": {
            "mode": args.mode,
            "base_url": base_url,
            "endpoint": (
                ENDPOINT
            ),
            "matrix_algorithm": (
                args.matrix_algorithm
            ),
            "use_cache": (
                args.use_cache
            ),
            "sizes": list(
                args.sizes
            ),
            "iterations": (
                args.iterations
            ),
            "warmup": (
                args.warmup
            ),
            "timeout_seconds": (
                args.timeout_seconds
            ),
        },
        "health_preflight": (
            preflight_result
        ),
        "records": (
            all_records
        ),
    }

    summary_payload = {
        "phase": PHASE,
        "benchmark": (
            "road_dispatch"
        ),
        "created_at_utc": (
            datetime.now(
                UTC
            ).isoformat()
        ),
        "configuration": {
            "mode": args.mode,
            "base_url": base_url,
            "endpoint": (
                ENDPOINT
            ),
            "matrix_algorithm": (
                args.matrix_algorithm
            ),
            "use_cache": (
                args.use_cache
            ),
            "sizes": list(
                args.sizes
            ),
            "iterations": (
                args.iterations
            ),
            "warmup": (
                args.warmup
            ),
        },
        "case_count": len(
            all_records
        ),
        "success_count": len(
            successful_records
        ),
        "failure_count": len(
            failure_records
        ),
        "success_rate_pct": round(
            (
                len(
                    successful_records
                )
                / len(
                    all_records
                )
                * 100.0
            )
            if all_records
            else 0.0,
            3,
        ),
        "all_non_regression": (
            all_non_regression
        ),
        "source_dijkstra_road_telemetry_present": (
            source_dijkstra_road_telemetry_present
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
                "status_code": (
                    record[
                        "status_code"
                    ]
                ),
                "request_error": (
                    record[
                        "request_error"
                    ]
                ),
                "validation_errors": (
                    record[
                        "validation_errors"
                    ]
                ),
            }
            for record
            in failure_records
        ],
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
        if not failure_records
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )