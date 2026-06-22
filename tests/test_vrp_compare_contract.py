# tests/test_vrp_compare_contract.py

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.vrp_compare import (
    VrpCompareRequest,
    VrpCompareResponse,
    VrpGreedySummary,
    VrpImprovementSummary,
    VrpTwoOptSummary,
)


def _coordinate(lat: float = 26.4499, lon: float = 80.3319) -> dict[str, float]:
    return {
        "lat": lat,
        "lon": lon,
    }


def test_vrp_compare_request_accepts_phase7_inputs() -> None:
    request = VrpCompareRequest(
        start=_coordinate(),
        stops=[
            _coordinate(26.4600, 80.3400),
            _coordinate(26.4700, 80.3500),
            _coordinate(26.4800, 80.3600),
        ],
        return_to_start=False,
        matrix_algorithm="source_dijkstra",
        use_cache=True,
        ttl_seconds=3600,
        two_opt_max_iterations=100,
        improvement_tolerance_m=0.001,
        keep_trace=True,
    )

    assert request.matrix_algorithm == "source_dijkstra"
    assert request.use_cache is True
    assert request.return_to_start is False
    assert request.two_opt_max_iterations == 100
    assert request.improvement_tolerance_m == 0.001
    assert request.keep_trace is True
    assert len(request.stops) == 3


def test_vrp_compare_request_rejects_too_many_stops() -> None:
    stops = [
        _coordinate(26.4400 + (index * 0.001), 80.3200 + (index * 0.001))
        for index in range(25)
    ]

    with pytest.raises(ValidationError):
        VrpCompareRequest(
            start=_coordinate(),
            stops=stops,
            matrix_algorithm="source_dijkstra",
        )


def test_vrp_compare_request_rejects_invalid_two_opt_iterations() -> None:
    with pytest.raises(ValidationError):
        VrpCompareRequest(
            start=_coordinate(),
            stops=[
                _coordinate(26.4600, 80.3400),
                _coordinate(26.4700, 80.3500),
            ],
            matrix_algorithm="source_dijkstra",
            two_opt_max_iterations=0,
        )


def test_vrp_compare_response_represents_greedy_to_two_opt_improvement() -> None:
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
            swaps_applied=2,
            converged=True,
        ),
        improvement=VrpImprovementSummary(
            baseline_distance_m=1000.0,
            optimized_distance_m=900.0,
            distance_saved_m=100.0,
            improvement_pct=10.0,
            improved=True,
            non_regression=True,
        ),
        matrix_generation_time_ms=4.12,
        total_time_ms=7.33,
        cache_used=True,
        cache_hits=1,
        cache_misses=0,
    )

    assert response.matrix_algorithm == "bidirectional_astar"
    assert response.stop_count == 3
    assert response.return_to_start is False

    assert response.greedy.algorithm == "nearest_neighbor_greedy"
    assert response.greedy.optimized_order == [0, 1, 2]
    assert response.greedy.total_distance_m == 1000.0

    assert response.two_opt.algorithm == "two_opt"
    assert response.two_opt.optimized_order == [0, 2, 1]
    assert response.two_opt.total_distance_m == 900.0
    assert response.two_opt.iterations == 3
    assert response.two_opt.swaps_applied == 2
    assert response.two_opt.converged is True

    assert response.improvement.baseline_distance_m == 1000.0
    assert response.improvement.optimized_distance_m == 900.0
    assert response.improvement.distance_saved_m == 100.0
    assert response.improvement.improvement_pct == 10.0
    assert response.improvement.improved is True
    assert response.improvement.non_regression is True

    assert response.cache_used is True
    assert response.cache_hits == 1
    assert response.cache_misses == 0


def test_vrp_compare_response_supports_equal_non_regression_result() -> None:
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
            swaps_applied=0,
            converged=True,
        ),
        improvement=VrpImprovementSummary(
            baseline_distance_m=1000.0,
            optimized_distance_m=1000.0,
            distance_saved_m=0.0,
            improvement_pct=0.0,
            improved=False,
            non_regression=True,
        ),
        matrix_generation_time_ms=3.5,
        total_time_ms=5.0,
        cache_used=True,
        cache_hits=1,
        cache_misses=0,
    )

    assert response.return_to_start is True
    assert response.improvement.baseline_distance_m == 1000.0
    assert response.improvement.optimized_distance_m == 1000.0
    assert response.improvement.distance_saved_m == 0.0
    assert response.improvement.improvement_pct == 0.0

    assert response.improvement.improved is False
    assert response.improvement.non_regression is True

    assert response.two_opt.swaps_applied == 0
    assert response.two_opt.converged is True