# phase9_dispatch_cache_probe.py

from __future__ import annotations

import argparse
import hashlib
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
class DispatchCacheRequestResult:
    mode: str
    base_url: str
    endpoint: str
    size: int
    cycle: int
    request_kind: str
    payload_hash: str
    status_code: int | None
    success: bool
    error: str | None
    request_elapsed_ms: float
    cache_used: bool | None
    api_elapsed_ms: float | None
    matrix_generation_time_ms: float | None
    greedy_total_cost: float | None
    hungarian_total_cost: float | None
    hungarian_non_regression: bool | None
    assigned_order_count: int | None
    hungarian_assigned_count: int | None


@dataclass(frozen=True)
class DispatchCacheCycleResult:
    mode: str
    size: int
    cycle: int
    payload_hash: str
    first_success: bool
    repeat_success: bool
    first_cache_used: bool | None
    repeat_cache_used: bool | None
    same_hungarian_total_cost: bool
    same_assignment_count: bool
    repeat_request_faster_or_equal: bool
    first_request_elapsed_ms: float
    repeat_request_elapsed_ms: float
    speedup_ratio: float | None
    cache_hit_observed: bool
    cache_field_present: bool


@dataclass(frozen=True)
class DispatchCacheGroupSummary:
    size: int
    cycle_count: int
    success_count: int
    failure_count: int
    success_rate_pct: float
    cache_hit_count: int
    cache_hit_rate_pct: float
    stable_cost_count: int
    stable_assignment_count: int
    repeat_faster_or_equal_count: int
    first_request_elapsed_ms: dict[str, float]
    repeat_request_elapsed_ms: dict[str, float]
    speedup_ratio: dict[str, float]


