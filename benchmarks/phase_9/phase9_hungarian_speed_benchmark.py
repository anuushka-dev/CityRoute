# phase9_hungarian_speed_benchmark.py

from __future__ import annotations

import argparse
import json
import random
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

from app.core.hungarian import solve_hungarian  # noqa: E402

DEFAULT_LOCAL_OUTPUT_DIR = PROJECT_ROOT / "benchmarks" / "phase_9" / "local_results"
DEFAULT_DOCKER_OUTPUT_DIR = PROJECT_ROOT / "benchmarks" / "phase_9" / "docker_results"


@dataclass(frozen=True)
class SpeedCaseResult:
    size: int
    iteration: int
    row_count: int
    col_count: int
    assigned_count: int
    total_cost: float
    elapsed_ms: float
    assignment_count_valid: bool


@dataclass(frozen=True)
class SpeedGroupSummary:
    size: int
    iteration_count: int
    success_count: int
    failure_count: int
    success_rate_pct: float
    elapsed_ms: dict[str, float]
    assigned_count_all_valid: bool
    target_250ms_met: bool | None
    target_2sec_met: bool | None


@dataclass(frozen=True)
class SpeedBenchmarkSummary:
    phase: str
    benchmark: str
    mode: str
    created_at_utc: str
    seed: int
    sizes: list[int]
    iterations_per_size: int
    case_count: int
    success_count: int
    failure_count: int
    success_rate_pct: float
    group_summaries: dict[str, SpeedGroupSummary]
    output_raw_file: str
    output_summary_file: str
    quality_flags: dict[str, bool]


def main() -> None:
    args = _parse_args()

    mode: Literal["local", "docker"] = args.mode
    output_dir = _resolve_output_dir(mode=mode, output_dir=args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    sizes = _parse_sizes(args.sizes)

    if any(size < 1 for size in sizes):
        raise ValueError("All sizes must be >= 1.")

    rng = random.Random(args.seed)
    results: list[SpeedCaseResult] = []

    for size in sizes:
        for iteration in range(1, args.iterations + 1):
            cost_matrix = _generate_cost_matrix(
                size=size,
                rng=rng,
                min_cost=args.min_cost,
                max_cost=args.max_cost,
            )

            results.append(
                _run_case(
                    cost_matrix=cost_matrix,
                    size=size,
                    iteration=iteration,
                )
            )

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    raw_path = output_dir / f"phase9_hungarian_speed_raw_{mode}_{timestamp}.json"
    summary_path = output_dir / f"phase9_hungarian_speed_summary_{mode}_{timestamp}.json"

    raw_payload = {
        "phase": "tier3_phase9",
        "benchmark": "hungarian_speed_benchmark",
        "mode": mode,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "seed": args.seed,
        "sizes": sizes,
        "iterations_per_size": args.iterations,
        "cases": [asdict(result) for result in results],
    }

    _write_json(raw_path, raw_payload)

    group_summaries = _build_group_summaries(results, sizes)
    success_count = sum(result.assignment_count_valid for result in results)
    failure_count = len(results) - success_count

    summary = SpeedBenchmarkSummary(
        phase="tier3_phase9",
        benchmark="hungarian_speed_benchmark",
        mode=mode,
        created_at_utc=datetime.now(UTC).isoformat(),
        seed=args.seed,
        sizes=sizes,
        iterations_per_size=args.iterations,
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
            "all_assignment_counts_valid": failure_count == 0,
            "size_50_median_under_250ms": _target_flag(
                group_summaries,
                size=50,
                target_key="target_250ms_met",
            ),
            "size_100_median_under_2sec": _target_flag(
                group_summaries,
                size=100,
                target_key="target_2sec_met",
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
        description="Phase 9 Hungarian algorithm speed benchmark.",
    )
    parser.add_argument(
        "--mode",
        choices=["local", "docker"],
        default="local",
        help="Result mode. Controls default output folder and filename suffix.",
    )
    parser.add_argument(
        "--sizes",
        default="5,10,25,50,100",
        help="Comma-separated square matrix sizes.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=20,
        help="Iterations per size.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=919,
        help="Deterministic random seed.",
    )
    parser.add_argument(
        "--min-cost",
        type=int,
        default=1,
        help="Minimum generated cost.",
    )
    parser.add_argument(
        "--max-cost",
        type=int,
        default=100_000,
        help="Maximum generated cost.",
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


def _parse_sizes(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _generate_cost_matrix(
    *,
    size: int,
    rng: random.Random,
    min_cost: int,
    max_cost: int,
) -> list[list[float]]:
    return [
        [float(rng.randint(min_cost, max_cost)) for _ in range(size)]
        for _ in range(size)
    ]


def _run_case(
    *,
    cost_matrix: list[list[float]],
    size: int,
    iteration: int,
) -> SpeedCaseResult:
    started_at = perf_counter()
    result = solve_hungarian(cost_matrix)
    elapsed_ms = round((perf_counter() - started_at) * 1000.0, 6)

    expected_assignment_count = min(len(cost_matrix), len(cost_matrix[0]))

    return SpeedCaseResult(
        size=size,
        iteration=iteration,
        row_count=len(cost_matrix),
        col_count=len(cost_matrix[0]),
        assigned_count=result.assigned_count,
        total_cost=result.total_cost,
        elapsed_ms=elapsed_ms,
        assignment_count_valid=result.assigned_count == expected_assignment_count,
    )


def _build_group_summaries(
    results: list[SpeedCaseResult],
    sizes: list[int],
) -> dict[str, SpeedGroupSummary]:
    summaries: dict[str, SpeedGroupSummary] = {}

    for size in sizes:
        group = [result for result in results if result.size == size]
        elapsed_values = [result.elapsed_ms for result in group]

        success_count = sum(result.assignment_count_valid for result in group)
        failure_count = len(group) - success_count

        median_ms = _median(elapsed_values)

        summaries[f"{size}x{size}"] = SpeedGroupSummary(
            size=size,
            iteration_count=len(group),
            success_count=success_count,
            failure_count=failure_count,
            success_rate_pct=round((success_count / len(group)) * 100.0, 6)
            if group
            else 0.0,
            elapsed_ms={
                "min": round(min(elapsed_values), 6) if elapsed_values else 0.0,
                "median": median_ms,
                "mean": round(statistics.mean(elapsed_values), 6)
                if elapsed_values
                else 0.0,
                "p95": _percentile(elapsed_values, 95),
                "max": round(max(elapsed_values), 6) if elapsed_values else 0.0,
            },
            assigned_count_all_valid=failure_count == 0,
            target_250ms_met=median_ms < 250.0 if size == 50 else None,
            target_2sec_met=median_ms < 2_000.0 if size == 100 else None,
        )

    return summaries


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
    group_summaries: dict[str, SpeedGroupSummary],
    *,
    size: int,
    target_key: str,
) -> bool:
    group = group_summaries.get(f"{size}x{size}")

    if group is None:
        return False

    value = getattr(group, target_key)

    return bool(value)


def _summary_to_jsonable_dict(summary: SpeedBenchmarkSummary) -> dict[str, Any]:
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