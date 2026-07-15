# app/models/matrix_model.py

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SUPPORTED_MATRIX_ALGORITHMS = (
    "source_dijkstra",
    "bidirectional_astar",
    "astar",
)


class MatrixLocation(BaseModel):

    id: str = Field(..., min_length=1, max_length=80)
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "depot",
                "lat": 26.44,
                "lon": 80.30,
            }
        }
    )

    @field_validator("id")
    @classmethod
    def clean_location_id(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Location id cannot be empty.")

        return cleaned


class MatrixRequest(BaseModel):

    locations: list[MatrixLocation] = Field(
        ...,
        min_length=1,
        description="Ordered list of GPS locations for directed N×N matrix generation.",
    )

    algorithm: str = Field(
        default="source_dijkstra",
        description=(
            "Matrix generation algorithm. Supported values: "
            "source_dijkstra, bidirectional_astar, astar. "
            "source_dijkstra is the optimized Phase 5.1 default for matrix workloads."
        ),
    )

    use_cache: bool = Field(
        default=True,
        description="When true, Redis cache is checked before computing the matrix.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "locations": [
                    {"id": "depot", "lat": 26.44, "lon": 80.30},
                    {"id": "stop_1", "lat": 26.45, "lon": 80.35},
                    {"id": "stop_2", "lat": 26.46, "lon": 80.33},
                ],
                "algorithm": "source_dijkstra",
                "use_cache": True,
            }
        }
    )

    @field_validator("algorithm")
    @classmethod
    def clean_algorithm(cls, value: str) -> str:
        cleaned = value.strip().lower()

        if not cleaned:
            raise ValueError("Algorithm cannot be empty.")

        return cleaned

    @model_validator(mode="after")
    def validate_unique_location_ids(self) -> MatrixRequest:
        ids = [location.id for location in self.locations]

        if len(ids) != len(set(ids)):
            raise ValueError("Location ids must be unique inside one matrix request.")

        return self


class MatrixCacheMetadata(BaseModel):
    enabled: bool
    hit: bool
    key: str | None = None
    ttl_seconds: int
    error: str | None = None


class MatrixPairFailure(BaseModel):

    from_index: int
    to_index: int
    from_id: str
    to_id: str
    error: str


class MatrixResponse(BaseModel):

    status: str
    n: int
    algorithm: str
    cache: MatrixCacheMetadata

    locations: list[MatrixLocation]

    matrix_distance_m: list[list[float | None]]
    matrix_eta_s: list[list[float | None]]

    pair_count: int
    computed_pairs: int
    failed_pairs: int
    failures: list[MatrixPairFailure] = Field(default_factory=list)

    generation_time_ms: float
    parallel_workers: int

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "ok",
                "n": 3,
                "algorithm": "source_dijkstra",
                "cache": {
                    "enabled": True,
                    "hit": False,
                    "key": (
                        "matrix:v1:data/graphs/kanpur_central.graphml:"
                        "source_dijkstra:abc123"
                    ),
                    "ttl_seconds": 86400,
                    "error": None,
                },
                "locations": [
                    {"id": "depot", "lat": 26.44, "lon": 80.30},
                    {"id": "stop_1", "lat": 26.45, "lon": 80.35},
                    {"id": "stop_2", "lat": 26.46, "lon": 80.33},
                ],
                "matrix_distance_m": [
                    [0.0, 6428.798, 3120.4],
                    [6501.2, 0.0, 1800.9],
                    [3300.1, 1750.3, 0.0],
                ],
                "matrix_eta_s": [
                    [0.0, 999.5, 480.2],
                    [1012.4, 0.0, 288.1],
                    [510.5, 280.9, 0.0],
                ],
                "pair_count": 9,
                "computed_pairs": 9,
                "failed_pairs": 0,
                "failures": [],
                "generation_time_ms": 245.2,
                "parallel_workers": 8,
            }
        }
    )


class MatrixComputationResult(BaseModel):

    matrix_distance_m: list[list[float | None]]
    matrix_eta_s: list[list[float | None]]
    pair_count: int
    computed_pairs: int
    failed_pairs: int
    failures: list[MatrixPairFailure] = Field(default_factory=list)


JsonDict = dict[str, Any]