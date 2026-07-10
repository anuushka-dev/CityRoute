# benchmarks/phase_9/phase9_dispatch_fairness_probe.py

from __future__ import annotations

import argparse
import itertools
import json
import random
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.hungarian import solve_hungarian  # noqa: E402

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "benchmarks" / "phase_9" / "docker_results"


@dataclass(frozen=True)
class ProbeCaseResult:
    size: int
    iteration: int
    row_count: int
    col_count: int
    hungarian_total_cost: float
    brute_force_total_cost: float
    cost_difference: float
    assignment_count: int
    expected_assignment_count: int
    matched_brute_force: bool
    elapsed_ms: float
    cost_matrix: list[list[float]]
    assignments: list[dict[str, Any]]


@dataclass(frozen=True)
class ProbeSummary:
    phase: str
    benchmark: str
    created_at_utc: str
    seed: int
    sizes: list[int]
    iterations_per_size: int
    case_count: int
    success_count: int
    mismatch_count: int
    success_rate_pct: float
    max_abs_cost_difference: float
    total_elapsed_ms: float
    output_raw_file: str
    quality_flags: dict[str, bool]


def main() -> None:
    args = _parse_args()

    output_dir = Path(args.output_dir)

    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir

    output_dir.mkdir(parents=True, exist_ok=True)

    sizes = _parse_sizes(args.sizes)

    if any(size < 1 for size in sizes):
        raise ValueError("All sizes must be >= 1.")

    if any(size > args.max_bruteforce_size for size in sizes):
        raise ValueError(
            "This correctness probe uses brute force. "
            f"Requested size exceeds max_bruteforce_size={args.max_bruteforce_size}."
        )

    rng = random.Random(args.seed)
    started_at = perf_counter()

    results: list[ProbeCaseResult] = []

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

    total_elapsed_ms = round((perf_counter() - started_at) * 1000.0, 6)

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    raw_path = output_dir / f"phase9_hungarian_correctness_raw_{timestamp}.json"
    summary_path = output_dir / f"phase9_hungarian_correctness_summary_{timestamp}.json"

    raw_payload = {
        "phase": "tier3_phase9",
        "benchmark": "hungarian_correctness_probe",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "seed": args.seed,
        "sizes": sizes,
        "iterations_per_size": args.iterations,
        "cases": [asdict(result) for result in results],
    }

    _write_json(raw_path, raw_payload)

    mismatch_count = sum(not result.matched_brute_force for result in results)
    success_count = len(results) - mismatch_count
    max_abs_cost_difference = (
        max(abs(result.cost_difference) for result in results) if results else 0.0
    )

    summary = ProbeSummary(
        phase="tier3_phase9",
        benchmark="hungarian_correctness_probe",
        created_at_utc=datetime.now(UTC).isoformat(),
        seed=args.seed,
        sizes=sizes,
        iterations_per_size=args.iterations,
        case_count=len(results),
        success_count=success_count,
        mismatch_count=mismatch_count,
        success_rate_pct=round((success_count / len(results)) * 100.0, 6)
        if results
        else 0.0,
        max_abs_cost_difference=round(max_abs_cost_difference, 6),
        total_elapsed_ms=total_elapsed_ms,
        output_raw_file=str(raw_path.relative_to(PROJECT_ROOT)),
        quality_flags={
            "all_cases_successful": mismatch_count == 0,
            "all_assignment_counts_valid": all(
                result.assignment_count == result.expected_assignment_count
                for result in results
            ),
            "all_cost_differences_zero": max_abs_cost_difference == 0.0,
        },
    )

    _write_json(summary_path, asdict(summary))

    print(json.dumps(asdict(summary), indent=2))

    if mismatch_count != 0:
        raise SystemExit(1)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 9 Hungarian correctness probe using brute force.",
    )
    parser.add_argument(
        "--sizes",
        default="2,3,4,5,6,7,8",
        help="Comma-separated square matrix sizes to test.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=50,
        help="Random cases per size.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=909,
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
        default=10_000,
        help="Maximum generated cost.",
    )
    parser.add_argument(
        "--max-bruteforce-size",
        type=int,
        default=8,
        help="Safety limit because brute force is factorial.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for raw and summary JSON outputs.",
    )
    return parser.parse_args()


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
) -> ProbeCaseResult:
    started_at = perf_counter()

    hungarian_result = solve_hungarian(cost_matrix)
    brute_force_total_cost = _brute_force_min_cost(cost_matrix)

    elapsed_ms = round((perf_counter() - started_at) * 1000.0, 6)

    cost_difference = round(
        hungarian_result.total_cost - brute_force_total_cost,
        6,
    )

    expected_assignment_count = min(len(cost_matrix), len(cost_matrix[0]))

    return ProbeCaseResult(
        size=size,
        iteration=iteration,
        row_count=len(cost_matrix),
        col_count=len(cost_matrix[0]),
        hungarian_total_cost=hungarian_result.total_cost,
        brute_force_total_cost=brute_force_total_cost,
        cost_difference=cost_difference,
        assignment_count=hungarian_result.assigned_count,
        expected_assignment_count=expected_assignment_count,
        matched_brute_force=cost_difference == 0.0
        and hungarian_result.assigned_count == expected_assignment_count,
        elapsed_ms=elapsed_ms,
        cost_matrix=cost_matrix,
        assignments=[
            {
                "row_index": assignment.row_index,
                "col_index": assignment.col_index,
                "cost": assignment.cost,
            }
            for assignment in hungarian_result.assignments
        ],
    )


def _brute_force_min_cost(cost_matrix: list[list[float]]) -> float:
    row_count = len(cost_matrix)
    col_count = len(cost_matrix[0])

    if row_count != col_count:
        raise ValueError("This probe only brute-forces square matrices.")

    best = float("inf")

    for col_permutation in itertools.permutations(range(col_count)):
        total = 0.0

        for row_index, col_index in enumerate(col_permutation):
            total += cost_matrix[row_index][col_index]

        if total < best:
            best = total

    return round(best, 6)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()