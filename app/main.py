# app/main.py

from __future__ import annotations

from collections.abc import Sequence
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Any

from fastapi import FastAPI

from app.api.dispatch import router as dispatch_router
from app.api.graph import router as graph_router
from app.api.health import router as health_router
from app.api.matrix import router as matrix_router
from app.api.route import router as route_router
from app.api.vrp import router as vrp_router
from app.config import settings
from app.core.graph_adjacency import (
    GraphAdjacency,
    build_graph_adjacency,
)
from app.core.multi_target_dijkstra import (
    multi_target_dijkstra,
)
from app.infrastructure.redis_cache import RedisCache
from app.observability.metrics import metrics_endpoint, metrics_middleware
from app.services.dispatch_road_matrix_service import (
    DispatchRoadMatrixDependencies,
)
from app.services.graph_service import load_or_download_graph
from app.utils.logger import get_logger, setup_logging
from app.utils.matrix_cache_key import (
    make_dispatch_road_matrix_cache_key_builder,
)
from app.utils.snap_index import (
    SnapIndex,
    build_snap_index,
    query_snap_index,
)

APP_VERSION = "0.1.0"

PROJECT_PHASE_CODE = "tier3_phase10"

PROJECT_PHASE_NAME = (
    "Tier 3 Phase 10 - Real Road-Network Dispatch Integration"
)


setup_logging(settings.log_level)
logger = get_logger(__name__)


def _build_dispatch_snap_adapter(
    *,
    graph: Any,
    snap_index: SnapIndex,
):

    def snap_node(
        lat: float,
        lon: float,
    ) -> int:
        result = query_snap_index(
            graph=graph,
            snap_index=snap_index,
            lat=float(lat),
            lon=float(lon),
        )

        return int(
            result["nearest_node"]
        )

    return snap_node


def _build_dispatch_source_distance_adapter(
    *,
    adjacency: GraphAdjacency,
):

    def source_distance_builder(
        source_node: int,
        target_nodes: Sequence[int],
    ) -> dict[int, float | None]:
        target_set = {
            int(node_id)
            for node_id in target_nodes
        }

        result = multi_target_dijkstra(
            adjacency=adjacency,
            source_node=int(source_node),
            target_nodes=target_set,
        )

        return {
            int(target_node): (
                None
                if distance_m is None
                else float(distance_m)
            )
            for (
                target_node,
                distance_m,
            ) in result.target_distances_m.items()
        }

    return source_distance_builder


def _build_dispatch_cache_get_adapter(
    redis_cache: RedisCache,
):

    def cache_get(
        key: str,
    ) -> Any:
        return redis_cache.client.get(
            key
        )

    return cache_get


def _build_dispatch_cache_set_adapter(
    redis_cache: RedisCache,
):

    def cache_set(
        key: str,
        value: str,
        ttl_seconds: int,
    ) -> bool:
        return bool(
            redis_cache.client.set(
                name=key,
                value=value,
                ex=ttl_seconds,
            )
        )

    return cache_set


