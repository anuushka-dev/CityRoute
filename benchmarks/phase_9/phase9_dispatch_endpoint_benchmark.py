# phase9_dispatch_endpoint_benchmark.py

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_LOCAL_OUTPUT_DIR = PROJECT_ROOT / "benchmarks" / "phase_9" / "local_results"
DEFAULT_DOCKER_OUTPUT_DIR = PROJECT_ROOT / "benchmarks" / "phase_9" / "docker_results"

DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_DOCKER_BASE_URL = "http://127.0.0.1:8001"

KANPUR_BASE_LAT = 26.4499
KANPUR_BASE_LON = 80.3319


@dataclass(frozen=True)
class DispatchEndpointCaseResult:
    mode: str
    base_url: str
    endpoint: str
    size: int
    iteration: int
    status_code: int | None
    success: bool
    error: str | None
    request_elapsed_ms: float
    api_elapsed_ms: float | None
    matrix_generation_time_ms: float | None
    greedy_total_cost: float | None
    hungarian_total_cost: float | None
    hungarian_cost_saved: float | None
    hungarian_improvement_pct: float | None
    hungarian_non_regression: bool | None
    driver_count: int | None
    order_count: int | None
    available_slot_count: int | None
    assigned_order_count: int | None
    unassigned_order_count: int | None
    unused_slot_count: int | None
    greedy_assigned_count: int | None
    hungarian_assigned_count: int | None
    fairness_score: float | None


@dataclass(frozen=True)
class DispatchEndpointGroupSummary:
    size: int
    iteration_count: int
    success_count: int
    failure_count: int
    success_rate_pct: float
    request_elapsed_ms: dict[str, float]
    api_elapsed_ms: dict[str, float]
    matrix_generation_time_ms: dict[str, float]
    hungarian_improvement_pct: dict[str, float]
    all_non_regression: bool
    all_assignment_counts_valid: bool
    all_capacity_counts_valid: bool
    median_request_under_250ms: bool | None
    median_request_under_500ms: bool | None


@dataclass(frozen=True)
class DispatchEndpointBenchmarkSummary:
    phase: str
    benchmark: str
    mode: str
    base_url: str
    endpoint: str
    matrix_algorithm: str
    created_at_utc: str
    sizes: list[int]
    iterations_per_size: int
    warmup_iterations: int
    case_count: int
    success_count: int
    failure_count: int
    success_rate_pct: float
    group_summaries: dict[str, DispatchEndpointGroupSummary]
    output_raw_file: str
    output_summary_file: str
    quality_flags: dict[str, bool]


