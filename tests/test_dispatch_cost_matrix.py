# tests/test_dispatch_cost_matrix.py

from __future__ import annotations

from math import inf, nan

import pytest

from app.core.dispatch_cost_matrix import (
    DispatchCostBreakdown,
    DispatchCostMatrixResult,
    DispatchDriver,
    DispatchOrder,
    DispatchSlot,
    build_dispatch_cost_matrix,
    haversine_distance_lookup,
    haversine_m,
)


def _constant_distance_lookup(
    driver: DispatchDriver,
    order: DispatchOrder,
) -> float:
    return 100.0


def test_build_dispatch_cost_matrix_returns_result_type():
    result = build_dispatch_cost_matrix(
        drivers=[DispatchDriver("d1", 26.45, 80.35)],
        orders=[DispatchOrder("o1", 26.451, 80.351)],
        distance_lookup=_constant_distance_lookup,
    )

    assert isinstance(result, DispatchCostMatrixResult)
    assert isinstance(result.slots[0], DispatchSlot)
    assert isinstance(result.breakdowns[0], DispatchCostBreakdown)


def test_build_dispatch_cost_matrix_creates_one_row_per_available_driver_slot():
    result = build_dispatch_cost_matrix(
        drivers=[
            DispatchDriver("d1", 26.45, 80.35, current_load=0, max_capacity=2),
            DispatchDriver("d2", 26.46, 80.36, current_load=1, max_capacity=3),
        ],
        orders=[DispatchOrder("o1", 26.451, 80.351)],
        distance_lookup=_constant_distance_lookup,
    )

    assert result.driver_count == 2
    assert result.order_count == 1
    assert result.available_slot_count == 4
    assert result.row_count == 4
    assert result.col_count == 1
    assert len(result.slots) == 4
    assert [slot.driver_id for slot in result.slots] == ["d1", "d1", "d2", "d2"]


def test_build_dispatch_cost_matrix_creates_one_column_per_order():
    result = build_dispatch_cost_matrix(
        drivers=[DispatchDriver("d1", 26.45, 80.35, max_capacity=1)],
        orders=[
            DispatchOrder("o1", 26.451, 80.351),
            DispatchOrder("o2", 26.452, 80.352),
            DispatchOrder("o3", 26.453, 80.353),
        ],
        distance_lookup=_constant_distance_lookup,
    )

    assert result.row_count == 1
    assert result.col_count == 3
    assert result.cost_matrix == [[100.0, 100.0, 100.0]]
    assert result.unassignable_order_count == 2
    assert result.unused_slot_count == 0


def test_build_dispatch_cost_matrix_tracks_unused_slots_when_capacity_exceeds_orders():
    result = build_dispatch_cost_matrix(
        drivers=[DispatchDriver("d1", 26.45, 80.35, max_capacity=3)],
        orders=[DispatchOrder("o1", 26.451, 80.351)],
        distance_lookup=_constant_distance_lookup,
    )

    assert result.available_slot_count == 3
    assert result.order_count == 1
    assert result.unassignable_order_count == 0
    assert result.unused_slot_count == 2


def test_build_dispatch_cost_matrix_applies_load_and_slot_penalties():
    result = build_dispatch_cost_matrix(
        drivers=[
            DispatchDriver(
                driver_id="d1",
                lat=26.45,
                lon=80.35,
                current_load=2,
                max_capacity=4,
            )
        ],
        orders=[DispatchOrder("o1", 26.451, 80.351)],
        distance_lookup=lambda driver, order: 5.0,
        load_penalty_m=100.0,
        slot_penalty_m=10.0,
    )

    assert result.cost_matrix == [[205.0], [215.0]]

    first_breakdown = result.breakdowns[0]
    second_breakdown = result.breakdowns[1]

    assert first_breakdown.distance_m == 5.0
    assert first_breakdown.load_penalty_m == 200.0
    assert first_breakdown.slot_penalty_m == 0.0
    assert first_breakdown.total_cost == 205.0

    assert second_breakdown.distance_m == 5.0
    assert second_breakdown.load_penalty_m == 200.0
    assert second_breakdown.slot_penalty_m == 10.0
    assert second_breakdown.total_cost == 215.0


def test_build_dispatch_cost_matrix_breakdowns_map_rows_and_columns_to_ids():
    result = build_dispatch_cost_matrix(
        drivers=[
            DispatchDriver("d1", 26.45, 80.35, max_capacity=1),
            DispatchDriver("d2", 26.46, 80.36, max_capacity=1),
        ],
        orders=[
            DispatchOrder("o1", 26.451, 80.351),
            DispatchOrder("o2", 26.452, 80.352),
        ],
        distance_lookup=_constant_distance_lookup,
    )

    assert len(result.breakdowns) == 4

    assert result.breakdowns[0].row_index == 0
    assert result.breakdowns[0].col_index == 0
    assert result.breakdowns[0].driver_id == "d1"
    assert result.breakdowns[0].order_id == "o1"

    assert result.breakdowns[3].row_index == 1
    assert result.breakdowns[3].col_index == 1
    assert result.breakdowns[3].driver_id == "d2"
    assert result.breakdowns[3].order_id == "o2"


def test_haversine_m_returns_zero_for_same_point():
    assert haversine_m(26.45, 80.35, 26.45, 80.35) == 0.0


def test_haversine_distance_lookup_returns_non_negative_distance():
    distance = haversine_distance_lookup(
        DispatchDriver("d1", 26.45, 80.35),
        DispatchOrder("o1", 26.451, 80.351),
    )

    assert distance > 0


def test_build_dispatch_cost_matrix_rejects_empty_drivers():
    with pytest.raises(ValueError, match="at least one driver"):
        build_dispatch_cost_matrix(
            drivers=[],
            orders=[DispatchOrder("o1", 26.451, 80.351)],
            distance_lookup=_constant_distance_lookup,
        )


