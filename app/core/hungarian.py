# app/core/hungarian.py

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

_EPSILON = 1e-12


@dataclass(frozen=True)
class AssignmentPair:

    row_index: int
    col_index: int
    cost: float


@dataclass(frozen=True)
class HungarianResult:

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

        return min(
            self.row_count,
            self.col_count,
        )

    @property
    def is_complete(
        self,
    ) -> bool:

        return (
            self.assigned_count
            == self.maximum_assignment_count
        )


def solve_hungarian(
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
) -> HungarianResult:

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

    if normalized_allowed is None:
        optimization_matrix = (
            normalized_costs
        )

    else:
        optimization_matrix = (
            _build_forbidden_aware_cost_matrix(
                cost_matrix=normalized_costs,
                allowed_matrix=normalized_allowed,
            )
        )

    transposed = False

    working_matrix = (
        optimization_matrix
    )

    # The core implementation expects:
    #
    #     rows <= columns
    #
    # If rows > columns, solve the transposed problem and map assignments back
    # to the original matrix coordinates.
    if row_count > col_count:
        working_matrix = (
            _transpose(
                optimization_matrix
            )
        )

        transposed = True

    working_assignments = (
        _hungarian_rows_leq_cols(
            working_matrix
        )
    )

    assignments: list[
        AssignmentPair
    ] = []

    assigned_rows: set[
        int
    ] = set()

    assigned_cols: set[
        int
    ] = set()

    for (
        work_row,
        work_col,
    ) in working_assignments:
        if transposed:
            original_row = (
                work_col
            )

            original_col = (
                work_row
            )

        else:
            original_row = (
                work_row
            )

            original_col = (
                work_col
            )

        # --------------------------------------------------------------
        # Phase 10 forbidden-pair protection.
        #
        # If the optimizer had to consume a forbidden pair because no full
        # feasible matching exists, do not expose that pair as a valid
        # dispatch assignment.
        # --------------------------------------------------------------

        if (
            normalized_allowed
            is not None
            and not normalized_allowed[
                original_row
            ][
                original_col
            ]
        ):
            continue

        cost = (
            normalized_costs[
                original_row
            ][
                original_col
            ]
        )

        assignments.append(
            AssignmentPair(
                row_index=(
                    original_row
                ),
                col_index=(
                    original_col
                ),
                cost=cost,
            )
        )

        assigned_rows.add(
            original_row
        )

        assigned_cols.add(
            original_col
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

    return HungarianResult(
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
            not in assigned_rows
        ],
        unassigned_cols=[
            col_index
            for col_index
            in range(
                col_count
            )
            if col_index
            not in assigned_cols
        ],
    )


