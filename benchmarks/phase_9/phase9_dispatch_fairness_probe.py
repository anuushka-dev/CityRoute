# benchmarks/phase_9/phase9_dispatch_fairness_probe.py

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.dispatch_cost_matrix import (  # noqa: E402
    DispatchDriver,
    DispatchOrder,
    build_dispatch_cost_matrix,
)
from app.core.dispatch_fairness import calculate_dispatch_fairness  # noqa: E402
from app.core.greedy_dispatch import solve_greedy_dispatch  # noqa: E402
from app.core.hungarian import solve_hungarian  # noqa: E402

DEFAULT_LOCAL_OUTPUT_DIR = PROJECT_ROOT / "benchmarks" / "phase_9" / "local_results"
DEFAULT_DOCKER_OUTPUT_DIR = PROJECT_ROOT / "benchmarks" / "phase_9" / "docker_results"


@dataclass(frozen=True)
class FairnessPolicy:
    name: str
    load_penalty_m: float
    slot_penalty_m: float


@dataclass(frozen=True)
class FairnessScenario:
    name: str
    driver_count: int
    order_count: int
    max_capacity_per_driver: int
    hotspot_driver_index: int
    hotspot_discount_m: float
    distance_step_m: float


@dataclass(frozen=True)
class FairnessProbeCaseResult:
    mode: str
    scenario_name: str
    policy_name: str
    algorithm: str
    driver_count: int
    order_count: int
    available_slot_count: int
    assigned_count: int
    total_cost: float
    fairness_score: float
    assigned_order_range: int
    assigned_order_std_dev: float
    projected_load_range: int
    projected_load_std_dev: float
    max_utilization_pct: float
    min_utilization_pct: float
    elapsed_ms: float
    non_negative_cost: bool
    assignment_count_valid: bool
    fairness_score_valid: bool
    driver_metrics: list[dict[str, Any]]


@dataclass(frozen=True)
class FairnessScenarioSummary:
    scenario_name: str
    policy_name: str
    driver_count: int
    order_count: int
    available_slot_count: int
    greedy_total_cost: float
    hungarian_total_cost: float
    hungarian_non_regression: bool
    greedy_fairness_score: float
    hungarian_fairness_score: float
    fairness_delta_hungarian_minus_greedy: float
    hungarian_assigned_order_range: int
    hungarian_projected_load_range: int
    assignment_count_valid: bool
    fairness_score_valid: bool


@dataclass(frozen=True)
class FairnessProbeSummary:
    phase: str
    benchmark: str
    mode: str
    created_at_utc: str
    scenario_count: int
    policy_count: int
    case_count: int
    success_count: int
    failure_count: int
    success_rate_pct: float
    scenario_summaries: list[FairnessScenarioSummary]
    output_raw_file: str
    output_summary_file: str
    quality_flags: dict[str, bool]


