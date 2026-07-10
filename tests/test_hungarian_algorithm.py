# teats/test_hungarian_algorithm.py

from __future__ import annotations

from itertools import combinations, permutations
from math import inf, isclose, nan

import pytest

from app.core.hungarian import AssignmentPair, HungarianResult, solve_hungarian


def _assignment_pairs_as_tuples(result: HungarianResult) -> set[tuple[int, int]]:
    return {
        (assignment.row_index, assignment.col_index)
        for assignment in result.assignments
    }


def _brute_force_min_cost(cost_matrix: list[list[float]]) -> float:
    row_count = len(cost_matrix)
    col_count = len(cost_matrix[0])

    best = float("inf")

    if row_count <= col_count:
        for selected_cols in permutations(range(col_count), row_count):
            total = sum(
                cost_matrix[row_index][col_index]
                for row_index, col_index in enumerate(selected_cols)
            )
            best = min(best, total)
    else:
        for selected_rows in combinations(range(row_count), col_count):
            for selected_rows_perm in permutations(selected_rows):
                total = sum(
                    cost_matrix[row_index][col_index]
                    for col_index, row_index in enumerate(selected_rows_perm)
                )
                best = min(best, total)

    return round(best, 6)


def test_hungarian_returns_result_type():
    result = solve_hungarian([[4, 1], [2, 3]])

    assert isinstance(result, HungarianResult)
    assert all(isinstance(item, AssignmentPair) for item in result.assignments)


def test_hungarian_solves_one_by_one_matrix():
    result = solve_hungarian([[7]])

    assert result.total_cost == 7.0
    assert result.assigned_count == 1
    assert result.unassigned_rows == []
    assert result.unassigned_cols == []
    assert _assignment_pairs_as_tuples(result) == {(0, 0)}


def test_hungarian_solves_simple_two_by_two_matrix():
    result = solve_hungarian([[4, 1], [2, 3]])

    assert result.total_cost == 3.0
    assert result.assigned_count == 2
    assert _assignment_pairs_as_tuples(result) == {(0, 1), (1, 0)}


def test_hungarian_beats_greedy_trap_case():
    cost_matrix = [
        [1.0, 2.0],
        [1.1, 100.0],
    ]

    result = solve_hungarian(cost_matrix)

    assert result.total_cost == 3.1
    assert _assignment_pairs_as_tuples(result) == {(0, 1), (1, 0)}


def test_hungarian_solves_three_by_three_matrix():
    cost_matrix = [
        [9, 2, 7],
        [6, 4, 3],
        [5, 8, 1],
    ]

    result = solve_hungarian(cost_matrix)

    assert result.total_cost == _brute_force_min_cost(cost_matrix)
    assert result.assigned_count == 3
    assert result.unassigned_rows == []
    assert result.unassigned_cols == []


def test_hungarian_supports_more_columns_than_rows():
    cost_matrix = [
        [10, 2, 8],
        [6, 4, 3],
    ]

    result = solve_hungarian(cost_matrix)

    assert result.row_count == 2
    assert result.col_count == 3
    assert result.assigned_count == 2
    assert result.total_cost == _brute_force_min_cost(cost_matrix)
    assert result.unassigned_rows == []
    assert len(result.unassigned_cols) == 1


def test_hungarian_supports_more_rows_than_columns():
    cost_matrix = [
        [10, 2],
        [6, 4],
        [3, 8],
    ]

    result = solve_hungarian(cost_matrix)

    assert result.row_count == 3
    assert result.col_count == 2
    assert result.assigned_count == 2
    assert result.total_cost == _brute_force_min_cost(cost_matrix)
    assert len(result.unassigned_rows) == 1
    assert result.unassigned_cols == []


def test_hungarian_is_deterministic_on_ties():
    cost_matrix = [
        [1, 1],
        [1, 1],
    ]

    first = solve_hungarian(cost_matrix)
    second = solve_hungarian(cost_matrix)

    assert first == second
    assert first.total_cost == 2.0
    assert first.assigned_count == 2


def test_hungarian_rejects_empty_matrix():
    with pytest.raises(ValueError, match="at least one row"):
        solve_hungarian([])


def test_hungarian_rejects_empty_row():
    with pytest.raises(ValueError, match="row 0 is empty"):
        solve_hungarian([[]])


def test_hungarian_rejects_non_rectangular_matrix():
    with pytest.raises(ValueError, match="rectangular"):
        solve_hungarian([[1, 2], [3]])


def test_hungarian_rejects_negative_cost():
    with pytest.raises(ValueError, match="non-negative"):
        solve_hungarian([[1, -2], [3, 4]])


def test_hungarian_rejects_nan_cost():
    with pytest.raises(ValueError, match="finite"):
        solve_hungarian([[1, nan], [3, 4]])


def test_hungarian_rejects_infinite_cost():
    with pytest.raises(ValueError, match="finite"):
        solve_hungarian([[1, inf], [3, 4]])


@pytest.mark.parametrize(
    "cost_matrix",
    [
        [[5, 9, 1], [10, 3, 2], [8, 7, 4]],
        [[12, 7, 9, 7], [8, 9, 6, 6], [7, 17, 12, 14]],
        [[4, 2, 8], [2, 3, 7], [3, 1, 6], [9, 5, 2]],
        [[11, 4, 8, 6], [3, 9, 10, 7], [5, 2, 1, 12], [6, 8, 4, 3]],
    ],
)
def test_hungarian_matches_brute_force_on_small_cases(cost_matrix):
    result = solve_hungarian(cost_matrix)

    assert isclose(
        result.total_cost,
        _brute_force_min_cost(cost_matrix),
        rel_tol=0,
        abs_tol=1e-6,
    )
    assert result.assigned_count == min(len(cost_matrix), len(cost_matrix[0]))