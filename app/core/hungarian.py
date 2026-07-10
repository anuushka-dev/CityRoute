# app/core/hungarian.py

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite

_EPSILON = 1e-12


@dataclass(frozen=True)
class AssignmentPair:
    """One row-to-column assignment produced by the Hungarian algorithm."""

    row_index: int
    col_index: int
    cost: float


@dataclass(frozen=True)
class HungarianResult:
    """Result returned by solve_hungarian."""

    assignments: list[AssignmentPair]
    total_cost: float
    row_count: int
    col_count: int
    assigned_count: int
    unassigned_rows: list[int]
    unassigned_cols: list[int]


def solve_hungarian(cost_matrix: Sequence[Sequence[float]]) -> HungarianResult:
    normalized = _validate_and_copy_cost_matrix(cost_matrix)
    row_count = len(normalized)
    col_count = len(normalized[0])

    transposed = False
    working_matrix = normalized

    # This implementation expects rows <= columns.
    # If rows > columns, solve the transposed problem and map the result back.
    if row_count > col_count:
        working_matrix = _transpose(normalized)
        transposed = True

    working_assignments = _hungarian_rows_leq_cols(working_matrix)

    assignments: list[AssignmentPair] = []
    assigned_rows: set[int] = set()
    assigned_cols: set[int] = set()

    for work_row, work_col in working_assignments:
        if transposed:
            original_row = work_col
            original_col = work_row
        else:
            original_row = work_row
            original_col = work_col

        cost = normalized[original_row][original_col]

        assignments.append(
            AssignmentPair(
                row_index=original_row,
                col_index=original_col,
                cost=cost,
            )
        )
        assigned_rows.add(original_row)
        assigned_cols.add(original_col)

    assignments.sort(key=lambda item: (item.row_index, item.col_index))

    return HungarianResult(
        assignments=assignments,
        total_cost=round(sum(item.cost for item in assignments), 6),
        row_count=row_count,
        col_count=col_count,
        assigned_count=len(assignments),
        unassigned_rows=[
            row_index for row_index in range(row_count) if row_index not in assigned_rows
        ],
        unassigned_cols=[
            col_index for col_index in range(col_count) if col_index not in assigned_cols
        ],
    )


def _hungarian_rows_leq_cols(cost_matrix: list[list[float]]) -> list[tuple[int, int]]:

    row_count = len(cost_matrix)
    col_count = len(cost_matrix[0])

    # 1-indexed arrays are used because this is the standard clean form.
    row_potential = [0.0] * (row_count + 1)
    col_potential = [0.0] * (col_count + 1)
    matching_row_for_col = [0] * (col_count + 1)
    previous_col = [0] * (col_count + 1)

    for current_row in range(1, row_count + 1):
        matching_row_for_col[0] = current_row

        min_slack = [float("inf")] * (col_count + 1)
        used_col = [False] * (col_count + 1)

        current_col = 0

        while True:
            used_col[current_col] = True
            matched_row = matching_row_for_col[current_col]

            delta = float("inf")
            next_col = 0

            for candidate_col in range(1, col_count + 1):
                if used_col[candidate_col]:
                    continue

                reduced_cost = (
                    cost_matrix[matched_row - 1][candidate_col - 1]
                    - row_potential[matched_row]
                    - col_potential[candidate_col]
                )

                if reduced_cost < min_slack[candidate_col] - _EPSILON:
                    min_slack[candidate_col] = reduced_cost
                    previous_col[candidate_col] = current_col

                # Deterministic tie behavior: keep the earliest candidate column.
                if min_slack[candidate_col] < delta - _EPSILON:
                    delta = min_slack[candidate_col]
                    next_col = candidate_col

            for col_index in range(0, col_count + 1):
                if used_col[col_index]:
                    row_potential[matching_row_for_col[col_index]] += delta
                    col_potential[col_index] -= delta
                else:
                    min_slack[col_index] -= delta

            current_col = next_col

            if matching_row_for_col[current_col] == 0:
                break

        # Augment the matching along the discovered path.
        while True:
            previous = previous_col[current_col]
            matching_row_for_col[current_col] = matching_row_for_col[previous]
            current_col = previous

            if current_col == 0:
                break

    assignments: list[tuple[int, int]] = []

    for col_index in range(1, col_count + 1):
        row_index = matching_row_for_col[col_index]
        if row_index != 0:
            assignments.append((row_index - 1, col_index - 1))

    assignments.sort(key=lambda pair: (pair[0], pair[1]))
    return assignments


def _validate_and_copy_cost_matrix(
    cost_matrix: Sequence[Sequence[float]],
) -> list[list[float]]:
    if len(cost_matrix) == 0:
        raise ValueError("cost_matrix must contain at least one row.")

    normalized: list[list[float]] = []
    expected_col_count: int | None = None

    for row_index, row in enumerate(cost_matrix):
        if len(row) == 0:
            raise ValueError(f"cost_matrix row {row_index} is empty.")

        copied_row = [float(value) for value in row]

        if expected_col_count is None:
            expected_col_count = len(copied_row)
        elif len(copied_row) != expected_col_count:
            raise ValueError("cost_matrix must be rectangular.")

        for col_index, value in enumerate(copied_row):
            if not isfinite(value):
                raise ValueError(
                    f"cost_matrix[{row_index}][{col_index}] must be finite."
                )

            if value < 0:
                raise ValueError(
                    f"cost_matrix[{row_index}][{col_index}] must be non-negative."
                )

        normalized.append(copied_row)

    return normalized


def _transpose(matrix: list[list[float]]) -> list[list[float]]:
    return [list(column) for column in zip(*matrix)]


__all__ = [
    "AssignmentPair",
    "HungarianResult",
    "solve_hungarian",
]