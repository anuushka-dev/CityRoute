# app/core/greedy_dispatch.py

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from app.core.hungarian import AssignmentPair


@dataclass(frozen=True)
class GreedyDispatchResult:
    """
    Result returned by `solve_greedy_dispatch`.

    Without an allowed matrix:

        assigned_count == min(row_count, col_count)

    With an allowed matrix:

        forbidden row-column pairs are never selected.

    Because this is a greedy baseline, it does not guarantee the maximum
    possible feasible assignment count when restrictions exist.
    """

    assignments: list[AssignmentPair]

    total_cost: float

    row_count: int
    col_count: int

    assigned_count: int

    unassigned_rows: list[int]
    unassigned_cols: list[int]

    @property
    def maximum_assignment_count(
        self,
    ) -> int:
        """
        Maximum possible assignment count based only on matrix dimensions.

        Feasibility restrictions may reduce the actual achievable count.
        """

        return min(
            self.row_count,
            self.col_count,
        )

    @property
    def is_complete(
        self,
    ) -> bool:
        """
        Return whether the greedy result reached the dimensional maximum.
        """

        return (
            self.assigned_count
            == self.maximum_assignment_count
        )


def solve_greedy_dispatch(
    cost_matrix: Sequence[
        Sequence[
            float
        ]
    ],
    *,
    allowed_matrix: Sequence[
        Sequence[
            bool
        ]
    ]
    | None = None,
) -> GreedyDispatchResult:
    """
    Solve the dispatch assignment problem using a deterministic greedy
    baseline.

    The algorithm:

        1. validates the rectangular cost matrix
        2. optionally validates a matching boolean feasibility matrix
        3. creates only valid candidate assignments
        4. sorts candidates by:

               cost
               row index
               column index

        5. repeatedly chooses the cheapest candidate whose row and column
           have not already been used

    Phase 9 behavior
    ----------------

    Existing callers remain valid:

        solve_greedy_dispatch(cost_matrix)

    Phase 10 behavior
    -----------------

    Road-network dispatch can use:

        solve_greedy_dispatch(
            cost_matrix,
            allowed_matrix=reachable_matrix,
        )

    so unreachable directed road pairs are never returned as assignments.

    Important
    ---------

    This is intentionally a greedy baseline.

    With restricted feasibility, it can produce fewer assignments than the
    maximum feasible matching because an early cheap choice may block later
    assignments.

    That is acceptable and useful for comparison against Hungarian.
    """

    normalized_costs = (
        _validate_and_copy_cost_matrix(
            cost_matrix
        )
    )

    row_count = len(
        normalized_costs
    )

    col_count = len(
        normalized_costs[
            0
        ]
    )

    normalized_allowed = (
        _validate_and_copy_allowed_matrix(
            allowed_matrix=allowed_matrix,
            row_count=row_count,
            col_count=col_count,
        )
    )

    target_assignment_count = min(
        row_count,
        col_count,
    )

    candidates: list[
        tuple[
            float,
            int,
            int,
        ]
    ] = []

    for (
        row_index,
        row,
    ) in enumerate(
        normalized_costs
    ):
        for (
            col_index,
            cost,
        ) in enumerate(
            row
        ):
            if (
                normalized_allowed
                is not None
                and not normalized_allowed[
                    row_index
                ][
                    col_index
                ]
            ):
                continue

            candidates.append(
                (
                    cost,
                    row_index,
                    col_index,
                )
            )

    # Deterministic order:
    #
    # 1. lowest cost
    # 2. lowest row index
    # 3. lowest column index
    candidates.sort(
        key=lambda item: (
            item[0],
            item[1],
            item[2],
        )
    )

    used_rows: set[
        int
    ] = set()

    used_cols: set[
        int
    ] = set()

    assignments: list[
        AssignmentPair
    ] = []

    for (
        cost,
        row_index,
        col_index,
    ) in candidates:
        if (
            len(
                assignments
            )
            >= target_assignment_count
        ):
            break

        if (
            row_index
            in used_rows
        ):
            continue

        if (
            col_index
            in used_cols
        ):
            continue

        assignments.append(
            AssignmentPair(
                row_index=row_index,
                col_index=col_index,
                cost=cost,
            )
        )

        used_rows.add(
            row_index
        )

        used_cols.add(
            col_index
        )

    assignments.sort(
        key=lambda item: (
            item.row_index,
            item.col_index,
        )
    )

    total_cost = round(
        sum(
            item.cost
            for item
            in assignments
        ),
        6,
    )

    return GreedyDispatchResult(
        assignments=assignments,
        total_cost=total_cost,
        row_count=row_count,
        col_count=col_count,
        assigned_count=len(
            assignments
        ),
        unassigned_rows=[
            row_index
            for row_index
            in range(
                row_count
            )
            if row_index
            not in used_rows
        ],
        unassigned_cols=[
            col_index
            for col_index
            in range(
                col_count
            )
            if col_index
            not in used_cols
        ],
    )


