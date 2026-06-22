# app/core/vrp_improvement_metrics.py

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


DEFAULT_DISTANCE_TOLERANCE_M = 1e-6


class VrpImprovementMetricError(ValueError):
    """Raised when VRP improvement metric inputs are invalid."""


@dataclass(frozen=True)
class VrpImprovementMetrics:
    baseline_total_distance_m: float
    improved_total_distance_m: float
    distance_saved_m: float
    improvement_pct: float
    is_improved_or_equal: bool
    is_strictly_improved: bool
    tolerance_m: float


def _validate_distance(name: str, value: float) -> None:
    if not isinstance(value, int | float):
        raise VrpImprovementMetricError(f"{name} must be numeric.")

    if not isfinite(float(value)):
        raise VrpImprovementMetricError(f"{name} must be finite.")

    if float(value) < 0:
        raise VrpImprovementMetricError(f"{name} cannot be negative.")


def calculate_vrp_improvement(
    *,
    baseline_total_distance_m: float,
    improved_total_distance_m: float,
    tolerance_m: float = DEFAULT_DISTANCE_TOLERANCE_M,
) -> VrpImprovementMetrics:
    """
    Compare a baseline VRP route against an improved route.

    Intended Phase 7 usage:
    - baseline_total_distance_m = greedy route distance
    - improved_total_distance_m = 2-Opt route distance

    Positive distance_saved_m means the improved route is shorter.
    Negative distance_saved_m means the improved route became worse.
    """

    _validate_distance("baseline_total_distance_m", baseline_total_distance_m)
    _validate_distance("improved_total_distance_m", improved_total_distance_m)
    _validate_distance("tolerance_m", tolerance_m)

    baseline = float(baseline_total_distance_m)
    improved = float(improved_total_distance_m)
    tolerance = float(tolerance_m)

    if baseline <= 0:
        raise VrpImprovementMetricError(
            "baseline_total_distance_m must be greater than zero."
        )

    distance_saved_m = baseline - improved
    improvement_pct = (distance_saved_m / baseline) * 100

    is_improved_or_equal = improved <= baseline + tolerance
    is_strictly_improved = improved < baseline - tolerance

    return VrpImprovementMetrics(
        baseline_total_distance_m=round(baseline, 3),
        improved_total_distance_m=round(improved, 3),
        distance_saved_m=round(distance_saved_m, 3),
        improvement_pct=round(improvement_pct, 6),
        is_improved_or_equal=is_improved_or_equal,
        is_strictly_improved=is_strictly_improved,
        tolerance_m=tolerance,
    )