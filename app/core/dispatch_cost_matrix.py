# app/core/dispatch_cost_matrix.py

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import asin, cos, isfinite, radians, sin, sqrt

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
        """Compatibility alias for Phase 9.1 cache/distance services."""

        return self.max_capacity

    @property
    def available_capacity(self) -> int:
        """Number of currently available assignment slots for this driver."""

        return max(0, self.max_capacity - self.current_load)

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
        """Compatibility alias for Phase 9.1 cache/distance services."""

        return self.pickup_lat

    @property
    def lon(self) -> float:
        """Compatibility alias for Phase 9.1 cache/distance services."""

        return self.pickup_lon


@dataclass(frozen=True)
class DispatchSlot:
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


@dataclass(frozen=True)
class DispatchCostMatrixResult:
    """Output consumed by greedy dispatch and Hungarian assignment."""

    cost_matrix: list[list[float]]
    slots: list[DispatchSlot]
    orders: list[DispatchOrder]
    breakdowns: list[DispatchCostBreakdown]
    row_count: int
    col_count: int
    driver_count: int
    order_count: int
    available_slot_count: int
    unassignable_order_count: int
    unused_slot_count: int


DistanceLookup = Callable[[DispatchDriver, DispatchOrder], float]


def build_dispatch_cost_matrix(
    drivers: Sequence[DispatchDriver],
    orders: Sequence[DispatchOrder],
    distance_lookup: DistanceLookup,
    *,
    load_penalty_m: float = 0.0,
    slot_penalty_m: float = 0.0,
) -> DispatchCostMatrixResult:
    normalized_drivers = _validate_drivers(drivers)
    normalized_orders = _validate_orders(orders)

    _validate_penalty(load_penalty_m, "load_penalty_m")
    _validate_penalty(slot_penalty_m, "slot_penalty_m")

    slots = _expand_driver_slots(normalized_drivers)

    if not slots:
        raise ValueError("at least one driver must have available capacity.")

    if not normalized_orders:
        raise ValueError("at least one order is required.")

    cost_matrix: list[list[float]] = []
    breakdowns: list[DispatchCostBreakdown] = []

    for slot in slots:
        driver = normalized_drivers[slot.driver_index]
        row: list[float] = []

        for col_index, order in enumerate(normalized_orders):
            distance_m = float(distance_lookup(driver, order))
            _validate_distance(distance_m, slot.row_index, col_index)

            load_penalty_value = float(driver.current_load) * float(load_penalty_m)
            slot_penalty_value = float(slot.driver_slot_index) * float(slot_penalty_m)
            total_cost = round(
                distance_m + load_penalty_value + slot_penalty_value,
                6,
            )

            row.append(total_cost)
            breakdowns.append(
                DispatchCostBreakdown(
                    row_index=slot.row_index,
                    col_index=col_index,
                    driver_id=driver.driver_id,
                    order_id=order.order_id,
                    distance_m=round(distance_m, 6),
                    load_penalty_m=round(load_penalty_value, 6),
                    slot_penalty_m=round(slot_penalty_value, 6),
                    total_cost=total_cost,
                )
            )

        cost_matrix.append(row)

    available_slot_count = len(slots)
    order_count = len(normalized_orders)

    return DispatchCostMatrixResult(
        cost_matrix=cost_matrix,
        slots=slots,
        orders=normalized_orders,
        breakdowns=breakdowns,
        row_count=len(cost_matrix),
        col_count=len(cost_matrix[0]),
        driver_count=len(normalized_drivers),
        order_count=order_count,
        available_slot_count=available_slot_count,
        unassignable_order_count=max(0, order_count - available_slot_count),
        unused_slot_count=max(0, available_slot_count - order_count),
    )


