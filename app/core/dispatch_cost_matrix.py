# app/core/dispatch_cost_matrix.py

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class DispatchDriver:
    """Driver input used by the dispatch cost-matrix builder."""

    driver_id: str
    lat: float
    lon: float
    current_load: int = 0
    max_capacity: int = 1

    @property
    def capacity(self) -> int:
        """Compatibility alias for earlier dispatch distance services."""

        return self.max_capacity

    @property
    def available_capacity(self) -> int:
        """Number of currently available assignment slots."""

        return max(
            0,
            self.max_capacity - self.current_load,
        )

    @property
    def has_available_capacity(self) -> bool:
        return self.available_capacity > 0


@dataclass(frozen=True)
class DispatchOrder:
    """Order input used by the dispatch cost-matrix builder."""

    order_id: str
    pickup_lat: float
    pickup_lon: float

    @property
    def lat(self) -> float:
        """Compatibility alias for earlier dispatch distance services."""

        return self.pickup_lat

    @property
    def lon(self) -> float:
        """Compatibility alias for earlier dispatch distance services."""

        return self.pickup_lon


@dataclass(frozen=True)
class DispatchSlot:
    """
    One currently available capacity slot belonging to a driver.

    Multiple rows may therefore refer to the same physical driver.
    """

    row_index: int
    driver_index: int
    driver_id: str
    driver_slot_index: int
    current_load: int
    max_capacity: int


@dataclass(frozen=True)
class DispatchCostBreakdown:
    """Detailed cost explanation for one slot-to-order matrix cell."""

    row_index: int
    col_index: int

    driver_id: str
    order_id: str

    distance_m: float
    load_penalty_m: float
    slot_penalty_m: float

    total_cost: float

    # Phase 10:
    # False means the road pair is not a valid assignment even though the
    # cost matrix still contains a finite replacement cost.
    allowed: bool = True


@dataclass(frozen=True)
class DispatchCostMatrixResult:
    """
    Output consumed by Greedy and Hungarian assignment algorithms.

    `cost_matrix`:
        capacity-slot x order finite numeric matrix.

    `allowed_matrix`:
        same shape as `cost_matrix`.

        True:
            assignment is valid.

        False:
            assignment is forbidden, for example because no directed road
            path exists between the driver and the order.

    Phase 9 callers that do not supply an `allowed_lookup` receive an
    all-True feasibility matrix.
    """

    cost_matrix: list[list[float]]

    slots: list[DispatchSlot]
    orders: list[DispatchOrder]

    breakdowns: list[DispatchCostBreakdown]

    row_count: int
    col_count: int

    driver_count: int
    order_count: int

    available_slot_count: int

    # Preserved Phase 9 dimensional-capacity metric.
    unassignable_order_count: int

    unused_slot_count: int

    # Phase 10 slot x order feasibility matrix.
    allowed_matrix: list[list[bool]] = field(
        default_factory=list
    )

    allowed_pair_count: int = 0
    forbidden_pair_count: int = 0

    # Number of orders with no valid slot at all.
    infeasible_order_count: int = 0

    infeasible_order_indices: list[int] = field(
        default_factory=list
    )

    @property
    def pair_count(self) -> int:
        return self.row_count * self.col_count

    @property
    def all_pairs_allowed(self) -> bool:
        return self.forbidden_pair_count == 0


DistanceLookup = Callable[
    [DispatchDriver, DispatchOrder],
    float,
]

AllowedLookup = Callable[
    [DispatchDriver, DispatchOrder],
    bool,
]


