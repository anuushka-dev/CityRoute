# app/schemas/vrp.py

from typing import Literal

from pydantic import BaseModel, Field

MAX_TOTAL_MATRIX_LOCATIONS = 25
MAX_GREEDY_STOPS = MAX_TOTAL_MATRIX_LOCATIONS - 1


class Coordinate(BaseModel):

    lat: float = Field(
        ...,
        ge=-90,
        le=90,
        description="Latitude in decimal degrees.",
        examples=[26.44],
    )
    lon: float = Field(
        ...,
        ge=-180,
        le=180,
        description="Longitude in decimal degrees.",
        examples=[80.30],
    )


class GreedyRouteRequest(BaseModel):

    start: Coordinate = Field(
        ...,
        description="Starting location, usually depot or driver current position.",
    )
    stops: list[Coordinate] = Field(
        ...,
        min_length=1,
        max_length=MAX_GREEDY_STOPS,
        description=(
            "Delivery stops to order. Max is 24 because Phase 5 matrix limit is "
            "25 total locations: 1 start + 24 stops."
        ),
    )
    return_to_start: bool = Field(
        default=False,
        description="Whether the greedy route should return to the start after visiting all stops.",
    )
    matrix_algorithm: Literal["source_dijkstra", "bidirectional_astar"] = Field(
        default="source_dijkstra",
        description="Phase 5 matrix algorithm used before greedy ordering.",
    )
    use_cache: bool = Field(
        default=True,
        description="Whether Redis matrix cache should be used when available.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "start": {"lat": 26.44, "lon": 80.30},
                "stops": [
                    {"lat": 26.45, "lon": 80.35},
                    {"lat": 26.47, "lon": 80.31},
                    {"lat": 26.43, "lon": 80.34},
                ],
                "return_to_start": False,
                "matrix_algorithm": "source_dijkstra",
                "use_cache": True,
            }
        }
    }


class GreedyLegResponse(BaseModel):

    from_type: Literal["start", "stop"] = Field(
        ...,
        description="Whether this leg starts from the start point or a stop.",
    )
    from_index: int | None = Field(
        default=None,
        ge=0,
        description="0-based stop index if from_type is stop; null if from_type is start.",
    )
    to_type: Literal["start", "stop"] = Field(
        ...,
        description="Whether this leg ends at the start point or a stop.",
    )
    to_index: int | None = Field(
        default=None,
        ge=0,
        description="0-based stop index if to_type is stop; null if to_type is start.",
    )
    distance_m: float = Field(
        ...,
        ge=0,
        description="Road distance for this leg in meters.",
    )


class GreedyRouteResponse(BaseModel):

    status: Literal["ok"] = "ok"
    phase: Literal["tier2_phase6"] = "tier2_phase6"
    algorithm: Literal["nearest_neighbor_greedy"] = "nearest_neighbor_greedy"

    matrix_algorithm: Literal["source_dijkstra", "bidirectional_astar"]

    stop_count: int = Field(..., ge=1)
    optimized_order: list[int] = Field(
        ...,
        description="0-based stop visit order returned by nearest-neighbor greedy.",
    )

    total_distance_m: float = Field(..., ge=0)
    return_to_start: bool

    legs: list[GreedyLegResponse]

    matrix_generation_time_ms: float = Field(..., ge=0)
    optimization_time_ms: float = Field(..., ge=0)
    total_time_ms: float = Field(..., ge=0)

    cache_used: bool | None = Field(
        default=None,
        description="Whether Phase 5 matrix result came from cache, if available.",
    )