@dataclass(frozen=True)
class DispatchCacheProbeSummary:
    phase: str
    benchmark: str
    mode: str
    base_url: str
    endpoint: str
    matrix_algorithm: str
    require_cache: bool
    created_at_utc: str
    sizes: list[int]
    cycles_per_size: int
    request_count: int
    cycle_count: int
    successful_cycle_count: int
    failed_cycle_count: int
    success_rate_pct: float
    cache_hit_count: int
    cache_hit_rate_pct: float
    group_summaries: dict[str, DispatchCacheGroupSummary]
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

    request_results: list[DispatchCacheRequestResult] = []
    cycle_results: list[DispatchCacheCycleResult] = []

    for size in sizes:
        for cycle in range(1, args.cycles + 1):
            payload = _build_payload(
                size=size,
                cycle=cycle,
                matrix_algorithm=args.matrix_algorithm,
                return_cost_breakdown=args.return_cost_breakdown,
                load_penalty_m=args.load_penalty_m,
                slot_penalty_m=args.slot_penalty_m,
            )
            payload_hash = _payload_hash(payload)

            first_result = _run_request(
                mode=mode,
                base_url=base_url,
                endpoint=endpoint,
                size=size,
                cycle=cycle,
                request_kind="first",
                payload=payload,
                payload_hash=payload_hash,
                timeout_s=args.timeout_s,
            )

            repeat_result = _run_request(
                mode=mode,
                base_url=base_url,
                endpoint=endpoint,
                size=size,
                cycle=cycle,
                request_kind="repeat",
                payload=payload,
                payload_hash=payload_hash,
                timeout_s=args.timeout_s,
            )

            request_results.extend([first_result, repeat_result])
            cycle_results.append(
                _build_cycle_result(
                    mode=mode,
                    size=size,
                    cycle=cycle,
                    payload_hash=payload_hash,
                    first=first_result,
                    repeat=repeat_result,
                )
            )

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    raw_path = output_dir / f"phase9_dispatch_cache_raw_{mode}_{timestamp}.json"
    summary_path = output_dir / f"phase9_dispatch_cache_summary_{mode}_{timestamp}.json"

    raw_payload = {
        "phase": "tier3_phase9",
        "benchmark": "dispatch_cache_probe",
        "mode": mode,
        "base_url": base_url,
        "endpoint": endpoint,
        "matrix_algorithm": args.matrix_algorithm,
        "require_cache": args.require_cache,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "sizes": sizes,
        "cycles_per_size": args.cycles,
        "requests": [asdict(result) for result in request_results],
        "cycles": [asdict(result) for result in cycle_results],
    }

    _write_json(raw_path, raw_payload)

    successful_cycle_count = sum(_cycle_successful(cycle) for cycle in cycle_results)
    failed_cycle_count = len(cycle_results) - successful_cycle_count
    cache_hit_count = sum(cycle.cache_hit_observed for cycle in cycle_results)

    group_summaries = _build_group_summaries(cycle_results, sizes)

    summary = DispatchCacheProbeSummary(
        phase="tier3_phase9",
        benchmark="dispatch_cache_probe",
        mode=mode,
        base_url=base_url,
        endpoint=endpoint,
        matrix_algorithm=args.matrix_algorithm,
        require_cache=args.require_cache,
        created_at_utc=datetime.now(UTC).isoformat(),
        sizes=sizes,
        cycles_per_size=args.cycles,
        request_count=len(request_results),
        cycle_count=len(cycle_results),
        successful_cycle_count=successful_cycle_count,
        failed_cycle_count=failed_cycle_count,
        success_rate_pct=round(
            (successful_cycle_count / len(cycle_results)) * 100.0,
            6,
        )
        if cycle_results
        else 0.0,
        cache_hit_count=cache_hit_count,
        cache_hit_rate_pct=round((cache_hit_count / len(cycle_results)) * 100.0, 6)
        if cycle_results
        else 0.0,
        group_summaries=group_summaries,
        output_raw_file=str(raw_path.relative_to(PROJECT_ROOT)),
        output_summary_file=str(summary_path.relative_to(PROJECT_ROOT)),
        quality_flags={
            "all_cycles_successful": failed_cycle_count == 0,
            "all_response_costs_stable": all(
                cycle.same_hungarian_total_cost for cycle in cycle_results
            ),
            "all_assignment_counts_stable": all(
                cycle.same_assignment_count for cycle in cycle_results
            ),
            "cache_field_present_all_cycles": all(
                cycle.cache_field_present for cycle in cycle_results
            ),
            "cache_hits_observed": cache_hit_count > 0,
            "cache_requirement_met": cache_hit_count > 0
            if args.require_cache
            else True,
            "repeat_faster_or_equal_all_cycles": all(
                cycle.repeat_request_faster_or_equal for cycle in cycle_results
            ),
        },
    )

    summary_payload = _summary_to_jsonable_dict(summary)
    _write_json(summary_path, summary_payload)

    print(json.dumps(summary_payload, indent=2))

    if failed_cycle_count != 0:
        raise SystemExit(1)

    if args.require_cache and cache_hit_count == 0:
        raise SystemExit(1)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 9 /dispatch/compare cache behavior probe.",
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
        "--cycles",
        type=int,
        default=10,
        help="Repeated first/repeat request cycles per size.",
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
            "Cost matrix algorithm. Current first Phase 9 proof usually uses "
            "haversine unless source_dijkstra is wired."
        ),
    )
    parser.add_argument(
        "--require-cache",
        action="store_true",
        help="Fail the probe if no repeat request reports cache_used=true.",
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
        help="Request full cost breakdown. Disabled by default for cache probe speed.",
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


def _build_payload(
    *,
    size: int,
    cycle: int,
    matrix_algorithm: str,
    return_cost_breakdown: bool,
    load_penalty_m: float,
    slot_penalty_m: float,
) -> dict[str, Any]:
    drivers = []
    orders = []

    jitter = cycle * 0.000001

    for index in range(size):
        drivers.append(
            {
                "driver_id": f"driver_{index + 1:03d}",
                "lat": round(KANPUR_BASE_LAT + (index * 0.001) + jitter, 6),
                "lon": round(KANPUR_BASE_LON + (index * 0.001) + jitter, 6),
                "current_load": 0,
                "max_capacity": 1,
            }
        )

        orders.append(
            {
                "order_id": f"order_{index + 1:03d}",
                "pickup_lat": round(
                    KANPUR_BASE_LAT + (index * 0.001) + 0.0003 + jitter,
                    6,
                ),
                "pickup_lon": round(
                    KANPUR_BASE_LON + (index * 0.001) + 0.0003 + jitter,
                    6,
                ),
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


def _payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _run_request(
    *,
    mode: str,
    base_url: str,
    endpoint: str,
    size: int,
    cycle: int,
    request_kind: str,
    payload: dict[str, Any],
    payload_hash: str,
    timeout_s: float,
) -> DispatchCacheRequestResult:
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
            return _failed_request_result(
                mode=mode,
                base_url=base_url,
                endpoint=endpoint,
                size=size,
                cycle=cycle,
                request_kind=request_kind,
                payload_hash=payload_hash,
                status_code=status_code,
                request_elapsed_ms=request_elapsed_ms,
                error=json.dumps(response_body),
            )

        return _successful_request_result(
            mode=mode,
            base_url=base_url,
            endpoint=endpoint,
            size=size,
            cycle=cycle,
            request_kind=request_kind,
            payload_hash=payload_hash,
            status_code=status_code,
            request_elapsed_ms=request_elapsed_ms,
            body=response_body,
        )

    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        request_elapsed_ms = round((perf_counter() - started_at) * 1000.0, 6)

        return _failed_request_result(
            mode=mode,
            base_url=base_url,
            endpoint=endpoint,
            size=size,
            cycle=cycle,
            request_kind=request_kind,
            payload_hash=payload_hash,
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


def _successful_request_result(
    *,
    mode: str,
    base_url: str,
    endpoint: str,
    size: int,
    cycle: int,
    request_kind: str,
    payload_hash: str,
    status_code: int,
    request_elapsed_ms: float,
    body: dict[str, Any],
) -> DispatchCacheRequestResult:
    timings = body.get("timings", {})
    comparison = body.get("comparison", {})
    hungarian = body.get("hungarian", {})

    success = _response_is_valid(body)

    return DispatchCacheRequestResult(
        mode=mode,
        base_url=base_url,
        endpoint=endpoint,
        size=size,
        cycle=cycle,
        request_kind=request_kind,
        payload_hash=payload_hash,
        status_code=status_code,
        success=success,
        error=None if success else "Response failed validation.",
        request_elapsed_ms=request_elapsed_ms,
        cache_used=body.get("cache_used"),
        api_elapsed_ms=_optional_float(timings.get("api_elapsed_ms")),
        matrix_generation_time_ms=_optional_float(
            timings.get("matrix_generation_time_ms")
        ),
        greedy_total_cost=_optional_float(body.get("greedy", {}).get("total_cost")),
        hungarian_total_cost=_optional_float(hungarian.get("total_cost")),
        hungarian_non_regression=comparison.get("hungarian_non_regression"),
        assigned_order_count=_optional_int(body.get("assigned_order_count")),
        hungarian_assigned_count=_optional_int(hungarian.get("assigned_count")),
    )


def _failed_request_result(
    *,
    mode: str,
    base_url: str,
    endpoint: str,
    size: int,
    cycle: int,
    request_kind: str,
    payload_hash: str,
    status_code: int | None,
    request_elapsed_ms: float,
    error: str,
) -> DispatchCacheRequestResult:
    return DispatchCacheRequestResult(
        mode=mode,
        base_url=base_url,
        endpoint=endpoint,
        size=size,
        cycle=cycle,
        request_kind=request_kind,
        payload_hash=payload_hash,
        status_code=status_code,
        success=False,
        error=error,
        request_elapsed_ms=request_elapsed_ms,
        cache_used=None,
        api_elapsed_ms=None,
        matrix_generation_time_ms=None,
        greedy_total_cost=None,
        hungarian_total_cost=None,
        hungarian_non_regression=None,
        assigned_order_count=None,
        hungarian_assigned_count=None,
    )


def _response_is_valid(body: dict[str, Any]) -> bool:
    comparison = body.get("comparison", {})
    hungarian = body.get("hungarian", {})

    return (
        body.get("status") == "ok"
        and body.get("phase") == "tier3_phase9"
        and comparison.get("hungarian_non_regression") is True
        and body.get("assigned_order_count") == hungarian.get("assigned_count")
        and isinstance(body.get("cache_used"), bool)
    )


def _build_cycle_result(
    *,
    mode: str,
    size: int,
    cycle: int,
    payload_hash: str,
    first: DispatchCacheRequestResult,
    repeat: DispatchCacheRequestResult,
) -> DispatchCacheCycleResult:
    same_hungarian_total_cost = (
        first.hungarian_total_cost == repeat.hungarian_total_cost
        and first.hungarian_total_cost is not None
    )
    same_assignment_count = (
        first.assigned_order_count == repeat.assigned_order_count
        and first.assigned_order_count is not None
    )

    speedup_ratio = None
    if repeat.request_elapsed_ms > 0:
        speedup_ratio = round(
            first.request_elapsed_ms / repeat.request_elapsed_ms,
            6,
        )

    return DispatchCacheCycleResult(
        mode=mode,
        size=size,
        cycle=cycle,
        payload_hash=payload_hash,
        first_success=first.success,
        repeat_success=repeat.success,
        first_cache_used=first.cache_used,
        repeat_cache_used=repeat.cache_used,
        same_hungarian_total_cost=same_hungarian_total_cost,
        same_assignment_count=same_assignment_count,
        repeat_request_faster_or_equal=repeat.request_elapsed_ms
        <= first.request_elapsed_ms,
        first_request_elapsed_ms=first.request_elapsed_ms,
        repeat_request_elapsed_ms=repeat.request_elapsed_ms,
        speedup_ratio=speedup_ratio,
        cache_hit_observed=repeat.cache_used is True,
        cache_field_present=isinstance(first.cache_used, bool)
        and isinstance(repeat.cache_used, bool),
    )


def _cycle_successful(cycle: DispatchCacheCycleResult) -> bool:
    return (
        cycle.first_success
        and cycle.repeat_success
        and cycle.same_hungarian_total_cost
        and cycle.same_assignment_count
        and cycle.cache_field_present
    )


def _build_group_summaries(
    cycles: list[DispatchCacheCycleResult],
    sizes: list[int],
) -> dict[str, DispatchCacheGroupSummary]:
    summaries: dict[str, DispatchCacheGroupSummary] = {}

    for size in sizes:
        group = [cycle for cycle in cycles if cycle.size == size]
        successful = [cycle for cycle in group if _cycle_successful(cycle)]

        success_count = len(successful)
        failure_count = len(group) - success_count
        cache_hit_count = sum(cycle.cache_hit_observed for cycle in group)

        first_elapsed_values = [
            cycle.first_request_elapsed_ms for cycle in successful
        ]
        repeat_elapsed_values = [
            cycle.repeat_request_elapsed_ms for cycle in successful
        ]
        speedup_values = [
            cycle.speedup_ratio
            for cycle in successful
            if cycle.speedup_ratio is not None
        ]

        summaries[f"{size}x{size}"] = DispatchCacheGroupSummary(
            size=size,
            cycle_count=len(group),
            success_count=success_count,
            failure_count=failure_count,
            success_rate_pct=round((success_count / len(group)) * 100.0, 6)
            if group
            else 0.0,
            cache_hit_count=cache_hit_count,
            cache_hit_rate_pct=round((cache_hit_count / len(group)) * 100.0, 6)
            if group
            else 0.0,
            stable_cost_count=sum(cycle.same_hungarian_total_cost for cycle in group),
            stable_assignment_count=sum(
                cycle.same_assignment_count for cycle in group
            ),
            repeat_faster_or_equal_count=sum(
                cycle.repeat_request_faster_or_equal for cycle in group
            ),
            first_request_elapsed_ms=_stats(first_elapsed_values),
            repeat_request_elapsed_ms=_stats(repeat_elapsed_values),
            speedup_ratio=_stats(speedup_values),
        )

    return summaries


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


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None

    return float(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None

    return int(value)


def _summary_to_jsonable_dict(summary: DispatchCacheProbeSummary) -> dict[str, Any]:
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