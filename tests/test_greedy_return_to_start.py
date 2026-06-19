# tests/test_greedy_return_to_start.py

from app.core.greedy_nearest_neighbor import solve_nearest_neighbor_greedy


def test_return_to_start_adds_final_depot_leg() -> None:
    distance_matrix = [
        [0.0, 10.0, 20.0],
        [10.0, 0.0, 5.0],
        [20.0, 5.0, 0.0],
    ]

    result = solve_nearest_neighbor_greedy(
        distance_matrix=distance_matrix,
        return_to_start=True,
    )

    assert result.optimized_order == [0, 1]
    assert len(result.legs) == 3
    assert result.total_distance_m == 35.0

    final_leg = result.legs[-1]
    assert final_leg.from_matrix_index == 2
    assert final_leg.to_matrix_index == 0
    assert final_leg.distance_m == 20.0


def test_open_route_does_not_add_depot_leg() -> None:
    distance_matrix = [
        [0.0, 10.0, 20.0],
        [10.0, 0.0, 5.0],
        [20.0, 5.0, 0.0],
    ]

    result = solve_nearest_neighbor_greedy(
        distance_matrix=distance_matrix,
        return_to_start=False,
    )

    assert result.optimized_order == [0, 1]
    assert len(result.legs) == 2
    assert result.total_distance_m == 15.0

    final_leg = result.legs[-1]
    assert final_leg.from_matrix_index == 1
    assert final_leg.to_matrix_index == 2


def test_return_to_start_distance_is_not_smaller_than_open_route() -> None:
    distance_matrix = [
        [0.0, 10.0, 20.0, 30.0],
        [10.0, 0.0, 7.0, 9.0],
        [20.0, 7.0, 0.0, 6.0],
        [30.0, 9.0, 6.0, 0.0],
    ]

    open_result = solve_nearest_neighbor_greedy(
        distance_matrix=distance_matrix,
        return_to_start=False,
    )

    closed_result = solve_nearest_neighbor_greedy(
        distance_matrix=distance_matrix,
        return_to_start=True,
    )

    assert len(open_result.legs) == 3
    assert len(closed_result.legs) == 4
    assert closed_result.total_distance_m >= open_result.total_distance_m

    assert closed_result.legs[-1].to_matrix_index == 0


def test_single_stop_return_to_start_has_two_legs() -> None:
    distance_matrix = [
        [0.0, 7.0],
        [7.0, 0.0],
    ]

    result = solve_nearest_neighbor_greedy(
        distance_matrix=distance_matrix,
        return_to_start=True,
    )

    assert result.optimized_order == [0]
    assert len(result.legs) == 2
    assert result.total_distance_m == 14.0

    assert result.legs[0].from_matrix_index == 0
    assert result.legs[0].to_matrix_index == 1

    assert result.legs[1].from_matrix_index == 1
    assert result.legs[1].to_matrix_index == 0