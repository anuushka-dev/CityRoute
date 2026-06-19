# tests/test_vrp_compare_contract.py

import pytest
from pydantic import ValidationError

from app.core.vrp_improvement_metrics import calculate_vrp_improvement
from app.schemas.vrp_compare import (
    VrpCompareRequest,
    VrpCompareResponse,
    VrpGreedySummary,
    VrpImprovementSummary,
    VrpTwoOptSummary,
)


def test_vrp_compare_request_accepts_phase7_inputs() -> None:
    request = VrpCompareRequest(
        start={"lat": 26.44, "lon": 80.30},
        stops=[
            {"lat": 26.45, "lon": 80.35},
            {"lat": 26.46, "lon": 80.34},
        ],
        return_to_start=True,
        matrix_algorithm="bidirectional_astar",
        use_cache=True,
        two_opt_max_iterations=250,
    )

    assert request.return_to_start is True
    assert request.matrix_algorithm == "bidirectional_astar"
    assert request.two_opt_max_iterations == 250
    assert len(request.stops) == 2


def test_vrp_compare_request_rejects_too_many_stops() -> None:
    stops = [
        {"lat": 26.45, "lon": 80.35}
        for _ in range(25)
    ]

    with pytest.raises(ValidationError):
        VrpCompareRequest(
            start={"lat": 26.44, "lon": 80.30},
            stops=stops,
        )


def test_vrp_compare_request_rejects_invalid_two_opt_iterations() -> None:
    with pytest.raises(ValidationError):
        VrpCompareRequest(
            start={"lat": 26.44, "lon": 80.30},
            stops=[{"lat": 26.45, "lon": 80.35}],
            two_opt_max_iterations=0,
        )


def test_vrp_compare_response_represents_greedy_to_two_opt_improvement() -> None:
    metrics = calculate_vrp_improvement(
        baseline_total_distance_m=1000.0,
        improved_total_distance_m=900.0,
    )

    response = VrpCompareResponse(
        matrix_algorithm="bidirectional_astar",
        stop_count=3,
        return_to_start=False,
        greedy=VrpGreedySummary(
            optimized_order=[0, 1, 2],
            total_distance_m=1000.0,
            optimization_time_ms=0.12,
        ),
        two_opt=VrpTwoOptSummary(
            optimized_order=[0, 2, 1],
            total_distance_m=900.0,
            optimization_time_ms=1.95,
            iterations=3,
            improvement_count=2,
        ),
        improvement=VrpImprovementSummary(
            distance_saved_m=metrics.distance_saved_m,
            improvement_pct=metrics.improvement_pct,
            is_improved_or_equal=metrics.is_improved_or_equal,
            is_strictly_improved=metrics.is_strictly_improved,
            tolerance_m=metrics.tolerance_m,
        ),
        matrix_generation_time_ms=4.12,
        total_time_ms=7.33,
        cache_used=True,
    )

    assert response.status == "ok"
    assert response.phase == "tier2_phase7"
    assert response.greedy.algorithm == "nearest_neighbor_greedy"
    assert response.two_opt.algorithm == "two_opt"
    assert response.improvement.distance_saved_m == 100.0
    assert response.improvement.improvement_pct == 10.0
    assert response.improvement.is_improved_or_equal is True
    assert response.improvement.is_strictly_improved is True


def test_vrp_compare_response_supports_equal_non_regression_result() -> None:
    metrics = calculate_vrp_improvement(
        baseline_total_distance_m=1000.0,
        improved_total_distance_m=1000.0,
    )

    response = VrpCompareResponse(
        matrix_algorithm="source_dijkstra",
        stop_count=2,
        return_to_start=True,
        greedy=VrpGreedySummary(
            optimized_order=[0, 1],
            total_distance_m=1000.0,
            optimization_time_ms=0.08,
        ),
        two_opt=VrpTwoOptSummary(
            optimized_order=[0, 1],
            total_distance_m=1000.0,
            optimization_time_ms=0.5,
            iterations=1,
            improvement_count=0,
        ),
        improvement=VrpImprovementSummary(
            distance_saved_m=metrics.distance_saved_m,
            improvement_pct=metrics.improvement_pct,
            is_improved_or_equal=metrics.is_improved_or_equal,
            is_strictly_improved=metrics.is_strictly_improved,
            tolerance_m=metrics.tolerance_m,
        ),
        matrix_generation_time_ms=3.5,
        total_time_ms=5.0,
        cache_used=True,
    )

    assert response.improvement.distance_saved_m == 0.0
    assert response.improvement.improvement_pct == 0.0
    assert response.improvement.is_improved_or_equal is True
    assert response.improvement.is_strictly_improved is False