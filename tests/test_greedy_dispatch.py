# tests/test_greedy_dispatch.py

from __future__ import annotations

from math import inf, nan

import pytest

from app.core.greedy_dispatch import GreedyDispatchResult, solve_greedy_dispatch
from app.core.hungarian import AssignmentPair, solve_hungarian


def _assignment_pairs_as_tuples(result: GreedyDispatchResult) -> set[tuple[int, int]]:
    return {
        (assignment.row_index, assignment.col_index)
        for assignment in result.assignments
    }


def test_greedy_returns_result_type():
    result = solve_greedy_dispatch([[4, 1], [2, 3]])

    assert isinstance(result, GreedyDispatchResult)
    assert all(isinstance(item, AssignmentPair) for item in result.assignments)


def test_greedy_solves_one_by_one_matrix():
    result = solve_greedy_dispatch([[7]])

    assert result.total_cost == 7.0
    assert result.assigned_count == 1
    assert result.unassigned_rows == []
    assert result.unassigned_cols == []
    assert _assignment_pairs_as_tuples(result) == {(0, 0)}


def test_greedy_solves_simple_two_by_two_matrix():
    result = solve_greedy_dispatch([[4, 1], [2, 3]])

    assert result.total_cost == 3.0
    assert result.assigned_count == 2
    assert result.unassigned_rows == []
    assert result.unassigned_cols == []
    assert _assignment_pairs_as_tuples(result) == {(0, 1), (1, 0)}


def test_greedy_is_intentionally_not_globally_optimal_on_trap_case():
    cost_matrix = [
        [1.0, 2.0],
        [1.1, 100.0],
    ]

    greedy = solve_greedy_dispatch(cost_matrix)
    hungarian = solve_hungarian(cost_matrix)

    assert greedy.total_cost == 101.0
    assert hungarian.total_cost == 3.1
    assert hungarian.total_cost < greedy.total_cost


def test_greedy_supports_more_columns_than_rows():
    result = solve_greedy_dispatch(
        [
            [10, 2, 8],
            [6, 4, 3],
        ]
    )

    assert result.row_count == 2
    assert result.col_count == 3
    assert result.assigned_count == 2
    assert result.unassigned_rows == []
    assert len(result.unassigned_cols) == 1


def test_greedy_supports_more_rows_than_columns():
    result = solve_greedy_dispatch(
        [
            [10, 2],
            [6, 4],
            [3, 8],
        ]
    )

    assert result.row_count == 3
    assert result.col_count == 2
    assert result.assigned_count == 2
    assert len(result.unassigned_rows) == 1
    assert result.unassigned_cols == []


def test_greedy_is_deterministic_on_ties():
    cost_matrix = [
        [1, 1],
        [1, 1],
    ]

    first = solve_greedy_dispatch(cost_matrix)
    second = solve_greedy_dispatch(cost_matrix)

    assert first == second
    assert first.total_cost == 2.0
    assert _assignment_pairs_as_tuples(first) == {(0, 0), (1, 1)}


def test_greedy_tie_breaking_can_create_non_optimal_result():
    cost_matrix = [
        [5, 1, 1],
        [1, 5, 1],
        [1, 1, 5],
    ]

    result = solve_greedy_dispatch(cost_matrix)
    hungarian = solve_hungarian(cost_matrix)

    assert result.assigned_count == 3
    assert result.total_cost == 7.0
    assert hungarian.total_cost == 3.0
    assert hungarian.total_cost < result.total_cost
    assert _assignment_pairs_as_tuples(result) == {(0, 1), (1, 0), (2, 2)}


def test_greedy_rejects_empty_matrix():
    with pytest.raises(ValueError, match="at least one row"):
        solve_greedy_dispatch([])


def test_greedy_rejects_empty_row():
    with pytest.raises(ValueError, match="row 0 is empty"):
        solve_greedy_dispatch([[]])


def test_greedy_rejects_non_rectangular_matrix():
    with pytest.raises(ValueError, match="rectangular"):
        solve_greedy_dispatch([[1, 2], [3]])


def test_greedy_rejects_negative_cost():
    with pytest.raises(ValueError, match="non-negative"):
        solve_greedy_dispatch([[1, -2], [3, 4]])


def test_greedy_rejects_nan_cost():
    with pytest.raises(ValueError, match="finite"):
        solve_greedy_dispatch([[1, nan], [3, 4]])


def test_greedy_rejects_infinite_cost():
    with pytest.raises(ValueError, match="finite"):
        solve_greedy_dispatch([[1, inf], [3, 4]])


@pytest.mark.parametrize(
    "cost_matrix",
    [
        [[5, 9, 1], [10, 3, 2], [8, 7, 4]],
        [[12, 7, 9, 7], [8, 9, 6, 6], [7, 17, 12, 14]],
        [[4, 2, 8], [2, 3, 7], [3, 1, 6], [9, 5, 2]],
    ],
)
def test_greedy_assignment_count_matches_min_dimension(cost_matrix):
    result = solve_greedy_dispatch(cost_matrix)

    assert result.assigned_count == min(len(cost_matrix), len(cost_matrix[0]))
    assert len(result.assignments) == result.assigned_count