import pytest

from app.core.lns import (
    UNREACHABLE_DISTANCE,
    cheapest_insertion_repair,
    large_neighborhood_search,
    route_distance_m,
)


def _line_distance_matrix(size: int) -> list[list[float]]:
    """Create simple symmetric matrix where distance = abs(i - j)."""
    return [[float(abs(i - j)) for j in range(size)] for i in range(size)]


def test_route_distance_open_route():
    matrix = _line_distance_matrix(5)

    distance = route_distance_m(
        [1, 2, 3, 4],
        matrix,
        depot_index=0,
        return_to_start=False,
    )

    assert distance == 4.0


def test_route_distance_return_to_start():
    matrix = _line_distance_matrix(5)

    distance = route_distance_m(
        [1, 2, 3, 4],
        matrix,
        depot_index=0,
        return_to_start=True,
    )

    assert distance == 8.0


def test_route_distance_returns_unreachable_when_leg_is_missing():
    matrix = _line_distance_matrix(4)
    matrix[1][2] = UNREACHABLE_DISTANCE

    distance = route_distance_m(
        [1, 2, 3],
        matrix,
        depot_index=0,
        return_to_start=False,
    )

    assert distance == UNREACHABLE_DISTANCE


def test_cheapest_insertion_repair_preserves_all_stops():
    matrix = _line_distance_matrix(5)

    repaired = cheapest_insertion_repair(
        partial_order=[1, 4],
        removed_stops=[2, 3],
        distance_matrix=matrix,
        depot_index=0,
        return_to_start=False,
    )

    assert sorted(repaired) == [1, 2, 3, 4]
    assert len(repaired) == 4


def test_lns_empty_order_returns_zero_distance():
    matrix = _line_distance_matrix(1)

    result = large_neighborhood_search([], matrix, random_seed=42)

    assert result.optimized_order == []
    assert result.total_distance_m == 0.0
    assert result.initial_distance_m == 0.0
    assert result.distance_saved_m == 0.0
    assert result.improvement_pct == 0.0
    assert result.iterations_run == 0
    assert result.improvements_applied == 0
    assert result.converged is True


def test_lns_improves_or_preserves_initial_order():
    matrix = _line_distance_matrix(5)
    bad_initial_order = [4, 1, 3, 2]

    result = large_neighborhood_search(
        bad_initial_order,
        matrix,
        max_iterations=50,
        destroy_fraction=1.0,
        random_seed=7,
        no_improvement_limit=10,
        keep_trace=True,
    )

    assert sorted(result.optimized_order) == sorted(bad_initial_order)
    assert result.total_distance_m <= result.initial_distance_m
    assert result.distance_saved_m >= 0.0
    assert result.improvement_pct >= 0.0
    assert result.iterations_run >= 1
    assert len(result.trace) == result.iterations_run


def test_lns_reproducible_with_same_seed():
    matrix = _line_distance_matrix(7)
    initial_order = [6, 1, 5, 2, 4, 3]

    result_1 = large_neighborhood_search(
        initial_order,
        matrix,
        max_iterations=30,
        destroy_fraction=0.5,
        random_seed=123,
        no_improvement_limit=10,
        keep_trace=True,
    )
    result_2 = large_neighborhood_search(
        initial_order,
        matrix,
        max_iterations=30,
        destroy_fraction=0.5,
        random_seed=123,
        no_improvement_limit=10,
        keep_trace=True,
    )

    assert result_1.optimized_order == result_2.optimized_order
    assert result_1.total_distance_m == result_2.total_distance_m
    assert result_1.improvement_pct == result_2.improvement_pct
    assert result_1.trace == result_2.trace


def test_lns_rejects_unreachable_initial_route():
    matrix = _line_distance_matrix(4)
    matrix[1][2] = UNREACHABLE_DISTANCE

    with pytest.raises(ValueError, match="initial_order contains unreachable route legs"):
        large_neighborhood_search([1, 2, 3], matrix, random_seed=42)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_iterations": 0}, "max_iterations must be >= 1"),
        ({"destroy_fraction": 0.0}, "destroy_fraction must be > 0 and <= 1"),
        ({"destroy_fraction": 1.5}, "destroy_fraction must be > 0 and <= 1"),
        ({"no_improvement_limit": 0}, "no_improvement_limit must be >= 1"),
    ],
)
def test_lns_parameter_validation(kwargs, message):
    matrix = _line_distance_matrix(5)

    with pytest.raises(ValueError, match=message):
        large_neighborhood_search([1, 2, 3, 4], matrix, random_seed=42, **kwargs)