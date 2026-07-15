
# benchmarks/phase_10/phase10_load_probe.py

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

PHASE = "tier3_phase10"
BENCHMARK = "load"
ENDPOINT = "/dispatch/compare"

DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_DOCKER_BASE_URL = "http://127.0.0.1:8001"

DEFAULT_SIZES = (10, 25, 50)
DEFAULT_CONCURRENCY_LEVELS = (1, 2, 4, 8)
DEFAULT_REQUESTS_PER_LEVEL = 40
DEFAULT_WARMUP = 2
DEFAULT_TIMEOUT_SECONDS = 180.0

KANPUR_CENTER_LAT = 26.4499
KANPUR_CENTER_LON = 80.3319


def parse_positive_int_list(
    raw_value: str,
) -> tuple[int, ...]:
    values: list[int] = []

    for item in raw_value.split(","):
        stripped = item.strip()

        if not stripped:
            continue

        value = int(stripped)

        if value < 1:
            raise argparse.ArgumentTypeError(
                "Every value must be >= 1."
            )

        values.append(value)

    if not values:
        raise argparse.ArgumentTypeError(
            "At least one value is required."
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
            "p99": 0.0,
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
        "p99": round(
            percentile(values, 99.0),
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


def finite_number(
    value: Any,
) -> float | None:
    if isinstance(value, bool):
        return None

    try:
        number = float(value)

    except (TypeError, ValueError):
        return None

    if not math.isfinite(number):
        return None

    return number


def scenario_shift(
    scenario_index: int,
) -> tuple[float, float]:
    lat_units = (
        (scenario_index * 37) % 41
    ) - 20

    lon_units = (
        (scenario_index * 53) % 43
    ) - 21

    return (
        lat_units * 0.000025,
        lon_units * 0.000025,
    )


def build_coordinate(
    index: int,
    *,
    latitude_offset: float,
    longitude_offset: float,
    scenario_index: int,
) -> tuple[float, float]:
    row = index // 10
    column = index % 10

    scenario_lat_shift, scenario_lon_shift = (
        scenario_shift(scenario_index)
    )

    lat = (
        KANPUR_CENTER_LAT
        + latitude_offset
        + scenario_lat_shift
        + row * 0.00115
        + column * 0.00017
    )

    lon = (
        KANPUR_CENTER_LON
        + longitude_offset
        + scenario_lon_shift
        + column * 0.00105
        + row * 0.00019
    )

    return (
        round(lat, 7),
        round(lon, 7),
    )


def build_payload(
    *,
    size: int,
    scenario_index: int,
    matrix_algorithm: str,
    use_cache: bool,
) -> dict[str, Any]:
    drivers: list[dict[str, Any]] = []
    orders: list[dict[str, Any]] = []

    scenario_label = (
        f"load_s{size}_"
        f"case{scenario_index}"
    )

    for index in range(size):
        driver_lat, driver_lon = (
            build_coordinate(
                index,
                latitude_offset=0.0,
                longitude_offset=0.0,
                scenario_index=scenario_index,
            )
        )

        order_lat, order_lon = (
            build_coordinate(
                index,
                latitude_offset=0.00043,
                longitude_offset=0.00061,
                scenario_index=scenario_index,
            )
        )

        drivers.append(
            {
                "driver_id": (
                    f"{scenario_label}_driver_{index}"
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
                    f"{scenario_label}_order_{index}"
                ),
                "pickup_lat": order_lat,
                "pickup_lon": order_lon,
            }
        )

    return {
        "drivers": drivers,
        "orders": orders,
        "matrix_algorithm": matrix_algorithm,
        "use_cache": use_cache,
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
        body.get("matrix_algorithm")
        != matrix_algorithm
    ):
        errors.append(
            "matrix_algorithm mismatch"
        )

    if body.get("driver_count") != size:
        errors.append(
            "driver_count mismatch"
        )

    if body.get("order_count") != size:
        errors.append(
            "order_count mismatch"
        )

    assigned_count = body.get(
        "assigned_order_count"
    )

    unassigned_count = body.get(
        "unassigned_order_count"
    )

    if (
        not isinstance(assigned_count, int)
        or isinstance(assigned_count, bool)
    ):
        errors.append(
            "assigned_order_count is invalid"
        )

    if (
        not isinstance(unassigned_count, int)
        or isinstance(unassigned_count, bool)
    ):
        errors.append(
            "unassigned_order_count is invalid"
        )

    if (
        isinstance(assigned_count, int)
        and not isinstance(assigned_count, bool)
        and isinstance(unassigned_count, int)
        and not isinstance(unassigned_count, bool)
        and (
            assigned_count
            + unassigned_count
            != size
        )
    ):
        errors.append(
            "assigned + unassigned order count mismatch"
        )

    greedy = body.get("greedy")

    if not isinstance(greedy, dict):
        errors.append(
            "greedy result missing"
        )

    hungarian = body.get(
        "hungarian"
    )

    if not isinstance(
        hungarian,
        dict,
    ):
        errors.append(
            "hungarian result missing"
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

            pair_count = (
                road_network.get(
                    "pair_count"
                )
            )

            reachable_count = (
                road_network.get(
                    "reachable_pair_count"
                )
            )

            unreachable_count = (
                road_network.get(
                    "unreachable_pair_count"
                )
            )

            if (
                pair_count
                != expected_pair_count
            ):
                errors.append(
                    "road-network pair_count mismatch"
                )

            if (
                isinstance(
                    reachable_count,
                    int,
                )
                and not isinstance(
                    reachable_count,
                    bool,
                )
                and isinstance(
                    unreachable_count,
                    int,
                )
                and not isinstance(
                    unreachable_count,
                    bool,
                )
                and (
                    reachable_count
                    + unreachable_count
                    != expected_pair_count
                )
            ):
                errors.append(
                    "reachable + unreachable pair count mismatch"
                )

    return errors


def extract_response_record(
    *,
    body: dict[str, Any],
) -> dict[str, Any]:
    comparison = body.get(
        "comparison"
    )

    if not isinstance(
        comparison,
        dict,
    ):
        comparison = {}

    greedy = body.get(
        "greedy"
    )

    if not isinstance(
        greedy,
        dict,
    ):
        greedy = {}

    hungarian = body.get(
        "hungarian"
    )

    if not isinstance(
        hungarian,
        dict,
    ):
        hungarian = {}

    road_network = body.get(
        "road_network"
    )

    if not isinstance(
        road_network,
        dict,
    ):
        road_network = {}

    return {
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
        "api_elapsed_ms": (
            body.get(
                "api_elapsed_ms"
            )
        ),
        "cache_used": (
            body.get(
                "cache_used"
            )
        ),
        "cache_hit": (
            body.get(
                "cache_hit"
            )
        ),
        "cache_status": (
            body.get(
                "cache_status"
            )
        ),
        "greedy_total_cost": (
            greedy.get(
                "total_cost"
            )
        ),
        "hungarian_total_cost": (
            hungarian.get(
                "total_cost"
            )
        ),
        "hungarian_non_regression": (
            comparison.get(
                "hungarian_non_regression"
            )
        ),
        "road_network": {
            "matrix_source": (
                road_network.get(
                    "matrix_source"
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
            "source_search_count": (
                road_network.get(
                    "source_search_count"
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
            "snap_time_ms": (
                road_network.get(
                    "snap_time_ms"
                )
            ),
            "matrix_build_time_ms": (
                road_network.get(
                    "matrix_build_time_ms"
                )
            ),
            "total_time_ms": (
                road_network.get(
                    "total_time_ms"
                )
            ),
        },
    }


async def run_request(
    *,
    client: httpx.AsyncClient,
    endpoint_url: str,
    payload: dict[str, Any],
    request_index: int,
    scenario_index: int,
    size: int,
    concurrency: int,
    matrix_algorithm: str,
) -> dict[str, Any]:
    started = time.perf_counter()

    try:
        response = await client.post(
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
                "request_index": request_index,
                "scenario_index": scenario_index,
                "size": size,
                "concurrency": concurrency,
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
                "validation_errors": [],
                "response": None,
            }

        if not isinstance(
            decoded,
            dict,
        ):
            return {
                "request_index": request_index,
                "scenario_index": scenario_index,
                "size": size,
                "concurrency": concurrency,
                "success": False,
                "status_code": (
                    response.status_code
                ),
                "elapsed_ms": round(
                    elapsed_ms,
                    6,
                ),
                "error": (
                    "Response JSON is not an object."
                ),
                "validation_errors": [],
                "response": None,
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
            "request_index": request_index,
            "scenario_index": scenario_index,
            "size": size,
            "concurrency": concurrency,
            "success": success,
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
                else response.text[:1000]
            ),
            "validation_errors": (
                validation_errors
            ),
            "response": (
                extract_response_record(
                    body=decoded
                )
            ),
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
            "request_index": request_index,
            "scenario_index": scenario_index,
            "size": size,
            "concurrency": concurrency,
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
            "response": None,
        }


async def run_load_level(
    *,
    client: httpx.AsyncClient,
    endpoint_url: str,
    payloads: list[
        tuple[
            int,
            dict[str, Any],
        ]
    ],
    size: int,
    concurrency: int,
    matrix_algorithm: str,
) -> dict[str, Any]:
    semaphore = asyncio.Semaphore(
        concurrency
    )

    start_event = asyncio.Event()

    async def execute_one(
        request_index: int,
        scenario_index: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        await start_event.wait()

        async with semaphore:
            return await run_request(
                client=client,
                endpoint_url=endpoint_url,
                payload=payload,
                request_index=request_index,
                scenario_index=(
                    scenario_index
                ),
                size=size,
                concurrency=concurrency,
                matrix_algorithm=(
                    matrix_algorithm
                ),
            )

    tasks = [
        asyncio.create_task(
            execute_one(
                request_index,
                scenario_index,
                payload,
            )
        )
        for request_index, (
            scenario_index,
            payload,
        ) in enumerate(
            payloads,
            start=1,
        )
    ]

    started = time.perf_counter()

    start_event.set()

    records = await asyncio.gather(
        *tasks
    )

    wall_time_ms = (
        (
            time.perf_counter()
            - started
        )
        * 1000.0
    )

    return {
        "size": size,
        "concurrency": concurrency,
        "request_count": len(records),
        "wall_time_ms": round(
            wall_time_ms,
            6,
        ),
        "records": records,
    }


def build_level_summary(
    level: dict[str, Any],
) -> dict[str, Any]:
    records = level["records"]

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

    elapsed_values = [
        float(
            record[
                "elapsed_ms"
            ]
        )
        for record in successful
    ]

    road_total_times: list[
        float
    ] = []

    snap_times: list[
        float
    ] = []

    matrix_build_times: list[
        float
    ] = []

    api_elapsed_times: list[
        float
    ] = []

    non_regression_count = 0

    assignment_count_integrity_count = 0

    for record in successful:
        response = record.get(
            "response"
        )

        if not isinstance(
            response,
            dict,
        ):
            continue

        if (
            response.get(
                "hungarian_non_regression"
            )
            is True
        ):
            non_regression_count += 1

        assigned_count = (
            response.get(
                "assigned_order_count"
            )
        )

        unassigned_count = (
            response.get(
                "unassigned_order_count"
            )
        )

        if (
            isinstance(
                assigned_count,
                int,
            )
            and not isinstance(
                assigned_count,
                bool,
            )
            and isinstance(
                unassigned_count,
                int,
            )
            and not isinstance(
                unassigned_count,
                bool,
            )
            and (
                assigned_count
                + unassigned_count
                == level["size"]
            )
        ):
            assignment_count_integrity_count += 1

        api_elapsed_ms = (
            finite_number(
                response.get(
                    "api_elapsed_ms"
                )
            )
        )

        if api_elapsed_ms is not None:
            api_elapsed_times.append(
                api_elapsed_ms
            )

        road_network = response.get(
            "road_network"
        )

        if not isinstance(
            road_network,
            dict,
        ):
            continue

        road_total_ms = finite_number(
            road_network.get(
                "total_time_ms"
            )
        )

        if road_total_ms is not None:
            road_total_times.append(
                road_total_ms
            )

        snap_time_ms = finite_number(
            road_network.get(
                "snap_time_ms"
            )
        )

        if snap_time_ms is not None:
            snap_times.append(
                snap_time_ms
            )

        matrix_build_time_ms = (
            finite_number(
                road_network.get(
                    "matrix_build_time_ms"
                )
            )
        )

        if (
            matrix_build_time_ms
            is not None
        ):
            matrix_build_times.append(
                matrix_build_time_ms
            )

    wall_time_s = (
        float(
            level[
                "wall_time_ms"
            ]
        )
        / 1000.0
    )

    request_count = len(records)

    total_throughput_rps = (
        request_count
        / wall_time_s
        if wall_time_s > 0.0
        else 0.0
    )

    successful_throughput_rps = (
        len(successful)
        / wall_time_s
        if wall_time_s > 0.0
        else 0.0
    )

    status_counts = Counter(
        str(
            record[
                "status_code"
            ]
        )
        for record in records
    )

    return {
        "size": level["size"],
        "concurrency": (
            level[
                "concurrency"
            ]
        ),
        "request_count": (
            request_count
        ),
        "success_count": (
            len(successful)
        ),
        "failure_count": (
            len(failures)
        ),
        "success_rate_pct": round(
            (
                len(successful)
                / request_count
                * 100.0
            )
            if request_count
            else 0.0,
            3,
        ),
        "wall_time_ms": (
            level[
                "wall_time_ms"
            ]
        ),
        "throughput_requests_per_second": round(
            total_throughput_rps,
            6,
        ),
        "successful_requests_per_second": round(
            successful_throughput_rps,
            6,
        ),
        "request_elapsed_ms": (
            summarize_values(
                elapsed_values
            )
        ),
        "api_elapsed_ms": (
            summarize_values(
                api_elapsed_times
            )
        ),
        "road_total_time_ms": (
            summarize_values(
                road_total_times
            )
        ),
        "road_snap_time_ms": (
            summarize_values(
                snap_times
            )
        ),
        "road_matrix_build_time_ms": (
            summarize_values(
                matrix_build_times
            )
        ),
        "hungarian_non_regression_count": (
            non_regression_count
        ),
        "expected_hungarian_non_regression_count": (
            len(successful)
        ),
        "assignment_count_integrity_count": (
            assignment_count_integrity_count
        ),
        "expected_assignment_count_integrity_count": (
            len(successful)
        ),
        "status_code_counts": dict(
            sorted(
                status_counts.items()
            )
        ),
    }


def add_baseline_comparisons(
    *,
    level_summaries: list[
        dict[str, Any]
    ],
) -> None:
    summaries_by_size: dict[
        int,
        list[dict[str, Any]],
    ] = {}

    for summary in level_summaries:
        summaries_by_size.setdefault(
            int(
                summary[
                    "size"
                ]
            ),
            [],
        ).append(
            summary
        )

    for summaries in (
        summaries_by_size.values()
    ):
        baseline = next(
            (
                summary
                for summary
                in summaries
                if (
                    summary[
                        "concurrency"
                    ]
                    == 1
                )
            ),
            None,
        )

        if baseline is None:
            for summary in summaries:
                summary[
                    "comparison_vs_concurrency_1"
                ] = None

            continue

        baseline_throughput = float(
            baseline[
                "throughput_requests_per_second"
            ]
        )

        baseline_median = float(
            baseline[
                "request_elapsed_ms"
            ][
                "median"
            ]
        )

        baseline_p95 = float(
            baseline[
                "request_elapsed_ms"
            ][
                "p95"
            ]
        )

        for summary in summaries:
            concurrency = int(
                summary[
                    "concurrency"
                ]
            )

            throughput = float(
                summary[
                    "throughput_requests_per_second"
                ]
            )

            median_latency = float(
                summary[
                    "request_elapsed_ms"
                ][
                    "median"
                ]
            )

            p95_latency = float(
                summary[
                    "request_elapsed_ms"
                ][
                    "p95"
                ]
            )

            throughput_scaling = (
                safe_ratio(
                    throughput,
                    baseline_throughput,
                )
            )

            median_inflation = (
                safe_ratio(
                    median_latency,
                    baseline_median,
                )
            )

            p95_inflation = safe_ratio(
                p95_latency,
                baseline_p95,
            )

            scaling_efficiency_pct = None

            if (
                throughput_scaling
                is not None
                and concurrency > 0
            ):
                scaling_efficiency_pct = (
                    throughput_scaling
                    / concurrency
                    * 100.0
                )

            summary[
                "comparison_vs_concurrency_1"
            ] = {
                "throughput_scaling_ratio": (
                    round(
                        throughput_scaling,
                        6,
                    )
                    if throughput_scaling
                    is not None
                    else None
                ),
                "median_latency_inflation_ratio": (
                    round(
                        median_inflation,
                        6,
                    )
                    if median_inflation
                    is not None
                    else None
                ),
                "p95_latency_inflation_ratio": (
                    round(
                        p95_inflation,
                        6,
                    )
                    if p95_inflation
                    is not None
                    else None
                ),
                "throughput_scaling_efficiency_pct": (
                    round(
                        scaling_efficiency_pct,
                        3,
                    )
                    if (
                        scaling_efficiency_pct
                        is not None
                    )
                    else None
                ),
            }


def build_size_summaries(
    *,
    sizes: tuple[int, ...],
    level_summaries: list[
        dict[str, Any]
    ],
) -> list[dict[str, Any]]:
    result: list[
        dict[str, Any]
    ] = []

    for size in sizes:
        levels = [
            summary
            for summary
            in level_summaries
            if (
                summary[
                    "size"
                ]
                == size
            )
        ]

        levels.sort(
            key=lambda item: int(
                item[
                    "concurrency"
                ]
            )
        )

        best_throughput = max(
            (
                float(
                    level[
                        "throughput_requests_per_second"
                    ]
                )
                for level
                in levels
            ),
            default=0.0,
        )

        best_level = next(
            (
                level
                for level in levels
                if (
                    float(
                        level[
                            "throughput_requests_per_second"
                        ]
                    )
                    == best_throughput
                )
            ),
            None,
        )

        result.append(
            {
                "size": size,
                "load_levels": (
                    levels
                ),
                "best_throughput_requests_per_second": (
                    round(
                        best_throughput,
                        6,
                    )
                ),
                "best_throughput_concurrency": (
                    best_level[
                        "concurrency"
                    ]
                    if best_level
                    is not None
                    else None
                ),
            }
        )

    return result


async def preflight(
    *,
    client: httpx.AsyncClient,
    base_url: str,
) -> dict[str, Any]:
    started = time.perf_counter()

    try:
        response = await client.get(
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


async def run_probe(
    args: argparse.Namespace,
) -> int:
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
            "phase10_load_raw_"
            f"{args.mode}_"
            f"{timestamp}.json"
        )
    )

    summary_path = (
        result_directory
        / (
            "phase10_load_summary_"
            f"{args.mode}_"
            f"{timestamp}.json"
        )
    )

    print("=" * 80)
    print(
        "CityRoute Phase 10 "
        "Concurrent Load Probe"
    )
    print("=" * 80)
    print(f"mode={args.mode}")
    print(f"base_url={base_url}")
    print(f"endpoint={ENDPOINT}")
    print(
        "matrix_algorithm="
        f"{args.matrix_algorithm}"
    )
    print(
        f"use_cache={args.use_cache}"
    )
    print(f"sizes={args.sizes}")
    print(
        "concurrency_levels="
        f"{args.concurrency_levels}"
    )
    print(
        "requests_per_level="
        f"{args.requests_per_level}"
    )
    print(
        f"warmup={args.warmup}"
    )
    print(
        "workload_policy="
        "same deterministic request set "
        "at every concurrency level"
    )
    print("=" * 80)

    maximum_concurrency = max(
        args.concurrency_levels
    )

    limits = httpx.Limits(
        max_connections=max(
            maximum_concurrency * 2,
            20,
        ),
        max_keepalive_connections=max(
            maximum_concurrency * 2,
            20,
        ),
    )

    timeout = httpx.Timeout(
        args.timeout_seconds
    )

    raw_levels: list[
        dict[str, Any]
    ] = []

    async with httpx.AsyncClient(
        timeout=timeout,
        limits=limits,
    ) as client:
        health = await preflight(
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

            workload = [
                (
                    request_index,
                    build_payload(
                        size=size,
                        scenario_index=(
                            request_index
                        ),
                        matrix_algorithm=(
                            args.matrix_algorithm
                        ),
                        use_cache=(
                            args.use_cache
                        ),
                    ),
                )
                for request_index
                in range(
                    args.requests_per_level
                )
            ]

            for warmup_index in range(
                args.warmup
            ):
                scenario_index = (
                    100_000
                    + size * 100
                    + warmup_index
                )

                warmup_payload = (
                    build_payload(
                        size=size,
                        scenario_index=(
                            scenario_index
                        ),
                        matrix_algorithm=(
                            args.matrix_algorithm
                        ),
                        use_cache=(
                            args.use_cache
                        ),
                    )
                )

                warmup_result = (
                    await run_request(
                        client=client,
                        endpoint_url=(
                            endpoint_url
                        ),
                        payload=(
                            warmup_payload
                        ),
                        request_index=(
                            warmup_index
                            + 1
                        ),
                        scenario_index=(
                            scenario_index
                        ),
                        size=size,
                        concurrency=1,
                        matrix_algorithm=(
                            args.matrix_algorithm
                        ),
                    )
                )

                print(
                    "warmup="
                    f"{warmup_index + 1}/"
                    f"{args.warmup} "
                    "success="
                    f"{warmup_result['success']} "
                    "elapsed_ms="
                    f"{warmup_result['elapsed_ms']}"
                )

                if not warmup_result[
                    "success"
                ]:
                    print(
                        "ERROR: warmup request failed."
                    )

                    return 1

            for level_index, concurrency in enumerate(
                args.concurrency_levels
            ):
                # Rotate submission order slightly while keeping
                # exactly the same workload set at each load level.
                shift = (
                    level_index
                    % len(workload)
                )

                ordered_workload = (
                    workload[shift:]
                    + workload[:shift]
                )

                print()
                print(
                    "running "
                    f"size={size} "
                    f"concurrency={concurrency} "
                    "requests="
                    f"{args.requests_per_level}"
                )

                raw_level = (
                    await run_load_level(
                        client=client,
                        endpoint_url=(
                            endpoint_url
                        ),
                        payloads=(
                            ordered_workload
                        ),
                        size=size,
                        concurrency=(
                            concurrency
                        ),
                        matrix_algorithm=(
                            args.matrix_algorithm
                        ),
                    )
                )

                raw_levels.append(
                    raw_level
                )

                level_summary = (
                    build_level_summary(
                        raw_level
                    )
                )

                latency = (
                    level_summary[
                        "request_elapsed_ms"
                    ]
                )

                print(
                    "result "
                    f"success="
                    f"{level_summary['success_count']}/"
                    f"{level_summary['request_count']} "
                    "wall_ms="
                    f"{level_summary['wall_time_ms']} "
                    "throughput_rps="
                    f"{level_summary['throughput_requests_per_second']} "
                    "median_ms="
                    f"{latency['median']} "
                    "p95_ms="
                    f"{latency['p95']} "
                    "p99_ms="
                    f"{latency['p99']} "
                    "max_ms="
                    f"{latency['max']}"
                )

    level_summaries = [
        build_level_summary(
            level
        )
        for level in raw_levels
    ]

    add_baseline_comparisons(
        level_summaries=(
            level_summaries
        )
    )

    size_summaries = (
        build_size_summaries(
            sizes=args.sizes,
            level_summaries=(
                level_summaries
            ),
        )
    )

    all_records = [
        record
        for level in raw_levels
        for record in level[
            "records"
        ]
    ]

    successful_records = [
        record
        for record in all_records
        if record["success"]
    ]

    failed_records = [
        record
        for record in all_records
        if not record["success"]
    ]

    non_regression_pass_count = sum(
        1
        for record in successful_records
        if (
            isinstance(
                record.get(
                    "response"
                ),
                dict,
            )
            and record[
                "response"
            ].get(
                "hungarian_non_regression"
            )
            is True
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
                args.matrix_algorithm
            ),
            "use_cache": (
                args.use_cache
            ),
            "sizes": list(
                args.sizes
            ),
            "concurrency_levels": list(
                args.concurrency_levels
            ),
            "requests_per_level": (
                args.requests_per_level
            ),
            "warmup": (
                args.warmup
            ),
            "timeout_seconds": (
                args.timeout_seconds
            ),
            "workload_policy": (
                "same deterministic request set "
                "at every concurrency level"
            ),
        },
        "health_preflight": health,
        "levels": raw_levels,
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
                args.matrix_algorithm
            ),
            "use_cache": (
                args.use_cache
            ),
            "sizes": list(
                args.sizes
            ),
            "concurrency_levels": list(
                args.concurrency_levels
            ),
            "requests_per_level": (
                args.requests_per_level
            ),
            "warmup": (
                args.warmup
            ),
        },
        "load_level_count": (
            len(
                raw_levels
            )
        ),
        "total_request_count": (
            len(
                all_records
            )
        ),
        "success_count": (
            len(
                successful_records
            )
        ),
        "failure_count": (
            len(
                failed_records
            )
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
        "all_requests_successful": (
            not failed_records
        ),
        "hungarian_non_regression_pass_count": (
            non_regression_pass_count
        ),
        "expected_hungarian_non_regression_pass_count": (
            len(
                successful_records
            )
        ),
        "all_hungarian_non_regression_checks_passed": (
            non_regression_pass_count
            == len(
                successful_records
            )
        ),
        "size_summaries": (
            size_summaries
        ),
        "failed_requests": [
            {
                "size": (
                    record[
                        "size"
                    ]
                ),
                "concurrency": (
                    record[
                        "concurrency"
                    ]
                ),
                "request_index": (
                    record[
                        "request_index"
                    ]
                ),
                "scenario_index": (
                    record[
                        "scenario_index"
                    ]
                ),
                "status_code": (
                    record[
                        "status_code"
                    ]
                ),
                "error": (
                    record[
                        "error"
                    ]
                ),
                "validation_errors": (
                    record[
                        "validation_errors"
                    ]
                ),
            }
            for record
            in failed_records
        ],
        "interpretation_note": (
            "For each matrix size, every concurrency level executes "
            "the same deterministic set of dispatch workloads. "
            "Cache is disabled by default so the source_dijkstra run "
            "measures concurrent road-network computation rather than "
            "warm Redis performance. Throughput scaling and latency "
            "inflation are reported relative to concurrency=1 when "
            "that baseline is included."
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
        if not failed_records
        else 1
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Measure concurrent Phase 10 dispatch API "
            "latency, throughput, and scaling."
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
        type=parse_positive_int_list,
        default=DEFAULT_SIZES,
    )

    parser.add_argument(
        "--concurrency-levels",
        type=parse_positive_int_list,
        default=(
            DEFAULT_CONCURRENCY_LEVELS
        ),
    )

    parser.add_argument(
        "--requests-per-level",
        type=int,
        default=(
            DEFAULT_REQUESTS_PER_LEVEL
        ),
    )

    parser.add_argument(
        "--warmup",
        type=int,
        default=DEFAULT_WARMUP,
    )

    parser.add_argument(
        "--matrix-algorithm",
        choices=(
            "source_dijkstra",
            "haversine",
        ),
        default="source_dijkstra",
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

    if args.requests_per_level < 1:
        parser.error(
            "--requests-per-level must be >= 1"
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

    return asyncio.run(
        run_probe(args)
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )