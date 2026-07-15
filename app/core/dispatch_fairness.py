# app/core/dispatch_fairness.py

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from math import sqrt

from app.core.dispatch_cost_matrix import DispatchSlot
from app.core.hungarian import AssignmentPair


@dataclass(frozen=True)
class DriverFairnessMetric:
    """
    Per-driver dispatch fairness details.

    Metrics describe the driver's projected state after the supplied
    assignments are applied.
    """

    driver_id: str

    current_load: int
    max_capacity: int

    available_slots: int
    assigned_orders: int

    projected_load: int
    remaining_capacity: int

    utilization_pct: float


@dataclass(frozen=True)
class DispatchFairnessResult:
    """
    Fairness metrics for one dispatch assignment result.

    Phase 10 behavior:

    Road-network infeasibility may result in fewer assignments than the
    dimensional maximum. Fairness is therefore calculated from the actual
    valid assignments returned by the assignment algorithm.
    """

    driver_metrics: list[DriverFairnessMetric]

    driver_count: int

    total_assigned_orders: int
    total_available_slots: int

    assigned_order_min: int
    assigned_order_max: int
    assigned_order_range: int
    assigned_order_mean: float
    assigned_order_std_dev: float

    projected_load_min: int
    projected_load_max: int
    projected_load_range: int
    projected_load_mean: float
    projected_load_std_dev: float

    max_utilization_pct: float
    min_utilization_pct: float

    fairness_score: float

    @property
    def assignment_utilization_pct(
        self,
    ) -> float:
        """
        Percentage of currently available capacity slots that were assigned.
        """

        if self.total_available_slots <= 0:
            return 0.0

        return round(
            (
                self.total_assigned_orders
                / self.total_available_slots
            )
            * 100.0,
            6,
        )


