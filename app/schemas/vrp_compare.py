# app/schemas/vrp_compare.py

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.vrp import Coordinate, MAX_GREEDY_STOPS


MatrixAlgorithm = Literal["source_dijkstra", "bidirectional_astar"]
VrpAlgorithm = Literal["nearest_neighbor_greedy", "two_opt"]
LegPointType = Literal["start", "stop"]
CacheStatus = Literal["hit", "miss", "partial", "disabled", "unknown"]


class VrpCompareRequest(BaseModel):
    start: Coordinate = Field(
        ...,
        description="Starting depot location.",
    )

    stops: list[Coordinate] = Field(
        ...,
        min_length=1,
        max_length=MAX_GREEDY_STOPS,
        description=(
            "Delivery stops to optimize. Max is 24 stops because Phase 5 "
            "matrix supports 25 total locations including depot."
        ),
    )

    return_to_start: bool = Field(
        default=False,
        description="Whether the optimized route should return to the starting depot.",
    )

    matrix_algorithm: MatrixAlgorithm = Field(
        default="source_dijkstra",
        description="Distance matrix algorithm reused from Phase 5.",
    )

    use_cache: bool = Field(
        default=True,
        description="Whether to use Redis-backed matrix cache.",
    )

    ttl_seconds: int | None = Field(
        default=None,
        ge=1,
        description="Optional Redis cache TTL override in seconds.",
    )

    two_opt_max_iterations: int = Field(
        default=100,
        ge=1,
        le=10_000,
        description="Maximum number of 2-Opt improvement iterations.",
    )

    improvement_tolerance_m: float = Field(
        default=0.001,
        ge=0,
        description="Minimum distance improvement required to accept a 2-Opt swap.",
    )

    keep_trace: bool = Field(
        default=True,
        description="Whether to include 2-Opt convergence trace in the response.",
    )


class VrpLeg(BaseModel):
    from_type: LegPointType

    from_index: int | None = Field(
        default=None,
        description="Zero-based stop index. Null when the leg starts from depot.",
    )

    to_type: LegPointType

    to_index: int | None = Field(
        default=None,
        description="Zero-based stop index. Null when the leg returns to depot.",
    )

    distance_m: float = Field(
        ...,
        ge=0,
        description="Road distance for this leg in meters.",
    )


class VrpRouteSummary(BaseModel):
    algorithm: VrpAlgorithm

    optimized_order: list[int] = Field(
        ...,
        description="Zero-based stop indexes in visit order.",
    )

    total_distance_m: float = Field(
        ...,
        ge=0,
        description="Total route distance in meters.",
    )

    legs: list[VrpLeg] = Field(
        default_factory=list,
        description="Route legs with per-leg road distance.",
    )

    optimization_time_ms: float = Field(
        ...,
        ge=0,
        description="Algorithm-only optimization time in milliseconds.",
    )

    iterations: int = Field(
        default=0,
        ge=0,
        description="Number of scan iterations executed by this algorithm.",
    )

    swaps_applied: int = Field(
        default=0,
        ge=0,
        description="Number of accepted improvement swaps.",
    )

    converged: bool = Field(
        default=True,
        description="True when the algorithm stopped because no further improvement was found.",
    )


class VrpGreedySummary(VrpRouteSummary):
    algorithm: Literal["nearest_neighbor_greedy"] = "nearest_neighbor_greedy"


class VrpTwoOptSummary(VrpRouteSummary):
    algorithm: Literal["two_opt"] = "two_opt"


class VrpImprovementSummary(BaseModel):
    baseline_distance_m: float = Field(
        ...,
        ge=0,
        description="Original Greedy route distance in meters.",
    )

    optimized_distance_m: float = Field(
        ...,
        ge=0,
        description="2-Opt route distance in meters.",
    )

    distance_saved_m: float = Field(
        ...,
        description="Greedy distance minus 2-Opt distance. Positive means improvement.",
    )

    improvement_pct: float = Field(
        ...,
        description="Percentage distance improvement from Greedy to 2-Opt.",
    )

    improved: bool = Field(
        ...,
        description="True when 2-Opt found a strictly shorter route.",
    )

    non_regression: bool = Field(
        ...,
        description="True when 2-Opt did not return a route worse than Greedy.",
    )


class TwoOptTraceItem(BaseModel):
    iteration: int = Field(..., ge=0)
    distance_m: float = Field(..., ge=0)
    improved: bool
    swap_i: int | None = None
    swap_j: int | None = None


class VrpCompareResponse(BaseModel):
    status: Literal["ok"] = "ok"
    phase: Literal["tier2_phase7"] = "tier2_phase7"

    comparison: Literal["greedy_vs_two_opt"] = "greedy_vs_two_opt"

    matrix_algorithm: MatrixAlgorithm

    stop_count: int = Field(..., ge=1)
    return_to_start: bool

    greedy: VrpGreedySummary
    two_opt: VrpTwoOptSummary
    improvement: VrpImprovementSummary

    convergence_trace: list[TwoOptTraceItem] = Field(
        default_factory=list,
        description="Optional 2-Opt convergence history.",
    )

    matrix_generation_time_ms: float = Field(..., ge=0)
    total_time_ms: float = Field(..., ge=0)

    cache_used: bool | None = Field(
        default=None,
        description="Whether matrix cache was enabled for this request.",
    )

    cache_status: CacheStatus = Field(
        default="unknown",
        description=(
            "Phase 7.1 cache telemetry status: hit, miss, partial, disabled, "
            "or unknown when the underlying matrix service does not expose enough telemetry."
        ),
    )

    cache_hits: int = Field(
        default=0,
        ge=0,
        description="Number of cache hits reported by the matrix layer.",
    )

    cache_misses: int = Field(
        default=0,
        ge=0,
        description="Number of cache misses reported by the matrix layer.",
    )