def test_build_dispatch_cost_matrix_rejects_empty_orders():
    with pytest.raises(ValueError, match="at least one order"):
        build_dispatch_cost_matrix(
            drivers=[DispatchDriver("d1", 26.45, 80.35)],
            orders=[],
            distance_lookup=_constant_distance_lookup,
        )


def test_build_dispatch_cost_matrix_rejects_driver_with_no_id():
    with pytest.raises(ValueError, match="driver_id"):
        build_dispatch_cost_matrix(
            drivers=[DispatchDriver("", 26.45, 80.35)],
            orders=[DispatchOrder("o1", 26.451, 80.351)],
            distance_lookup=_constant_distance_lookup,
        )


def test_build_dispatch_cost_matrix_rejects_order_with_no_id():
    with pytest.raises(ValueError, match="order_id"):
        build_dispatch_cost_matrix(
            drivers=[DispatchDriver("d1", 26.45, 80.35)],
            orders=[DispatchOrder("", 26.451, 80.351)],
            distance_lookup=_constant_distance_lookup,
        )


@pytest.mark.parametrize(
    ("lat", "lon"),
    [
        (91.0, 80.35),
        (-91.0, 80.35),
        (26.45, 181.0),
        (26.45, -181.0),
        (nan, 80.35),
        (26.45, inf),
    ],
)
def test_build_dispatch_cost_matrix_rejects_invalid_driver_coordinates(lat, lon):
    with pytest.raises(ValueError):
        build_dispatch_cost_matrix(
            drivers=[DispatchDriver("d1", lat, lon)],
            orders=[DispatchOrder("o1", 26.451, 80.351)],
            distance_lookup=_constant_distance_lookup,
        )


@pytest.mark.parametrize(
    ("lat", "lon"),
    [
        (91.0, 80.35),
        (-91.0, 80.35),
        (26.45, 181.0),
        (26.45, -181.0),
        (nan, 80.35),
        (26.45, inf),
    ],
)
def test_build_dispatch_cost_matrix_rejects_invalid_order_coordinates(lat, lon):
    with pytest.raises(ValueError):
        build_dispatch_cost_matrix(
            drivers=[DispatchDriver("d1", 26.45, 80.35)],
            orders=[DispatchOrder("o1", lat, lon)],
            distance_lookup=_constant_distance_lookup,
        )


def test_build_dispatch_cost_matrix_rejects_negative_current_load():
    with pytest.raises(ValueError, match="current_load"):
        build_dispatch_cost_matrix(
            drivers=[DispatchDriver("d1", 26.45, 80.35, current_load=-1)],
            orders=[DispatchOrder("o1", 26.451, 80.351)],
            distance_lookup=_constant_distance_lookup,
        )


def test_build_dispatch_cost_matrix_rejects_zero_max_capacity():
    with pytest.raises(ValueError, match="max_capacity"):
        build_dispatch_cost_matrix(
            drivers=[DispatchDriver("d1", 26.45, 80.35, max_capacity=0)],
            orders=[DispatchOrder("o1", 26.451, 80.351)],
            distance_lookup=_constant_distance_lookup,
        )


def test_build_dispatch_cost_matrix_rejects_current_load_above_capacity():
    with pytest.raises(ValueError, match="must not exceed"):
        build_dispatch_cost_matrix(
            drivers=[
                DispatchDriver(
                    "d1",
                    26.45,
                    80.35,
                    current_load=3,
                    max_capacity=2,
                )
            ],
            orders=[DispatchOrder("o1", 26.451, 80.351)],
            distance_lookup=_constant_distance_lookup,
        )


def test_build_dispatch_cost_matrix_rejects_all_drivers_full():
    with pytest.raises(ValueError, match="available capacity"):
        build_dispatch_cost_matrix(
            drivers=[DispatchDriver("d1", 26.45, 80.35, current_load=1, max_capacity=1)],
            orders=[DispatchOrder("o1", 26.451, 80.351)],
            distance_lookup=_constant_distance_lookup,
        )


def test_build_dispatch_cost_matrix_rejects_negative_load_penalty():
    with pytest.raises(ValueError, match="load_penalty_m"):
        build_dispatch_cost_matrix(
            drivers=[DispatchDriver("d1", 26.45, 80.35)],
            orders=[DispatchOrder("o1", 26.451, 80.351)],
            distance_lookup=_constant_distance_lookup,
            load_penalty_m=-1,
        )


def test_build_dispatch_cost_matrix_rejects_negative_slot_penalty():
    with pytest.raises(ValueError, match="slot_penalty_m"):
        build_dispatch_cost_matrix(
            drivers=[DispatchDriver("d1", 26.45, 80.35)],
            orders=[DispatchOrder("o1", 26.451, 80.351)],
            distance_lookup=_constant_distance_lookup,
            slot_penalty_m=-1,
        )


def test_build_dispatch_cost_matrix_rejects_negative_distance_lookup_result():
    with pytest.raises(ValueError, match="negative distance"):
        build_dispatch_cost_matrix(
            drivers=[DispatchDriver("d1", 26.45, 80.35)],
            orders=[DispatchOrder("o1", 26.451, 80.351)],
            distance_lookup=lambda driver, order: -1.0,
        )


def test_build_dispatch_cost_matrix_rejects_non_finite_distance_lookup_result():
    with pytest.raises(ValueError, match="non-finite distance"):
        build_dispatch_cost_matrix(
            drivers=[DispatchDriver("d1", 26.45, 80.35)],
            orders=[DispatchOrder("o1", 26.451, 80.351)],
            distance_lookup=lambda driver, order: inf,
        )