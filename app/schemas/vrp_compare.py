# app/schemas/vrp_compare.py

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.vrp import Coordinate, MAX_GREEDY_STOPS


class VrpCompareRequest(BaseModel):
    start: Coordinate

    stops: list[Coordinate] = Field(
        ...,
        min_length=1,
        max_length=MAX_GREEDY_STOPS,
        description="Delivery stops to optimize. Max is 24 stops because Phase 5 matrix supports 25 total locations including depot.",
    )

    return_to_start: bool = Field(
        default=False,
        description="Whether the route should return to the starting depot.",
    )

    matrix_algorithm: Literal["source_dijkstra", "bidirectional_astar"] = Field(
        default="source_dijkstra",
        description="Distance matrix algorithm reused from Phase 5.",
    )

    use_cache: bool = Field(
        default=True,
        description="Whether to use Redis-backed matrix cache.",
    )

    two_opt_max_iterations: int = Field(
        default=100,
        ge=1,
        le=10_000,
        description="Maximum number of 2-Opt improvement iterations.",
    )


class VrpRouteSummary(BaseModel):
    algorithm: Literal["nearest_neighbor_greedy", "two_opt"]

    optimized_order: list[int] = Field(
        ...,
        description="Zero-based stop indexes in visit order.",
    )

    total_distance_m: float = Field(
        ...,
        ge=0,
        description="Total route distance in meters.",
    )

    optimization_time_ms: float = Field(
        ...,
        ge=0,
        description="Algorithm-only optimization time in milliseconds.",
    )


class VrpTwoOptSummary(VrpRouteSummary):
    algorithm: Literal["two_opt"] = "two_opt"

    iterations: int = Field(
        ...,
        ge=0,
        description="Number of 2-Opt scan iterations executed.",
    )

    improvement_count: int = Field(
        ...,
        ge=0,
        description="Number of accepted 2-Opt route improvements.",
    )


class VrpGreedySummary(VrpRouteSummary):
    algorithm: Literal["nearest_neighbor_greedy"] = "nearest_neighbor_greedy"


class VrpImprovementSummary(BaseModel):
    distance_saved_m: float = Field(
        ...,
        description="Greedy distance minus 2-Opt distance. Positive means 2-Opt improved the route.",
    )

    improvement_pct: float = Field(
        ...,
        description="Percentage distance improvement from Greedy to 2-Opt.",
    )

    is_improved_or_equal: bool = Field(
        ...,
        description="True when 2-Opt is not worse than Greedy within tolerance.",
    )

    is_strictly_improved: bool = Field(
        ...,
        description="True when 2-Opt is strictly shorter than Greedy beyond tolerance.",
    )

    tolerance_m: float = Field(
        ...,
        ge=0,
        description="Floating-point comparison tolerance in meters.",
    )


class VrpCompareResponse(BaseModel):
    status: Literal["ok"] = "ok"
    phase: Literal["tier2_phase7"] = "tier2_phase7"

    matrix_algorithm: Literal["source_dijkstra", "bidirectional_astar"]

    stop_count: int = Field(..., ge=1)
    return_to_start: bool

    greedy: VrpGreedySummary
    two_opt: VrpTwoOptSummary
    improvement: VrpImprovementSummary

    matrix_generation_time_ms: float = Field(..., ge=0)
    total_time_ms: float = Field(..., ge=0)
    cache_used: bool | None = None