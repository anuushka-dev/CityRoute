# benchmarks/phase_9_1/phase91_dispatch_source_dijkstra_probe.py

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

PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.dispatch_cost_matrix import DispatchDriver, DispatchOrder  # noqa: E402
from app.schemas.dispatch import DispatchCompareRequest  # noqa: E402
from app.services.dispatch_service import compare_dispatch_assignments  # noqa: E402

Mode = Literal["local", "docker"]


@dataclass(frozen=True)
class SourceDijkstraProbeCase:
    case_id: str
    size: int
    iteration: int
    success: bool
    error: str | None
    elapsed_ms: float
    builder_call_count: int
    status: str | None
    phase: str | None
    matrix_algorithm: str | None
    driver_count: int | None
    order_count: int | None
    available_slot_count: int | None
    assigned_order_count: int | None
    unassigned_order_count: int | None
    unused_slot_count: int | None
    greedy_total_cost: float | None
    hungarian_total_cost: float | None
    hungarian_non_regression: bool | None
    assignment_count_valid: bool
    capacity_count_valid: bool
    cost_non_negative: bool
    source_dijkstra_used: bool
    cache_used: bool | None
    cache_hit: bool | None
    total_time_ms: float | None
    cost_matrix_build_time_ms: float | None


@dataclass(frozen=True)
class SourceDijkstraProbeSummary:
    phase: str
    benchmark: str
    mode: Mode
    created_at_utc: str
    sizes: list[int]
    iterations_per_size: int
    case_count: int
    success_count: int
    failure_count: int
    success_rate_pct: float
    group_summaries: dict[str, dict[str, Any]]
    output_raw_file: str
    output_summary_file: str
    quality_flags: dict[str, bool]
    evidence_note: str


class CountingSourceDijkstraBuilder:
    """Deterministic internal source-Dijkstra stand-in.

    This proves dispatch_service can consume an injected internal Phase 5-style
    driver-to-order matrix builder. It does not call the /matrix HTTP endpoint.
    """

    def __init__(self, size: int, iteration: int) -> None:
        self.size = size
        self.iteration = iteration
        self.call_count = 0

    def __call__(
        self,
        drivers: list[DispatchDriver],
        orders: list[DispatchOrder],
    ) -> list[list[float]]:
        self.call_count += 1

        if len(drivers) != self.size:
            raise ValueError(
                f"expected {self.size} drivers, got {len(drivers)}"
            )

        if len(orders) != self.size:
            raise ValueError(
                f"expected {self.size} orders, got {len(orders)}"
            )

        return _build_synthetic_source_dijkstra_matrix(
            drivers=drivers,
            orders=orders,
            iteration=self.iteration,
        )


def main() -> None:
    args = _parse_args()

    sizes = _parse_sizes(args.sizes)
    output_dir = _resolve_output_dir(
        mode=args.mode,
        output_dir_arg=args.output_dir,
    )

    created_at = datetime.now(UTC)
    timestamp = created_at.strftime("%Y%m%d_%H%M%S")

    raw_file = output_dir / f"phase91_dispatch_source_dijkstra_raw_{args.mode}_{timestamp}.json"
    summary_file = output_dir / (
        f"phase91_dispatch_source_dijkstra_summary_{args.mode}_{timestamp}.json"
    )

    cases: list[SourceDijkstraProbeCase] = []

    for size in sizes:
        for iteration in range(args.iterations):
            cases.append(
                _run_case(
                    size=size,
                    iteration=iteration,
                )
            )

    summary = _build_summary(
        mode=args.mode,
        created_at=created_at,
        sizes=sizes,
        iterations=args.iterations,
        cases=cases,
        raw_file=raw_file,
        summary_file=summary_file,
    )

    raw_payload = {
        "phase": "tier3_phase9_1",
        "benchmark": "dispatch_source_dijkstra_probe",
        "mode": args.mode,
        "created_at_utc": created_at.isoformat(),
        "sizes": sizes,
        "iterations_per_size": args.iterations,
        "case_count": len(cases),
        "cases": [asdict(case) for case in cases],
    }

    _write_json(raw_file, raw_payload)
    _write_json(summary_file, asdict(summary))

    print(json.dumps(asdict(summary), indent=2))


