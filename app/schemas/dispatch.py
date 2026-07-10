# app/schemas/dispatch.py

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DispatchPhase = Literal["tier3_phase9", "tier3_phase9_1"]
DispatchMatrixAlgorithm = Literal["haversine", "source_dijkstra"]


class DispatchDriverRequest(BaseModel):
    driver_id: str = Field(..., min_length=1, max_length=100)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    current_load: int = Field(default=0, ge=0)
    max_capacity: int = Field(default=1, ge=1)


class DispatchOrderRequest(BaseModel):
    order_id: str = Field(..., min_length=1, max_length=100)
    pickup_lat: float = Field(..., ge=-90, le=90)
    pickup_lon: float = Field(..., ge=-180, le=180)


class DispatchCompareRequest(BaseModel):
    drivers: list[DispatchDriverRequest] = Field(..., min_length=1, max_length=50)
    orders: list[DispatchOrderRequest] = Field(..., min_length=1, max_length=50)

    matrix_algorithm: DispatchMatrixAlgorithm = "haversine"
    use_cache: bool = True

    load_penalty_m: float = Field(default=0.0, ge=0)
    slot_penalty_m: float = Field(default=0.0, ge=0)

    return_cost_breakdown: bool = False


class DispatchAssignmentResponse(BaseModel):
    driver_id: str
    order_id: str
    row_index: int
    col_index: int
    cost: float


class DispatchAlgorithmResultResponse(BaseModel):
    algorithm: str
    assignments: list[DispatchAssignmentResponse]
    total_cost: float
    assigned_count: int
    unassigned_driver_slot_rows: list[int]
    unassigned_order_ids: list[str]


class DriverFairnessMetricResponse(BaseModel):
    driver_id: str
    current_load: int
    max_capacity: int
    available_slots: int
    assigned_orders: int
    projected_load: int
    remaining_capacity: int
    utilization_pct: float


class DispatchFairnessResponse(BaseModel):
    driver_metrics: list[DriverFairnessMetricResponse]
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


class DispatchCostBreakdownResponse(BaseModel):
    row_index: int
    col_index: int
    driver_id: str
    order_id: str
    distance_m: float
    load_penalty_m: float
    slot_penalty_m: float
    total_cost: float


class DispatchComparisonResponse(BaseModel):
    hungarian_non_regression: bool
    hungarian_vs_greedy_cost_saved: float
    hungarian_vs_greedy_improvement_pct: float


class DispatchCompareResponse(BaseModel):
    status: Literal["ok"]
    phase: DispatchPhase

    driver_count: int
    order_count: int
    available_slot_count: int
    assigned_order_count: int
    unassigned_order_count: int
    unused_slot_count: int

    matrix_algorithm: DispatchMatrixAlgorithm

    # Phase 9 kept only cache_used.
    # Phase 9.1 adds cache_hit/cache_key so evidence can prove repeated-request behavior.
    cache_used: bool
    cache_hit: bool = False
    cache_key: str | None = None

    cost_matrix_build_time_ms: float
    total_time_ms: float

    greedy: DispatchAlgorithmResultResponse
    hungarian: DispatchAlgorithmResultResponse
    comparison: DispatchComparisonResponse

    greedy_fairness: DispatchFairnessResponse
    hungarian_fairness: DispatchFairnessResponse

    cost_breakdown: list[DispatchCostBreakdownResponse] = Field(default_factory=list)


__all__ = [
    "DispatchAlgorithmResultResponse",
    "DispatchAssignmentResponse",
    "DispatchCompareRequest",
    "DispatchCompareResponse",
    "DispatchComparisonResponse",
    "DispatchCostBreakdownResponse",
    "DispatchDriverRequest",
    "DispatchFairnessResponse",
    "DispatchMatrixAlgorithm",
    "DispatchOrderRequest",
    "DispatchPhase",
    "DriverFairnessMetricResponse",
]