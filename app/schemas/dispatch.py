# app/schemas/dispatch.py

from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

DispatchPhase = Literal[
    "tier3_phase9",
    "tier3_phase9_1",
    "tier3_phase10",
]

DispatchMatrixAlgorithm = Literal[
    "haversine",
    "source_dijkstra",
]

DispatchCacheStatus = Literal[
    "disabled",
    "hit",
    "miss",
]

DispatchMatrixSource = Literal[
    "computed",
    "cache",
]


# ---------------------------------------------------------------------------
# Shared schema base
# ---------------------------------------------------------------------------


class DispatchSchemaModel(BaseModel):
    """
    Shared validation behavior for dispatch API schemas.

    - rejects unexpected fields
    - strips surrounding whitespace from strings
    - rejects NaN and infinity
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class DispatchDriverRequest(
    DispatchSchemaModel
):
    driver_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
    )

    lat: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
    )

    lon: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
    )

    current_load: int = Field(
        default=0,
        ge=0,
    )

    max_capacity: int = Field(
        default=1,
        ge=1,
    )

    @field_validator(
        "driver_id"
    )
    @classmethod
    def validate_driver_id(
        cls,
        value: str,
    ) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError(
                "driver_id must not be empty."
            )

        return normalized

    @model_validator(
        mode="after"
    )
    def validate_capacity(
        self,
    ) -> DispatchDriverRequest:
        if (
            self.current_load
            > self.max_capacity
        ):
            raise ValueError(
                "current_load must not exceed "
                "max_capacity."
            )

        return self


class DispatchOrderRequest(
    DispatchSchemaModel
):
    order_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
    )

    pickup_lat: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
    )

    pickup_lon: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
    )

    @field_validator(
        "order_id"
    )
    @classmethod
    def validate_order_id(
        cls,
        value: str,
    ) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError(
                "order_id must not be empty."
            )

        return normalized


class DispatchCompareRequest(
    DispatchSchemaModel
):
    drivers: list[
        DispatchDriverRequest
    ] = Field(
        ...,
        min_length=1,
        max_length=50,
    )

    orders: list[
        DispatchOrderRequest
    ] = Field(
        ...,
        min_length=1,
        max_length=50,
    )

    matrix_algorithm: (
        DispatchMatrixAlgorithm
    ) = "haversine"

    use_cache: bool = True

    load_penalty_m: float = Field(
        default=0.0,
        ge=0.0,
    )

    slot_penalty_m: float = Field(
        default=0.0,
        ge=0.0,
    )

    return_cost_breakdown: bool = False

    @model_validator(
        mode="after"
    )
    def validate_unique_ids(
        self,
    ) -> DispatchCompareRequest:
        driver_ids = [
            driver.driver_id
            for driver
            in self.drivers
        ]

        if (
            len(
                driver_ids
            )
            != len(
                set(
                    driver_ids
                )
            )
        ):
            raise ValueError(
                "driver_id values must be unique."
            )

        order_ids = [
            order.order_id
            for order
            in self.orders
        ]

        if (
            len(
                order_ids
            )
            != len(
                set(
                    order_ids
                )
            )
        ):
            raise ValueError(
                "order_id values must be unique."
            )

        return self


# ---------------------------------------------------------------------------
# Assignment response models
# ---------------------------------------------------------------------------


class DispatchAssignmentResponse(
    DispatchSchemaModel
):
    driver_id: str
    order_id: str

    row_index: int = Field(
        ...,
        ge=0,
    )

    col_index: int = Field(
        ...,
        ge=0,
    )

    cost: float = Field(
        ...,
        ge=0.0,
    )


class DispatchAlgorithmResultResponse(
    DispatchSchemaModel
):
    algorithm: str

    assignments: list[
        DispatchAssignmentResponse
    ]

    total_cost: float = Field(
        ...,
        ge=0.0,
    )

    assigned_count: int = Field(
        ...,
        ge=0,
    )

    unassigned_driver_slot_rows: list[
        int
    ]

    unassigned_order_ids: list[
        str
    ]


# ---------------------------------------------------------------------------
# Fairness response models
# ---------------------------------------------------------------------------


class DriverFairnessMetricResponse(
    DispatchSchemaModel
):
    driver_id: str

    current_load: int = Field(
        ...,
        ge=0,
    )

    max_capacity: int = Field(
        ...,
        ge=1,
    )

    available_slots: int = Field(
        ...,
        ge=0,
    )

    assigned_orders: int = Field(
        ...,
        ge=0,
    )

    projected_load: int = Field(
        ...,
        ge=0,
    )

    remaining_capacity: int = Field(
        ...,
        ge=0,
    )

    utilization_pct: float = Field(
        ...,
        ge=0.0,
        le=100.0,
    )


class DispatchFairnessResponse(
    DispatchSchemaModel
):
    driver_metrics: list[
        DriverFairnessMetricResponse
    ]

    driver_count: int = Field(
        ...,
        ge=0,
    )

    total_assigned_orders: int = Field(
        ...,
        ge=0,
    )

    total_available_slots: int = Field(
        ...,
        ge=0,
    )

    assigned_order_min: int = Field(
        ...,
        ge=0,
    )

    assigned_order_max: int = Field(
        ...,
        ge=0,
    )

    assigned_order_range: int = Field(
        ...,
        ge=0,
    )

    assigned_order_mean: float = Field(
        ...,
        ge=0.0,
    )

    assigned_order_std_dev: float = Field(
        ...,
        ge=0.0,
    )

    projected_load_min: int = Field(
        ...,
        ge=0,
    )

    projected_load_max: int = Field(
        ...,
        ge=0,
    )

    projected_load_range: int = Field(
        ...,
        ge=0,
    )

    projected_load_mean: float = Field(
        ...,
        ge=0.0,
    )

    projected_load_std_dev: float = Field(
        ...,
        ge=0.0,
    )

    max_utilization_pct: float = Field(
        ...,
        ge=0.0,
        le=100.0,
    )

    min_utilization_pct: float = Field(
        ...,
        ge=0.0,
        le=100.0,
    )

    fairness_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
    )


# ---------------------------------------------------------------------------
# Cost breakdown response
# ---------------------------------------------------------------------------


class DispatchCostBreakdownResponse(
    DispatchSchemaModel
):
    row_index: int = Field(
        ...,
        ge=0,
    )

    col_index: int = Field(
        ...,
        ge=0,
    )

    driver_id: str
    order_id: str

    distance_m: float = Field(
        ...,
        ge=0.0,
    )

    load_penalty_m: float = Field(
        ...,
        ge=0.0,
    )

    slot_penalty_m: float = Field(
        ...,
        ge=0.0,
    )

    total_cost: float = Field(
        ...,
        ge=0.0,
    )

    # Phase 10:
    #
    # False means the cost is a finite replacement value for a forbidden
    # road-network assignment.
    #
    # Default=True preserves compatibility with Phase 9 response builders.
    allowed: bool = True


# ---------------------------------------------------------------------------
# Greedy vs Hungarian comparison
# ---------------------------------------------------------------------------


class DispatchComparisonResponse(
    DispatchSchemaModel
):
    """
    Assignment comparison summary.

    Under Phase 10 feasibility constraints, assignment count takes priority
    over direct cost comparison.
    """

    hungarian_non_regression: bool

    hungarian_vs_greedy_cost_saved: float

    hungarian_vs_greedy_improvement_pct: float


# ---------------------------------------------------------------------------
# Phase 10 real road-network metadata
# ---------------------------------------------------------------------------


class DispatchUnreachableRoadPairResponse(
    DispatchSchemaModel
):
    """
    One driver-to-order pair with no valid directed road path.
    """

    driver_index: int = Field(
        ...,
        ge=0,
    )

    order_index: int = Field(
        ...,
        ge=0,
    )

    # Optional for compatibility with the current core road-matrix result,
    # which stores indices and graph nodes but not domain IDs directly.
    driver_id: str | None = None
    order_id: str | None = None

    driver_node: int
    order_node: int

    replacement_cost_m: float = Field(
        ...,
        gt=0.0,
    )


class DispatchRoadNetworkResponse(
    DispatchSchemaModel
):
    """
    Phase 10 telemetry for source-Dijkstra road-network dispatch.

    This object is None for Haversine dispatch.
    """

    matrix_source: (
        DispatchMatrixSource
    )

    snapped_driver_count: int = Field(
        ...,
        ge=0,
    )

    snapped_order_count: int = Field(
        ...,
        ge=0,
    )

    unique_driver_node_count: int = Field(
        ...,
        ge=0,
    )

    unique_order_node_count: int = Field(
        ...,
        ge=0,
    )

    source_search_count: int = Field(
        ...,
        ge=0,
    )

    pair_count: int = Field(
        ...,
        ge=0,
    )

    reachable_pair_count: int = Field(
        ...,
        ge=0,
    )

    unreachable_pair_count: int = Field(
        ...,
        ge=0,
    )

    all_pairs_reachable: bool

    unreachable_cost_m: float = Field(
        ...,
        gt=0.0,
    )

    snap_time_ms: float = Field(
        ...,
        ge=0.0,
    )

    cache_lookup_time_ms: float = Field(
        ...,
        ge=0.0,
    )

    cache_write_time_ms: float = Field(
        ...,
        ge=0.0,
    )

    matrix_generation_time_ms: float = Field(
        ...,
        ge=0.0,
    )

    # Matches DispatchRoadMatrixServiceResult.total_time_ms and the updated
    # dispatch_service.py response builder.
    total_time_ms: float = Field(
        ...,
        ge=0.0,
    )

    unreachable_pairs: list[
        DispatchUnreachableRoadPairResponse
    ] = Field(
        default_factory=list,
    )

    @model_validator(
        mode="after"
    )
    def validate_pair_counts(
        self,
    ) -> DispatchRoadNetworkResponse:
        if (
            self.reachable_pair_count
            + self.unreachable_pair_count
            != self.pair_count
        ):
            raise ValueError(
                "reachable_pair_count + "
                "unreachable_pair_count must equal "
                "pair_count."
            )

        if (
            self.all_pairs_reachable
            != (
                self.unreachable_pair_count
                == 0
            )
        ):
            raise ValueError(
                "all_pairs_reachable is inconsistent "
                "with unreachable_pair_count."
            )

        if (
            len(
                self.unreachable_pairs
            )
            != self.unreachable_pair_count
        ):
            raise ValueError(
                "unreachable_pairs length must equal "
                "unreachable_pair_count."
            )

        return self


# ---------------------------------------------------------------------------
# Main dispatch response
# ---------------------------------------------------------------------------


class DispatchCompareResponse(
    DispatchSchemaModel
):
    status: Literal[
        "ok"
    ]

    phase: DispatchPhase

    driver_count: int = Field(
        ...,
        ge=0,
    )

    order_count: int = Field(
        ...,
        ge=0,
    )

    available_slot_count: int = Field(
        ...,
        ge=0,
    )

    assigned_order_count: int = Field(
        ...,
        ge=0,
    )

    unassigned_order_count: int = Field(
        ...,
        ge=0,
    )

    unused_slot_count: int = Field(
        ...,
        ge=0,
    )

    matrix_algorithm: (
        DispatchMatrixAlgorithm
    )

    # ------------------------------------------------------------------
    # Backward-compatible Phase 9 / 9.1 cache fields
    # ------------------------------------------------------------------

    cache_used: bool

    cache_hit: bool = False

    cache_key: str | None = None

    # ------------------------------------------------------------------
    # Phase 10 detailed cache telemetry
    # ------------------------------------------------------------------

    cache_status: (
        DispatchCacheStatus
        | None
    ) = None

    cache_hits: int | None = Field(
        default=None,
        ge=0,
    )

    cache_misses: int | None = Field(
        default=None,
        ge=0,
    )

    cache_error: str | None = None

    # ------------------------------------------------------------------
    # Timing
    # ------------------------------------------------------------------

    cost_matrix_build_time_ms: float = Field(
        ...,
        ge=0.0,
    )

    total_time_ms: float = Field(
        ...,
        ge=0.0,
    )

    # ------------------------------------------------------------------
    # Algorithm results
    # ------------------------------------------------------------------

    greedy: (
        DispatchAlgorithmResultResponse
    )

    hungarian: (
        DispatchAlgorithmResultResponse
    )

    comparison: (
        DispatchComparisonResponse
    )

    # ------------------------------------------------------------------
    # Fairness
    # ------------------------------------------------------------------

    greedy_fairness: (
        DispatchFairnessResponse
    )

    hungarian_fairness: (
        DispatchFairnessResponse
    )

    # ------------------------------------------------------------------
    # Optional detailed evidence
    # ------------------------------------------------------------------

    cost_breakdown: list[
        DispatchCostBreakdownResponse
    ] = Field(
        default_factory=list,
    )

    # None for Haversine.
    # Populated for real-road source_dijkstra.
    road_network: (
        DispatchRoadNetworkResponse
        | None
    ) = None

    @model_validator(
        mode="after"
    )
    def validate_response_counts(
        self,
    ) -> DispatchCompareResponse:
        if (
            self.assigned_order_count
            + self.unassigned_order_count
            != self.order_count
        ):
            raise ValueError(
                "assigned_order_count + "
                "unassigned_order_count must equal "
                "order_count."
            )

        if (
            self.matrix_algorithm
            == "haversine"
            and self.road_network
            is not None
        ):
            raise ValueError(
                "road_network must be None for "
                "haversine dispatch."
            )

        return self


__all__ = [
    "DispatchAlgorithmResultResponse",
    "DispatchAssignmentResponse",
    "DispatchCacheStatus",
    "DispatchCompareRequest",
    "DispatchCompareResponse",
    "DispatchComparisonResponse",
    "DispatchCostBreakdownResponse",
    "DispatchDriverRequest",
    "DispatchFairnessResponse",
    "DispatchMatrixAlgorithm",
    "DispatchMatrixSource",
    "DispatchOrderRequest",
    "DispatchPhase",
    "DispatchRoadNetworkResponse",
    "DispatchSchemaModel",
    "DispatchUnreachableRoadPairResponse",
    "DriverFairnessMetricResponse",
]