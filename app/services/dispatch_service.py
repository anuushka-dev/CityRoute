# app/services/dispatch_service.py

from __future__ import annotations

from collections.abc import Sequence
from time import perf_counter

from app.core.dispatch_cost_matrix import (
    DispatchCostBreakdown,
    DispatchCostMatrixResult,
    DispatchDriver,
    DispatchOrder,
    build_dispatch_cost_matrix,
)
from app.core.dispatch_fairness import (
    DispatchFairnessResult,
    DriverFairnessMetric,
    calculate_dispatch_fairness,
)
from app.core.greedy_dispatch import solve_greedy_dispatch
from app.core.hungarian import AssignmentPair, solve_hungarian
from app.schemas.dispatch import (
    DispatchAlgorithmResultResponse,
    DispatchAssignmentResponse,
    DispatchCompareRequest,
    DispatchCompareResponse,
    DispatchComparisonResponse,
    DispatchCostBreakdownResponse,
    DispatchFairnessResponse,
    DriverFairnessMetricResponse,
)
from app.services.dispatch_distance_service import (
    DispatchDistanceCacheBackend,
    DispatchDistanceError,
    SourceDijkstraMatrixBuilder,
    build_dispatch_distance_lookup,
)


def compare_dispatch_assignments(
    request: DispatchCompareRequest,
    *,
    source_dijkstra_matrix_builder: SourceDijkstraMatrixBuilder | None = None,
    cache_backend: DispatchDistanceCacheBackend | None = None,
    cache_ttl_seconds: int | None = 86_400,
) -> DispatchCompareResponse:

    total_start = perf_counter()

    drivers = _build_core_drivers(request)
    orders = _build_core_orders(request)

    _validate_unique_driver_ids(drivers)
    _validate_unique_order_ids(orders)

    matrix_start = perf_counter()

    try:
        distance_result = build_dispatch_distance_lookup(
            drivers=drivers,
            orders=orders,
            matrix_algorithm=request.matrix_algorithm,
            source_dijkstra_matrix_builder=source_dijkstra_matrix_builder,
            use_cache=request.use_cache,
            cache_backend=cache_backend,
            cache_ttl_seconds=cache_ttl_seconds,
        )
    except DispatchDistanceError as exc:
        raise ValueError(str(exc)) from exc

    matrix_result = build_dispatch_cost_matrix(
        drivers=drivers,
        orders=orders,
        distance_lookup=distance_result.distance_lookup,
        load_penalty_m=request.load_penalty_m,
        slot_penalty_m=request.slot_penalty_m,
    )

    cost_matrix_build_time_ms = _elapsed_ms(matrix_start)

    greedy_result = solve_greedy_dispatch(matrix_result.cost_matrix)
    hungarian_result = solve_hungarian(matrix_result.cost_matrix)

    greedy_fairness = calculate_dispatch_fairness(
        assignments=greedy_result.assignments,
        slots=matrix_result.slots,
    )
    hungarian_fairness = calculate_dispatch_fairness(
        assignments=hungarian_result.assignments,
        slots=matrix_result.slots,
    )

    assigned_order_count = hungarian_result.assigned_count
    unassigned_order_count = len(hungarian_result.unassigned_cols)

    return DispatchCompareResponse(
        status="ok",
        phase="tier3_phase9_1",
        driver_count=matrix_result.driver_count,
        order_count=matrix_result.order_count,
        available_slot_count=matrix_result.available_slot_count,
        assigned_order_count=assigned_order_count,
        unassigned_order_count=unassigned_order_count,
        unused_slot_count=matrix_result.unused_slot_count,
        matrix_algorithm=request.matrix_algorithm,
        cache_used=distance_result.cache_used,
        cache_hit=distance_result.cache_hit,
        cache_key=distance_result.cache_key,
        cost_matrix_build_time_ms=cost_matrix_build_time_ms,
        total_time_ms=_elapsed_ms(total_start),
        greedy=_build_algorithm_response(
            algorithm="greedy_dispatch",
            assignments=greedy_result.assignments,
            total_cost=greedy_result.total_cost,
            assigned_count=greedy_result.assigned_count,
            unassigned_rows=greedy_result.unassigned_rows,
            unassigned_cols=greedy_result.unassigned_cols,
            matrix_result=matrix_result,
        ),
        hungarian=_build_algorithm_response(
            algorithm="hungarian",
            assignments=hungarian_result.assignments,
            total_cost=hungarian_result.total_cost,
            assigned_count=hungarian_result.assigned_count,
            unassigned_rows=hungarian_result.unassigned_rows,
            unassigned_cols=hungarian_result.unassigned_cols,
            matrix_result=matrix_result,
        ),
        comparison=_build_comparison_response(
            greedy_total_cost=greedy_result.total_cost,
            hungarian_total_cost=hungarian_result.total_cost,
        ),
        greedy_fairness=_build_fairness_response(greedy_fairness),
        hungarian_fairness=_build_fairness_response(hungarian_fairness),
        cost_breakdown=(
            _build_cost_breakdown_response(matrix_result.breakdowns)
            if request.return_cost_breakdown
            else []
        ),
    )


def _build_core_drivers(request: DispatchCompareRequest) -> list[DispatchDriver]:
    return [
        DispatchDriver(
            driver_id=driver.driver_id.strip(),
            lat=driver.lat,
            lon=driver.lon,
            current_load=driver.current_load,
            max_capacity=driver.max_capacity,
        )
        for driver in request.drivers
    ]


