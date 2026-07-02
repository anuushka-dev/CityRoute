from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MatrixAlgorithm = Literal["source_dijkstra", "bidirectional_astar"]


class AdvancedCompareLocation(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)


class AdvancedCompareRequest(BaseModel):
    start: AdvancedCompareLocation
    stops: list[AdvancedCompareLocation] = Field(..., min_length=1, max_length=24)

    return_to_start: bool = False
    matrix_algorithm: MatrixAlgorithm = "source_dijkstra"
    use_cache: bool = True

    two_opt_max_iterations: int = Field(default=100, ge=1, le=10_000)
    two_opt_improvement_tolerance_m: float = Field(default=0.001, ge=0.0)

    lns_max_iterations: int = Field(default=500, ge=1, le=50_000)
    lns_destroy_fraction: float = Field(default=0.30, gt=0.0, le=1.0)
    lns_no_improvement_limit: int = Field(default=100, ge=1, le=50_000)
    lns_random_seed: int | None = None

    keep_trace: bool = False


class AdvancedRouteLeg(BaseModel):
    from_type: str
    from_index: int | None
    to_type: str
    to_index: int | None
    distance_m: float


class AdvancedGreedyResult(BaseModel):
    algorithm: Literal["nearest_neighbor_greedy"]
    optimized_order: list[int]
    total_distance_m: float
    legs: list[AdvancedRouteLeg]
    optimization_time_ms: float


class AdvancedTwoOptTraceItem(BaseModel):
    iteration: int
    best_distance_m: float
    improved: bool


class AdvancedTwoOptResult(BaseModel):
    algorithm: Literal["two_opt"]
    optimized_order: list[int]
    total_distance_m: float
    initial_distance_m: float
    distance_saved_m: float
    improvement_pct: float
    iterations_run: int
    swaps_applied: int
    converged: bool
    legs: list[AdvancedRouteLeg]
    optimization_time_ms: float
    trace: list[AdvancedTwoOptTraceItem] = Field(default_factory=list)


class AdvancedLNSTraceItem(BaseModel):
    iteration: int
    best_distance_m: float
    candidate_distance_m: float
    improved: bool
    removed_count: int


class AdvancedLNSResult(BaseModel):
    algorithm: Literal["large_neighborhood_search"]
    optimized_order: list[int]
    total_distance_m: float
    initial_distance_m: float
    distance_saved_m: float
    improvement_pct: float
    iterations_run: int
    improvements_applied: int
    converged: bool
    random_seed: int | None
    legs: list[AdvancedRouteLeg]
    optimization_time_ms: float
    trace: list[AdvancedLNSTraceItem] = Field(default_factory=list)


class AdvancedComparisonSummary(BaseModel):
    two_opt_vs_greedy_distance_saved_m: float
    two_opt_vs_greedy_improvement_pct: float

    lns_vs_two_opt_distance_saved_m: float
    lns_vs_two_opt_improvement_pct: float

    lns_vs_greedy_distance_saved_m: float
    lns_vs_greedy_improvement_pct: float

    two_opt_non_regression: bool
    lns_non_regression: bool


class AdvancedCompareResponse(BaseModel):
    status: Literal["ok"]
    phase: Literal["tier3_phase8"]
    matrix_algorithm: MatrixAlgorithm
    stop_count: int
    return_to_start: bool

    greedy: AdvancedGreedyResult
    two_opt: AdvancedTwoOptResult
    lns: AdvancedLNSResult
    comparison: AdvancedComparisonSummary

    matrix_generation_time_ms: float
    cache_used: bool
    cache_status: str | None = None
    cache_hits: int = 0
    cache_misses: int = 0

    total_time_ms: float