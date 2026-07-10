# tests/test_dispatch_fairness.py

from __future__ import annotations

import pytest

from app.core.dispatch_cost_matrix import DispatchSlot
from app.core.dispatch_fairness import (
    DispatchFairnessResult,
    DriverFairnessMetric,
    calculate_dispatch_fairness,
)
from app.core.hungarian import AssignmentPair


def test_calculate_dispatch_fairness_returns_result_type():
    slots = [
        DispatchSlot(0, 0, "d1", 0, 0, 2),
        DispatchSlot(1, 1, "d2", 0, 0, 2),
    ]
    assignments = [
        AssignmentPair(0, 0, 10.0),
        AssignmentPair(1, 1, 20.0),
    ]

    result = calculate_dispatch_fairness(assignments, slots)

    assert isinstance(result, DispatchFairnessResult)
    assert all(isinstance(item, DriverFairnessMetric) for item in result.driver_metrics)


def test_calculate_dispatch_fairness_balanced_assignment():
    slots = [
        DispatchSlot(0, 0, "d1", 0, 0, 2),
        DispatchSlot(1, 0, "d1", 1, 0, 2),
        DispatchSlot(2, 1, "d2", 0, 0, 2),
        DispatchSlot(3, 1, "d2", 1, 0, 2),
    ]
    assignments = [
        AssignmentPair(0, 0, 10.0),
        AssignmentPair(2, 1, 20.0),
    ]

    result = calculate_dispatch_fairness(assignments, slots)

    assert result.driver_count == 2
    assert result.total_assigned_orders == 2
    assert result.total_available_slots == 4
    assert result.assigned_order_min == 1
    assert result.assigned_order_max == 1
    assert result.assigned_order_range == 0
    assert result.assigned_order_mean == 1.0
    assert result.assigned_order_std_dev == 0.0
    assert result.projected_load_min == 1
    assert result.projected_load_max == 1
    assert result.projected_load_range == 0
    assert result.projected_load_mean == 1.0
    assert result.projected_load_std_dev == 0.0
    assert result.fairness_score == 100.0


def test_calculate_dispatch_fairness_unbalanced_assignment():
    slots = [
        DispatchSlot(0, 0, "d1", 0, 0, 3),
        DispatchSlot(1, 0, "d1", 1, 0, 3),
        DispatchSlot(2, 0, "d1", 2, 0, 3),
        DispatchSlot(3, 1, "d2", 0, 0, 3),
        DispatchSlot(4, 1, "d2", 1, 0, 3),
        DispatchSlot(5, 1, "d2", 2, 0, 3),
    ]
    assignments = [
        AssignmentPair(0, 0, 10.0),
        AssignmentPair(1, 1, 20.0),
        AssignmentPair(2, 2, 30.0),
    ]

    result = calculate_dispatch_fairness(assignments, slots)

    assert result.driver_count == 2
    assert result.total_assigned_orders == 3
    assert result.assigned_order_min == 0
    assert result.assigned_order_max == 3
    assert result.assigned_order_range == 3
    assert result.assigned_order_mean == 1.5
    assert result.assigned_order_std_dev == 1.5
    assert result.projected_load_min == 0
    assert result.projected_load_max == 3
    assert result.projected_load_range == 3
    assert result.projected_load_mean == 1.5
    assert result.projected_load_std_dev == 1.5
    assert result.fairness_score == 62.5


def test_calculate_dispatch_fairness_includes_current_load_in_projected_load():
    slots = [
        DispatchSlot(0, 0, "d1", 0, 1, 3),
        DispatchSlot(1, 0, "d1", 1, 1, 3),
        DispatchSlot(2, 1, "d2", 0, 2, 3),
    ]
    assignments = [
        AssignmentPair(0, 0, 10.0),
        AssignmentPair(2, 1, 20.0),
    ]

    result = calculate_dispatch_fairness(assignments, slots)

    metrics = {metric.driver_id: metric for metric in result.driver_metrics}

    assert metrics["d1"].current_load == 1
    assert metrics["d1"].assigned_orders == 1
    assert metrics["d1"].projected_load == 2
    assert metrics["d1"].remaining_capacity == 1

    assert metrics["d2"].current_load == 2
    assert metrics["d2"].assigned_orders == 1
    assert metrics["d2"].projected_load == 3
    assert metrics["d2"].remaining_capacity == 0


def test_calculate_dispatch_fairness_computes_utilization_percentages():
    slots = [
        DispatchSlot(0, 0, "d1", 0, 0, 2),
        DispatchSlot(1, 0, "d1", 1, 0, 2),
        DispatchSlot(2, 1, "d2", 0, 1, 4),
        DispatchSlot(3, 1, "d2", 1, 1, 4),
        DispatchSlot(4, 1, "d2", 2, 1, 4),
    ]
    assignments = [
        AssignmentPair(0, 0, 10.0),
        AssignmentPair(2, 1, 20.0),
    ]

    result = calculate_dispatch_fairness(assignments, slots)
    metrics = {metric.driver_id: metric for metric in result.driver_metrics}

    assert metrics["d1"].projected_load == 1
    assert metrics["d1"].utilization_pct == 50.0

    assert metrics["d2"].projected_load == 2
    assert metrics["d2"].utilization_pct == 50.0

    assert result.max_utilization_pct == 50.0
    assert result.min_utilization_pct == 50.0


