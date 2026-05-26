# app/config.py
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "CityRoute"
    environment: str = "local"
    city_name: str = "Kanpur, Uttar Pradesh, India"
    log_level: str = "INFO"

    data_dir: Path = Path("data")
    graph_dir: Path = Path("data/graphs")
    graph_file: str = "kanpur.graphml"

    model_config = SettingsConfigDict(
        env_file=".env", 
        env_prefix="CITYROUTE_", 
        extra="ignore",
        )

    @property
    def graph_path(self) -> Path:
        return self.graph_dir / self.graph_file

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()