@asynccontextmanager
async def lifespan(
    app: FastAPI,
):
    logger.info(
        "Starting CityRoute application | phase=%s",
        PROJECT_PHASE_CODE,
    )

    app.state.started_at = (
        perf_counter()
    )

    app.state.phase = (
        PROJECT_PHASE_CODE
    )

    app.state.phase_name = (
        PROJECT_PHASE_NAME
    )

    # ------------------------------------------------------------------
    # Phase 10 safe defaults.
    # ------------------------------------------------------------------

    app.state.dispatch_road_matrix_dependencies = None

    app.state.dispatch_road_matrix_ready = False

    app.state.dispatch_road_matrix_error = None

    app.state.dispatch_graph_adjacency = None

    app.state.dispatch_redis_cache = None

    app.state.dispatch_road_cache_available = False

    # ------------------------------------------------------------------
    # 1. Load the road graph.
    # ------------------------------------------------------------------

    logger.info(
        "Loading CityRoute graph"
    )

    graph, graph_stats = (
        load_or_download_graph()
    )

    app.state.graph = graph

    app.state.graph_loaded = (
        graph is not None
    )

    app.state.graph_stats = (
        graph_stats
    )

    app.state.snap_index = None

    # ------------------------------------------------------------------
    # 2. Safe observability defaults.
    # ------------------------------------------------------------------

    app.state.graph_stats[
        "snap_index_loaded"
    ] = False

    app.state.graph_stats[
        "snap_index_build_time_ms"
    ] = None

    app.state.graph_stats[
        "snap_index_method"
    ] = None

    app.state.graph_stats[
        "snap_index_import_error"
    ] = None

    app.state.graph_stats[
        "dispatch_adjacency_loaded"
    ] = False

    app.state.graph_stats[
        "dispatch_adjacency_build_time_ms"
    ] = None

    app.state.graph_stats[
        "dispatch_adjacency_node_count"
    ] = None

    app.state.graph_stats[
        "dispatch_adjacency_edge_count"
    ] = None

    app.state.graph_stats[
        "dispatch_road_matrix_ready"
    ] = False

    app.state.graph_stats[
        "dispatch_road_cache_available"
    ] = False

    app.state.graph_stats[
        "dispatch_road_matrix_error"
    ] = None

    # ------------------------------------------------------------------
    # 3. Build BallTree snap index.
    # ------------------------------------------------------------------

    if graph is not None:
        logger.info(
            "Building snap index"
        )

        try:
            snap_index = (
                build_snap_index(
                    graph
                )
            )

            app.state.snap_index = (
                snap_index
            )

            app.state.graph_stats[
                "snap_index_loaded"
            ] = True

            app.state.graph_stats[
                "snap_index_build_time_ms"
            ] = (
                snap_index.build_time_ms
            )

            app.state.graph_stats[
                "snap_index_method"
            ] = (
                snap_index.method
            )

            app.state.graph_stats[
                "snap_index_import_error"
            ] = (
                snap_index.import_error
            )

            logger.info(
                (
                    "Snap index ready | "
                    "nodes=%s | "
                    "method=%s | "
                    "build_time_ms=%s"
                ),
                len(
                    snap_index.node_ids
                ),
                snap_index.method,
                snap_index.build_time_ms,
            )

            if (
                snap_index.import_error
                is not None
            ):
                logger.warning(
                    (
                        "BallTree unavailable. "
                        "Using linear fallback snap index | "
                        "error=%s"
                    ),
                    snap_index.import_error,
                )

        except Exception as exc:
            logger.exception(
                "Snap index build failed: %s",
                exc,
            )

            app.state.snap_index = (
                None
            )

            app.state.graph_stats[
                "snap_index_loaded"
            ] = False

            app.state.graph_stats[
                "snap_index_build_time_ms"
            ] = None

            app.state.graph_stats[
                "snap_index_method"
            ] = None

            app.state.graph_stats[
                "snap_index_import_error"
            ] = repr(
                exc
            )

    else:
        logger.warning(

                "Graph not loaded. "
                "Route, snap, matrix, VRP, and "
                "road-network dispatch operations "
                "will be unavailable."

        )

    # ------------------------------------------------------------------
    # 4. Build Phase 10 reusable graph adjacency.
    #
    # This is built once during startup and reused by all road-aware
    # dispatch requests.
    # ------------------------------------------------------------------

    if (
        app.state.graph is not None
        and app.state.snap_index is not None
    ):
        logger.info(
            "Building Phase 10 dispatch graph adjacency"
        )

        try:
            dispatch_adjacency = (
                build_graph_adjacency(
                    app.state.graph
                )
            )

            app.state.dispatch_graph_adjacency = (
                dispatch_adjacency
            )

            app.state.graph_stats[
                "dispatch_adjacency_loaded"
            ] = True

            app.state.graph_stats[
                "dispatch_adjacency_build_time_ms"
            ] = (
                dispatch_adjacency.build_time_ms
            )

            app.state.graph_stats[
                "dispatch_adjacency_node_count"
            ] = (
                dispatch_adjacency.node_count
            )

            app.state.graph_stats[
                "dispatch_adjacency_edge_count"
            ] = (
                dispatch_adjacency.edge_count
            )

            logger.info(
                (
                    "Phase 10 dispatch adjacency ready | "
                    "nodes=%s | "
                    "edges=%s | "
                    "directed=%s | "
                    "build_time_ms=%s"
                ),
                dispatch_adjacency.node_count,
                dispatch_adjacency.edge_count,
                dispatch_adjacency.directed,
                dispatch_adjacency.build_time_ms,
            )

        except Exception as exc:
            logger.exception(
                (
                    "Phase 10 dispatch adjacency "
                    "build failed: %s"
                ),
                exc,
            )

            app.state.dispatch_graph_adjacency = (
                None
            )

            app.state.dispatch_road_matrix_error = (
                "dispatch_adjacency_build_failed"
            )

            app.state.graph_stats[
                "dispatch_adjacency_loaded"
            ] = False

            app.state.graph_stats[
                "dispatch_road_matrix_error"
            ] = repr(
                exc
            )

    # ------------------------------------------------------------------
    # 5. Initialize Redis for Phase 10 road-matrix caching.
    #
    # Redis is not required for the road algorithm itself.
    #
    # If Redis is unavailable:
    # - road dispatch can still work with use_cache=false
    # - cache operations fail open inside the road-matrix service
    # ------------------------------------------------------------------

    redis_cache: RedisCache | None = None

    try:
        redis_cache = RedisCache(
            redis_url=str(
                settings.redis_url
            ),
            ttl_seconds=int(
                settings.matrix_cache_ttl_seconds
            ),
        )

        app.state.dispatch_redis_cache = (
            redis_cache
        )

        try:
            redis_available = (
                redis_cache.ping()
            )

        except Exception as exc:
            redis_available = False

            logger.warning(
                (
                    "Phase 10 Redis startup ping failed | "
                    "url=%s | "
                    "error=%s"
                ),
                settings.redis_url,
                exc,
            )

        app.state.dispatch_road_cache_available = (
            bool(
                redis_available
            )
        )

        app.state.graph_stats[
            "dispatch_road_cache_available"
        ] = bool(
            redis_available
        )

        if redis_available:
            logger.info(
                (
                    "Phase 10 Redis cache ready | "
                    "url=%s"
                ),
                settings.redis_url,
            )

    except Exception as exc:
        logger.warning(
            (
                "Phase 10 Redis initialization failed | "
                "error=%s"
            ),
            exc,
        )

        redis_cache = None

        app.state.dispatch_redis_cache = (
            None
        )

        app.state.dispatch_road_cache_available = (
            False
        )

        app.state.graph_stats[
            "dispatch_road_cache_available"
        ] = False

    # ------------------------------------------------------------------
    # 6. Wire the actual Phase 10 live adapters.
    # ------------------------------------------------------------------

    if (
        app.state.graph is None
        or app.state.snap_index is None
    ):
        app.state.dispatch_road_matrix_ready = (
            False
        )

        app.state.dispatch_road_matrix_error = (
            "graph_or_snap_index_unavailable"
        )

    elif (
        app.state.dispatch_graph_adjacency
        is None
    ):
        app.state.dispatch_road_matrix_ready = (
            False
        )

        if (
            app.state.dispatch_road_matrix_error
            is None
        ):
            app.state.dispatch_road_matrix_error = (
                "dispatch_adjacency_unavailable"
            )

    else:
        try:
            snap_node = (
                _build_dispatch_snap_adapter(
                    graph=app.state.graph,
                    snap_index=app.state.snap_index,
                )
            )

            source_distance_builder = (
                _build_dispatch_source_distance_adapter(
                    adjacency=(
                        app.state.dispatch_graph_adjacency
                    ),
                )
            )

            cache_key_builder = (
                make_dispatch_road_matrix_cache_key_builder(
                    graph_identity=str(
                        settings.graph_path
                    ),
                    algorithm="source_dijkstra",
                )
            )

            # Redis adapters are optional.
            #
            # If Redis initialization succeeded, inject them.
            # Otherwise source_dijkstra remains available when callers use:
            #
            #     "use_cache": false
            #

            cache_get = (
                _build_dispatch_cache_get_adapter(
                    redis_cache
                )
                if redis_cache is not None
                else None
            )

            cache_set = (
                _build_dispatch_cache_set_adapter(
                    redis_cache
                )
                if redis_cache is not None
                else None
            )

            dependencies = (
                DispatchRoadMatrixDependencies(
                    snap_node=snap_node,
                    source_distance_builder=(
                        source_distance_builder
                    ),
                    cache_get=cache_get,
                    cache_set=cache_set,
                    cache_key_builder=(
                        cache_key_builder
                    ),
                )
            )

            app.state.dispatch_road_matrix_dependencies = (
                dependencies
            )

            app.state.dispatch_road_matrix_ready = (
                True
            )

            app.state.dispatch_road_matrix_error = (
                None
            )

            app.state.graph_stats[
                "dispatch_road_matrix_ready"
            ] = True

            app.state.graph_stats[
                "dispatch_road_matrix_error"
            ] = None

            logger.info(
                (
                    "Phase 10 live road-dispatch adapters ready | "
                    "snap=%s | "
                    "source_dijkstra=%s | "
                    "redis_cache_available=%s"
                ),
                True,
                True,
                app.state.dispatch_road_cache_available,
            )

        except Exception as exc:
            logger.exception(
                (
                    "Phase 10 live adapter wiring failed: %s"
                ),
                exc,
            )

            app.state.dispatch_road_matrix_dependencies = (
                None
            )

            app.state.dispatch_road_matrix_ready = (
                False
            )

            app.state.dispatch_road_matrix_error = (
                "phase10_live_adapter_wiring_failed"
            )

            app.state.graph_stats[
                "dispatch_road_matrix_ready"
            ] = False

            app.state.graph_stats[
                "dispatch_road_matrix_error"
            ] = repr(
                exc
            )

    # ------------------------------------------------------------------
    # 7. Final startup observability.
    # ------------------------------------------------------------------

    app.state.graph_stats[
        "dispatch_road_matrix_ready"
    ] = (
        app.state.dispatch_road_matrix_ready
    )

    if (
        app.state.dispatch_road_matrix_error
        is not None
    ):
        app.state.graph_stats[
            "dispatch_road_matrix_error"
        ] = (
            app.state.dispatch_road_matrix_error
        )

    logger.info(
        (
            "CityRoute startup complete | "
            "phase=%s | "
            "graph_loaded=%s | "
            "snap_index_loaded=%s | "
            "dispatch_adjacency_loaded=%s | "
            "dispatch_road_matrix_ready=%s | "
            "dispatch_road_cache_available=%s"
        ),
        PROJECT_PHASE_CODE,
        app.state.graph_loaded,
        (
            app.state.snap_index
            is not None
        ),
        (
            app.state.dispatch_graph_adjacency
            is not None
        ),
        app.state.dispatch_road_matrix_ready,
        app.state.dispatch_road_cache_available,
    )

    yield

    # ------------------------------------------------------------------
    # 8. Shutdown cleanup.
    # ------------------------------------------------------------------

    if (
        app.state.dispatch_redis_cache
        is not None
    ):
        try:
            app.state.dispatch_redis_cache.close()

            logger.info(
                "Phase 10 Redis connection closed"
            )

        except Exception as exc:
            logger.warning(
                (
                    "Phase 10 Redis shutdown failed | "
                    "error=%s"
                ),
                exc,
            )

    logger.info(
        "Shutting down CityRoute application"
    )


