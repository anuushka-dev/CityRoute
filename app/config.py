# app/config.py

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "CityRoute"
    environment: str = "local"
    city_name: str = "Kanpur Central, Uttar Pradesh, India"
    log_level: str = "INFO"

    data_dir: Path = Path("data")
    graph_dir: Path = Path("data/graphs")
    graph_file: str = "kanpur_central.graphml"

    use_bbox_graph: bool = True

    bbox_north: float = 26.50
    bbox_south: float = 26.43
    bbox_east: float = 80.38
    bbox_west: float = 80.28

    # Tier 2 Phase 5 / 5.1 - Distance Matrix + Redis cache
    redis_url: str = "redis://localhost:6379/0"
    matrix_cache_ttl_seconds: int = 86_400
    matrix_max_locations: int = 25
    matrix_workers: int = 8

    # Tier 2 Phase 6 - Greedy Baseline
    # Phase 5 matrix limit is 25 total locations:
    # 1 start + 24 delivery stops.
    vrp_max_stops: int = 24
    vrp_default_matrix_algorithm: str = "source_dijkstra"
    vrp_default_use_cache: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CITYROUTE_",
        extra="ignore",
    )

    @property
    def graph_path(self) -> Path:
        return self.graph_dir / self.graph_file


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()