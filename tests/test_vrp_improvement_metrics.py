# tests/test_vrp_improvement_metrics.py

import math

import pytest

from app.core.vrp_improvement_metrics import (
    VrpImprovementMetricError,
    calculate_vrp_improvement,
)


def test_improvement_metrics_for_shorter_route() -> None:
    metrics = calculate_vrp_improvement(
        baseline_total_distance_m=1000.0,
        improved_total_distance_m=900.0,
    )

    assert metrics.baseline_total_distance_m == 1000.0
    assert metrics.improved_total_distance_m == 900.0
    assert metrics.distance_saved_m == 100.0
    assert metrics.improvement_pct == 10.0
    assert metrics.is_improved_or_equal is True
    assert metrics.is_strictly_improved is True


def test_improvement_metrics_for_equal_route() -> None:
    metrics = calculate_vrp_improvement(
        baseline_total_distance_m=1000.0,
        improved_total_distance_m=1000.0,
    )

    assert metrics.distance_saved_m == 0.0
    assert metrics.improvement_pct == 0.0
    assert metrics.is_improved_or_equal is True
    assert metrics.is_strictly_improved is False


def test_improvement_metrics_for_worse_route() -> None:
    metrics = calculate_vrp_improvement(
        baseline_total_distance_m=1000.0,
        improved_total_distance_m=1100.0,
    )

    assert metrics.distance_saved_m == -100.0
    assert metrics.improvement_pct == -10.0
    assert metrics.is_improved_or_equal is False
    assert metrics.is_strictly_improved is False


def test_tolerance_allows_tiny_floating_point_worse_route() -> None:
    metrics = calculate_vrp_improvement(
        baseline_total_distance_m=1000.0,
        improved_total_distance_m=1000.0000004,
        tolerance_m=1e-3,
    )

    assert metrics.is_improved_or_equal is True
    assert metrics.is_strictly_improved is False


def test_rejects_zero_baseline_distance() -> None:
    with pytest.raises(VrpImprovementMetricError):
        calculate_vrp_improvement(
            baseline_total_distance_m=0.0,
            improved_total_distance_m=0.0,
        )


def test_rejects_negative_distance() -> None:
    with pytest.raises(VrpImprovementMetricError):
        calculate_vrp_improvement(
            baseline_total_distance_m=1000.0,
            improved_total_distance_m=-1.0,
        )


def test_rejects_non_finite_distance() -> None:
    with pytest.raises(VrpImprovementMetricError):
        calculate_vrp_improvement(
            baseline_total_distance_m=1000.0,
            improved_total_distance_m=math.inf,
        )


def test_rejects_negative_tolerance() -> None:
    with pytest.raises(VrpImprovementMetricError):
        calculate_vrp_improvement(
            baseline_total_distance_m=1000.0,
            improved_total_distance_m=900.0,
            tolerance_m=-1.0,
        )