def main() -> None:
    args = _parse_args()

    mode: Literal["local", "docker"] = args.mode
    output_dir = _resolve_output_dir(mode=mode, output_dir=args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    base_url = _resolve_base_url(mode=mode, base_url=args.base_url).rstrip("/")
    endpoint = args.endpoint

    sizes = _parse_sizes(args.sizes)

    if any(size < 1 for size in sizes):
        raise ValueError("All sizes must be >= 1.")

    if any(size > args.max_size for size in sizes):
        raise ValueError(
            f"Requested size exceeds max_size={args.max_size}. "
            "The current dispatch schema is capped at 50 drivers/orders."
        )

    _run_warmup(
        base_url=base_url,
        endpoint=endpoint,
        warmup_iterations=args.warmup_iterations,
        timeout_s=args.timeout_s,
        matrix_algorithm=args.matrix_algorithm,
    )

    results: list[DispatchEndpointCaseResult] = []

    for size in sizes:
        for iteration in range(1, args.iterations + 1):
            payload = _build_payload(
                size=size,
                matrix_algorithm=args.matrix_algorithm,
                return_cost_breakdown=args.return_cost_breakdown,
                load_penalty_m=args.load_penalty_m,
                slot_penalty_m=args.slot_penalty_m,
            )

            results.append(
                _run_case(
                    mode=mode,
                    base_url=base_url,
                    endpoint=endpoint,
                    size=size,
                    iteration=iteration,
                    payload=payload,
                    timeout_s=args.timeout_s,
                )
            )

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    raw_path = output_dir / f"phase9_dispatch_endpoint_raw_{mode}_{timestamp}.json"
    summary_path = (
        output_dir / f"phase9_dispatch_endpoint_summary_{mode}_{timestamp}.json"
    )

    raw_payload = {
        "phase": "tier3_phase9",
        "benchmark": "dispatch_endpoint_benchmark",
        "mode": mode,
        "base_url": base_url,
        "endpoint": endpoint,
        "matrix_algorithm": args.matrix_algorithm,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "sizes": sizes,
        "iterations_per_size": args.iterations,
        "warmup_iterations": args.warmup_iterations,
        "cases": [asdict(result) for result in results],
    }

    _write_json(raw_path, raw_payload)

    success_count = sum(result.success for result in results)
    failure_count = len(results) - success_count

    group_summaries = _build_group_summaries(results, sizes)

    summary = DispatchEndpointBenchmarkSummary(
        phase="tier3_phase9",
        benchmark="dispatch_endpoint_benchmark",
        mode=mode,
        base_url=base_url,
        endpoint=endpoint,
        matrix_algorithm=args.matrix_algorithm,
        created_at_utc=datetime.now(UTC).isoformat(),
        sizes=sizes,
        iterations_per_size=args.iterations,
        warmup_iterations=args.warmup_iterations,
        case_count=len(results),
        success_count=success_count,
        failure_count=failure_count,
        success_rate_pct=round((success_count / len(results)) * 100.0, 6)
        if results
        else 0.0,
        group_summaries=group_summaries,
        output_raw_file=str(raw_path.relative_to(PROJECT_ROOT)),
        output_summary_file=str(summary_path.relative_to(PROJECT_ROOT)),
        quality_flags={
            "all_requests_successful": failure_count == 0,
            "all_non_regression": all(
                result.hungarian_non_regression is True
                for result in results
                if result.success
            )
            and failure_count == 0,
            "all_assignment_counts_valid": all(
                _assignment_counts_valid(result) for result in results
            )
            and failure_count == 0,
            "all_capacity_counts_valid": all(
                _capacity_counts_valid(result) for result in results
            )
            and failure_count == 0,
            "size_25_median_request_under_250ms": _target_flag(
                group_summaries,
                size=25,
                target_key="median_request_under_250ms",
            ),
            "size_50_median_request_under_500ms": _target_flag(
                group_summaries,
                size=50,
                target_key="median_request_under_500ms",
            ),
        },
    )

    summary_payload = _summary_to_jsonable_dict(summary)
    _write_json(summary_path, summary_payload)

    print(json.dumps(summary_payload, indent=2))

    if failure_count != 0:
        raise SystemExit(1)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 9 /dispatch/compare endpoint benchmark.",
    )
    parser.add_argument(
        "--mode",
        choices=["local", "docker"],
        default="local",
        help="Result mode. Controls default base URL and output folder.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=(
            "Optional API base URL. If omitted, local uses 127.0.0.1:8000 "
            "and docker uses 127.0.0.1:8001."
        ),
    )
    parser.add_argument(
        "--endpoint",
        default="/dispatch/compare",
        help="Dispatch endpoint path.",
    )
    parser.add_argument(
        "--sizes",
        default="5,10,25,50",
        help="Comma-separated driver/order counts.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=20,
        help="Measured iterations per size.",
    )
    parser.add_argument(
        "--warmup-iterations",
        type=int,
        default=2,
        help="Warmup requests before measured benchmark.",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=30.0,
        help="HTTP request timeout in seconds.",
    )
    parser.add_argument(
        "--matrix-algorithm",
        choices=["haversine", "source_dijkstra"],
        default="haversine",
        help=(
            "Cost matrix algorithm. Use haversine until source_dijkstra "
            "is wired in dispatch_service."
        ),
    )
    parser.add_argument(
        "--load-penalty-m",
        type=float,
        default=0.0,
        help="Driver current-load penalty in meters.",
    )
    parser.add_argument(
        "--slot-penalty-m",
        type=float,
        default=0.0,
        help="Repeated driver slot penalty in meters.",
    )
    parser.add_argument(
        "--return-cost-breakdown",
        action="store_true",
        help="Request full cost breakdown. Disabled by default for clean speed data.",
    )
    parser.add_argument(
        "--max-size",
        type=int,
        default=50,
        help="Safety cap matching dispatch request schema.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Optional custom output directory. If omitted, writes to "
            "benchmarks/phase_9/local_results or benchmarks/phase_9/docker_results."
        ),
    )
    return parser.parse_args()