def _build_core_orders(request: DispatchCompareRequest) -> list[DispatchOrder]:
    return [
        DispatchOrder(
            order_id=order.order_id.strip(),
            pickup_lat=order.pickup_lat,
            pickup_lon=order.pickup_lon,
        )
        for order in request.orders
    ]


def _validate_unique_driver_ids(drivers: Sequence[DispatchDriver]) -> None:
    seen: set[str] = set()

    for driver in drivers:
        if driver.driver_id in seen:
            raise ValueError(f"duplicate driver_id found: {driver.driver_id}")

        seen.add(driver.driver_id)


def _validate_unique_order_ids(orders: Sequence[DispatchOrder]) -> None:
    seen: set[str] = set()

    for order in orders:
        if order.order_id in seen:
            raise ValueError(f"duplicate order_id found: {order.order_id}")

        seen.add(order.order_id)


def _build_algorithm_response(
    *,
    algorithm: str,
    assignments: Sequence[AssignmentPair],
    total_cost: float,
    assigned_count: int,
    unassigned_rows: Sequence[int],
    unassigned_cols: Sequence[int],
    matrix_result: DispatchCostMatrixResult,
) -> DispatchAlgorithmResultResponse:
    slots_by_row = {slot.row_index: slot for slot in matrix_result.slots}

    assignment_responses: list[DispatchAssignmentResponse] = []

    for assignment in assignments:
        slot = slots_by_row[assignment.row_index]
        order = matrix_result.orders[assignment.col_index]

        assignment_responses.append(
            DispatchAssignmentResponse(
                driver_id=slot.driver_id,
                order_id=order.order_id,
                row_index=assignment.row_index,
                col_index=assignment.col_index,
                cost=round(assignment.cost, 6),
            )
        )

    return DispatchAlgorithmResultResponse(
        algorithm=algorithm,
        assignments=assignment_responses,
        total_cost=round(total_cost, 6),
        assigned_count=assigned_count,
        unassigned_driver_slot_rows=list(unassigned_rows),
        unassigned_order_ids=[
            matrix_result.orders[col_index].order_id for col_index in unassigned_cols
        ],
    )


def _build_comparison_response(
    *,
    greedy_total_cost: float,
    hungarian_total_cost: float,
) -> DispatchComparisonResponse:
    cost_saved = round(greedy_total_cost - hungarian_total_cost, 6)

    improvement_pct = (
        round((cost_saved / greedy_total_cost) * 100.0, 6)
        if greedy_total_cost > 0
        else 0.0
    )

    return DispatchComparisonResponse(
        hungarian_non_regression=hungarian_total_cost <= greedy_total_cost,
        hungarian_vs_greedy_cost_saved=cost_saved,
        hungarian_vs_greedy_improvement_pct=improvement_pct,
    )


def _build_fairness_response(
    fairness: DispatchFairnessResult,
) -> DispatchFairnessResponse:
    return DispatchFairnessResponse(
        driver_metrics=[
            _build_driver_fairness_metric_response(metric)
            for metric in fairness.driver_metrics
        ],
        driver_count=fairness.driver_count,
        total_assigned_orders=fairness.total_assigned_orders,
        total_available_slots=fairness.total_available_slots,
        assigned_order_min=fairness.assigned_order_min,
        assigned_order_max=fairness.assigned_order_max,
        assigned_order_range=fairness.assigned_order_range,
        assigned_order_mean=fairness.assigned_order_mean,
        assigned_order_std_dev=fairness.assigned_order_std_dev,
        projected_load_min=fairness.projected_load_min,
        projected_load_max=fairness.projected_load_max,
        projected_load_range=fairness.projected_load_range,
        projected_load_mean=fairness.projected_load_mean,
        projected_load_std_dev=fairness.projected_load_std_dev,
        max_utilization_pct=fairness.max_utilization_pct,
        min_utilization_pct=fairness.min_utilization_pct,
        fairness_score=fairness.fairness_score,
    )


def _build_driver_fairness_metric_response(
    metric: DriverFairnessMetric,
) -> DriverFairnessMetricResponse:
    return DriverFairnessMetricResponse(
        driver_id=metric.driver_id,
        current_load=metric.current_load,
        max_capacity=metric.max_capacity,
        available_slots=metric.available_slots,
        assigned_orders=metric.assigned_orders,
        projected_load=metric.projected_load,
        remaining_capacity=metric.remaining_capacity,
        utilization_pct=metric.utilization_pct,
    )


def _build_cost_breakdown_response(
    breakdowns: Sequence[DispatchCostBreakdown],
) -> list[DispatchCostBreakdownResponse]:
    return [
        DispatchCostBreakdownResponse(
            row_index=breakdown.row_index,
            col_index=breakdown.col_index,
            driver_id=breakdown.driver_id,
            order_id=breakdown.order_id,
            distance_m=breakdown.distance_m,
            load_penalty_m=breakdown.load_penalty_m,
            slot_penalty_m=breakdown.slot_penalty_m,
            total_cost=breakdown.total_cost,
        )
        for breakdown in breakdowns
    ]


def _elapsed_ms(start_time: float) -> float:
    return round((perf_counter() - start_time) * 1000.0, 6)


__all__ = [
    "compare_dispatch_assignments",
]