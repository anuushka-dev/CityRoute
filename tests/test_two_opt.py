# tests/test_two_opt.py

from __future__ import annotations

import pytest

from app.core.two_opt import (
    TwoOptResult,
    assert_two_opt_non_regression,
    calculate_route_distance_m,
    two_optimize,
)


def improvement_matrix() -> list[list[float]]:

    return [
        # depot, stop0, stop1, stop2
        [0.0, 10.0, 1.0, 10.0],  # depot
        [10.0, 0.0, 10.0, 1.0],  # stop 0
        [1.0, 10.0, 0.0, 1.0],  # stop 1
        [10.0, 1.0, 1.0, 0.0],  # stop 2
    ]


def already_good_matrix() -> list[list[float]]:

    return [
        # depot, stop0, stop1, stop2
        [0.0, 1.0, 10.0, 20.0],
        [1.0, 0.0, 1.0, 10.0],
        [10.0, 1.0, 0.0, 1.0],
        [20.0, 10.0, 1.0, 0.0],
    ]


def test_calculate_route_distance_open_route() -> None:
    matrix = improvement_matrix()

    distance = calculate_route_distance_m(
        [0, 1, 2],
        matrix,
        return_to_start=False,
    )

    assert distance == 21.0


def test_calculate_route_distance_return_to_start() -> None:
    matrix = improvement_matrix()

    distance = calculate_route_distance_m(
        [0, 1, 2],
        matrix,
        return_to_start=True,
    )

    # open distance 21 + stop2 -> depot 10
    assert distance == 31.0


def test_two_opt_improves_bad_route() -> None:
    matrix = improvement_matrix()

    result = two_optimize(
        [0, 1, 2],
        matrix,
        return_to_start=False,
        max_iterations=20,
    )

    assert isinstance(result, TwoOptResult)
    assert result.initial_order == [0, 1, 2]
    assert result.optimized_order == [1, 2, 0]

    assert result.initial_distance_m == 21.0
    assert result.optimized_distance_m == 3.0
    assert result.improvement_m == 18.0
    assert result.improvement_pct == pytest.approx(85.714, abs=0.001)

    assert result.improved is True
    assert result.swaps_applied >= 1
    assert result.converged is True
    assert result.return_to_start is False

    assert_two_opt_non_regression(result)


def test_two_opt_supports_return_to_start() -> None:
    matrix = improvement_matrix()

    result = two_optimize(
        [0, 1, 2],
        matrix,
        return_to_start=True,
        max_iterations=20,
    )

    assert result.return_to_start is True
    assert result.optimized_distance_m <= result.initial_distance_m
    assert result.improved is True
    assert result.swaps_applied >= 1

    assert_two_opt_non_regression(result)


def test_two_opt_does_not_mutate_input_order() -> None:
    matrix = improvement_matrix()
    original_order = [0, 1, 2]

    result = two_optimize(
        original_order,
        matrix,
        return_to_start=False,
        max_iterations=20,
    )

    assert original_order == [0, 1, 2]
    assert result.initial_order == [0, 1, 2]


def test_two_opt_never_makes_already_good_route_worse() -> None:
    matrix = already_good_matrix()

    result = two_optimize(
        [0, 1, 2],
        matrix,
        return_to_start=False,
        max_iterations=20,
    )

    assert result.initial_distance_m == 3.0
    assert result.optimized_distance_m == 3.0
    assert result.improvement_m == 0.0
    assert result.improvement_pct == 0.0
    assert result.improved is False
    assert result.swaps_applied == 0
    assert result.converged is True

    assert_two_opt_non_regression(result)


def test_two_opt_convergence_trace_starts_at_iteration_zero() -> None:
    matrix = improvement_matrix()

    result = two_optimize(
        [0, 1, 2],
        matrix,
        return_to_start=False,
        max_iterations=20,
        keep_trace=True,
    )

    assert len(result.convergence_trace) >= 2

    first_item = result.convergence_trace[0]
    assert first_item.iteration == 0
    assert first_item.distance_m == result.initial_distance_m
    assert first_item.improved is False

    final_item = result.convergence_trace[-1]
    assert final_item.distance_m == result.optimized_distance_m
    assert final_item.improved is False


def test_two_opt_can_disable_trace() -> None:
    matrix = improvement_matrix()

    result = two_optimize(
        [0, 1, 2],
        matrix,
        return_to_start=False,
        max_iterations=20,
        keep_trace=False,
    )

    assert result.convergence_trace == []
    assert result.swaps_applied >= 1
    assert result.optimized_distance_m <= result.initial_distance_m


def test_single_stop_route_is_valid() -> None:
    matrix = [
        [0.0, 12.0],
        [12.0, 0.0],
    ]

    result = two_optimize(
        [0],
        matrix,
        return_to_start=True,
        max_iterations=10,
    )

    assert result.initial_distance_m == 24.0
    assert result.optimized_distance_m == 24.0
    assert result.optimized_order == [0]
    assert result.improved is False
    assert result.swaps_applied == 0
    assert result.converged is True


def test_invalid_empty_matrix_rejected() -> None:
    with pytest.raises(ValueError, match="distance_matrix must not be empty"):
        calculate_route_distance_m([0], [])


def test_invalid_non_square_matrix_rejected() -> None:
    matrix = [
        [0.0, 1.0],
        [1.0],
    ]

    with pytest.raises(ValueError, match="distance_matrix must be square"):
        calculate_route_distance_m([0], matrix)


def test_invalid_duplicate_stop_rejected() -> None:
    matrix = improvement_matrix()

    with pytest.raises(ValueError, match="duplicate stops"):
        two_optimize([0, 0, 1], matrix)


def test_invalid_out_of_range_stop_rejected() -> None:
    matrix = improvement_matrix()

    with pytest.raises(ValueError, match="out of range"):
        two_optimize([0, 1, 99], matrix)


def test_invalid_unreachable_edge_rejected() -> None:
    matrix = [
        [0.0, 5.0, 10.0],
        [5.0, 0.0, -1.0],
        [10.0, -1.0, 0.0],
    ]

    with pytest.raises(ValueError, match="unreachable edge"):
        calculate_route_distance_m(
            [0, 1],
            matrix,
            return_to_start=False,
        )


def test_invalid_max_iterations_rejected() -> None:
    matrix = improvement_matrix()

    with pytest.raises(ValueError, match="max_iterations"):
        two_optimize(
            [0, 1, 2],
            matrix,
            max_iterations=0,
        )


def test_invalid_negative_tolerance_rejected() -> None:
    matrix = improvement_matrix()

    with pytest.raises(ValueError, match="improvement_tolerance_m"):
        two_optimize(
            [0, 1, 2],
            matrix,
            improvement_tolerance_m=-1.0,
        )


def test_non_regression_guard_raises_for_bad_result() -> None:
    bad_result = TwoOptResult(
        initial_order=[0, 1],
        optimized_order=[1, 0],
        initial_distance_m=100.0,
        optimized_distance_m=120.0,
        improvement_m=-20.0,
        improvement_pct=-20.0,
        improved=False,
        iterations=1,
        swaps_applied=1,
        converged=True,
        return_to_start=False,
        convergence_trace=[],
    )

    with pytest.raises(AssertionError, match="2-Opt regression detected"):
        assert_two_opt_non_regression(bad_result)