app = FastAPI(
    title="CityRoute",
    version=APP_VERSION,
    description=(
        "Open-source last-mile delivery routing and "
        "dispatch optimization engine"
    ),
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------

app.middleware("http")(metrics_middleware)

app.add_api_route(
    "/metrics",
    metrics_endpoint,
    methods=["GET"],
    include_in_schema=False,
)


# ---------------------------------------------------------------------------
# API routers
# ---------------------------------------------------------------------------

app.include_router(
    health_router,
    tags=["Health"],
)

app.include_router(
    graph_router,
    tags=["Graph"],
)

app.include_router(
    route_router,
    tags=["Route"],
)

app.include_router(
    matrix_router,
)

app.include_router(
    vrp_router,
)

app.include_router(
    dispatch_router,
)


@app.get("/")
def root():

    return {
        "status": "ok",
        "service": "cityroute",
        "version": APP_VERSION,
        "phase": PROJECT_PHASE_NAME,
        "phase_code": PROJECT_PHASE_CODE,
        "docs": "/docs",
        "health": "/health",
        "graph_stats": "/graph/stats",
        "metrics": "/metrics",
        "route": "/route",
        "route_compare": "/route/compare",
        "matrix": "/matrix",
        "vrp_greedy": "/vrp/greedy",
        "vrp_compare": "/vrp/compare",
        "vrp_advanced_compare": (
            "/vrp/compare/advanced"
        ),
        "dispatch_compare": (
            "/dispatch/compare"
        ),
        "dispatch_matrix_algorithms": [
            "haversine",
            "source_dijkstra",
        ],
        "phase10_goal": (
            "Real road-network driver-to-order "
            "dispatch cost integration"
        ),
    }