# benchmarks/phase_9_1/phase91_dispatch_cache_probe.py

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections.abc import Sequence
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
class CacheProbeCycle:
    cycle_id: str
    size: int
    cycle_index: int
    success: bool
    error: str | None

    first_elapsed_ms: float
    second_elapsed_ms: float

    first_cache_used: bool | None
    first_cache_hit: bool | None
    first_cache_key: str | None

    second_cache_used: bool | None
    second_cache_hit: bool | None
    second_cache_key: str | None

    builder_call_count_after_first: int
    builder_call_count_after_second: int

    first_total_cost: float | None
    second_total_cost: float | None

    first_assignment_count: int | None
    second_assignment_count: int | None

    cache_key_stable: bool
    response_cost_stable: bool
    assignment_count_stable: bool
    first_miss_second_hit: bool
    builder_not_called_on_hit: bool
    non_regression_stable: bool

    first_total_time_ms: float | None
    second_total_time_ms: float | None
    first_cost_matrix_build_time_ms: float | None
    second_cost_matrix_build_time_ms: float | None


@dataclass(frozen=True)
class CacheProbeSummary:
    phase: str
    benchmark: str
    mode: Mode
    created_at_utc: str
    sizes: list[int]
    cycles_per_size: int
    cycle_count: int
    successful_cycle_count: int
    failed_cycle_count: int
    success_rate_pct: float

    request_count: int
    cache_used_count: int
    cache_hit_count: int
    cache_hit_rate_pct: float

    group_summaries: dict[str, dict[str, Any]]

    output_raw_file: str
    output_summary_file: str

    quality_flags: dict[str, bool]
    evidence_note: str


class FakeDispatchCache:
    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.get_count = 0
        self.set_count = 0
        self.last_ttl_seconds: int | None = None

    def get(self, key: str) -> Any:
        self.get_count += 1
        return self.store.get(key)

    def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> None:
        self.set_count += 1
        self.last_ttl_seconds = ttl_seconds
        self.store[key] = value