def calculate_dispatch_fairness(
    assignments: Sequence[AssignmentPair],
    slots: Sequence[DispatchSlot],
) -> DispatchFairnessResult:
    """
    Calculate deterministic dispatch fairness metrics.

    The function works for:

    Phase 9:
        unrestricted Haversine assignment.

    Phase 10:
        road-network assignment where unreachable pairs have already been
        removed through the Greedy/Hungarian `allowed_matrix` contract.

    Important:

    This function does not attempt to decide whether an assignment is
    reachable. That belongs to the assignment feasibility layer.

    Fairness only evaluates the assignments actually supplied.
    """

    normalized_slots = _validate_slots(
        slots
    )

    normalized_assignments = (
        _validate_assignments(
            assignments,
            normalized_slots,
        )
    )

    slot_by_row = {
        slot.row_index: slot
        for slot in normalized_slots
    }

    # ------------------------------------------------------------------
    # 1. Build one canonical state record per driver.
    # ------------------------------------------------------------------

    driver_state: dict[
        str,
        dict[str, int],
    ] = {}

    for slot in normalized_slots:
        state = driver_state.get(
            slot.driver_id
        )

        if state is None:
            driver_state[
                slot.driver_id
            ] = {
                "driver_index": (
                    slot.driver_index
                ),
                "current_load": (
                    slot.current_load
                ),
                "max_capacity": (
                    slot.max_capacity
                ),
                "available_slots": 1,
                "assigned_orders": 0,
            }

        else:
            state[
                "available_slots"
            ] += 1

    # ------------------------------------------------------------------
    # 2. Apply assignments to driver states.
    # ------------------------------------------------------------------

    for assignment in normalized_assignments:
        slot = slot_by_row[
            assignment.row_index
        ]

        driver_state[
            slot.driver_id
        ][
            "assigned_orders"
        ] += 1

    # ------------------------------------------------------------------
    # 3. Build per-driver fairness metrics.
    # ------------------------------------------------------------------

    driver_metrics: list[
        DriverFairnessMetric
    ] = []

    for driver_id in sorted(
        driver_state
    ):
        state = driver_state[
            driver_id
        ]

        current_load = state[
            "current_load"
        ]

        max_capacity = state[
            "max_capacity"
        ]

        available_slots = state[
            "available_slots"
        ]

        assigned_orders = state[
            "assigned_orders"
        ]

        projected_load = (
            current_load
            + assigned_orders
        )

        if projected_load > max_capacity:
            raise ValueError(
                "Assignments exceed driver capacity: "
                f"driver_id={driver_id!r}, "
                f"projected_load={projected_load}, "
                f"max_capacity={max_capacity}."
            )

        remaining_capacity = (
            max_capacity
            - projected_load
        )

        utilization_pct = round(
            (
                projected_load
                / max_capacity
            )
            * 100.0,
            6,
        )

        driver_metrics.append(
            DriverFairnessMetric(
                driver_id=driver_id,
                current_load=(
                    current_load
                ),
                max_capacity=(
                    max_capacity
                ),
                available_slots=(
                    available_slots
                ),
                assigned_orders=(
                    assigned_orders
                ),
                projected_load=(
                    projected_load
                ),
                remaining_capacity=(
                    remaining_capacity
                ),
                utilization_pct=(
                    utilization_pct
                ),
            )
        )

    # ------------------------------------------------------------------
    # 4. Aggregate fairness statistics.
    # ------------------------------------------------------------------

    assigned_counts = [
        metric.assigned_orders
        for metric in driver_metrics
    ]

    projected_loads = [
        metric.projected_load
        for metric in driver_metrics
    ]

    utilizations = [
        metric.utilization_pct
        for metric in driver_metrics
    ]

    assigned_min = min(
        assigned_counts
    )

    assigned_max = max(
        assigned_counts
    )

    projected_min = min(
        projected_loads
    )

    projected_max = max(
        projected_loads
    )

    assigned_mean = _mean(
        assigned_counts
    )

    projected_mean = _mean(
        projected_loads
    )

    assigned_std_dev = (
        _population_std_dev(
            assigned_counts
        )
    )

    projected_std_dev = (
        _population_std_dev(
            projected_loads
        )
    )

    # ------------------------------------------------------------------
    # Existing explainable Phase 9 fairness score.
    #
    # Lower projected-load spread produces a higher score.
    #
    # This remains a project metric rather than a scientific or legal
    # fairness definition.
    # ------------------------------------------------------------------

    fairness_score = round(
        max(
            0.0,
            min(
                100.0,
                100.0
                - (
                    projected_std_dev
                    * 25.0
                ),
            ),
        ),
        6,
    )

    return DispatchFairnessResult(
        driver_metrics=(
            driver_metrics
        ),
        driver_count=len(
            driver_metrics
        ),
        total_assigned_orders=sum(
            assigned_counts
        ),
        total_available_slots=sum(
            metric.available_slots
            for metric
            in driver_metrics
        ),
        assigned_order_min=(
            assigned_min
        ),
        assigned_order_max=(
            assigned_max
        ),
        assigned_order_range=(
            assigned_max
            - assigned_min
        ),
        assigned_order_mean=(
            assigned_mean
        ),
        assigned_order_std_dev=(
            assigned_std_dev
        ),
        projected_load_min=(
            projected_min
        ),
        projected_load_max=(
            projected_max
        ),
        projected_load_range=(
            projected_max
            - projected_min
        ),
        projected_load_mean=(
            projected_mean
        ),
        projected_load_std_dev=(
            projected_std_dev
        ),
        max_utilization_pct=max(
            utilizations
        ),
        min_utilization_pct=min(
            utilizations
        ),
        fairness_score=(
            fairness_score
        ),
    )


