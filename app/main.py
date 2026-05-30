# app/main.py

from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI

from app.api.graph import router as graph_router
from app.api.health import router as health_router
from app.config import settings
from app.utils.logger import get_logger, setup_logging


setup_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting CityRoute application")

    app.state.started_at = perf_counter()
    app.state.graph = None
    app.state.graph_loaded = False
    app.state.graph_stats = {
        "city": settings.city_name,
        "graph_loaded": False,
        "nodes": 0,
        "edges": 0,
        "load_time_s": None,
        "graph_path": str(settings.graph_path),
        "memory_mb": None,
    }

    logger.info("CityRoute startup complete")

    yield

    logger.info("Shutting down CityRoute application")


app = FastAPI(
    title="CityRoute",
    version="0.1.0",
    description="Open-source last-mile delivery routing engine",
    lifespan=lifespan,
)

app.include_router(health_router, tags=["Health"])
app.include_router(graph_router, tags=["Graph"])


@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "cityroute",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
        "graph_stats": "/graph/stats",
    }