def test_calculate_dispatch_fairness_keeps_drivers_with_zero_new_assignments():
    slots = [
        DispatchSlot(0, 0, "d1", 0, 0, 2),
        DispatchSlot(1, 0, "d1", 1, 0, 2),
        DispatchSlot(2, 1, "d2", 0, 0, 2),
        DispatchSlot(3, 1, "d2", 1, 0, 2),
    ]
    assignments = [
        AssignmentPair(0, 0, 10.0),
    ]

    result = calculate_dispatch_fairness(assignments, slots)
    metrics = {metric.driver_id: metric for metric in result.driver_metrics}

    assert metrics["d1"].assigned_orders == 1
    assert metrics["d2"].assigned_orders == 0
    assert result.total_assigned_orders == 1


def test_calculate_dispatch_fairness_allows_no_assignments():
    slots = [
        DispatchSlot(0, 0, "d1", 0, 0, 2),
        DispatchSlot(1, 0, "d1", 1, 0, 2),
        DispatchSlot(2, 1, "d2", 0, 0, 2),
    ]

    result = calculate_dispatch_fairness([], slots)

    assert result.total_assigned_orders == 0
    assert result.assigned_order_min == 0
    assert result.assigned_order_max == 0
    assert result.assigned_order_mean == 0.0
    assert result.assigned_order_std_dev == 0.0


def test_calculate_dispatch_fairness_sorts_driver_metrics_by_driver_id():
    slots = [
        DispatchSlot(0, 0, "driver_z", 0, 0, 1),
        DispatchSlot(1, 1, "driver_a", 0, 0, 1),
    ]

    result = calculate_dispatch_fairness([], slots)

    assert [metric.driver_id for metric in result.driver_metrics] == [
        "driver_a",
        "driver_z",
    ]


def test_calculate_dispatch_fairness_rejects_empty_slots():
    with pytest.raises(ValueError, match="at least one dispatch slot"):
        calculate_dispatch_fairness([], [])


def test_calculate_dispatch_fairness_rejects_duplicate_slot_rows():
    slots = [
        DispatchSlot(0, 0, "d1", 0, 0, 2),
        DispatchSlot(0, 1, "d2", 0, 0, 2),
    ]

    with pytest.raises(ValueError, match="duplicate slot row_index"):
        calculate_dispatch_fairness([], slots)


def test_calculate_dispatch_fairness_rejects_negative_slot_row():
    slots = [
        DispatchSlot(-1, 0, "d1", 0, 0, 2),
    ]

    with pytest.raises(ValueError, match="row_index"):
        calculate_dispatch_fairness([], slots)


def test_calculate_dispatch_fairness_rejects_empty_driver_id():
    slots = [
        DispatchSlot(0, 0, "", 0, 0, 2),
    ]

    with pytest.raises(ValueError, match="driver_id"):
        calculate_dispatch_fairness([], slots)


def test_calculate_dispatch_fairness_rejects_negative_current_load():
    slots = [
        DispatchSlot(0, 0, "d1", 0, -1, 2),
    ]

    with pytest.raises(ValueError, match="current_load"):
        calculate_dispatch_fairness([], slots)


def test_calculate_dispatch_fairness_rejects_non_positive_capacity():
    slots = [
        DispatchSlot(0, 0, "d1", 0, 0, 0),
    ]

    with pytest.raises(ValueError, match="max_capacity"):
        calculate_dispatch_fairness([], slots)


def test_calculate_dispatch_fairness_rejects_current_load_above_capacity():
    slots = [
        DispatchSlot(0, 0, "d1", 0, 3, 2),
    ]

    with pytest.raises(ValueError, match="must not exceed"):
        calculate_dispatch_fairness([], slots)


def test_calculate_dispatch_fairness_rejects_assignment_row_not_in_slots():
    slots = [
        DispatchSlot(0, 0, "d1", 0, 0, 2),
    ]
    assignments = [
        AssignmentPair(99, 0, 10.0),
    ]

    with pytest.raises(ValueError, match="does not exist"):
        calculate_dispatch_fairness(assignments, slots)


def test_calculate_dispatch_fairness_rejects_duplicate_assignment_rows():
    slots = [
        DispatchSlot(0, 0, "d1", 0, 0, 2),
        DispatchSlot(1, 0, "d1", 1, 0, 2),
    ]
    assignments = [
        AssignmentPair(0, 0, 10.0),
        AssignmentPair(0, 1, 20.0),
    ]

    with pytest.raises(ValueError, match="duplicate assignment row_index"):
        calculate_dispatch_fairness(assignments, slots)


def test_calculate_dispatch_fairness_rejects_duplicate_assignment_cols():
    slots = [
        DispatchSlot(0, 0, "d1", 0, 0, 2),
        DispatchSlot(1, 0, "d1", 1, 0, 2),
    ]
    assignments = [
        AssignmentPair(0, 0, 10.0),
        AssignmentPair(1, 0, 20.0),
    ]

    with pytest.raises(ValueError, match="duplicate assignment col_index"):
        calculate_dispatch_fairness(assignments, slots)


def test_calculate_dispatch_fairness_rejects_negative_assignment_col():
    slots = [
        DispatchSlot(0, 0, "d1", 0, 0, 2),
    ]
    assignments = [
        AssignmentPair(0, -1, 10.0),
    ]

    with pytest.raises(ValueError, match="col_index"):
        calculate_dispatch_fairness(assignments, slots)