def _validate_slots(
    slots: Sequence[DispatchSlot],
) -> list[DispatchSlot]:
    """
    Validate dispatch-slot integrity.

    Phase 10 adds stronger checks because the same slot matrix is now used
    together with road-network feasibility restrictions.
    """

    if isinstance(
        slots,
        (
            str,
            bytes,
            bytearray,
        ),
    ):
        raise TypeError(
            "slots must be a sequence of DispatchSlot objects."
        )

    if len(
        slots
    ) == 0:
        raise ValueError(
            "slots must contain at least one dispatch slot."
        )

    normalized = list(
        slots
    )

    seen_rows: set[
        int
    ] = set()

    seen_driver_slots: set[
        tuple[
            str,
            int,
        ]
    ] = set()

    driver_metadata: dict[
        str,
        tuple[
            int,
            int,
            int,
        ]
    ] = {}

    slot_count_by_driver: dict[
        str,
        int,
    ] = {}

    for (
        index,
        slot,
    ) in enumerate(
        normalized
    ):
        if not isinstance(
            slot,
            DispatchSlot,
        ):
            raise TypeError(
                f"slots[{index}] must be DispatchSlot."
            )

        if (
            isinstance(
                slot.row_index,
                bool,
            )
            or not isinstance(
                slot.row_index,
                int,
            )
        ):
            raise ValueError(
                f"slots[{index}].row_index must be an integer."
            )

        if slot.row_index < 0:
            raise ValueError(
                f"slots[{index}].row_index must be non-negative."
            )

        if (
            slot.row_index
            in seen_rows
        ):
            raise ValueError(
                "duplicate slot row_index found: "
                f"{slot.row_index}"
            )

        seen_rows.add(
            slot.row_index
        )

        if (
            isinstance(
                slot.driver_index,
                bool,
            )
            or not isinstance(
                slot.driver_index,
                int,
            )
        ):
            raise ValueError(
                f"slots[{index}].driver_index must be an integer."
            )

        if slot.driver_index < 0:
            raise ValueError(
                f"slots[{index}].driver_index must be non-negative."
            )

        driver_id = (
            slot.driver_id.strip()
        )

        if not driver_id:
            raise ValueError(
                f"slots[{index}].driver_id must not be empty."
            )

        if (
            isinstance(
                slot.driver_slot_index,
                bool,
            )
            or not isinstance(
                slot.driver_slot_index,
                int,
            )
        ):
            raise ValueError(
                f"slots[{index}].driver_slot_index must be an integer."
            )

        if (
            slot.driver_slot_index
            < 0
        ):
            raise ValueError(
                f"slots[{index}].driver_slot_index must be non-negative."
            )

        _validate_non_negative_int(
            slot.current_load,
            f"slots[{index}].current_load",
        )

        _validate_positive_int(
            slot.max_capacity,
            f"slots[{index}].max_capacity",
        )

        if (
            slot.current_load
            > slot.max_capacity
        ):
            raise ValueError(
                f"slots[{index}].current_load must not exceed "
                "max_capacity."
            )

        available_capacity = (
            slot.max_capacity
            - slot.current_load
        )

        if (
            slot.driver_slot_index
            >= available_capacity
        ):
            raise ValueError(
                f"slots[{index}].driver_slot_index exceeds "
                "the driver's available capacity."
            )

        driver_slot_key = (
            driver_id,
            slot.driver_slot_index,
        )

        if (
            driver_slot_key
            in seen_driver_slots
        ):
            raise ValueError(
                "duplicate driver slot found: "
                f"driver_id={driver_id!r}, "
                f"driver_slot_index={slot.driver_slot_index}."
            )

        seen_driver_slots.add(
            driver_slot_key
        )

        metadata = (
            slot.driver_index,
            slot.current_load,
            slot.max_capacity,
        )

        previous_metadata = (
            driver_metadata.get(
                driver_id
            )
        )

        if (
            previous_metadata
            is None
        ):
            driver_metadata[
                driver_id
            ] = metadata

        elif (
            previous_metadata
            != metadata
        ):
            raise ValueError(
                "Inconsistent slot metadata for driver: "
                f"driver_id={driver_id!r}."
            )

        slot_count_by_driver[
            driver_id
        ] = (
            slot_count_by_driver.get(
                driver_id,
                0,
            )
            + 1
        )

    # Verify that malformed external slot collections cannot represent more
    # available rows than the driver's real remaining capacity.
    for (
        driver_id,
        slot_count,
    ) in slot_count_by_driver.items():
        (
            _,
            current_load,
            max_capacity,
        ) = driver_metadata[
            driver_id
        ]

        available_capacity = (
            max_capacity
            - current_load
        )

        if (
            slot_count
            > available_capacity
        ):
            raise ValueError(
                "Dispatch slot count exceeds available driver capacity: "
                f"driver_id={driver_id!r}, "
                f"slot_count={slot_count}, "
                f"available_capacity={available_capacity}."
            )

    return normalized