def _run_case(
    *,
    size: int,
    iteration: int,
) -> SourceDijkstraProbeCase:
    case_id = f"{size}x{size}_iter_{iteration:03d}"
    builder = CountingSourceDijkstraBuilder(size=size, iteration=iteration)

    start = perf_counter()

    try:
        payload = _build_payload(size=size, iteration=iteration)
        request = DispatchCompareRequest(**payload)

        response = compare_dispatch_assignments(
            request,
            source_dijkstra_matrix_builder=builder,
            cache_backend=None,
        )

        elapsed_ms = _elapsed_ms(start)

        assignment_count_valid = response.assigned_order_count == min(
            response.available_slot_count,
            response.order_count,
        )
        capacity_count_valid = (
            response.assigned_order_count
            + response.unassigned_order_count
            == response.order_count
        )
        cost_non_negative = (
            response.greedy.total_cost >= 0
            and response.hungarian.total_cost >= 0
        )
        source_dijkstra_used = (
            response.matrix_algorithm == "source_dijkstra"
            and builder.call_count == 1
        )

        return SourceDijkstraProbeCase(
            case_id=case_id,
            size=size,
            iteration=iteration,
            success=(
                response.status == "ok"
                and response.phase == "tier3_phase9_1"
                and source_dijkstra_used
                and response.comparison.hungarian_non_regression
                and assignment_count_valid
                and capacity_count_valid
                and cost_non_negative
            ),
            error=None,
            elapsed_ms=elapsed_ms,
            builder_call_count=builder.call_count,
            status=response.status,
            phase=response.phase,
            matrix_algorithm=response.matrix_algorithm,
            driver_count=response.driver_count,
            order_count=response.order_count,
            available_slot_count=response.available_slot_count,
            assigned_order_count=response.assigned_order_count,
            unassigned_order_count=response.unassigned_order_count,
            unused_slot_count=response.unused_slot_count,
            greedy_total_cost=response.greedy.total_cost,
            hungarian_total_cost=response.hungarian.total_cost,
            hungarian_non_regression=response.comparison.hungarian_non_regression,
            assignment_count_valid=assignment_count_valid,
            capacity_count_valid=capacity_count_valid,
            cost_non_negative=cost_non_negative,
            source_dijkstra_used=source_dijkstra_used,
            cache_used=response.cache_used,
            cache_hit=response.cache_hit,
            total_time_ms=response.total_time_ms,
            cost_matrix_build_time_ms=response.cost_matrix_build_time_ms,
        )

    except Exception as exc:
        return SourceDijkstraProbeCase(
            case_id=case_id,
            size=size,
            iteration=iteration,
            success=False,
            error=f"{type(exc).__name__}: {exc}",
            elapsed_ms=_elapsed_ms(start),
            builder_call_count=builder.call_count,
            status=None,
            phase=None,
            matrix_algorithm=None,
            driver_count=None,
            order_count=None,
            available_slot_count=None,
            assigned_order_count=None,
            unassigned_order_count=None,
            unused_slot_count=None,
            greedy_total_cost=None,
            hungarian_total_cost=None,
            hungarian_non_regression=None,
            assignment_count_valid=False,
            capacity_count_valid=False,
            cost_non_negative=False,
            source_dijkstra_used=False,
            cache_used=None,
            cache_hit=None,
            total_time_ms=None,
            cost_matrix_build_time_ms=None,
        )


