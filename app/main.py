# app/main.py

from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI

from app.api.graph import router as graph_router
from app.api.health import router as health_router
from app.api.route import router as route_router
from app.config import settings
from app.services.graph_service import load_or_download_graph
from app.utils.logger import get_logger, setup_logging

setup_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting CityRoute application")

    app.state.started_at = perf_counter()
    logger.info("Loading CityRoute graph")

    graph, graph_stats = load_or_download_graph()

    app.state.graph = graph
    app.state.graph_loaded = graph is not None
    app.state.graph_stats = graph_stats
    app.state.snap_index = None

    # Safe defaults for Phase 2 + Phase 3 observability.
    # These fields should exist even if graph loading fails.
    app.state.graph_stats["snap_index_loaded"] = False
    app.state.graph_stats["snap_index_build_time_ms"] = None

    if graph is not None:
        from app.utils.snap_index import build_snap_index

        logger.info("Building snap index")
        snap_index = build_snap_index(graph)

        app.state.snap_index = snap_index
        app.state.graph_stats["snap_index_loaded"] = True
        app.state.graph_stats["snap_index_build_time_ms"] = snap_index.build_time_ms

        logger.info(
            "Snap index ready | nodes=%s | build_time_ms=%s",
            len(snap_index.node_ids),
            snap_index.build_time_ms,
        )
    else:
        logger.warning(
            "Graph not loaded. Route, snap, and routing-dependent endpoints will return unavailable responses."
        )

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
app.include_router(route_router, tags=["Route"])


@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "cityroute",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
        "graph_stats": "/graph/stats",
        "route": "/route",
        "phase": "Tier 1 Phase 3 - A* Routing",
    }