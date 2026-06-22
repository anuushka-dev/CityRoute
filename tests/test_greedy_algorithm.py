# tests/test_greedy_algorithm.py

import pytest

from app.core.greedy_nearest_neighbor import (
    GreedyMatrixError,
    solve_nearest_neighbor_greedy,
)


def test_greedy_single_stop_returns_only_stop_zero():
    matrix = [
        [0, 100],
        [100, 0],
    ]

    result = solve_nearest_neighbor_greedy(
        distance_matrix=matrix,
        return_to_start=False,
    )

    assert result.optimized_order == [0]
    assert result.total_distance_m == 100
    assert len(result.legs) == 1

    assert result.legs[0].from_matrix_index == 0
    assert result.legs[0].to_matrix_index == 1
    assert result.legs[0].distance_m == 100


def test_greedy_selects_nearest_unvisited_stop_each_step():
    matrix = [
        # start, stop0, stop1, stop2
        [0, 10, 5, 20],
        [10, 0, 7, 3],
        [5, 7, 0, 2],
        [20, 3, 2, 0],
    ]

    result = solve_nearest_neighbor_greedy(
        distance_matrix=matrix,
        return_to_start=False,
    )

    # Matrix route:
    # start index 0 -> matrix index 2 -> matrix index 3 -> matrix index 1
    #
    # User-facing stop indexes:
    # matrix 2 = stop 1
    # matrix 3 = stop 2
    # matrix 1 = stop 0
    assert result.optimized_order == [1, 2, 0]
    assert result.total_distance_m == 10

    assert [(leg.from_matrix_index, leg.to_matrix_index) for leg in result.legs] == [
        (0, 2),
        (2, 3),
        (3, 1),
    ]


def test_greedy_returns_every_stop_exactly_once():
    matrix = [
        [0, 9, 3, 8, 7, 4],
        [9, 0, 6, 2, 5, 8],
        [3, 6, 0, 4, 7, 1],
        [8, 2, 4, 0, 3, 6],
        [7, 5, 7, 3, 0, 2],
        [4, 8, 1, 6, 2, 0],
    ]

    result = solve_nearest_neighbor_greedy(
        distance_matrix=matrix,
        return_to_start=False,
    )

    stop_count = len(matrix) - 1

    assert sorted(result.optimized_order) == list(range(stop_count))
    assert len(result.optimized_order) == stop_count
    assert len(set(result.optimized_order)) == stop_count


def test_greedy_uses_deterministic_tie_breaker():
    matrix = [
        # start, stop0, stop1, stop2
        [0, 5, 5, 9],
        [5, 0, 2, 3],
        [5, 2, 0, 1],
        [9, 3, 1, 0],
    ]

    result = solve_nearest_neighbor_greedy(
        distance_matrix=matrix,
        return_to_start=False,
    )

    # stop0 and stop1 are both distance 5 from start.
    # Smaller matrix index wins, so stop0 is selected first.
    assert result.optimized_order[0] == 0


def test_greedy_return_to_start_adds_final_leg():
    matrix = [
        [0, 10, 5],
        [10, 0, 2],
        [5, 2, 0],
    ]

    result = solve_nearest_neighbor_greedy(
        distance_matrix=matrix,
        return_to_start=True,
    )

    # start -> stop1 = 5
    # stop1 -> stop0 = 2
    # stop0 -> start = 10
    assert result.optimized_order == [1, 0]
    assert result.total_distance_m == 17
    assert len(result.legs) == 3

    assert result.legs[-1].from_matrix_index == 1
    assert result.legs[-1].to_matrix_index == 0
    assert result.legs[-1].distance_m == 10


def test_greedy_rejects_empty_matrix():
    with pytest.raises(GreedyMatrixError, match="empty"):
        solve_nearest_neighbor_greedy(
            distance_matrix=[],
            return_to_start=False,
        )


def test_greedy_rejects_matrix_without_stop():
    matrix = [[0]]

    with pytest.raises(GreedyMatrixError, match="At least one delivery stop"):
        solve_nearest_neighbor_greedy(
            distance_matrix=matrix,
            return_to_start=False,
        )


def test_greedy_rejects_non_square_matrix():
    matrix = [
        [0, 1],
        [1],
    ]

    with pytest.raises(GreedyMatrixError, match="square"):
        solve_nearest_neighbor_greedy(
            distance_matrix=matrix,
            return_to_start=False,
        )


def test_greedy_rejects_non_zero_diagonal():
    matrix = [
        [0, 10],
        [10, 3],
    ]

    with pytest.raises(GreedyMatrixError, match="diagonal"):
        solve_nearest_neighbor_greedy(
            distance_matrix=matrix,
            return_to_start=False,
        )


def test_greedy_rejects_none_distance():
    matrix = [
        [0, None],
        [10, 0],
    ]

    with pytest.raises(GreedyMatrixError, match="No path found"):
        solve_nearest_neighbor_greedy(
            distance_matrix=matrix,
            return_to_start=False,
        )


def test_greedy_rejects_negative_distance():
    matrix = [
        [0, -5],
        [5, 0],
    ]

    with pytest.raises(GreedyMatrixError, match="Negative distance"):
        solve_nearest_neighbor_greedy(
            distance_matrix=matrix,
            return_to_start=False,
        )


def test_greedy_rejects_non_finite_distance():
    matrix = [
        [0, float("inf")],
        [5, 0],
    ]

    with pytest.raises(GreedyMatrixError, match="Non-finite distance"):
        solve_nearest_neighbor_greedy(
            distance_matrix=matrix,
            return_to_start=False,
        )