def _resolve_output_dir(*, mode: str, output_dir: str | None) -> Path:
    if output_dir is not None:
        return Path(output_dir)

    if mode == "docker":
        return DEFAULT_DOCKER_OUTPUT_DIR

    return DEFAULT_LOCAL_OUTPUT_DIR


def _resolve_base_url(*, mode: str, base_url: str | None) -> str:
    if base_url is not None:
        return base_url

    if mode == "docker":
        return DEFAULT_DOCKER_BASE_URL

    return DEFAULT_LOCAL_BASE_URL


def _parse_sizes(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _run_warmup(
    *,
    base_url: str,
    endpoint: str,
    warmup_iterations: int,
    timeout_s: float,
    matrix_algorithm: str,
) -> None:
    for iteration in range(1, warmup_iterations + 1):
        payload = _build_payload(
            size=5,
            matrix_algorithm=matrix_algorithm,
            return_cost_breakdown=False,
            load_penalty_m=0.0,
            slot_penalty_m=0.0,
        )

        _run_case(
            mode="warmup",
            base_url=base_url,
            endpoint=endpoint,
            size=5,
            iteration=iteration,
            payload=payload,
            timeout_s=timeout_s,
        )


def _build_payload(
    *,
    size: int,
    matrix_algorithm: str,
    return_cost_breakdown: bool,
    load_penalty_m: float,
    slot_penalty_m: float,
) -> dict[str, Any]:
    drivers = []
    orders = []

    for index in range(size):
        drivers.append(
            {
                "driver_id": f"driver_{index + 1:03d}",
                "lat": round(KANPUR_BASE_LAT + (index * 0.001), 6),
                "lon": round(KANPUR_BASE_LON + (index * 0.001), 6),
                "current_load": 0,
                "max_capacity": 1,
            }
        )

        orders.append(
            {
                "order_id": f"order_{index + 1:03d}",
                "pickup_lat": round(KANPUR_BASE_LAT + (index * 0.001) + 0.0003, 6),
                "pickup_lon": round(KANPUR_BASE_LON + (index * 0.001) + 0.0003, 6),
            }
        )

    return {
        "drivers": drivers,
        "orders": orders,
        "matrix_algorithm": matrix_algorithm,
        "use_cache": True,
        "load_penalty_m": load_penalty_m,
        "slot_penalty_m": slot_penalty_m,
        "return_cost_breakdown": return_cost_breakdown,
    }


def _run_case(
    *,
    mode: str,
    base_url: str,
    endpoint: str,
    size: int,
    iteration: int,
    payload: dict[str, Any],
    timeout_s: float,
) -> DispatchEndpointCaseResult:
    url = f"{base_url}{endpoint}"
    started_at = perf_counter()

    status_code: int | None = None

    try:
        status_code, response_body = _post_json(
            url=url,
            payload=payload,
            timeout_s=timeout_s,
        )
        request_elapsed_ms = round((perf_counter() - started_at) * 1000.0, 6)

        if status_code != 200:
            return _failed_case(
                mode=mode,
                base_url=base_url,
                endpoint=endpoint,
                size=size,
                iteration=iteration,
                status_code=status_code,
                request_elapsed_ms=request_elapsed_ms,
                error=json.dumps(response_body),
            )

        return _successful_case(
            mode=mode,
            base_url=base_url,
            endpoint=endpoint,
            size=size,
            iteration=iteration,
            status_code=status_code,
            request_elapsed_ms=request_elapsed_ms,
            body=response_body,
        )

    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        request_elapsed_ms = round((perf_counter() - started_at) * 1000.0, 6)

        return _failed_case(
            mode=mode,
            base_url=base_url,
            endpoint=endpoint,
            size=size,
            iteration=iteration,
            status_code=status_code,
            request_elapsed_ms=request_elapsed_ms,
            error=str(exc),
        )


def _post_json(
    *,
    url: str,
    payload: dict[str, Any],
    timeout_s: float,
) -> tuple[int, dict[str, Any]]:
    encoded_payload = json.dumps(payload).encode("utf-8")

    request = Request(
        url=url,
        data=encoded_payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout_s) as response:
            status_code = response.status
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        status_code = exc.code
        body = exc.read().decode("utf-8")

    parsed_body = json.loads(body) if body else {}

    return status_code, parsed_body


def _successful_case(
    *,
    mode: str,
    base_url: str,
    endpoint: str,
    size: int,
    iteration: int,
    status_code: int,
    request_elapsed_ms: float,
    body: dict[str, Any],
) -> DispatchEndpointCaseResult:
    timings = body.get("timings", {})
    comparison = body.get("comparison", {})
    greedy = body.get("greedy", {})
    hungarian = body.get("hungarian", {})
    fairness = body.get("hungarian_fairness", {})

    api_elapsed_ms = timings.get("api_elapsed_ms", body.get("total_time_ms"))
    matrix_generation_time_ms = timings.get(
        "matrix_generation_time_ms",
        body.get("cost_matrix_build_time_ms"),
    )

    return DispatchEndpointCaseResult(
        mode=mode,
        base_url=base_url,
        endpoint=endpoint,
        size=size,
        iteration=iteration,
        status_code=status_code,
        success=_response_is_valid(body),
        error=None if _response_is_valid(body) else "Response failed validation.",
        request_elapsed_ms=request_elapsed_ms,
        api_elapsed_ms=_optional_float(api_elapsed_ms),
        matrix_generation_time_ms=_optional_float(matrix_generation_time_ms),
        greedy_total_cost=_optional_float(greedy.get("total_cost")),
        hungarian_total_cost=_optional_float(hungarian.get("total_cost")),
        hungarian_cost_saved=_optional_float(
            comparison.get("hungarian_vs_greedy_cost_saved")
        ),
        hungarian_improvement_pct=_optional_float(
            comparison.get("hungarian_vs_greedy_improvement_pct")
        ),
        hungarian_non_regression=comparison.get("hungarian_non_regression"),
        driver_count=_optional_int(body.get("driver_count")),
        order_count=_optional_int(body.get("order_count")),
        available_slot_count=_optional_int(body.get("available_slot_count")),
        assigned_order_count=_optional_int(body.get("assigned_order_count")),
        unassigned_order_count=_optional_int(body.get("unassigned_order_count")),
        unused_slot_count=_optional_int(body.get("unused_slot_count")),
        greedy_assigned_count=_optional_int(greedy.get("assigned_count")),
        hungarian_assigned_count=_optional_int(hungarian.get("assigned_count")),
        fairness_score=_optional_float(fairness.get("fairness_score")),
    )


def _failed_case(
    *,
    mode: str,
    base_url: str,
    endpoint: str,
    size: int,
    iteration: int,
    status_code: int | None,
    request_elapsed_ms: float,
    error: str,
) -> DispatchEndpointCaseResult:
    return DispatchEndpointCaseResult(
        mode=mode,
        base_url=base_url,
        endpoint=endpoint,
        size=size,
        iteration=iteration,
        status_code=status_code,
        success=False,
        error=error,
        request_elapsed_ms=request_elapsed_ms,
        api_elapsed_ms=None,
        matrix_generation_time_ms=None,
        greedy_total_cost=None,
        hungarian_total_cost=None,
        hungarian_cost_saved=None,
        hungarian_improvement_pct=None,
        hungarian_non_regression=None,
        driver_count=None,
        order_count=None,
        available_slot_count=None,
        assigned_order_count=None,
        unassigned_order_count=None,
        unused_slot_count=None,
        greedy_assigned_count=None,
        hungarian_assigned_count=None,
        fairness_score=None,
    )


def _response_is_valid(body: dict[str, Any]) -> bool:
    comparison = body.get("comparison", {})
    greedy = body.get("greedy", {})
    hungarian = body.get("hungarian", {})

    return (
        body.get("status") == "ok"
        and body.get("phase") == "tier3_phase9"
        and comparison.get("hungarian_non_regression") is True
        and greedy.get("assigned_count") == hungarian.get("assigned_count")
        and body.get("assigned_order_count") == hungarian.get("assigned_count")
    )


def _build_group_summaries(
    results: list[DispatchEndpointCaseResult],
    sizes: list[int],
) -> dict[str, DispatchEndpointGroupSummary]:
    summaries: dict[str, DispatchEndpointGroupSummary] = {}

    for size in sizes:
        group = [result for result in results if result.size == size]
        successes = [result for result in group if result.success]

        request_elapsed_values = [
            result.request_elapsed_ms for result in successes
        ]
        api_elapsed_values = _non_null_values(
            result.api_elapsed_ms for result in successes
        )
        matrix_elapsed_values = _non_null_values(
            result.matrix_generation_time_ms for result in successes
        )
        improvement_values = _non_null_values(
            result.hungarian_improvement_pct for result in successes
        )

        success_count = len(successes)
        failure_count = len(group) - success_count
        request_median = _median(request_elapsed_values)

        summaries[f"{size}x{size}"] = DispatchEndpointGroupSummary(
            size=size,
            iteration_count=len(group),
            success_count=success_count,
            failure_count=failure_count,
            success_rate_pct=round((success_count / len(group)) * 100.0, 6)
            if group
            else 0.0,
            request_elapsed_ms=_stats(request_elapsed_values),
            api_elapsed_ms=_stats(api_elapsed_values),
            matrix_generation_time_ms=_stats(matrix_elapsed_values),
            hungarian_improvement_pct=_stats(improvement_values),
            all_non_regression=all(
                result.hungarian_non_regression is True for result in successes
            )
            and failure_count == 0,
            all_assignment_counts_valid=all(
                _assignment_counts_valid(result) for result in group
            )
            and failure_count == 0,
            all_capacity_counts_valid=all(
                _capacity_counts_valid(result) for result in group
            )
            and failure_count == 0,
            median_request_under_250ms=request_median < 250.0
            if size == 25
            else None,
            median_request_under_500ms=request_median < 500.0
            if size == 50
            else None,
        )

    return summaries


def _assignment_counts_valid(result: DispatchEndpointCaseResult) -> bool:
    if not result.success:
        return False

    return (
        result.assigned_order_count == result.greedy_assigned_count
        and result.assigned_order_count == result.hungarian_assigned_count
        and result.assigned_order_count
        == min(result.available_slot_count or 0, result.order_count or 0)
    )


def _capacity_counts_valid(result: DispatchEndpointCaseResult) -> bool:
    if not result.success:
        return False

    if result.available_slot_count is None or result.order_count is None:
        return False

    if result.unassigned_order_count is None or result.unused_slot_count is None:
        return False

    expected_unassigned_orders = max(0, result.order_count - result.available_slot_count)
    expected_unused_slots = max(0, result.available_slot_count - result.order_count)

    return (
        result.unassigned_order_count == expected_unassigned_orders
        and result.unused_slot_count == expected_unused_slots
    )


def _non_null_values(values: Any) -> list[float]:
    return [float(value) for value in values if value is not None]


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {
            "min": 0.0,
            "median": 0.0,
            "mean": 0.0,
            "p95": 0.0,
            "max": 0.0,
        }

    return {
        "min": round(min(values), 6),
        "median": _median(values),
        "mean": round(statistics.mean(values), 6),
        "p95": _percentile(values, 95),
        "max": round(max(values), 6),
    }


def _median(values: list[float]) -> float:
    return round(statistics.median(values), 6) if values else 0.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0

    sorted_values = sorted(values)

    if len(sorted_values) == 1:
        return round(sorted_values[0], 6)

    rank = (percentile / 100.0) * (len(sorted_values) - 1)
    lower_index = int(rank)
    upper_index = min(lower_index + 1, len(sorted_values) - 1)
    weight = rank - lower_index

    interpolated = (
        sorted_values[lower_index] * (1.0 - weight)
        + sorted_values[upper_index] * weight
    )

    return round(interpolated, 6)


def _target_flag(
    group_summaries: dict[str, DispatchEndpointGroupSummary],
    *,
    size: int,
    target_key: str,
) -> bool:
    group = group_summaries.get(f"{size}x{size}")

    if group is None:
        return False

    value = getattr(group, target_key)

    return bool(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None

    return float(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None

    return int(value)


def _summary_to_jsonable_dict(
    summary: DispatchEndpointBenchmarkSummary,
) -> dict[str, Any]:
    payload = asdict(summary)
    payload["group_summaries"] = {
        key: asdict(value) for key, value in summary.group_summaries.items()
    }
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()