class CountingSourceDijkstraBuilder:
    def __init__(self, size: int, cycle_index: int) -> None:
        self.size = size
        self.cycle_index = cycle_index
        self.call_count = 0

    def __call__(
        self,
        drivers: Sequence[DispatchDriver],
        orders: Sequence[DispatchOrder],
    ) -> list[list[float]]:
        self.call_count += 1

        if len(drivers) != self.size:
            raise ValueError(f"expected {self.size} drivers, got {len(drivers)}")

        if len(orders) != self.size:
            raise ValueError(f"expected {self.size} orders, got {len(orders)}")

        return _build_synthetic_source_dijkstra_matrix(
            drivers=drivers,
            orders=orders,
            cycle_index=self.cycle_index,
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

    raw_file = output_dir / f"phase91_dispatch_cache_raw_{args.mode}_{timestamp}.json"
    summary_file = output_dir / f"phase91_dispatch_cache_summary_{args.mode}_{timestamp}.json"

    cycles: list[CacheProbeCycle] = []

    for size in sizes:
        for cycle_index in range(args.cycles):
            cycles.append(
                _run_cycle(
                    size=size,
                    cycle_index=cycle_index,
                    cache_ttl_seconds=args.cache_ttl_seconds,
                )
            )

    summary = _build_summary(
        mode=args.mode,
        created_at=created_at,
        sizes=sizes,
        cycles_per_size=args.cycles,
        cycles=cycles,
        raw_file=raw_file,
        summary_file=summary_file,
    )

    raw_payload = {
        "phase": "tier3_phase9_1",
        "benchmark": "dispatch_cache_probe",
        "mode": args.mode,
        "created_at_utc": created_at.isoformat(),
        "sizes": sizes,
        "cycles_per_size": args.cycles,
        "cycle_count": len(cycles),
        "request_count": len(cycles) * 2,
        "cache_backend": "fake_in_process",
        "cycles": [asdict(cycle) for cycle in cycles],
    }

    _write_json(raw_file, raw_payload)
    _write_json(summary_file, asdict(summary))

    print(json.dumps(asdict(summary), indent=2))


def _run_cycle(
    *,
    size: int,
    cycle_index: int,
    cache_ttl_seconds: int,
) -> CacheProbeCycle:
    cycle_id = f"{size}x{size}_cycle_{cycle_index:03d}"

    cache = FakeDispatchCache()
    builder = CountingSourceDijkstraBuilder(size=size, cycle_index=cycle_index)
    request = DispatchCompareRequest(
        **_build_payload(
            size=size,
            cycle_index=cycle_index,
        )
    )

    first_start = perf_counter()

    try:
        first = compare_dispatch_assignments(
            request,
            source_dijkstra_matrix_builder=builder,
            cache_backend=cache,
            cache_ttl_seconds=cache_ttl_seconds,
        )
        first_elapsed_ms = _elapsed_ms(first_start)
        builder_call_count_after_first = builder.call_count

        second_start = perf_counter()
        second = compare_dispatch_assignments(
            request,
            source_dijkstra_matrix_builder=builder,
            cache_backend=cache,
            cache_ttl_seconds=cache_ttl_seconds,
        )
        second_elapsed_ms = _elapsed_ms(second_start)
        builder_call_count_after_second = builder.call_count

        cache_key_stable = (
            first.cache_key is not None
            and second.cache_key is not None
            and first.cache_key == second.cache_key
        )
        response_cost_stable = first.hungarian.total_cost == second.hungarian.total_cost
        assignment_count_stable = (
            first.hungarian.assigned_count == second.hungarian.assigned_count
        )
        first_miss_second_hit = (
            first.cache_used is True
            and first.cache_hit is False
            and second.cache_used is True
            and second.cache_hit is True
        )
        builder_not_called_on_hit = (
            builder_call_count_after_first == 1
            and builder_call_count_after_second == 1
        )
        non_regression_stable = (
            first.comparison.hungarian_non_regression is True
            and second.comparison.hungarian_non_regression is True
        )

        success = (
            first.status == "ok"
            and second.status == "ok"
            and first.phase == "tier3_phase9_1"
            and second.phase == "tier3_phase9_1"
            and first.matrix_algorithm == "source_dijkstra"
            and second.matrix_algorithm == "source_dijkstra"
            and cache_key_stable
            and response_cost_stable
            and assignment_count_stable
            and first_miss_second_hit
            and builder_not_called_on_hit
            and non_regression_stable
        )

        return CacheProbeCycle(
            cycle_id=cycle_id,
            size=size,
            cycle_index=cycle_index,
            success=success,
            error=None,
            first_elapsed_ms=first_elapsed_ms,
            second_elapsed_ms=second_elapsed_ms,
            first_cache_used=first.cache_used,
            first_cache_hit=first.cache_hit,
            first_cache_key=first.cache_key,
            second_cache_used=second.cache_used,
            second_cache_hit=second.cache_hit,
            second_cache_key=second.cache_key,
            builder_call_count_after_first=builder_call_count_after_first,
            builder_call_count_after_second=builder_call_count_after_second,
            first_total_cost=first.hungarian.total_cost,
            second_total_cost=second.hungarian.total_cost,
            first_assignment_count=first.hungarian.assigned_count,
            second_assignment_count=second.hungarian.assigned_count,
            cache_key_stable=cache_key_stable,
            response_cost_stable=response_cost_stable,
            assignment_count_stable=assignment_count_stable,
            first_miss_second_hit=first_miss_second_hit,
            builder_not_called_on_hit=builder_not_called_on_hit,
            non_regression_stable=non_regression_stable,
            first_total_time_ms=first.total_time_ms,
            second_total_time_ms=second.total_time_ms,
            first_cost_matrix_build_time_ms=first.cost_matrix_build_time_ms,
            second_cost_matrix_build_time_ms=second.cost_matrix_build_time_ms,
        )

    except Exception as exc:
        elapsed_ms = _elapsed_ms(first_start)

        return CacheProbeCycle(
            cycle_id=cycle_id,
            size=size,
            cycle_index=cycle_index,
            success=False,
            error=f"{type(exc).__name__}: {exc}",
            first_elapsed_ms=elapsed_ms,
            second_elapsed_ms=0.0,
            first_cache_used=None,
            first_cache_hit=None,
            first_cache_key=None,
            second_cache_used=None,
            second_cache_hit=None,
            second_cache_key=None,
            builder_call_count_after_first=builder.call_count,
            builder_call_count_after_second=builder.call_count,
            first_total_cost=None,
            second_total_cost=None,
            first_assignment_count=None,
            second_assignment_count=None,
            cache_key_stable=False,
            response_cost_stable=False,
            assignment_count_stable=False,
            first_miss_second_hit=False,
            builder_not_called_on_hit=False,
            non_regression_stable=False,
            first_total_time_ms=None,
            second_total_time_ms=None,
            first_cost_matrix_build_time_ms=None,
            second_cost_matrix_build_time_ms=None,
        )


def _build_payload(
    *,
    size: int,
    cycle_index: int,
) -> dict[str, Any]:
    base_lat = 26.45 + cycle_index * 0.00001
    base_lon = 80.35 + cycle_index * 0.00001

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
        "use_cache": True,
        "load_penalty_m": 0.0,
        "slot_penalty_m": 0.0,
        "return_cost_breakdown": False,
    }


