# app/core/dispatch_fairness.py

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import sqrt

from app.core.dispatch_cost_matrix import DispatchSlot
from app.core.hungarian import AssignmentPair


@dataclass(frozen=True)
class DriverFairnessMetric:
    """Per-driver dispatch fairness details."""

    driver_id: str
    current_load: int
    max_capacity: int
    available_slots: int
    assigned_orders: int
    projected_load: int
    remaining_capacity: int
    utilization_pct: float


@dataclass(frozen=True)
class DispatchFairnessResult:
    """Fairness metrics for one dispatch assignment result."""

    driver_metrics: list[DriverFairnessMetric]
    driver_count: int
    total_assigned_orders: int
    total_available_slots: int
    assigned_order_min: int
    assigned_order_max: int
    assigned_order_range: int
    assigned_order_mean: float
    assigned_order_std_dev: float
    projected_load_min: int
    projected_load_max: int
    projected_load_range: int
    projected_load_mean: float
    projected_load_std_dev: float
    max_utilization_pct: float
    min_utilization_pct: float
    fairness_score: float


def calculate_dispatch_fairness(
    assignments: Sequence[AssignmentPair],
    slots: Sequence[DispatchSlot],
) -> DispatchFairnessResult:

    normalized_slots = _validate_slots(slots)
    normalized_assignments = _validate_assignments(assignments, normalized_slots)

    slot_by_row = {slot.row_index: slot for slot in normalized_slots}

    driver_state: dict[str, dict[str, int]] = {}

    for slot in normalized_slots:
        if slot.driver_id not in driver_state:
            driver_state[slot.driver_id] = {
                "current_load": slot.current_load,
                "max_capacity": slot.max_capacity,
                "available_slots": 0,
                "assigned_orders": 0,
            }

        driver_state[slot.driver_id]["available_slots"] += 1

    for assignment in normalized_assignments:
        slot = slot_by_row[assignment.row_index]
        driver_state[slot.driver_id]["assigned_orders"] += 1

    driver_metrics: list[DriverFairnessMetric] = []

    for driver_id in sorted(driver_state):
        state = driver_state[driver_id]

        current_load = state["current_load"]
        max_capacity = state["max_capacity"]
        available_slots = state["available_slots"]
        assigned_orders = state["assigned_orders"]

        projected_load = current_load + assigned_orders
        remaining_capacity = max_capacity - projected_load

        utilization_pct = (
            round((projected_load / max_capacity) * 100.0, 6)
            if max_capacity > 0
            else 0.0
        )

        driver_metrics.append(
            DriverFairnessMetric(
                driver_id=driver_id,
                current_load=current_load,
                max_capacity=max_capacity,
                available_slots=available_slots,
                assigned_orders=assigned_orders,
                projected_load=projected_load,
                remaining_capacity=remaining_capacity,
                utilization_pct=utilization_pct,
            )
        )

    assigned_counts = [metric.assigned_orders for metric in driver_metrics]
    projected_loads = [metric.projected_load for metric in driver_metrics]
    utilizations = [metric.utilization_pct for metric in driver_metrics]

    assigned_min = min(assigned_counts)
    assigned_max = max(assigned_counts)
    projected_min = min(projected_loads)
    projected_max = max(projected_loads)

    assigned_std_dev = _population_std_dev(assigned_counts)
    projected_std_dev = _population_std_dev(projected_loads)

    # A simple 0..100 score where lower projected-load spread is better.
    # This is explainable for audit purposes; not a scientific fairness model.
    fairness_score = round(max(0.0, 100.0 - (projected_std_dev * 25.0)), 6)

    return DispatchFairnessResult(
        driver_metrics=driver_metrics,
        driver_count=len(driver_metrics),
        total_assigned_orders=sum(assigned_counts),
        total_available_slots=sum(metric.available_slots for metric in driver_metrics),
        assigned_order_min=assigned_min,
        assigned_order_max=assigned_max,
        assigned_order_range=assigned_max - assigned_min,
        assigned_order_mean=round(sum(assigned_counts) / len(assigned_counts), 6),
        assigned_order_std_dev=assigned_std_dev,
        projected_load_min=projected_min,
        projected_load_max=projected_max,
        projected_load_range=projected_max - projected_min,
        projected_load_mean=round(sum(projected_loads) / len(projected_loads), 6),
        projected_load_std_dev=projected_std_dev,
        max_utilization_pct=max(utilizations),
        min_utilization_pct=min(utilizations),
        fairness_score=fairness_score,
    )


def _validate_slots(slots: Sequence[DispatchSlot]) -> list[DispatchSlot]:
    if len(slots) == 0:
        raise ValueError("slots must contain at least one dispatch slot.")

    normalized = list(slots)

    seen_rows: set[int] = set()

    for index, slot in enumerate(normalized):
        if slot.row_index in seen_rows:
            raise ValueError(f"duplicate slot row_index found: {slot.row_index}")

        seen_rows.add(slot.row_index)

        if slot.row_index < 0:
            raise ValueError(f"slots[{index}].row_index must be non-negative.")

        if not slot.driver_id.strip():
            raise ValueError(f"slots[{index}].driver_id must not be empty.")

        if slot.current_load < 0:
            raise ValueError(f"slots[{index}].current_load must be non-negative.")

        if slot.max_capacity <= 0:
            raise ValueError(f"slots[{index}].max_capacity must be positive.")

        if slot.current_load > slot.max_capacity:
            raise ValueError(
                f"slots[{index}].current_load must not exceed max_capacity."
            )

    return normalized


def _validate_assignments(
    assignments: Sequence[AssignmentPair],
    slots: Sequence[DispatchSlot],
) -> list[AssignmentPair]:
    normalized = list(assignments)

    valid_rows = {slot.row_index for slot in slots}
    seen_rows: set[int] = set()
    seen_cols: set[int] = set()

    for index, assignment in enumerate(normalized):
        if assignment.row_index not in valid_rows:
            raise ValueError(
                f"assignments[{index}].row_index does not exist in dispatch slots."
            )

        if assignment.row_index in seen_rows:
            raise ValueError(
                f"duplicate assignment row_index found: {assignment.row_index}"
            )

        if assignment.col_index in seen_cols:
            raise ValueError(
                f"duplicate assignment col_index found: {assignment.col_index}"
            )

        if assignment.col_index < 0:
            raise ValueError(f"assignments[{index}].col_index must be non-negative.")

        seen_rows.add(assignment.row_index)
        seen_cols.add(assignment.col_index)

    return normalized


def _population_std_dev(values: Sequence[int]) -> float:
    if len(values) == 0:
        return 0.0

    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)

    return round(sqrt(variance), 6)


__all__ = [
    "DispatchFairnessResult",
    "DriverFairnessMetric",
    "calculate_dispatch_fairness",
]