def _build_payload(
    *,
    size: int,
    iteration: int,
) -> dict[str, Any]:
    base_lat = 26.45 + (iteration * 0.00001)
    base_lon = 80.35 + (iteration * 0.00001)

    drivers = []
    orders = []

    for index in range(size):
        drivers.append(
            {
                "driver_id": f"driver_{index:03d}",
                "lat": round(base_lat + index * 0.001, 7),
                "lon": round(base_lon + index * 0.001, 7),
                "current_load": 0,
                "max_capacity": 1,
            }
        )

        orders.append(
            {
                "order_id": f"order_{index:03d}",
                "pickup_lat": round(base_lat + index * 0.001 + 0.0003, 7),
                "pickup_lon": round(base_lon + index * 0.001 + 0.0003, 7),
            }
        )

    return {
        "drivers": drivers,
        "orders": orders,
        "matrix_algorithm": "source_dijkstra",
        "use_cache": False,
        "load_penalty_m": 0.0,
        "slot_penalty_m": 0.0,
        "return_cost_breakdown": False,
    }


def _build_synthetic_source_dijkstra_matrix(
    *,
    drivers: list[DispatchDriver],
    orders: list[DispatchOrder],
    iteration: int,
) -> list[list[float]]:
    """Build deterministic road-network-like matrix.

    Diagonal pairs are cheap, off-diagonal pairs are increasingly expensive.
    The extra row/column penalty makes this non-trivial while still stable.
    """

    matrix: list[list[float]] = []

    for row_index, driver in enumerate(drivers):
        row: list[float] = []

        for col_index, order in enumerate(orders):
            coordinate_distance = _pseudo_road_distance_m(driver, order)
            index_gap_penalty = abs(row_index - col_index) * 850.0
            directional_penalty = max(0, col_index - row_index) * 17.5
            iteration_noise = (iteration % 7) * 0.125

            total = round(
                coordinate_distance
                + index_gap_penalty
                + directional_penalty
                + iteration_noise,
                6,
            )

            row.append(total)

        matrix.append(row)

    return matrix


def _pseudo_road_distance_m(
    driver: DispatchDriver,
    order: DispatchOrder,
) -> float:
    lat_delta_m = abs(driver.lat - order.pickup_lat) * 111_000.0
    lon_delta_m = abs(driver.lon - order.pickup_lon) * 101_000.0

    # Manhattan-style multiplier approximates road distance more than straight-line.
    return round((lat_delta_m + lon_delta_m) * 1.18, 6)