def main() -> None:
    args = _parse_args()

    mode: Literal["local", "docker"] = args.mode
    output_dir = _resolve_output_dir(mode=mode, output_dir=args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    scenarios = _build_scenarios()
    policies = _build_policies()

    results: list[FairnessProbeCaseResult] = []

    for scenario in scenarios:
        drivers = _build_drivers(scenario)
        orders = _build_orders(scenario)

        for policy in policies:
            cost_matrix_result = build_dispatch_cost_matrix(
                drivers=drivers,
                orders=orders,
                distance_lookup=lambda driver, order, scenario=scenario: (
                    _synthetic_distance_lookup(
                        driver=driver,
                        order=order,
                        scenario=scenario,
                    )
                ),
                load_penalty_m=policy.load_penalty_m,
                slot_penalty_m=policy.slot_penalty_m,
            )

            greedy_started_at = perf_counter()
            greedy_result = solve_greedy_dispatch(cost_matrix_result.cost_matrix)
            greedy_elapsed_ms = round((perf_counter() - greedy_started_at) * 1000.0, 6)

            greedy_fairness = calculate_dispatch_fairness(
                greedy_result.assignments,
                cost_matrix_result.slots,
            )

            results.append(
                _build_case_result(
                    mode=mode,
                    scenario=scenario,
                    policy=policy,
                    algorithm="greedy_dispatch",
                    available_slot_count=cost_matrix_result.available_slot_count,
                    assigned_count=greedy_result.assigned_count,
                    total_cost=greedy_result.total_cost,
                    fairness_result=greedy_fairness,
                    elapsed_ms=greedy_elapsed_ms,
                )
            )

            hungarian_started_at = perf_counter()
            hungarian_result = solve_hungarian(cost_matrix_result.cost_matrix)
            hungarian_elapsed_ms = round(
                (perf_counter() - hungarian_started_at) * 1000.0,
                6,
            )

            hungarian_fairness = calculate_dispatch_fairness(
                hungarian_result.assignments,
                cost_matrix_result.slots,
            )

            results.append(
                _build_case_result(
                    mode=mode,
                    scenario=scenario,
                    policy=policy,
                    algorithm="hungarian",
                    available_slot_count=cost_matrix_result.available_slot_count,
                    assigned_count=hungarian_result.assigned_count,
                    total_cost=hungarian_result.total_cost,
                    fairness_result=hungarian_fairness,
                    elapsed_ms=hungarian_elapsed_ms,
                )
            )

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    raw_path = output_dir / f"phase9_dispatch_fairness_raw_{mode}_{timestamp}.json"
    summary_path = (
        output_dir / f"phase9_dispatch_fairness_summary_{mode}_{timestamp}.json"
    )

    raw_payload = {
        "phase": "tier3_phase9",
        "benchmark": "dispatch_fairness_probe",
        "mode": mode,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "scenarios": [asdict(scenario) for scenario in scenarios],
        "policies": [asdict(policy) for policy in policies],
        "cases": [asdict(result) for result in results],
    }

    _write_json(raw_path, raw_payload)

    scenario_summaries = _build_scenario_summaries(results)

    success_count = sum(_case_successful(result) for result in results)
    failure_count = len(results) - success_count

    summary = FairnessProbeSummary(
        phase="tier3_phase9",
        benchmark="dispatch_fairness_probe",
        mode=mode,
        created_at_utc=datetime.now(UTC).isoformat(),
        scenario_count=len(scenarios),
        policy_count=len(policies),
        case_count=len(results),
        success_count=success_count,
        failure_count=failure_count,
        success_rate_pct=round((success_count / len(results)) * 100.0, 6)
        if results
        else 0.0,
        scenario_summaries=scenario_summaries,
        output_raw_file=str(raw_path.relative_to(PROJECT_ROOT)),
        output_summary_file=str(summary_path.relative_to(PROJECT_ROOT)),
        quality_flags={
            "all_cases_successful": failure_count == 0,
            "all_costs_non_negative": all(result.non_negative_cost for result in results),
            "all_assignment_counts_valid": all(
                result.assignment_count_valid for result in results
            ),
            "all_fairness_scores_valid": all(
                result.fairness_score_valid for result in results
            ),
            "all_hungarian_non_regression": all(
                item.hungarian_non_regression for item in scenario_summaries
            ),
            "at_least_one_policy_changes_fairness": _at_least_one_policy_changes_fairness(
                scenario_summaries
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
        description="Phase 9 dispatch fairness probe.",
    )
    parser.add_argument(
        "--mode",
        choices=["local", "docker"],
        default="local",
        help="Result mode. Controls default output folder.",
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


def _build_scenarios() -> list[FairnessScenario]:
    return [
        FairnessScenario(
            name="small_hotspot_4_drivers_8_orders",
            driver_count=4,
            order_count=8,
            max_capacity_per_driver=4,
            hotspot_driver_index=0,
            hotspot_discount_m=700.0,
            distance_step_m=180.0,
        ),
        FairnessScenario(
            name="medium_hotspot_6_drivers_12_orders",
            driver_count=6,
            order_count=12,
            max_capacity_per_driver=4,
            hotspot_driver_index=0,
            hotspot_discount_m=900.0,
            distance_step_m=170.0,
        ),
        FairnessScenario(
            name="larger_hotspot_8_drivers_16_orders",
            driver_count=8,
            order_count=16,
            max_capacity_per_driver=4,
            hotspot_driver_index=0,
            hotspot_discount_m=1_100.0,
            distance_step_m=160.0,
        ),
    ]


def _build_policies() -> list[FairnessPolicy]:
    return [
        FairnessPolicy(
            name="no_fairness_penalty",
            load_penalty_m=0.0,
            slot_penalty_m=0.0,
        ),
        FairnessPolicy(
            name="slot_fairness_penalty_250m",
            load_penalty_m=0.0,
            slot_penalty_m=250.0,
        ),
        FairnessPolicy(
            name="strong_slot_fairness_penalty_500m",
            load_penalty_m=0.0,
            slot_penalty_m=500.0,
        ),
    ]


def _build_drivers(scenario: FairnessScenario) -> list[DispatchDriver]:
    drivers = []

    for index in range(scenario.driver_count):
        drivers.append(
            DispatchDriver(
                driver_id=f"driver_{index + 1:03d}",
                lat=26.4499 + (index * 0.001),
                lon=80.3319 + (index * 0.001),
                current_load=0,
                max_capacity=scenario.max_capacity_per_driver,
            )
        )

    return drivers


def _build_orders(scenario: FairnessScenario) -> list[DispatchOrder]:
    orders = []

    for index in range(scenario.order_count):
        orders.append(
            DispatchOrder(
                order_id=f"order_{index + 1:03d}",
                pickup_lat=26.4502 + (index * 0.0005),
                pickup_lon=80.3322 + (index * 0.0005),
            )
        )

    return orders


def _synthetic_distance_lookup(
    *,
    driver: DispatchDriver,
    order: DispatchOrder,
    scenario: FairnessScenario,
) -> float:
    driver_index = _id_suffix_to_index(driver.driver_id)
    order_index = _id_suffix_to_index(order.order_id)

    natural_driver_index = order_index % scenario.driver_count

    base_distance = 1_000.0
    distance = base_distance + (
        abs(driver_index - natural_driver_index) * scenario.distance_step_m
    )

    if driver_index == scenario.hotspot_driver_index:
        distance -= scenario.hotspot_discount_m

    return round(max(distance, 1.0), 6)


def _id_suffix_to_index(value: str) -> int:
    return int(value.rsplit("_", maxsplit=1)[1]) - 1


def _build_case_result(
    *,
    mode: str,
    scenario: FairnessScenario,
    policy: FairnessPolicy,
    algorithm: str,
    available_slot_count: int,
    assigned_count: int,
    total_cost: float,
    fairness_result: Any,
    elapsed_ms: float,
) -> FairnessProbeCaseResult:
    expected_assignment_count = min(available_slot_count, scenario.order_count)

    return FairnessProbeCaseResult(
        mode=mode,
        scenario_name=scenario.name,
        policy_name=policy.name,
        algorithm=algorithm,
        driver_count=scenario.driver_count,
        order_count=scenario.order_count,
        available_slot_count=available_slot_count,
        assigned_count=assigned_count,
        total_cost=total_cost,
        fairness_score=fairness_result.fairness_score,
        assigned_order_range=fairness_result.assigned_order_range,
        assigned_order_std_dev=fairness_result.assigned_order_std_dev,
        projected_load_range=fairness_result.projected_load_range,
        projected_load_std_dev=fairness_result.projected_load_std_dev,
        max_utilization_pct=fairness_result.max_utilization_pct,
        min_utilization_pct=fairness_result.min_utilization_pct,
        elapsed_ms=elapsed_ms,
        non_negative_cost=total_cost >= 0.0,
        assignment_count_valid=assigned_count == expected_assignment_count,
        fairness_score_valid=0.0 <= fairness_result.fairness_score <= 100.0,
        driver_metrics=[
            {
                "driver_id": metric.driver_id,
                "current_load": metric.current_load,
                "max_capacity": metric.max_capacity,
                "available_slots": metric.available_slots,
                "assigned_orders": metric.assigned_orders,
                "projected_load": metric.projected_load,
                "remaining_capacity": metric.remaining_capacity,
                "utilization_pct": metric.utilization_pct,
            }
            for metric in fairness_result.driver_metrics
        ],
    )


def _build_scenario_summaries(
    results: list[FairnessProbeCaseResult],
) -> list[FairnessScenarioSummary]:
    summaries: list[FairnessScenarioSummary] = []

    scenario_policy_pairs = sorted(
        {
            (result.scenario_name, result.policy_name)
            for result in results
        }
    )

    for scenario_name, policy_name in scenario_policy_pairs:
        matching = [
            result
            for result in results
            if result.scenario_name == scenario_name
            and result.policy_name == policy_name
        ]

        greedy = _find_algorithm_result(matching, "greedy_dispatch")
        hungarian = _find_algorithm_result(matching, "hungarian")

        summaries.append(
            FairnessScenarioSummary(
                scenario_name=scenario_name,
                policy_name=policy_name,
                driver_count=hungarian.driver_count,
                order_count=hungarian.order_count,
                available_slot_count=hungarian.available_slot_count,
                greedy_total_cost=greedy.total_cost,
                hungarian_total_cost=hungarian.total_cost,
                hungarian_non_regression=hungarian.total_cost <= greedy.total_cost,
                greedy_fairness_score=greedy.fairness_score,
                hungarian_fairness_score=hungarian.fairness_score,
                fairness_delta_hungarian_minus_greedy=round(
                    hungarian.fairness_score - greedy.fairness_score,
                    6,
                ),
                hungarian_assigned_order_range=hungarian.assigned_order_range,
                hungarian_projected_load_range=hungarian.projected_load_range,
                assignment_count_valid=greedy.assignment_count_valid
                and hungarian.assignment_count_valid,
                fairness_score_valid=greedy.fairness_score_valid
                and hungarian.fairness_score_valid,
            )
        )

    return summaries

def _at_least_one_policy_changes_fairness(
    summaries: list[FairnessScenarioSummary],
) -> bool:
    scores_by_scenario: dict[str, set[float]] = {}

    for summary in summaries:
        scores_by_scenario.setdefault(summary.scenario_name, set()).add(
            summary.hungarian_fairness_score
        )

    return any(len(scores) > 1 for scores in scores_by_scenario.values())


def _find_algorithm_result(
    results: list[FairnessProbeCaseResult],
    algorithm: str,
) -> FairnessProbeCaseResult:
    for result in results:
        if result.algorithm == algorithm:
            return result

    raise ValueError(f"Missing algorithm result: {algorithm}")


def _case_successful(result: FairnessProbeCaseResult) -> bool:
    return (
        result.non_negative_cost
        and result.assignment_count_valid
        and result.fairness_score_valid
    )


def _summary_to_jsonable_dict(summary: FairnessProbeSummary) -> dict[str, Any]:
    payload = asdict(summary)
    payload["scenario_summaries"] = [
        asdict(value) for value in summary.scenario_summaries
    ]
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()