def _validate_assignments(
    assignments: Sequence[AssignmentPair],
    slots: Sequence[DispatchSlot],
) -> list[AssignmentPair]:
    """
    Validate assignments before fairness aggregation.

    Greedy and Hungarian both guarantee unique rows and columns, but this
    function validates the contract independently.
    """

    if isinstance(
        assignments,
        (
            str,
            bytes,
            bytearray,
        ),
    ):
        raise TypeError(
            "assignments must be a sequence of AssignmentPair objects."
        )

    normalized = list(
        assignments
    )

    valid_rows = {
        slot.row_index
        for slot in slots
    }

    seen_rows: set[
        int
    ] = set()

    seen_cols: set[
        int
    ] = set()

    for (
        index,
        assignment,
    ) in enumerate(
        normalized
    ):
        if not isinstance(
            assignment,
            AssignmentPair,
        ):
            raise TypeError(
                f"assignments[{index}] must be AssignmentPair."
            )

        if (
            isinstance(
                assignment.row_index,
                bool,
            )
            or not isinstance(
                assignment.row_index,
                int,
            )
        ):
            raise ValueError(
                f"assignments[{index}].row_index must be an integer."
            )

        if (
            assignment.row_index
            not in valid_rows
        ):
            raise ValueError(
                f"assignments[{index}].row_index does not exist "
                "in dispatch slots."
            )

        if (
            assignment.row_index
            in seen_rows
        ):
            raise ValueError(
                "duplicate assignment row_index found: "
                f"{assignment.row_index}"
            )

        if (
            isinstance(
                assignment.col_index,
                bool,
            )
            or not isinstance(
                assignment.col_index,
                int,
            )
        ):
            raise ValueError(
                f"assignments[{index}].col_index must be an integer."
            )

        if (
            assignment.col_index
            < 0
        ):
            raise ValueError(
                f"assignments[{index}].col_index must be non-negative."
            )

        if (
            assignment.col_index
            in seen_cols
        ):
            raise ValueError(
                "duplicate assignment col_index found: "
                f"{assignment.col_index}"
            )

        if isinstance(
            assignment.cost,
            bool,
        ):
            raise TypeError(
                f"assignments[{index}].cost must be numeric."
            )

        try:
            assignment_cost = float(
                assignment.cost
            )

        except (
            TypeError,
            ValueError,
            OverflowError,
        ) as exc:
            raise TypeError(
                f"assignments[{index}].cost must be numeric."
            ) from exc

        if not math.isfinite(
            assignment_cost
        ):
            raise ValueError(
                f"assignments[{index}].cost must be finite."
            )

        if assignment_cost < 0:
            raise ValueError(
                f"assignments[{index}].cost must be non-negative."
            )

        seen_rows.add(
            assignment.row_index
        )

        seen_cols.add(
            assignment.col_index
        )

    return normalized


def _mean(
    values: Sequence[int],
) -> float:
    if len(
        values
    ) == 0:
        return 0.0

    return round(
        sum(
            values
        )
        / len(
            values
        ),
        6,
    )


def _population_std_dev(
    values: Sequence[int],
) -> float:
    if len(
        values
    ) == 0:
        return 0.0

    mean = (
        sum(
            values
        )
        / len(
            values
        )
    )

    variance = (
        sum(
            (
                value
                - mean
            )
            ** 2
            for value
            in values
        )
        / len(
            values
        )
    )

    return round(
        sqrt(
            variance
        ),
        6,
    )


def _validate_non_negative_int(
    value: int,
    label: str,
) -> None:
    if (
        isinstance(
            value,
            bool,
        )
        or not isinstance(
            value,
            int,
        )
    ):
        raise ValueError(
            f"{label} must be an integer."
        )

    if value < 0:
        raise ValueError(
            f"{label} must be non-negative."
        )


def _validate_positive_int(
    value: int,
    label: str,
) -> None:
    if (
        isinstance(
            value,
            bool,
        )
        or not isinstance(
            value,
            int,
        )
    ):
        raise ValueError(
            f"{label} must be an integer."
        )

    if value <= 0:
        raise ValueError(
            f"{label} must be positive."
        )


__all__ = [
    "DispatchFairnessResult",
    "DriverFairnessMetric",
    "calculate_dispatch_fairness",
]