# app/config.py

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central CityRoute application configuration.

    Environment variables use the `CITYROUTE_` prefix.

    Example:

        CITYROUTE_CONCURRENCY_MAX_ACTIVE_REQUESTS=4
        CITYROUTE_ROUTE_TIMEOUT_S=5
        CITYROUTE_REDIS_FAIL_OPEN=true
    """

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------

    app_name: str = "CityRoute"
    environment: str = "local"
    city_name: str = "Kanpur Central, Uttar Pradesh, India"
    log_level: str = "INFO"

    # ------------------------------------------------------------------
    # Graph storage and loading
    # ------------------------------------------------------------------

    data_dir: Path = Path("data")
    graph_dir: Path = Path("data/graphs")
    graph_file: str = "kanpur_central.graphml"

    use_bbox_graph: bool = True

    bbox_north: float = Field(default=26.50, ge=-90.0, le=90.0)
    bbox_south: float = Field(default=26.43, ge=-90.0, le=90.0)
    bbox_east: float = Field(default=80.38, ge=-180.0, le=180.0)
    bbox_west: float = Field(default=80.28, ge=-180.0, le=180.0)

    # ------------------------------------------------------------------
    # Tier 2 Phase 5 / 5.1 - Distance Matrix and Redis
    # ------------------------------------------------------------------

    redis_url: str = "redis://localhost:6379/0"
    redis_socket_timeout_s: float = Field(default=2.0, gt=0.0)

    matrix_cache_ttl_seconds: int = Field(
        default=86_400,
        ge=1,
    )
    matrix_max_locations: int = Field(
        default=25,
        ge=2,
    )
    matrix_workers: int = Field(
        default=8,
        ge=1,
    )

    # ------------------------------------------------------------------
    # Tier 2 Phase 6+ - Vehicle Routing
    # ------------------------------------------------------------------

    # Matrix limit is 25 total locations:
    # one start location plus at most 24 delivery stops.
    vrp_max_stops: int = Field(
        default=24,
        ge=1,
    )
    vrp_default_matrix_algorithm: str = "source_dijkstra"
    vrp_default_use_cache: bool = True

    # ------------------------------------------------------------------
    # Tier 4 Phase 11 - Reliability feature controls
    # ------------------------------------------------------------------

    lifecycle_guard_enabled: bool = True
    concurrency_control_enabled: bool = True
    request_timeout_enabled: bool = True
    redis_recovery_enabled: bool = True
    graceful_shutdown_enabled: bool = True
    metrics_enabled: bool = True

    # ------------------------------------------------------------------
    # Phase 11 - Readiness policy
    # ------------------------------------------------------------------

    readiness_require_graph: bool = True
    readiness_require_snap_index: bool = True
    readiness_require_adjacency: bool = True

    # Redis remains optional because cache operations are fail-open by
    # default. Set this to true when Redis must block production readiness.
    readiness_require_redis: bool = False
    redis_fail_open: bool = True

    # ------------------------------------------------------------------
    # Phase 11 - Bounded concurrency and backpressure
    # ------------------------------------------------------------------

    # These limits are process-local. With four Uvicorn workers and an active
    # limit of four, the approximate process-wide maximum is sixteen active
    # protected requests.
    concurrency_max_active_requests: int = Field(
        default=4,
        ge=1,
    )
    concurrency_max_waiting_requests: int = Field(
        default=8,
        ge=0,
    )
    concurrency_wait_timeout_s: float = Field(
        default=1.0,
        ge=0.0,
    )
    concurrency_retry_after_s: int = Field(
        default=1,
        ge=0,
    )
    concurrency_emit_admission_headers: bool = True

    # Lifecycle guard rejection response.
    lifecycle_retry_after_s: int = Field(
        default=1,
        ge=0,
    )

    # ------------------------------------------------------------------
    # Phase 11 - Endpoint-specific execution timeouts
    # ------------------------------------------------------------------

    route_timeout_s: float = Field(
        default=5.0,
        gt=0.0,
    )
    route_compare_timeout_s: float = Field(
        default=10.0,
        gt=0.0,
    )
    matrix_timeout_s: float = Field(
        default=15.0,
        gt=0.0,
    )
    vrp_timeout_s: float = Field(
        default=20.0,
        gt=0.0,
    )
    advanced_vrp_timeout_s: float = Field(
        default=30.0,
        gt=0.0,
    )
    dispatch_timeout_s: float = Field(
        default=20.0,
        gt=0.0,
    )

    request_timeout_cancellation_grace_s: float = Field(
        default=0.05,
        ge=0.0,
    )
    request_timeout_emit_headers: bool = True

    # ------------------------------------------------------------------
    # Phase 11 - Redis failure handling and recovery
    # ------------------------------------------------------------------

    redis_recovery_interval_s: float = Field(
        default=5.0,
        gt=0.0,
    )
    redis_max_recovery_interval_s: float = Field(
        default=60.0,
        gt=0.0,
    )
    redis_recovery_backoff_multiplier: float = Field(
        default=2.0,
        ge=1.0,
    )
    redis_run_sync_healthcheck_in_thread: bool = True

    # Optional background health-check cadence. The recovery controller
    # itself still enforces its own bounded exponential backoff.
    redis_healthcheck_interval_s: float = Field(
        default=15.0,
        gt=0.0,
    )

    # ------------------------------------------------------------------
    # Phase 11 - Graceful shutdown
    # ------------------------------------------------------------------

    shutdown_drain_timeout_s: float = Field(
        default=30.0,
        ge=0.0,
    )
    shutdown_cleanup_timeout_s: float = Field(
        default=15.0,
        ge=0.0,
    )
    shutdown_default_hook_timeout_s: float = Field(
        default=5.0,
        ge=0.0,
    )
    shutdown_run_sync_hooks_in_thread: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="CITYROUTE_",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator(
        "app_name",
        "environment",
        "city_name",
        "graph_file",
        "vrp_default_matrix_algorithm",
    )
    @classmethod
    def validate_non_empty_text(
        cls,
        value: str,
    ) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError("Configuration string must not be empty")

        return normalized

    @field_validator("log_level")
    @classmethod
    def validate_log_level(
        cls,
        value: str,
    ) -> str:
        normalized = value.strip().upper()

        supported_levels = {
            "CRITICAL",
            "ERROR",
            "WARNING",
            "INFO",
            "DEBUG",
        }

        if normalized not in supported_levels:
            allowed = ", ".join(sorted(supported_levels))
            raise ValueError(
                f"Unsupported log level {value!r}; expected one of: "
                f"{allowed}"
            )

        return normalized

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(
        cls,
        value: str,
    ) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError("redis_url must not be empty")

        return normalized

    @model_validator(mode="after")
    def validate_configuration(
        self,
    ) -> Settings:
        if self.bbox_north <= self.bbox_south:
            raise ValueError(
                "bbox_north must be greater than bbox_south"
            )

        if self.bbox_east <= self.bbox_west:
            raise ValueError(
                "bbox_east must be greater than bbox_west"
            )

        required_matrix_locations = self.vrp_max_stops + 1

        if required_matrix_locations > self.matrix_max_locations:
            raise ValueError(
                "vrp_max_stops plus the start location cannot exceed "
                "matrix_max_locations"
            )

        if (
            self.redis_max_recovery_interval_s
            < self.redis_recovery_interval_s
        ):
            raise ValueError(
                "redis_max_recovery_interval_s must be greater than or "
                "equal to redis_recovery_interval_s"
            )

        if (
            self.route_compare_timeout_s
            < self.route_timeout_s
        ):
            raise ValueError(
                "route_compare_timeout_s must be greater than or equal "
                "to route_timeout_s"
            )

        if (
            self.advanced_vrp_timeout_s
            < self.vrp_timeout_s
        ):
            raise ValueError(
                "advanced_vrp_timeout_s must be greater than or equal "
                "to vrp_timeout_s"
            )

        if (
            not self.redis_fail_open
            and not self.readiness_require_redis
        ):
            raise ValueError(
                "readiness_require_redis must be true when "
                "redis_fail_open is false"
            )

        return self

    @property
    def graph_path(self) -> Path:
        """Return the complete configured GraphML path."""

        return self.graph_dir / self.graph_file


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the process-local cached settings instance.

    Tests that modify environment variables should call:

        get_settings.cache_clear()
    """

    return Settings()


settings = get_settings()


__all__ = [
    "Settings",
    "get_settings",
    "settings",
]