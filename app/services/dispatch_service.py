# app/services/dispatch_service.py

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import perf_counter

from app.core.dispatch_cost_matrix import (
    AllowedLookup,
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
from app.core.greedy_dispatch import (
    solve_greedy_dispatch,
)
from app.core.hungarian import (
    AssignmentPair,
    solve_hungarian,
)
from app.schemas.dispatch import (
    DispatchAlgorithmResultResponse,
    DispatchAssignmentResponse,
    DispatchCompareRequest,
    DispatchCompareResponse,
    DispatchComparisonResponse,
    DispatchCostBreakdownResponse,
    DispatchFairnessResponse,
    DispatchRoadNetworkResponse,
    DispatchUnreachableRoadPairResponse,
    DriverFairnessMetricResponse,
)
from app.services.dispatch_distance_service import (
    DispatchDistanceCacheBackend,
    DispatchDistanceError,
    SourceDijkstraMatrixBuilder,
    build_dispatch_distance_lookup,
)
from app.services.dispatch_road_matrix_service import (
    DispatchRoadMatrixDependencies,
    DispatchRoadMatrixServiceResult,
    GeoCoordinate,
    build_dispatch_road_matrix,
)

DistanceLookup = Callable[
    [DispatchDriver, DispatchOrder],
    float,
]


@dataclass(frozen=True)
class _DispatchDistancePath:
    """
    Internal normalized distance-path result.

    This lets the main dispatch flow consume either:

    - legacy Haversine / Phase 9.1 distance infrastructure
    - Phase 10 real road-network infrastructure

    through one common contract.
    """

    distance_lookup: DistanceLookup
    allowed_lookup: AllowedLookup | None

    cache_used: bool
    cache_hit: bool
    cache_key: str | None

    cache_status: str
    cache_hits: int
    cache_misses: int
    cache_error: str | None

    road_result: (
        DispatchRoadMatrixServiceResult
        | None
    )


async def compare_dispatch_assignments(
    request: DispatchCompareRequest,
    *,
    source_dijkstra_matrix_builder: (
        SourceDijkstraMatrixBuilder | None
    ) = None,
    cache_backend: (
        DispatchDistanceCacheBackend | None
    ) = None,
    cache_ttl_seconds: int | None = 86_400,
    road_matrix_dependencies: (
        DispatchRoadMatrixDependencies | None
    ) = None,
    unreachable_cost_m: float = (
        1_000_000_000.0
    ),
    fail_open_on_cache_error: bool = True,
) -> DispatchCompareResponse:
    """
    Compare Greedy and Hungarian dispatch assignments.

    Phase 10 supports two distance paths.

    Haversine / legacy path:
        GPS
        -> straight-line or injected Phase 9.1 matrix lookup
        -> capacity-slot cost matrix
        -> Greedy and Hungarian

    Real road-network path:
        GPS
        -> graph-node snapping
        -> source-wise Dijkstra
        -> driver x order road matrix
        -> Redis cache
        -> road reachability matrix
        -> capacity-slot feasibility matrix
        -> Greedy and Hungarian

    Real-road unreachable pairs are explicitly forbidden through the
    assignment algorithms' `allowed_matrix` contract.
    """

    total_start = perf_counter()

    drivers = _build_core_drivers(
        request
    )

    orders = _build_core_orders(
        request
    )

    _validate_unique_driver_ids(
        drivers
    )

    _validate_unique_order_ids(
        orders
    )

    # ------------------------------------------------------------------
    # 1. Build the requested distance path.
    # ------------------------------------------------------------------

    matrix_start = perf_counter()

    if (
        request.matrix_algorithm
        == "source_dijkstra"
        and road_matrix_dependencies
        is not None
    ):
        distance_path = (
            await _build_phase10_road_distance_path(
                request=request,
                drivers=drivers,
                orders=orders,
                dependencies=(
                    road_matrix_dependencies
                ),
                cache_ttl_seconds=(
                    cache_ttl_seconds
                ),
                unreachable_cost_m=(
                    unreachable_cost_m
                ),
                fail_open_on_cache_error=(
                    fail_open_on_cache_error
                ),
            )
        )

    else:
        distance_path = (
            _build_legacy_distance_path(
                request=request,
                drivers=drivers,
                orders=orders,
                source_dijkstra_matrix_builder=(
                    source_dijkstra_matrix_builder
                ),
                cache_backend=(
                    cache_backend
                ),
                cache_ttl_seconds=(
                    cache_ttl_seconds
                ),
            )
        )

    # ------------------------------------------------------------------
    # 2. Build capacity-slot x order optimization matrix.
    #
    # Phase 10:
    #
    # driver x order reachability
    #       ↓
    # allowed_lookup
    #       ↓
    # automatically expanded across all capacity-slot rows
    # ------------------------------------------------------------------

    matrix_result = (
        build_dispatch_cost_matrix(
            drivers=drivers,
            orders=orders,
            distance_lookup=(
                distance_path.distance_lookup
            ),
            allowed_lookup=(
                distance_path.allowed_lookup
            ),
            load_penalty_m=(
                request.load_penalty_m
            ),
            slot_penalty_m=(
                request.slot_penalty_m
            ),
        )
    )

    cost_matrix_build_time_ms = (
        _elapsed_ms(
            matrix_start
        )
    )

    # ------------------------------------------------------------------
    # 3. Solve both assignment strategies.
    #
    # Both algorithms receive the same feasibility matrix.
    #
    # Haversine:
    #     all cells are True.
    #
    # Real road network:
    #     unreachable directed pairs are False.
    # ------------------------------------------------------------------

    greedy_result = (
        solve_greedy_dispatch(
            matrix_result.cost_matrix,
            allowed_matrix=(
                matrix_result
                .allowed_matrix
            ),
        )
    )

    hungarian_result = (
        solve_hungarian(
            matrix_result.cost_matrix,
            allowed_matrix=(
                matrix_result
                .allowed_matrix
            ),
        )
    )

    # ------------------------------------------------------------------
    # 4. Fairness is calculated only from assignments actually accepted by
    #    each algorithm.
    # ------------------------------------------------------------------

    greedy_fairness = (
        calculate_dispatch_fairness(
            assignments=(
                greedy_result.assignments
            ),
            slots=(
                matrix_result.slots
            ),
        )
    )

    hungarian_fairness = (
        calculate_dispatch_fairness(
            assignments=(
                hungarian_result.assignments
            ),
            slots=(
                matrix_result.slots
            ),
        )
    )

    assigned_order_count = (
        hungarian_result.assigned_count
    )

    unassigned_order_count = (
        matrix_result.order_count
        - assigned_order_count
    )

    # ------------------------------------------------------------------
    # 5. Build API response.
    # ------------------------------------------------------------------

    return DispatchCompareResponse(
        status="ok",
        phase="tier3_phase10",
        driver_count=(
            matrix_result.driver_count
        ),
        order_count=(
            matrix_result.order_count
        ),
        available_slot_count=(
            matrix_result
            .available_slot_count
        ),
        assigned_order_count=(
            assigned_order_count
        ),
        unassigned_order_count=(
            unassigned_order_count
        ),
        unused_slot_count=(
            len(
                hungarian_result
                .unassigned_rows
            )
        ),
        matrix_algorithm=(
            request.matrix_algorithm
        ),
        cache_used=(
            distance_path.cache_used
        ),
        cache_hit=(
            distance_path.cache_hit
        ),
        cache_key=(
            distance_path.cache_key
        ),
        cache_status=(
            distance_path.cache_status
        ),
        cache_hits=(
            distance_path.cache_hits
        ),
        cache_misses=(
            distance_path.cache_misses
        ),
        cache_error=(
            distance_path.cache_error
        ),
        cost_matrix_build_time_ms=(
            cost_matrix_build_time_ms
        ),
        total_time_ms=(
            _elapsed_ms(
                total_start
            )
        ),
        greedy=(
            _build_algorithm_response(
                algorithm=(
                    "greedy_dispatch"
                ),
                assignments=(
                    greedy_result
                    .assignments
                ),
                total_cost=(
                    greedy_result
                    .total_cost
                ),
                assigned_count=(
                    greedy_result
                    .assigned_count
                ),
                unassigned_rows=(
                    greedy_result
                    .unassigned_rows
                ),
                unassigned_cols=(
                    greedy_result
                    .unassigned_cols
                ),
                matrix_result=(
                    matrix_result
                ),
            )
        ),
        hungarian=(
            _build_algorithm_response(
                algorithm="hungarian",
                assignments=(
                    hungarian_result
                    .assignments
                ),
                total_cost=(
                    hungarian_result
                    .total_cost
                ),
                assigned_count=(
                    hungarian_result
                    .assigned_count
                ),
                unassigned_rows=(
                    hungarian_result
                    .unassigned_rows
                ),
                unassigned_cols=(
                    hungarian_result
                    .unassigned_cols
                ),
                matrix_result=(
                    matrix_result
                ),
            )
        ),
        comparison=(
            _build_comparison_response(
                greedy_total_cost=(
                    greedy_result
                    .total_cost
                ),
                hungarian_total_cost=(
                    hungarian_result
                    .total_cost
                ),
                greedy_assigned_count=(
                    greedy_result
                    .assigned_count
                ),
                hungarian_assigned_count=(
                    hungarian_result
                    .assigned_count
                ),
            )
        ),
        greedy_fairness=(
            _build_fairness_response(
                greedy_fairness
            )
        ),
        hungarian_fairness=(
            _build_fairness_response(
                hungarian_fairness
            )
        ),
        cost_breakdown=(
            _build_cost_breakdown_response(
                matrix_result.breakdowns
            )
            if (
                request
                .return_cost_breakdown
            )
            else []
        ),
        road_network=(
            _build_road_network_response(
                distance_path.road_result
            )
            if (
                distance_path.road_result
                is not None
            )
            else None
        ),
    )


async def _build_phase10_road_distance_path(
    *,
    request: DispatchCompareRequest,
    drivers: Sequence[
        DispatchDriver
    ],
    orders: Sequence[
        DispatchOrder
    ],
    dependencies: (
        DispatchRoadMatrixDependencies
    ),
    cache_ttl_seconds: int | None,
    unreachable_cost_m: float,
    fail_open_on_cache_error: bool,
) -> _DispatchDistancePath:
    """
    Build the Phase 10 real-road dispatch path.

    Produces:

    - finite road-distance lookup
    - explicit road reachability lookup
    - Redis/cache telemetry
    - complete road-matrix telemetry
    """

    resolved_cache_ttl_seconds = (
        cache_ttl_seconds
        if cache_ttl_seconds
        is not None
        else 86_400
    )

    road_result = (
        await build_dispatch_road_matrix(
            drivers=(
                _build_driver_coordinates(
                    drivers
                )
            ),
            orders=(
                _build_order_coordinates(
                    orders
                )
            ),
            dependencies=dependencies,
            use_cache=(
                request.use_cache
            ),
            cache_ttl_seconds=(
                resolved_cache_ttl_seconds
            ),
            unreachable_cost_m=(
                unreachable_cost_m
            ),
            fail_open_on_cache_error=(
                fail_open_on_cache_error
            ),
        )
    )

    (
        distance_lookup,
        allowed_lookup,
    ) = _build_road_lookups(
        drivers=drivers,
        orders=orders,
        road_result=road_result,
    )

    return _DispatchDistancePath(
        distance_lookup=(
            distance_lookup
        ),
        allowed_lookup=(
            allowed_lookup
        ),
        cache_used=(
            road_result.cache_used
        ),
        cache_hit=(
            road_result.cache_status
            == "hit"
        ),
        cache_key=(
            road_result.cache_key
        ),
        cache_status=(
            road_result.cache_status
        ),
        cache_hits=(
            road_result.cache_hits
        ),
        cache_misses=(
            road_result.cache_misses
        ),
        cache_error=(
            road_result.cache_error
        ),
        road_result=(
            road_result
        ),
    )


def _build_legacy_distance_path(
    *,
    request: DispatchCompareRequest,
    drivers: Sequence[
        DispatchDriver
    ],
    orders: Sequence[
        DispatchOrder
    ],
    source_dijkstra_matrix_builder: (
        SourceDijkstraMatrixBuilder
        | None
    ),
    cache_backend: (
        DispatchDistanceCacheBackend
        | None
    ),
    cache_ttl_seconds: int | None,
) -> _DispatchDistancePath:
    """
    Preserve Phase 9 / Phase 9.1 behavior.

    Haversine has no road-network restrictions, so:

        allowed_lookup = None

    which causes `build_dispatch_cost_matrix()` to produce an all-True
    allowed matrix.
    """

    try:
        distance_result = (
            build_dispatch_distance_lookup(
                drivers=drivers,
                orders=orders,
                matrix_algorithm=(
                    request
                    .matrix_algorithm
                ),
                source_dijkstra_matrix_builder=(
                    source_dijkstra_matrix_builder
                ),
                use_cache=(
                    request.use_cache
                ),
                cache_backend=(
                    cache_backend
                ),
                cache_ttl_seconds=(
                    cache_ttl_seconds
                ),
            )
        )

    except DispatchDistanceError as exc:
        raise ValueError(
            str(
                exc
            )
        ) from exc

    if (
        distance_result.cache_used
    ):
        cache_status = (
            "hit"
            if distance_result.cache_hit
            else "miss"
        )

        cache_hits = (
            1
            if distance_result.cache_hit
            else 0
        )

        cache_misses = (
            0
            if distance_result.cache_hit
            else 1
        )

    else:
        cache_status = "disabled"
        cache_hits = 0
        cache_misses = 0

    return _DispatchDistancePath(
        distance_lookup=(
            distance_result
            .distance_lookup
        ),
        allowed_lookup=None,
        cache_used=(
            distance_result
            .cache_used
        ),
        cache_hit=(
            distance_result
            .cache_hit
        ),
        cache_key=(
            distance_result
            .cache_key
        ),
        cache_status=(
            cache_status
        ),
        cache_hits=(
            cache_hits
        ),
        cache_misses=(
            cache_misses
        ),
        cache_error=None,
        road_result=None,
    )


def _build_driver_coordinates(
    drivers: Sequence[
        DispatchDriver
    ],
) -> tuple[
    GeoCoordinate,
    ...,
]:
    """Convert dispatch drivers to Phase 10 road coordinates."""

    return tuple(
        GeoCoordinate(
            lat=driver.lat,
            lon=driver.lon,
        )
        for driver
        in drivers
    )


def _build_order_coordinates(
    orders: Sequence[
        DispatchOrder
    ],
) -> tuple[
    GeoCoordinate,
    ...,
]:
    """Convert order pickup positions to Phase 10 road coordinates."""

    return tuple(
        GeoCoordinate(
            lat=(
                order.pickup_lat
            ),
            lon=(
                order.pickup_lon
            ),
        )
        for order
        in orders
    )


def _build_road_lookups(
    *,
    drivers: Sequence[
        DispatchDriver
    ],
    orders: Sequence[
        DispatchOrder
    ],
    road_result: (
        DispatchRoadMatrixServiceResult
    ),
) -> tuple[
    DistanceLookup,
    AllowedLookup,
]:
    """
    Adapt the driver x order Phase 10 road matrix to the existing
    dispatch-cost-matrix lookup contracts.

    Both lookups use exactly the same matrix indices:

        distance_lookup
            -> finite optimization cost

        allowed_lookup
            -> actual directed-road reachability

    This separation is important because an unreachable pair may contain a
    finite replacement cost but must still remain forbidden.
    """

    driver_index_by_id = {
        driver.driver_id: index
        for index, driver
        in enumerate(
            drivers
        )
    }

    order_index_by_id = {
        order.order_id: index
        for index, order
        in enumerate(
            orders
        )
    }

    def _resolve_indices(
        driver: DispatchDriver,
        order: DispatchOrder,
    ) -> tuple[
        int,
        int,
    ]:
        try:
            driver_index = (
                driver_index_by_id[
                    driver.driver_id
                ]
            )

        except KeyError as exc:
            raise ValueError(
                "Road matrix lookup received "
                "an unknown driver_id: "
                f"{driver.driver_id}"
            ) from exc

        try:
            order_index = (
                order_index_by_id[
                    order.order_id
                ]
            )

        except KeyError as exc:
            raise ValueError(
                "Road matrix lookup received "
                "an unknown order_id: "
                f"{order.order_id}"
            ) from exc

        return (
            driver_index,
            order_index,
        )

    def distance_lookup(
        driver: DispatchDriver,
        order: DispatchOrder,
    ) -> float:
        (
            driver_index,
            order_index,
        ) = _resolve_indices(
            driver,
            order,
        )

        return float(
            road_result
            .matrix_result
            .cost_matrix_m[
                driver_index
            ][
                order_index
            ]
        )

    def allowed_lookup(
        driver: DispatchDriver,
        order: DispatchOrder,
    ) -> bool:
        (
            driver_index,
            order_index,
        ) = _resolve_indices(
            driver,
            order,
        )

        return bool(
            road_result
            .matrix_result
            .reachable_matrix[
                driver_index
            ][
                order_index
            ]
        )

    return (
        distance_lookup,
        allowed_lookup,
    )


def _build_core_drivers(
    request: DispatchCompareRequest,
) -> list[
    DispatchDriver
]:
    return [
        DispatchDriver(
            driver_id=(
                driver.driver_id.strip()
            ),
            lat=driver.lat,
            lon=driver.lon,
            current_load=(
                driver.current_load
            ),
            max_capacity=(
                driver.max_capacity
            ),
        )
        for driver
        in request.drivers
    ]


def _build_core_orders(
    request: DispatchCompareRequest,
) -> list[
    DispatchOrder
]:
    return [
        DispatchOrder(
            order_id=(
                order.order_id.strip()
            ),
            pickup_lat=(
                order.pickup_lat
            ),
            pickup_lon=(
                order.pickup_lon
            ),
        )
        for order
        in request.orders
    ]


def _validate_unique_driver_ids(
    drivers: Sequence[
        DispatchDriver
    ],
) -> None:
    seen: set[
        str
    ] = set()

    for driver in drivers:
        if (
            driver.driver_id
            in seen
        ):
            raise ValueError(
                "duplicate driver_id found: "
                f"{driver.driver_id}"
            )

        seen.add(
            driver.driver_id
        )


def _validate_unique_order_ids(
    orders: Sequence[
        DispatchOrder
    ],
) -> None:
    seen: set[
        str
    ] = set()

    for order in orders:
        if (
            order.order_id
            in seen
        ):
            raise ValueError(
                "duplicate order_id found: "
                f"{order.order_id}"
            )

        seen.add(
            order.order_id
        )


def _build_algorithm_response(
    *,
    algorithm: str,
    assignments: Sequence[
        AssignmentPair
    ],
    total_cost: float,
    assigned_count: int,
    unassigned_rows: Sequence[
        int
    ],
    unassigned_cols: Sequence[
        int
    ],
    matrix_result: (
        DispatchCostMatrixResult
    ),
) -> DispatchAlgorithmResultResponse:
    slots_by_row = {
        slot.row_index: slot
        for slot
        in matrix_result.slots
    }

    assignment_responses: list[
        DispatchAssignmentResponse
    ] = []

    for assignment in assignments:
        slot = slots_by_row[
            assignment.row_index
        ]

        order = (
            matrix_result.orders[
                assignment.col_index
            ]
        )

        assignment_responses.append(
            DispatchAssignmentResponse(
                driver_id=(
                    slot.driver_id
                ),
                order_id=(
                    order.order_id
                ),
                row_index=(
                    assignment.row_index
                ),
                col_index=(
                    assignment.col_index
                ),
                cost=round(
                    assignment.cost,
                    6,
                ),
            )
        )

    return DispatchAlgorithmResultResponse(
        algorithm=algorithm,
        assignments=(
            assignment_responses
        ),
        total_cost=round(
            total_cost,
            6,
        ),
        assigned_count=(
            assigned_count
        ),
        unassigned_driver_slot_rows=list(
            unassigned_rows
        ),
        unassigned_order_ids=[
            matrix_result.orders[
                col_index
            ].order_id
            for col_index
            in unassigned_cols
        ],
    )


def _build_comparison_response(
    *,
    greedy_total_cost: float,
    hungarian_total_cost: float,
    greedy_assigned_count: int,
    hungarian_assigned_count: int,
) -> DispatchComparisonResponse:
    """
    Compare assignment quality safely under Phase 10 feasibility rules.

    Assignment count has priority over cost.

    Example:

        Greedy assigns 4 valid orders for cost 100.
        Hungarian assigns 5 valid orders for cost 120.

    Comparing only 100 vs 120 would incorrectly mark Hungarian as worse.
    """

    if (
        hungarian_assigned_count
        > greedy_assigned_count
    ):
        hungarian_non_regression = True

    elif (
        hungarian_assigned_count
        < greedy_assigned_count
    ):
        hungarian_non_regression = False

    else:
        hungarian_non_regression = (
            hungarian_total_cost
            <= greedy_total_cost
            + 1e-9
        )

    # Cost savings are directly comparable only when both algorithms assign
    # the same number of orders.
    if (
        hungarian_assigned_count
        == greedy_assigned_count
    ):
        cost_saved = round(
            greedy_total_cost
            - hungarian_total_cost,
            6,
        )

        improvement_pct = (
            round(
                (
                    cost_saved
                    / greedy_total_cost
                )
                * 100.0,
                6,
            )
            if greedy_total_cost > 0
            else 0.0
        )

    else:
        cost_saved = 0.0
        improvement_pct = 0.0

    return DispatchComparisonResponse(
        hungarian_non_regression=(
            hungarian_non_regression
        ),
        hungarian_vs_greedy_cost_saved=(
            cost_saved
        ),
        hungarian_vs_greedy_improvement_pct=(
            improvement_pct
        ),
    )


def _build_fairness_response(
    fairness: DispatchFairnessResult,
) -> DispatchFairnessResponse:
    return DispatchFairnessResponse(
        driver_metrics=[
            _build_driver_fairness_metric_response(
                metric
            )
            for metric
            in fairness.driver_metrics
        ],
        driver_count=(
            fairness.driver_count
        ),
        total_assigned_orders=(
            fairness
            .total_assigned_orders
        ),
        total_available_slots=(
            fairness
            .total_available_slots
        ),
        assigned_order_min=(
            fairness
            .assigned_order_min
        ),
        assigned_order_max=(
            fairness
            .assigned_order_max
        ),
        assigned_order_range=(
            fairness
            .assigned_order_range
        ),
        assigned_order_mean=(
            fairness
            .assigned_order_mean
        ),
        assigned_order_std_dev=(
            fairness
            .assigned_order_std_dev
        ),
        projected_load_min=(
            fairness
            .projected_load_min
        ),
        projected_load_max=(
            fairness
            .projected_load_max
        ),
        projected_load_range=(
            fairness
            .projected_load_range
        ),
        projected_load_mean=(
            fairness
            .projected_load_mean
        ),
        projected_load_std_dev=(
            fairness
            .projected_load_std_dev
        ),
        max_utilization_pct=(
            fairness
            .max_utilization_pct
        ),
        min_utilization_pct=(
            fairness
            .min_utilization_pct
        ),
        fairness_score=(
            fairness.fairness_score
        ),
    )


def _build_driver_fairness_metric_response(
    metric: DriverFairnessMetric,
) -> DriverFairnessMetricResponse:
    return DriverFairnessMetricResponse(
        driver_id=(
            metric.driver_id
        ),
        current_load=(
            metric.current_load
        ),
        max_capacity=(
            metric.max_capacity
        ),
        available_slots=(
            metric.available_slots
        ),
        assigned_orders=(
            metric.assigned_orders
        ),
        projected_load=(
            metric.projected_load
        ),
        remaining_capacity=(
            metric.remaining_capacity
        ),
        utilization_pct=(
            metric.utilization_pct
        ),
    )


def _build_cost_breakdown_response(
    breakdowns: Sequence[
        DispatchCostBreakdown
    ],
) -> list[
    DispatchCostBreakdownResponse
]:
    return [
        DispatchCostBreakdownResponse(
            row_index=(
                breakdown.row_index
            ),
            col_index=(
                breakdown.col_index
            ),
            driver_id=(
                breakdown.driver_id
            ),
            order_id=(
                breakdown.order_id
            ),
            distance_m=(
                breakdown.distance_m
            ),
            load_penalty_m=(
                breakdown.load_penalty_m
            ),
            slot_penalty_m=(
                breakdown.slot_penalty_m
            ),
            total_cost=(
                breakdown.total_cost
            ),
            allowed=(
                breakdown.allowed
            ),
        )
        for breakdown
        in breakdowns
    ]


def _build_road_network_response(
    road_result: (
        DispatchRoadMatrixServiceResult
    ),
) -> DispatchRoadNetworkResponse:
    """
    Convert internal Phase 10 road-matrix telemetry into API telemetry.
    """

    matrix_result = (
        road_result.matrix_result
    )

    return DispatchRoadNetworkResponse(
        matrix_source=(
            road_result.matrix_source
        ),
        snapped_driver_count=(
            road_result
            .snapped_driver_count
        ),
        snapped_order_count=(
            road_result
            .snapped_order_count
        ),
        unique_driver_node_count=(
            matrix_result
            .unique_driver_node_count
        ),
        unique_order_node_count=(
            matrix_result
            .unique_order_node_count
        ),
        source_search_count=(
            matrix_result
            .source_search_count
        ),
        pair_count=(
            matrix_result
            .pair_count
        ),
        reachable_pair_count=(
            matrix_result
            .reachable_pair_count
        ),
        unreachable_pair_count=(
            matrix_result
            .unreachable_pair_count
        ),
        all_pairs_reachable=(
            matrix_result
            .all_pairs_reachable
        ),
        unreachable_cost_m=(
            matrix_result
            .unreachable_cost_m
        ),
        snap_time_ms=(
            road_result.snap_time_ms
        ),
        cache_lookup_time_ms=(
            road_result
            .cache_lookup_time_ms
        ),
        cache_write_time_ms=(
            road_result
            .cache_write_time_ms
        ),
        matrix_generation_time_ms=(
            road_result
            .matrix_generation_time_ms
        ),
        total_time_ms=(
            road_result.total_time_ms
        ),
        unreachable_pairs=[
            DispatchUnreachableRoadPairResponse(
                driver_index=(
                    pair.driver_index
                ),
                order_index=(
                    pair.order_index
                ),
                driver_node=(
                    pair.driver_node
                ),
                order_node=(
                    pair.order_node
                ),
                replacement_cost_m=(
                    pair
                    .replacement_cost_m
                ),
            )
            for pair
            in matrix_result
            .unreachable_pairs
        ],
    )


def _elapsed_ms(
    start_time: float,
) -> float:
    return round(
        (
            perf_counter()
            - start_time
        )
        * 1000.0,
        6,
    )


__all__ = [
    "compare_dispatch_assignments",
]