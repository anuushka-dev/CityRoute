# app/core/greedy_dispatch.py

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite

from app.core.hungarian import AssignmentPair


@dataclass(frozen=True)
class GreedyDispatchResult:
    """Result returned by solve_greedy_dispatch."""

    assignments: list[AssignmentPair]
    total_cost: float
    row_count: int
    col_count: int
    assigned_count: int
    unassigned_rows: list[int]
    unassigned_cols: list[int]


def solve_greedy_dispatch(cost_matrix: Sequence[Sequence[float]]) -> GreedyDispatchResult:

    normalized = _validate_and_copy_cost_matrix(cost_matrix)

    row_count = len(normalized)
    col_count = len(normalized[0])
    target_assignment_count = min(row_count, col_count)

    candidates: list[tuple[float, int, int]] = []

    for row_index, row in enumerate(normalized):
        for col_index, cost in enumerate(row):
            candidates.append((cost, row_index, col_index))

    candidates.sort(key=lambda item: (item[0], item[1], item[2]))

    used_rows: set[int] = set()
    used_cols: set[int] = set()
    assignments: list[AssignmentPair] = []

    for cost, row_index, col_index in candidates:
        if len(assignments) >= target_assignment_count:
            break

        if row_index in used_rows:
            continue

        if col_index in used_cols:
            continue

        assignments.append(
            AssignmentPair(
                row_index=row_index,
                col_index=col_index,
                cost=cost,
            )
        )
        used_rows.add(row_index)
        used_cols.add(col_index)

    assignments.sort(key=lambda item: (item.row_index, item.col_index))

    return GreedyDispatchResult(
        assignments=assignments,
        total_cost=round(sum(item.cost for item in assignments), 6),
        row_count=row_count,
        col_count=col_count,
        assigned_count=len(assignments),
        unassigned_rows=[
            row_index for row_index in range(row_count) if row_index not in used_rows
        ],
        unassigned_cols=[
            col_index for col_index in range(col_count) if col_index not in used_cols
        ],
    )


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


__all__ = [
    "GreedyDispatchResult",
    "solve_greedy_dispatch",
]