def build_dispatch_cost_matrix(
    drivers: Sequence[DispatchDriver],
    orders: Sequence[DispatchOrder],
    distance_lookup: DistanceLookup,
    *,
    load_penalty_m: float = 0.0,
    slot_penalty_m: float = 0.0,
    allowed_lookup: AllowedLookup | None = None,
) -> DispatchCostMatrixResult:
    """
    Build the capacity-slot x order dispatch optimization matrix.

    Phase 9
    -------
    Existing usage remains valid:

        build_dispatch_cost_matrix(
            drivers,
            orders,
            distance_lookup,
        )

    Every pair is considered allowed.

    Phase 10
    --------
    Real road-network dispatch can additionally supply:

        allowed_lookup(driver, order) -> bool

    The driver-level reachability result is automatically expanded across
    every available capacity slot belonging to that driver.

    Example:

        Driver A has 3 available slots.
        Driver A -> Order X is unreachable.

    Then all three slot rows for Driver A will contain:

        allowed_matrix[row][order_x] = False

    while the numeric cost matrix still contains a finite replacement cost.
    """

    normalized_drivers = _validate_drivers(
        drivers
    )

    normalized_orders = _validate_orders(
        orders
    )

    if not callable(
        distance_lookup
    ):
        raise TypeError(
            "distance_lookup must be callable."
        )

    if (
        allowed_lookup is not None
        and not callable(
            allowed_lookup
        )
    ):
        raise TypeError(
            "allowed_lookup must be callable or None."
        )

    _validate_penalty(
        load_penalty_m,
        "load_penalty_m",
    )

    _validate_penalty(
        slot_penalty_m,
        "slot_penalty_m",
    )

    slots = _expand_driver_slots(
        normalized_drivers
    )

    if not slots:
        raise ValueError(
            "at least one driver must have available capacity."
        )

    if not normalized_orders:
        raise ValueError(
            "at least one order is required."
        )

    cost_matrix: list[
        list[float]
    ] = []

    allowed_matrix: list[
        list[bool]
    ] = []

    breakdowns: list[
        DispatchCostBreakdown
    ] = []

    allowed_pair_count = 0
    forbidden_pair_count = 0

    for slot in slots:
        driver = normalized_drivers[
            slot.driver_index
        ]

        cost_row: list[
            float
        ] = []

        allowed_row: list[
            bool
        ] = []

        load_penalty_value = (
            float(
                driver.current_load
            )
            * float(
                load_penalty_m
            )
        )

        slot_penalty_value = (
            float(
                slot.driver_slot_index
            )
            * float(
                slot_penalty_m
            )
        )

        for (
            col_index,
            order,
        ) in enumerate(
            normalized_orders
        ):
            raw_distance = distance_lookup(
                driver,
                order,
            )

            distance_m = _normalize_distance(
                raw_distance,
                row_index=slot.row_index,
                col_index=col_index,
            )

            allowed = _resolve_allowed_pair(
                driver=driver,
                order=order,
                allowed_lookup=allowed_lookup,
                row_index=slot.row_index,
                col_index=col_index,
            )

            total_cost = round(
                distance_m
                + load_penalty_value
                + slot_penalty_value,
                6,
            )

            _validate_total_cost(
                total_cost=total_cost,
                row_index=slot.row_index,
                col_index=col_index,
            )

            cost_row.append(
                total_cost
            )

            allowed_row.append(
                allowed
            )

            if allowed:
                allowed_pair_count += 1
            else:
                forbidden_pair_count += 1

            breakdowns.append(
                DispatchCostBreakdown(
                    row_index=(
                        slot.row_index
                    ),
                    col_index=(
                        col_index
                    ),
                    driver_id=(
                        driver.driver_id
                    ),
                    order_id=(
                        order.order_id
                    ),
                    distance_m=round(
                        distance_m,
                        6,
                    ),
                    load_penalty_m=round(
                        load_penalty_value,
                        6,
                    ),
                    slot_penalty_m=round(
                        slot_penalty_value,
                        6,
                    ),
                    total_cost=(
                        total_cost
                    ),
                    allowed=(
                        allowed
                    ),
                )
            )

        cost_matrix.append(
            cost_row
        )

        allowed_matrix.append(
            allowed_row
        )

    available_slot_count = len(
        slots
    )

    order_count = len(
        normalized_orders
    )

    infeasible_order_indices = (
        _find_infeasible_order_indices(
            allowed_matrix
        )
    )

    return DispatchCostMatrixResult(
        cost_matrix=cost_matrix,
        slots=slots,
        orders=normalized_orders,
        breakdowns=breakdowns,
        row_count=len(
            cost_matrix
        ),
        col_count=len(
            cost_matrix[
                0
            ]
        ),
        driver_count=len(
            normalized_drivers
        ),
        order_count=order_count,
        available_slot_count=(
            available_slot_count
        ),
        # Preserve the original Phase 9 meaning:
        # orders that cannot be assigned due only to insufficient capacity.
        unassignable_order_count=max(
            0,
            order_count
            - available_slot_count,
        ),
        unused_slot_count=max(
            0,
            available_slot_count
            - order_count,
        ),
        allowed_matrix=(
            allowed_matrix
        ),
        allowed_pair_count=(
            allowed_pair_count
        ),
        forbidden_pair_count=(
            forbidden_pair_count
        ),
        infeasible_order_count=len(
            infeasible_order_indices
        ),
        infeasible_order_indices=(
            infeasible_order_indices
        ),
    )


def haversine_distance_lookup(
    driver: DispatchDriver,
    order: DispatchOrder,
) -> float:
    """
    Straight-line geographic distance lookup.

    Phase 9:
        primary dispatch proof path.

    Phase 10:
        retained as the fast approximation and comparison baseline.
    """

    return haversine_m(
        driver.lat,
        driver.lon,
        order.pickup_lat,
        order.pickup_lon,
    )