def _build_synthetic_source_dijkstra_matrix(
    *,
    drivers: Sequence[DispatchDriver],
    orders: Sequence[DispatchOrder],
    cycle_index: int,
) -> list[list[float]]:
    matrix: list[list[float]] = []

    for row_index, driver in enumerate(drivers):
        row: list[float] = []

        for col_index, order in enumerate(orders):
            coordinate_distance = _pseudo_road_distance_m(driver, order)
            index_gap_penalty = abs(row_index - col_index) * 850.0
            directional_penalty = max(0, col_index - row_index) * 17.5
            cycle_noise = (cycle_index % 11) * 0.137

            row.append(
                round(
                    coordinate_distance
                    + index_gap_penalty
                    + directional_penalty
                    + cycle_noise,
                    6,
                )
            )

        matrix.append(row)

    return matrix


def _pseudo_road_distance_m(
    driver: DispatchDriver,
    order: DispatchOrder,
) -> float:
    lat_delta_m = abs(driver.lat - order.pickup_lat) * 111_000.0
    lon_delta_m = abs(driver.lon - order.pickup_lon) * 101_000.0

    return round((lat_delta_m + lon_delta_m) * 1.18, 6)


def _build_summary(
    *,
    mode: Mode,
    created_at: datetime,
    sizes: list[int],
    cycles_per_size: int,
    cycles: list[CacheProbeCycle],
    raw_file: Path,
    summary_file: Path,
) -> CacheProbeSummary:
    cycle_count = len(cycles)
    successful_cycle_count = sum(1 for cycle in cycles if cycle.success)
    failed_cycle_count = cycle_count - successful_cycle_count
    request_count = cycle_count * 2

    cache_used_count = sum(
        int(cycle.first_cache_used is True) + int(cycle.second_cache_used is True)
        for cycle in cycles
    )
    cache_hit_count = sum(
        int(cycle.first_cache_hit is True) + int(cycle.second_cache_hit is True)
        for cycle in cycles
    )

    group_summaries: dict[str, dict[str, Any]] = {}

    for size in sizes:
        group_cycles = [cycle for cycle in cycles if cycle.size == size]
        successful_group_cycles = [cycle for cycle in group_cycles if cycle.success]

        group_summaries[f"{size}x{size}"] = {
            "size": size,
            "cycle_count": len(group_cycles),
            "successful_cycle_count": len(successful_group_cycles),
            "failed_cycle_count": len(group_cycles) - len(successful_group_cycles),
            "success_rate_pct": _pct(len(successful_group_cycles), len(group_cycles)),
            "first_elapsed_ms": _stats(
                [cycle.first_elapsed_ms for cycle in successful_group_cycles]
            ),
            "second_elapsed_ms": _stats(
                [cycle.second_elapsed_ms for cycle in successful_group_cycles]
            ),
            "first_total_time_ms": _stats(
                [
                    cycle.first_total_time_ms
                    for cycle in successful_group_cycles
                    if cycle.first_total_time_ms is not None
                ]
            ),
            "second_total_time_ms": _stats(
                [
                    cycle.second_total_time_ms
                    for cycle in successful_group_cycles
                    if cycle.second_total_time_ms is not None
                ]
            ),
            "all_first_miss_second_hit": all(
                cycle.first_miss_second_hit for cycle in group_cycles
            ),
            "all_cache_keys_stable": all(
                cycle.cache_key_stable for cycle in group_cycles
            ),
            "all_response_costs_stable": all(
                cycle.response_cost_stable for cycle in group_cycles
            ),
            "all_assignment_counts_stable": all(
                cycle.assignment_count_stable for cycle in group_cycles
            ),
            "all_builder_not_called_on_hit": all(
                cycle.builder_not_called_on_hit for cycle in group_cycles
            ),
        }

    quality_flags = {
        "all_cycles_successful": successful_cycle_count == cycle_count and cycle_count > 0,
        "cache_backend_used": cache_used_count == request_count and request_count > 0,
        "cache_hits_observed": cache_hit_count > 0,
        "cache_hit_count_matches_second_requests": cache_hit_count == cycle_count,
        "all_first_requests_miss": all(cycle.first_cache_hit is False for cycle in cycles),
        "all_second_requests_hit": all(cycle.second_cache_hit is True for cycle in cycles),
        "all_cache_keys_stable": all(cycle.cache_key_stable for cycle in cycles),
        "all_response_costs_stable": all(cycle.response_cost_stable for cycle in cycles),
        "all_assignment_counts_stable": all(
            cycle.assignment_count_stable for cycle in cycles
        ),
        "all_builder_not_called_on_hit": all(
            cycle.builder_not_called_on_hit for cycle in cycles
        ),
        "all_non_regression_stable": all(
            cycle.non_regression_stable for cycle in cycles
        ),
    }

    return CacheProbeSummary(
        phase="tier3_phase9_1",
        benchmark="dispatch_cache_probe",
        mode=mode,
        created_at_utc=created_at.isoformat(),
        sizes=sizes,
        cycles_per_size=cycles_per_size,
        cycle_count=cycle_count,
        successful_cycle_count=successful_cycle_count,
        failed_cycle_count=failed_cycle_count,
        success_rate_pct=_pct(successful_cycle_count, cycle_count),
        request_count=request_count,
        cache_used_count=cache_used_count,
        cache_hit_count=cache_hit_count,
        cache_hit_rate_pct=_pct(cache_hit_count, request_count),
        group_summaries=group_summaries,
        output_raw_file=_relative_path(raw_file),
        output_summary_file=_relative_path(summary_file),
        quality_flags=quality_flags,
        evidence_note=(
            "This probe proves Phase 9.1 service-level cache behavior using an "
            "in-process fake backend: first identical request misses, second "
            "identical request hits, and the source_dijkstra builder is not "
            "called again on hit. It does not prove real Redis yet."
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
        description="Phase 9.1 dispatch cache service integration probe."
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
        "--cycles",
        type=int,
        default=10,
        help="Miss-hit cycles per size.",
    )
    parser.add_argument(
        "--cache-ttl-seconds",
        type=int,
        default=600,
        help="TTL value passed to the fake cache backend.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional output directory.",
    )

    return parser.parse_args()


if __name__ == "__main__":
    main()