def _hungarian_rows_leq_cols(
    cost_matrix: list[
        list[
            float
        ]
    ],
) -> list[
    tuple[
        int,
        int,
    ]
]:

    row_count = len(
        cost_matrix
    )

    col_count = len(
        cost_matrix[
            0
        ]
    )

    # 1-indexed arrays are used because this is the standard clean form of
    # the potential-based Hungarian algorithm.
    row_potential = [
        0.0
    ] * (
        row_count
        + 1
    )

    col_potential = [
        0.0
    ] * (
        col_count
        + 1
    )

    matching_row_for_col = [
        0
    ] * (
        col_count
        + 1
    )

    previous_col = [
        0
    ] * (
        col_count
        + 1
    )

    for current_row in range(
        1,
        row_count + 1,
    ):
        matching_row_for_col[
            0
        ] = current_row

        min_slack = [
            math.inf
        ] * (
            col_count
            + 1
        )

        used_col = [
            False
        ] * (
            col_count
            + 1
        )

        current_col = 0

        while True:
            used_col[
                current_col
            ] = True

            matched_row = (
                matching_row_for_col[
                    current_col
                ]
            )

            delta = (
                math.inf
            )

            next_col = 0

            for candidate_col in range(
                1,
                col_count + 1,
            ):
                if used_col[
                    candidate_col
                ]:
                    continue

                reduced_cost = (
                    cost_matrix[
                        matched_row - 1
                    ][
                        candidate_col - 1
                    ]
                    - row_potential[
                        matched_row
                    ]
                    - col_potential[
                        candidate_col
                    ]
                )

                if (
                    reduced_cost
                    < min_slack[
                        candidate_col
                    ]
                    - _EPSILON
                ):
                    min_slack[
                        candidate_col
                    ] = (
                        reduced_cost
                    )

                    previous_col[
                        candidate_col
                    ] = (
                        current_col
                    )

                # Deterministic tie behavior:
                #
                # because candidates are visited from low to high column
                # index, equal slacks retain the earliest candidate.
                if (
                    min_slack[
                        candidate_col
                    ]
                    < delta
                    - _EPSILON
                ):
                    delta = (
                        min_slack[
                            candidate_col
                        ]
                    )

                    next_col = (
                        candidate_col
                    )

            if (
                not math.isfinite(
                    delta
                )
                or next_col == 0
            ):
                raise RuntimeError(
                    "Hungarian algorithm could not find "
                    "a valid augmenting column."
                )

            for col_index in range(
                0,
                col_count + 1,
            ):
                if used_col[
                    col_index
                ]:
                    row_potential[
                        matching_row_for_col[
                            col_index
                        ]
                    ] += delta

                    col_potential[
                        col_index
                    ] -= delta

                else:
                    min_slack[
                        col_index
                    ] -= delta

            current_col = (
                next_col
            )

            if (
                matching_row_for_col[
                    current_col
                ]
                == 0
            ):
                break

        # Augment the matching along the discovered alternating path.
        while True:
            previous = (
                previous_col[
                    current_col
                ]
            )

            matching_row_for_col[
                current_col
            ] = (
                matching_row_for_col[
                    previous
                ]
            )

            current_col = (
                previous
            )

            if current_col == 0:
                break

    assignments: list[
        tuple[
            int,
            int,
        ]
    ] = []

    for col_index in range(
        1,
        col_count + 1,
    ):
        row_index = (
            matching_row_for_col[
                col_index
            ]
        )

        if row_index != 0:
            assignments.append(
                (
                    row_index - 1,
                    col_index - 1,
                )
            )

    assignments.sort(
        key=lambda pair: (
            pair[0],
            pair[1],
        )
    )

    return assignments


def _build_forbidden_aware_cost_matrix(
    *,
    cost_matrix: list[
        list[
            float
        ]
    ],
    allowed_matrix: list[
        list[
            bool
        ]
    ],
) -> list[
    list[
        float
    ]
]:

    row_count = len(
        cost_matrix
    )

    col_count = len(
        cost_matrix[
            0
        ]
    )

    assignment_count = min(
        row_count,
        col_count,
    )

    allowed_costs = [
        cost_matrix[
            row_index
        ][
            col_index
        ]
        for row_index
        in range(
            row_count
        )
        for col_index
        in range(
            col_count
        )
        if allowed_matrix[
            row_index
        ][
            col_index
        ]
    ]

    maximum_allowed_cost = (
        max(
            allowed_costs
        )
        if allowed_costs
        else 0.0
    )

    forbidden_penalty = (
        float(
            assignment_count
            + 1
        )
        * (
            maximum_allowed_cost
            + 1.0
        )
    )

    if not math.isfinite(
        forbidden_penalty
    ):
        raise ValueError(
            "Could not construct a finite forbidden-assignment penalty."
        )

    return [
        [
            cost_matrix[
                row_index
            ][
                col_index
            ]
            if allowed_matrix[
                row_index
            ][
                col_index
            ]
            else forbidden_penalty
            for col_index
            in range(
                col_count
            )
        ]
        for row_index
        in range(
            row_count
        )
    ]


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
                f"cost_matrix row {row_index} must be a numeric sequence."
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
                    f"row={row_index}, col={col_index}."
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
            "allowed_matrix must have the same row count as cost_matrix."
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
        if len(
            row
        ) != col_count:
            raise ValueError(
                "allowed_matrix must have the same shape as cost_matrix: "
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


def _transpose(
    matrix: list[
        list[
            float
        ]
    ],
) -> list[
    list[
        float
    ]
]:
    return [
        list(
            column
        )
        for column
        in zip(
            *matrix
        )
    ]


def _transpose_bool(
    matrix: list[
        list[
            bool
        ]
    ],
) -> list[
    list[
        bool
    ]
]:
    return [
        list(
            column
        )
        for column
        in zip(
            *matrix
        )
    ]


__all__ = [
    "AssignmentPair",
    "HungarianResult",
    "solve_hungarian",
]