def _validate_and_copy_cost_matrix(
    cost_matrix: Sequence[
        Sequence[
            float
        ]
    ],
) -> list[
    list[
        float
    ]
]:
    """
    Validate and copy the input cost matrix.

    Requirements:

    - at least one row
    - at least one column
    - rectangular shape
    - numeric values
    - finite values
    - non-negative values
    """

    if isinstance(
        cost_matrix,
        (
            str,
            bytes,
            bytearray,
        ),
    ):
        raise TypeError(
            "cost_matrix must be a sequence of numeric rows."
        )

    if len(
        cost_matrix
    ) == 0:
        raise ValueError(
            "cost_matrix must contain at least one row."
        )

    normalized: list[
        list[
            float
        ]
    ] = []

    expected_col_count: (
        int | None
    ) = None

    for (
        row_index,
        row,
    ) in enumerate(
        cost_matrix
    ):
        if isinstance(
            row,
            (
                str,
                bytes,
                bytearray,
            ),
        ):
            raise TypeError(
                f"cost_matrix row {row_index} "
                "must be a numeric sequence."
            )

        if len(
            row
        ) == 0:
            raise ValueError(
                f"cost_matrix row {row_index} is empty."
            )

        copied_row: list[
            float
        ] = []

        for (
            col_index,
            raw_value,
        ) in enumerate(
            row
        ):
            if isinstance(
                raw_value,
                bool,
            ):
                raise TypeError(
                    "cost_matrix values must be numeric, not bool: "
                    f"row={row_index}, "
                    f"col={col_index}."
                )

            try:
                value = float(
                    raw_value
                )

            except (
                TypeError,
                ValueError,
                OverflowError,
            ) as exc:
                raise TypeError(
                    "cost_matrix contains a non-numeric value: "
                    f"row={row_index}, "
                    f"col={col_index}, "
                    f"value={raw_value!r}."
                ) from exc

            if not math.isfinite(
                value
            ):
                raise ValueError(
                    f"cost_matrix[{row_index}]"
                    f"[{col_index}] must be finite."
                )

            if value < 0:
                raise ValueError(
                    f"cost_matrix[{row_index}]"
                    f"[{col_index}] must be non-negative."
                )

            copied_row.append(
                value
            )

        if (
            expected_col_count
            is None
        ):
            expected_col_count = len(
                copied_row
            )

        elif (
            len(
                copied_row
            )
            != expected_col_count
        ):
            raise ValueError(
                "cost_matrix must be rectangular."
            )

        normalized.append(
            copied_row
        )

    return normalized


def _validate_and_copy_allowed_matrix(
    *,
    allowed_matrix: Sequence[
        Sequence[
            bool
        ]
    ]
    | None,
    row_count: int,
    col_count: int,
) -> list[
    list[
        bool
    ]
] | None:
    """
    Validate the optional Phase 10 feasibility matrix.

    Shape must exactly match `cost_matrix`.

    Semantics:

        True
            row-column assignment is valid

        False
            row-column assignment is forbidden
    """

    if allowed_matrix is None:
        return None

    if isinstance(
        allowed_matrix,
        (
            str,
            bytes,
            bytearray,
        ),
    ):
        raise TypeError(
            "allowed_matrix must be a sequence of boolean rows."
        )

    if len(
        allowed_matrix
    ) != row_count:
        raise ValueError(
            "allowed_matrix must have the same row count "
            "as cost_matrix."
        )

    normalized: list[
        list[
            bool
        ]
    ] = []

    for (
        row_index,
        row,
    ) in enumerate(
        allowed_matrix
    ):
        if isinstance(
            row,
            (
                str,
                bytes,
                bytearray,
            ),
        ):
            raise TypeError(
                f"allowed_matrix row {row_index} "
                "must be a boolean sequence."
            )

        if len(
            row
        ) != col_count:
            raise ValueError(
                "allowed_matrix must have the same shape "
                "as cost_matrix: "
                f"invalid row={row_index}."
            )

        normalized_row: list[
            bool
        ] = []

        for (
            col_index,
            value,
        ) in enumerate(
            row
        ):
            if not isinstance(
                value,
                bool,
            ):
                raise TypeError(
                    "allowed_matrix values must be bool: "
                    f"row={row_index}, "
                    f"col={col_index}, "
                    f"value={value!r}."
                )

            normalized_row.append(
                value
            )

        normalized.append(
            normalized_row
        )

    return normalized


__all__ = [
    "GreedyDispatchResult",
    "solve_greedy_dispatch",
]