def haversine_distance_lookup(
    driver: DispatchDriver,
    order: DispatchOrder,
) -> float:
    """Straight-line fallback distance lookup.

    Phase 9 used this as the primary proof path.
    Phase 9.1 keeps this mode but adds source_dijkstra integration separately.
    """

    return haversine_m(
        driver.lat,
        driver.lon,
        order.pickup_lat,
        order.pickup_lon,
    )


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_rad = radians(lat1)
    lon1_rad = radians(lon1)
    lat2_rad = radians(lat2)
    lon2_rad = radians(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = (
        sin(dlat / 2) ** 2
        + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2) ** 2
    )
    c = 2 * asin(sqrt(a))

    return round(EARTH_RADIUS_M * c, 6)


def _expand_driver_slots(drivers: Sequence[DispatchDriver]) -> list[DispatchSlot]:
    slots: list[DispatchSlot] = []

    for driver_index, driver in enumerate(drivers):
        for driver_slot_index in range(driver.available_capacity):
            slots.append(
                DispatchSlot(
                    row_index=len(slots),
                    driver_index=driver_index,
                    driver_id=driver.driver_id,
                    driver_slot_index=driver_slot_index,
                    current_load=driver.current_load,
                    max_capacity=driver.max_capacity,
                )
            )

    return slots


def _validate_drivers(drivers: Sequence[DispatchDriver]) -> list[DispatchDriver]:
    if len(drivers) == 0:
        raise ValueError("at least one driver is required.")

    normalized: list[DispatchDriver] = []

    for index, driver in enumerate(drivers):
        if not driver.driver_id.strip():
            raise ValueError(f"drivers[{index}].driver_id must not be empty.")

        _validate_lat_lon(driver.lat, driver.lon, f"drivers[{index}]")
        _validate_non_negative_int(driver.current_load, f"drivers[{index}].current_load")
        _validate_non_negative_int(driver.max_capacity, f"drivers[{index}].max_capacity")

        if driver.max_capacity == 0:
            raise ValueError(f"drivers[{index}].max_capacity must be at least 1.")

        if driver.current_load > driver.max_capacity:
            raise ValueError(
                f"drivers[{index}].current_load must not exceed max_capacity."
            )

        normalized.append(
            DispatchDriver(
                driver_id=driver.driver_id.strip(),
                lat=float(driver.lat),
                lon=float(driver.lon),
                current_load=int(driver.current_load),
                max_capacity=int(driver.max_capacity),
            )
        )

    return normalized


def _validate_orders(orders: Sequence[DispatchOrder]) -> list[DispatchOrder]:
    normalized: list[DispatchOrder] = []

    for index, order in enumerate(orders):
        if not order.order_id.strip():
            raise ValueError(f"orders[{index}].order_id must not be empty.")

        _validate_lat_lon(
            order.pickup_lat,
            order.pickup_lon,
            f"orders[{index}]",
        )

        normalized.append(
            DispatchOrder(
                order_id=order.order_id.strip(),
                pickup_lat=float(order.pickup_lat),
                pickup_lon=float(order.pickup_lon),
            )
        )

    return normalized


def _validate_lat_lon(lat: float, lon: float, label: str) -> None:
    lat_value = float(lat)
    lon_value = float(lon)

    if not isfinite(lat_value):
        raise ValueError(f"{label}.lat must be finite.")

    if not isfinite(lon_value):
        raise ValueError(f"{label}.lon must be finite.")

    if not -90 <= lat_value <= 90:
        raise ValueError(f"{label}.lat must be between -90 and 90.")

    if not -180 <= lon_value <= 180:
        raise ValueError(f"{label}.lon must be between -180 and 180.")


def _validate_non_negative_int(value: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer.")

    if value < 0:
        raise ValueError(f"{label} must be non-negative.")


def _validate_penalty(value: float, label: str) -> None:
    value_float = float(value)

    if not isfinite(value_float):
        raise ValueError(f"{label} must be finite.")

    if value_float < 0:
        raise ValueError(f"{label} must be non-negative.")


def _validate_distance(distance_m: float, row_index: int, col_index: int) -> None:
    if not isfinite(distance_m):
        raise ValueError(
            f"distance_lookup returned non-finite distance for "
            f"row={row_index}, col={col_index}."
        )

    if distance_m < 0:
        raise ValueError(
            f"distance_lookup returned negative distance for "
            f"row={row_index}, col={col_index}."
        )


__all__ = [
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