def haversine_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Calculate Haversine distance in meters."""

    normalized_lat1 = float(
        lat1
    )
    normalized_lon1 = float(
        lon1
    )
    normalized_lat2 = float(
        lat2
    )
    normalized_lon2 = float(
        lon2
    )

    _validate_lat_lon(
        normalized_lat1,
        normalized_lon1,
        "first_coordinate",
    )

    _validate_lat_lon(
        normalized_lat2,
        normalized_lon2,
        "second_coordinate",
    )

    lat1_rad = radians(
        normalized_lat1
    )

    lon1_rad = radians(
        normalized_lon1
    )

    lat2_rad = radians(
        normalized_lat2
    )

    lon2_rad = radians(
        normalized_lon2
    )

    dlat = (
        lat2_rad
        - lat1_rad
    )

    dlon = (
        lon2_rad
        - lon1_rad
    )

    haversine_a = (
        sin(
            dlat / 2.0
        )
        ** 2
        + cos(
            lat1_rad
        )
        * cos(
            lat2_rad
        )
        * sin(
            dlon / 2.0
        )
        ** 2
    )

    haversine_a = min(
        1.0,
        max(
            0.0,
            haversine_a,
        ),
    )

    haversine_c = (
        2.0
        * asin(
            sqrt(
                haversine_a
            )
        )
    )

    return round(
        EARTH_RADIUS_M
        * haversine_c,
        6,
    )


def _expand_driver_slots(
    drivers: Sequence[
        DispatchDriver
    ],
) -> list[
    DispatchSlot
]:
    """
    Expand driver capacity into independent assignment rows.

    Example:

        driver max_capacity = 4
        current_load = 1

    creates:

        3 available slot rows
    """

    slots: list[
        DispatchSlot
    ] = []

    for (
        driver_index,
        driver,
    ) in enumerate(
        drivers
    ):
        for driver_slot_index in range(
            driver.available_capacity
        ):
            slots.append(
                DispatchSlot(
                    row_index=len(
                        slots
                    ),
                    driver_index=(
                        driver_index
                    ),
                    driver_id=(
                        driver.driver_id
                    ),
                    driver_slot_index=(
                        driver_slot_index
                    ),
                    current_load=(
                        driver.current_load
                    ),
                    max_capacity=(
                        driver.max_capacity
                    ),
                )
            )

    return slots


def _resolve_allowed_pair(
    *,
    driver: DispatchDriver,
    order: DispatchOrder,
    allowed_lookup: AllowedLookup | None,
    row_index: int,
    col_index: int,
) -> bool:
    """
    Resolve whether one driver-to-order pair is a valid assignment.

    When no lookup is supplied, preserve Phase 9 behavior and allow all pairs.
    """

    if allowed_lookup is None:
        return True

    result = allowed_lookup(
        driver,
        order,
    )

    if not isinstance(
        result,
        bool,
    ):
        raise TypeError(
            "allowed_lookup must return bool for "
            f"row={row_index}, "
            f"col={col_index}; "
            f"received {type(result).__name__}."
        )

    return result


def _find_infeasible_order_indices(
    allowed_matrix: Sequence[
        Sequence[
            bool
        ]
    ],
) -> list[int]:
    """
    Return orders that cannot be reached from any available driver slot.

    This is not the same as solving the full maximum matching problem.
    It only identifies columns with zero valid candidate rows.
    """

    if not allowed_matrix:
        return []

    col_count = len(
        allowed_matrix[
            0
        ]
    )

    infeasible: list[
        int
    ] = []

    for col_index in range(
        col_count
    ):
        if not any(
            row[
                col_index
            ]
            for row
            in allowed_matrix
        ):
            infeasible.append(
                col_index
            )

    return infeasible


def _validate_drivers(
    drivers: Sequence[
        DispatchDriver
    ],
) -> list[
    DispatchDriver
]:
    if len(
        drivers
    ) == 0:
        raise ValueError(
            "at least one driver is required."
        )

    normalized: list[
        DispatchDriver
    ] = []

    for (
        index,
        driver,
    ) in enumerate(
        drivers
    ):
        if not isinstance(
            driver,
            DispatchDriver,
        ):
            raise TypeError(
                f"drivers[{index}] must be DispatchDriver."
            )

        if not driver.driver_id.strip():
            raise ValueError(
                f"drivers[{index}].driver_id must not be empty."
            )

        _validate_lat_lon(
            driver.lat,
            driver.lon,
            f"drivers[{index}]",
        )

        _validate_non_negative_int(
            driver.current_load,
            f"drivers[{index}].current_load",
        )

        _validate_non_negative_int(
            driver.max_capacity,
            f"drivers[{index}].max_capacity",
        )

        if driver.max_capacity == 0:
            raise ValueError(
                f"drivers[{index}].max_capacity must be at least 1."
            )

        if (
            driver.current_load
            > driver.max_capacity
        ):
            raise ValueError(
                f"drivers[{index}].current_load must not "
                "exceed max_capacity."
            )

        normalized.append(
            DispatchDriver(
                driver_id=(
                    driver.driver_id.strip()
                ),
                lat=float(
                    driver.lat
                ),
                lon=float(
                    driver.lon
                ),
                current_load=int(
                    driver.current_load
                ),
                max_capacity=int(
                    driver.max_capacity
                ),
            )
        )

    return normalized


def _validate_orders(
    orders: Sequence[
        DispatchOrder
    ],
) -> list[
    DispatchOrder
]:
    normalized: list[
        DispatchOrder
    ] = []

    for (
        index,
        order,
    ) in enumerate(
        orders
    ):
        if not isinstance(
            order,
            DispatchOrder,
        ):
            raise TypeError(
                f"orders[{index}] must be DispatchOrder."
            )

        if not order.order_id.strip():
            raise ValueError(
                f"orders[{index}].order_id must not be empty."
            )

        _validate_lat_lon(
            order.pickup_lat,
            order.pickup_lon,
            f"orders[{index}]",
        )

        normalized.append(
            DispatchOrder(
                order_id=(
                    order.order_id.strip()
                ),
                pickup_lat=float(
                    order.pickup_lat
                ),
                pickup_lon=float(
                    order.pickup_lon
                ),
            )
        )

    return normalized


def _validate_lat_lon(
    lat: float,
    lon: float,
    label: str,
) -> None:
    if (
        isinstance(
            lat,
            bool,
        )
        or isinstance(
            lon,
            bool,
        )
    ):
        raise TypeError(
            f"{label} latitude and longitude must be numeric."
        )

    try:
        lat_value = float(
            lat
        )

        lon_value = float(
            lon
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as exc:
        raise TypeError(
            f"{label} latitude and longitude must be numeric."
        ) from exc

    if not math.isfinite(
        lat_value
    ):
        raise ValueError(
            f"{label}.lat must be finite."
        )

    if not math.isfinite(
        lon_value
    ):
        raise ValueError(
            f"{label}.lon must be finite."
        )

    if not (
        -90.0
        <= lat_value
        <= 90.0
    ):
        raise ValueError(
            f"{label}.lat must be between -90 and 90."
        )

    if not (
        -180.0
        <= lon_value
        <= 180.0
    ):
        raise ValueError(
            f"{label}.lon must be between -180 and 180."
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


def _validate_penalty(
    value: float,
    label: str,
) -> None:
    if isinstance(
        value,
        bool,
    ):
        raise TypeError(
            f"{label} must be numeric."
        )

    try:
        value_float = float(
            value
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as exc:
        raise TypeError(
            f"{label} must be numeric."
        ) from exc

    if not math.isfinite(
        value_float
    ):
        raise ValueError(
            f"{label} must be finite."
        )

    if value_float < 0:
        raise ValueError(
            f"{label} must be non-negative."
        )


def _normalize_distance(
    distance_m: float,
    *,
    row_index: int,
    col_index: int,
) -> float:
    if isinstance(
        distance_m,
        bool,
    ):
        raise TypeError(
            "distance_lookup returned bool instead of numeric distance for "
            f"row={row_index}, col={col_index}."
        )

    try:
        normalized = float(
            distance_m
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as exc:
        raise TypeError(
            "distance_lookup returned a non-numeric distance for "
            f"row={row_index}, col={col_index}."
        ) from exc

    if not math.isfinite(
        normalized
    ):
        raise ValueError(
            "distance_lookup returned non-finite distance for "
            f"row={row_index}, col={col_index}."
        )

    if normalized < 0:
        raise ValueError(
            "distance_lookup returned negative distance for "
            f"row={row_index}, col={col_index}."
        )

    return normalized


def _validate_total_cost(
    *,
    total_cost: float,
    row_index: int,
    col_index: int,
) -> None:
    if not math.isfinite(
        total_cost
    ):
        raise ValueError(
            "dispatch total cost became non-finite for "
            f"row={row_index}, col={col_index}."
        )

    if total_cost < 0:
        raise ValueError(
            "dispatch total cost became negative for "
            f"row={row_index}, col={col_index}."
        )


__all__ = [
    "AllowedLookup",
    "DispatchCostBreakdown",
    "DispatchCostMatrixResult",
    "DispatchDriver",
    "DispatchOrder",
    "DispatchSlot",
    "DistanceLookup",
    "build_dispatch_cost_matrix",
    "haversine_distance_lookup",
    "haversine_m",
]