def _build_summary(
    *,
    mode: Mode,
    created_at: datetime,
    sizes: list[int],
    iterations: int,
    cases: list[SourceDijkstraProbeCase],
    raw_file: Path,
    summary_file: Path,
) -> SourceDijkstraProbeSummary:
    case_count = len(cases)
    success_count = sum(1 for case in cases if case.success)
    failure_count = case_count - success_count
    success_rate_pct = _pct(success_count, case_count)

    group_summaries: dict[str, dict[str, Any]] = {}

    for size in sizes:
        group_cases = [case for case in cases if case.size == size]
        successful_group_cases = [case for case in group_cases if case.success]

        group_summaries[f"{size}x{size}"] = {
            "size": size,
            "case_count": len(group_cases),
            "success_count": len(successful_group_cases),
            "failure_count": len(group_cases) - len(successful_group_cases),
            "success_rate_pct": _pct(len(successful_group_cases), len(group_cases)),
            "elapsed_ms": _stats([case.elapsed_ms for case in successful_group_cases]),
            "total_time_ms": _stats(
                [
                    case.total_time_ms
                    for case in successful_group_cases
                    if case.total_time_ms is not None
                ]
            ),
            "cost_matrix_build_time_ms": _stats(
                [
                    case.cost_matrix_build_time_ms
                    for case in successful_group_cases
                    if case.cost_matrix_build_time_ms is not None
                ]
            ),
            "all_source_dijkstra_used": all(
                case.source_dijkstra_used for case in group_cases
            ),
            "all_non_regression": all(
                case.hungarian_non_regression is True for case in group_cases
            ),
            "all_assignment_counts_valid": all(
                case.assignment_count_valid for case in group_cases
            ),
            "all_capacity_counts_valid": all(
                case.capacity_count_valid for case in group_cases
            ),
            "all_costs_non_negative": all(
                case.cost_non_negative for case in group_cases
            ),
        }

    quality_flags = {
        "all_cases_successful": success_count == case_count and case_count > 0,
        "all_source_dijkstra_used": all(case.source_dijkstra_used for case in cases),
        "all_builder_called_once": all(case.builder_call_count == 1 for case in cases),
        "all_non_regression": all(
            case.hungarian_non_regression is True for case in cases
        ),
        "all_assignment_counts_valid": all(
            case.assignment_count_valid for case in cases
        ),
        "all_capacity_counts_valid": all(case.capacity_count_valid for case in cases),
        "all_costs_non_negative": all(case.cost_non_negative for case in cases),
        "cache_not_used_in_this_probe": all(case.cache_used is False for case in cases),
    }

    return SourceDijkstraProbeSummary(
        phase="tier3_phase9_1",
        benchmark="dispatch_source_dijkstra_probe",
        mode=mode,
        created_at_utc=created_at.isoformat(),
        sizes=sizes,
        iterations_per_size=iterations,
        case_count=case_count,
        success_count=success_count,
        failure_count=failure_count,
        success_rate_pct=success_rate_pct,
        group_summaries=group_summaries,
        output_raw_file=_relative_path(raw_file),
        output_summary_file=_relative_path(summary_file),
        quality_flags=quality_flags,
        evidence_note=(
            "This probe proves source_dijkstra dispatch service integration "
            "through an injected internal matrix builder. It does not prove the "
            "live API is wired to the real Phase 5 graph builder yet."
        ),
    )


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {
            "min": None,
            "median": None,
            "mean": None,
            "p95": None,
            "max": None,
        }

    sorted_values = sorted(values)

    return {
        "min": round(min(sorted_values), 6),
        "median": round(statistics.median(sorted_values), 6),
        "mean": round(statistics.mean(sorted_values), 6),
        "p95": round(_percentile(sorted_values, 95), 6),
        "max": round(max(sorted_values), 6),
    }


def _percentile(
    sorted_values: list[float],
    percentile: float,
) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]

    index = (len(sorted_values) - 1) * percentile / 100.0
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = index - lower

    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def _pct(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0

    return round((numerator / denominator) * 100.0, 6)


def _parse_sizes(value: str) -> list[int]:
    sizes = [int(item.strip()) for item in value.split(",") if item.strip()]

    if not sizes:
        raise ValueError("at least one size is required.")

    for size in sizes:
        if size < 1:
            raise ValueError("sizes must be positive integers.")

        if size > 50:
            raise ValueError("sizes must be <= 50 for dispatch schema compatibility.")

    return sizes


def _resolve_output_dir(
    *,
    mode: Mode,
    output_dir_arg: str | None,
) -> Path:
    if output_dir_arg:
        output_dir = Path(output_dir_arg)
    else:
        output_dir = PROJECT_ROOT / "benchmarks" / "phase_9_1" / f"{mode}_results"

    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir

    output_dir.mkdir(parents=True, exist_ok=True)

    return output_dir


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def _relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _elapsed_ms(start_time: float) -> float:
    return round((perf_counter() - start_time) * 1000.0, 6)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 9.1 source_dijkstra dispatch service integration probe."
    )

    parser.add_argument(
        "--mode",
        choices=["local", "docker"],
        default="local",
        help="Evidence mode label. This probe runs in-process, not over HTTP.",
    )
    parser.add_argument(
        "--sizes",
        default="2,5,10,25,50",
        help="Comma-separated square dispatch sizes.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=20,
        help="Iterations per size.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional output directory.",
    )

    return parser.parse_args()


if __name__ == "__main__":
    main()