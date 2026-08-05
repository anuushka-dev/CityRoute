# app/main.py

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Any

from fastapi import FastAPI

from app.api.dispatch import router as dispatch_router
from app.api.graph import router as graph_router
from app.api.health import router as health_router
from app.api.matrix import router as matrix_router
from app.api.metrics import router as metrics_router
from app.api.route import router as route_router
from app.api.vrp import router as vrp_router
from app.config import settings
from app.core.concurrency_limiter import ConcurrencyLimiter
from app.core.graph_adjacency import (
    GraphAdjacency,
    build_graph_adjacency,
)
from app.core.multi_target_dijkstra import multi_target_dijkstra
from app.core.timeout_policy import TimeoutPolicy
from app.infrastructure.redis_cache import RedisCache
from app.infrastructure.redis_resilience import RedisRecoveryController
from app.infrastructure.resilience_state import (
    ComponentName,
    ResilienceState,
)
from app.middleware.concurrency_control import ConcurrencyControlMiddleware
from app.middleware.lifecycle_guard import (
    DEFAULT_ENDPOINT_REQUIREMENTS,
    LifecycleGuardMiddleware,
)
from app.middleware.request_timeout import RequestTimeoutMiddleware
from app.observability.metrics import metrics_middleware
from app.observability.reliability_metrics import (
    ReliabilityMetrics,
    get_reliability_metrics,
)
from app.services.dispatch_road_matrix_service import (
    DispatchRoadMatrixDependencies,
)
from app.services.graph_service import load_or_download_graph
from app.services.readiness_service import ReadinessPolicy, ReadinessService
from app.services.shutdown_service import (
    ShutdownHook,
    ShutdownPolicy,
    ShutdownService,
)
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

PROJECT_PHASE_CODE = "tier4_phase11"

PROJECT_PHASE_NAME = (
    "Tier 4 Phase 11 - Production Reliability and Concurrency Hardening"
)


setup_logging(settings.log_level)
logger = get_logger(__name__)


_resilience_state = ResilienceState()

_concurrency_limiter = ConcurrencyLimiter(
    max_active_requests=settings.concurrency_max_active_requests,
    max_waiting_requests=settings.concurrency_max_waiting_requests,
    default_wait_timeout_s=settings.concurrency_wait_timeout_s,
)

_timeout_policy = TimeoutPolicy.from_settings(settings)

_readiness_policy = ReadinessPolicy.from_settings(settings)

_readiness_service = ReadinessService(
    resilience_state=_resilience_state,
    phase=PROJECT_PHASE_CODE,
    policy=_readiness_policy,
)

_reliability_metrics: ReliabilityMetrics = get_reliability_metrics()


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

        return int(result["nearest_node"])

    return snap_node


def _build_dispatch_source_distance_adapter(
    *,
    adjacency: GraphAdjacency,
):
    def source_distance_builder(
        source_node: int,
        target_nodes: Sequence[int],
    ) -> dict[int, float | None]:
        target_set = {int(node_id) for node_id in target_nodes}

        result = multi_target_dijkstra(
            adjacency=adjacency,
            source_node=int(source_node),
            target_nodes=target_set,
        )

        return {
            int(target_node): (
                None if distance_m is None else float(distance_m)
            )
            for target_node, distance_m in result.target_distances_m.items()
        }

    return source_distance_builder


def _build_dispatch_cache_get_adapter(
    redis_cache: RedisCache,
):
    def cache_get(
        key: str,
    ) -> Any:
        return redis_cache.client.get(key)

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


def _phase11_graph_stats_defaults() -> dict[str, Any]:
    return {
        "snap_index_loaded": False,
        "snap_index_build_time_ms": None,
        "snap_index_method": None,
        "snap_index_import_error": None,
        "dispatch_adjacency_loaded": False,
        "dispatch_adjacency_build_time_ms": None,
        "dispatch_adjacency_node_count": None,
        "dispatch_adjacency_edge_count": None,
        "dispatch_road_matrix_ready": False,
        "dispatch_road_cache_available": False,
        "dispatch_road_matrix_error": None,
        "phase11_reliability_enabled": True,
        "phase11_accepting_requests": False,
    }


def _lifecycle_requirements() -> dict[
    tuple[str, str],
    frozenset[ComponentName],
]:
    requirements = {
        endpoint: set(components)
        for endpoint, components in DEFAULT_ENDPOINT_REQUIREMENTS.items()
    }

    redis_is_required = (
        settings.readiness_require_redis or not settings.redis_fail_open
    )

    if redis_is_required:
        for components in requirements.values():
            components.add("redis")

    return {
        endpoint: frozenset(components)
        for endpoint, components in requirements.items()
    }


async def _redis_recovery_loop(
    *,
    app: FastAPI,
    controller: RedisRecoveryController,
    stop_event: asyncio.Event,
) -> None:
    interval_s = settings.redis_healthcheck_interval_s

    while not stop_event.is_set():
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=interval_s,
            )
            break
        except TimeoutError:
            pass

        try:
            snapshot = await controller.snapshot()

            if snapshot.available:
                await controller.check_health()
            elif await controller.should_attempt_recovery():
                await controller.attempt_recovery()

            refreshed = await controller.snapshot()
            app.state.dispatch_road_cache_available = refreshed.available
            app.state.graph_stats[
                "dispatch_road_cache_available"
            ] = refreshed.available
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Redis recovery loop iteration failed")


async def _stop_background_task(
    *,
    stop_event: asyncio.Event,
    task: asyncio.Task[None] | None,
) -> None:
    stop_event.set()

    if task is None:
        return

    if not task.done():
        task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass


async def _refresh_reliability_metrics(
    *,
    redis_controller: RedisRecoveryController | None,
) -> None:
    try:
        readiness = await _readiness_service.get_readiness()
        resilience_snapshot = await _resilience_state.snapshot()
        limiter_snapshot = await _concurrency_limiter.snapshot()
        redis_snapshot = (
            await redis_controller.snapshot()
            if redis_controller is not None
            else None
        )

        _reliability_metrics.refresh_gauges(
            resilience_snapshot=resilience_snapshot,
            limiter_snapshot=limiter_snapshot,
            redis_snapshot=redis_snapshot,
            ready=readiness.ready,
        )
    except Exception:
        logger.exception("Unable to refresh startup reliability metrics")


@asynccontextmanager
async def lifespan(
    app: FastAPI,
):
    logger.info(
        "Starting CityRoute application | phase=%s",
        PROJECT_PHASE_CODE,
    )

    # Middleware stores references to these process-local runtime objects.
    # Reset those same objects before each lifespan so shutdown state from a
    # previous TestClient or embedded server cycle cannot leak into startup.
    await _resilience_state.reset_for_startup()
    await _concurrency_limiter.reset_for_startup()

    app.state.started_at = perf_counter()
    app.state.phase = PROJECT_PHASE_CODE
    app.state.phase_name = PROJECT_PHASE_NAME

    app.state.resilience_state = _resilience_state
    app.state.concurrency_limiter = _concurrency_limiter
    app.state.timeout_policy = _timeout_policy
    app.state.readiness_policy = _readiness_policy
    app.state.readiness_service = _readiness_service
    app.state.reliability_metrics = _reliability_metrics

    app.state.graph = None
    app.state.graph_loaded = False
    app.state.graph_stats = _phase11_graph_stats_defaults()
    app.state.snap_index = None

    app.state.dispatch_road_matrix_dependencies = None
    app.state.dispatch_road_matrix_ready = False
    app.state.dispatch_road_matrix_error = None

    app.state.dispatch_graph_adjacency = None
    app.state.dispatch_adjacency = None

    app.state.dispatch_redis_cache = None
    app.state.dispatch_road_cache_available = False

    app.state.redis_recovery_controller = None
    app.state.redis_resilience = None
    app.state.redis_recovery_task = None
    app.state.shutdown_service = None

    await _resilience_state.mark_startup_started()

    # ------------------------------------------------------------------
    # 1. Load the road graph.
    # ------------------------------------------------------------------

    logger.info("Loading CityRoute graph")

    try:
        graph, graph_stats = load_or_download_graph()
    except Exception as exc:
        logger.exception("Graph loading failed: %s", exc)
        graph = None
        graph_stats = {
            "load_error": repr(exc),
        }

    app.state.graph = graph
    app.state.graph_loaded = graph is not None
    app.state.graph_stats.update(dict(graph_stats or {}))

    await _resilience_state.set_graph_ready(graph is not None)

    # ------------------------------------------------------------------
    # 2. Build the snap index.
    # ------------------------------------------------------------------

    if graph is not None:
        logger.info("Building snap index")

        try:
            snap_index = build_snap_index(graph)
            app.state.snap_index = snap_index

            app.state.graph_stats.update(
                {
                    "snap_index_loaded": True,
                    "snap_index_build_time_ms": snap_index.build_time_ms,
                    "snap_index_method": snap_index.method,
                    "snap_index_import_error": snap_index.import_error,
                }
            )

            logger.info(
                "Snap index ready | nodes=%s | method=%s | "
                "build_time_ms=%s",
                len(snap_index.node_ids),
                snap_index.method,
                snap_index.build_time_ms,
            )

            if snap_index.import_error is not None:
                logger.warning(
                    "BallTree unavailable; using fallback snap index | "
                    "error=%s",
                    snap_index.import_error,
                )
        except Exception as exc:
            logger.exception("Snap index build failed: %s", exc)

            app.state.snap_index = None
            app.state.graph_stats.update(
                {
                    "snap_index_loaded": False,
                    "snap_index_build_time_ms": None,
                    "snap_index_method": None,
                    "snap_index_import_error": repr(exc),
                }
            )
    else:
        logger.warning(
            "Graph not loaded; route, matrix, VRP, and road dispatch "
            "operations are unavailable"
        )

    await _resilience_state.set_snap_index_ready(
        app.state.snap_index is not None
    )

    # ------------------------------------------------------------------
    # 3. Build the reusable directed graph adjacency.
    # ------------------------------------------------------------------

    if app.state.graph is not None and app.state.snap_index is not None:
        logger.info("Building reusable dispatch graph adjacency")

        try:
            dispatch_adjacency = build_graph_adjacency(app.state.graph)

            app.state.dispatch_graph_adjacency = dispatch_adjacency
            app.state.dispatch_adjacency = dispatch_adjacency

            app.state.graph_stats.update(
                {
                    "dispatch_adjacency_loaded": True,
                    "dispatch_adjacency_build_time_ms": (
                        dispatch_adjacency.build_time_ms
                    ),
                    "dispatch_adjacency_node_count": (
                        dispatch_adjacency.node_count
                    ),
                    "dispatch_adjacency_edge_count": (
                        dispatch_adjacency.edge_count
                    ),
                }
            )

            logger.info(
                "Dispatch adjacency ready | nodes=%s | edges=%s | "
                "directed=%s | build_time_ms=%s",
                dispatch_adjacency.node_count,
                dispatch_adjacency.edge_count,
                dispatch_adjacency.directed,
                dispatch_adjacency.build_time_ms,
            )
        except Exception as exc:
            logger.exception(
                "Dispatch adjacency build failed: %s",
                exc,
            )

            app.state.dispatch_graph_adjacency = None
            app.state.dispatch_adjacency = None
            app.state.dispatch_road_matrix_error = (
                "dispatch_adjacency_build_failed"
            )

            app.state.graph_stats.update(
                {
                    "dispatch_adjacency_loaded": False,
                    "dispatch_road_matrix_error": repr(exc),
                }
            )

    # ------------------------------------------------------------------
    # 4. Initialize Redis and the automatic recovery controller.
    # ------------------------------------------------------------------

    redis_cache: RedisCache | None = None

    try:
        redis_cache = RedisCache(
            redis_url=str(settings.redis_url),
            ttl_seconds=int(settings.matrix_cache_ttl_seconds),
            socket_timeout_s=float(settings.redis_socket_timeout_s),
        )

        app.state.dispatch_redis_cache = redis_cache
    except Exception as exc:
        logger.warning(
            "Redis client initialization failed | error=%s",
            exc,
        )

    def redis_health_check() -> bool:
        if redis_cache is None:
            return False

        return bool(redis_cache.ping())

    redis_controller = RedisRecoveryController(
        resilience_state=_resilience_state,
        health_check=redis_health_check,
        fail_open_enabled=settings.redis_fail_open,
        recovery_interval_s=settings.redis_recovery_interval_s,
        max_recovery_interval_s=(
            settings.redis_max_recovery_interval_s
        ),
        backoff_multiplier=(
            settings.redis_recovery_backoff_multiplier
        ),
        run_sync_healthcheck_in_thread=(
            settings.redis_run_sync_healthcheck_in_thread
        ),
    )

    app.state.redis_recovery_controller = redis_controller
    app.state.redis_resilience = redis_controller

    redis_available = await redis_controller.initialize()

    app.state.dispatch_road_cache_available = redis_available
    app.state.graph_stats[
        "dispatch_road_cache_available"
    ] = redis_available

    if redis_available:
        logger.info("Redis cache is available")
    else:
        logger.warning(
            "Redis cache is unavailable; fail_open=%s",
            settings.redis_fail_open,
        )

    # ------------------------------------------------------------------
    # 5. Wire the Phase 10 road-dispatch adapters.
    # ------------------------------------------------------------------

    if app.state.graph is None or app.state.snap_index is None:
        app.state.dispatch_road_matrix_error = (
            "graph_or_snap_index_unavailable"
        )
    elif app.state.dispatch_graph_adjacency is None:
        app.state.dispatch_road_matrix_error = (
            app.state.dispatch_road_matrix_error
            or "dispatch_adjacency_unavailable"
        )
    else:
        try:
            snap_node = _build_dispatch_snap_adapter(
                graph=app.state.graph,
                snap_index=app.state.snap_index,
            )

            source_distance_builder = (
                _build_dispatch_source_distance_adapter(
                    adjacency=app.state.dispatch_graph_adjacency,
                )
            )

            cache_key_builder = (
                make_dispatch_road_matrix_cache_key_builder(
                    graph_identity=str(settings.graph_path),
                    algorithm="source_dijkstra",
                )
            )

            cache_get = (
                _build_dispatch_cache_get_adapter(redis_cache)
                if redis_cache is not None
                else None
            )
            cache_set = (
                _build_dispatch_cache_set_adapter(redis_cache)
                if redis_cache is not None
                else None
            )

            app.state.dispatch_road_matrix_dependencies = (
                DispatchRoadMatrixDependencies(
                    snap_node=snap_node,
                    source_distance_builder=source_distance_builder,
                    cache_get=cache_get,
                    cache_set=cache_set,
                    cache_key_builder=cache_key_builder,
                )
            )
            app.state.dispatch_road_matrix_ready = True
            app.state.dispatch_road_matrix_error = None

            logger.info(
                "Road-dispatch adapters ready | Redis available=%s",
                app.state.dispatch_road_cache_available,
            )
        except Exception as exc:
            logger.exception(
                "Road-dispatch adapter wiring failed: %s",
                exc,
            )

            app.state.dispatch_road_matrix_dependencies = None
            app.state.dispatch_road_matrix_ready = False
            app.state.dispatch_road_matrix_error = (
                "road_dispatch_adapter_wiring_failed"
            )
            app.state.graph_stats[
                "dispatch_road_matrix_error"
            ] = repr(exc)

    app.state.graph_stats.update(
        {
            "dispatch_road_matrix_ready": (
                app.state.dispatch_road_matrix_ready
            ),
            "dispatch_road_matrix_error": (
                app.state.dispatch_road_matrix_error
            ),
        }
    )

    await _resilience_state.set_dispatch_adjacency_ready(
        app.state.dispatch_road_matrix_ready
    )

    # Startup initialization has finished. Endpoint-specific lifecycle checks
    # still reject operations whose required components are unavailable.
    await _resilience_state.mark_startup_complete(
        accepting_requests=True
    )

    app.state.graph_stats["phase11_accepting_requests"] = True

    # ------------------------------------------------------------------
    # 6. Start Redis recovery and configure graceful shutdown.
    # ------------------------------------------------------------------

    redis_recovery_stop_event = asyncio.Event()
    redis_recovery_task: asyncio.Task[None] | None = None

    if settings.redis_recovery_enabled:
        redis_recovery_task = asyncio.create_task(
            _redis_recovery_loop(
                app=app,
                controller=redis_controller,
                stop_event=redis_recovery_stop_event,
            ),
            name="cityroute-redis-recovery",
        )

    app.state.redis_recovery_stop_event = redis_recovery_stop_event
    app.state.redis_recovery_task = redis_recovery_task

    async def stop_redis_recovery() -> None:
        await _stop_background_task(
            stop_event=redis_recovery_stop_event,
            task=redis_recovery_task,
        )

    cleanup_hooks: list[ShutdownHook] = [
        ShutdownHook(
            name="stop_redis_recovery",
            callback=stop_redis_recovery,
        )
    ]

    if redis_cache is not None:
        cleanup_hooks.append(
            ShutdownHook(
                name="close_redis_cache",
                callback=redis_cache.close,
            )
        )

    shutdown_service = ShutdownService(
        resilience_state=_resilience_state,
        concurrency_limiter=_concurrency_limiter,
        policy=ShutdownPolicy(
            drain_timeout_s=settings.shutdown_drain_timeout_s,
            cleanup_timeout_s=settings.shutdown_cleanup_timeout_s,
            default_hook_timeout_s=(
                settings.shutdown_default_hook_timeout_s
            ),
            run_sync_hooks_in_thread=(
                settings.shutdown_run_sync_hooks_in_thread
            ),
        ),
        cleanup_hooks=tuple(cleanup_hooks),
        metrics=_reliability_metrics,
    )

    app.state.shutdown_service = shutdown_service

    await _refresh_reliability_metrics(
        redis_controller=redis_controller
    )

    readiness = await _readiness_service.get_readiness()

    logger.info(
        "CityRoute startup complete | phase=%s | ready=%s | "
        "readiness_status=%s | graph_loaded=%s | "
        "snap_index_loaded=%s | dispatch_ready=%s | Redis=%s",
        PROJECT_PHASE_CODE,
        readiness.ready,
        readiness.status,
        app.state.graph_loaded,
        app.state.snap_index is not None,
        app.state.dispatch_road_matrix_ready,
        redis_available,
    )

    try:
        yield
    finally:
        logger.info("CityRoute shutdown requested")

        if settings.graceful_shutdown_enabled:
            result = await shutdown_service.shutdown()

            logger.info(
                "CityRoute shutdown complete | phase=%s | graceful=%s | "
                "forced=%s | drained=%s | cleanup_success=%s",
                result.phase,
                result.graceful,
                result.forced,
                result.drained,
                result.cleanup_success,
            )
        else:
            await _resilience_state.begin_shutdown()
            await _concurrency_limiter.close(
                reason="service_shutdown",
            )
            await stop_redis_recovery()

            if redis_cache is not None:
                try:
                    await asyncio.to_thread(redis_cache.close)
                except Exception:
                    logger.exception("Redis shutdown cleanup failed")

            await _resilience_state.mark_shutdown_complete()

        app.state.graph_stats["phase11_accepting_requests"] = False


app = FastAPI(
    title="CityRoute",
    version=APP_VERSION,
    description=(
        "Open-source last-mile delivery routing and dispatch "
        "optimization engine"
    ),
    lifespan=lifespan,
)

app.state.resilience_state = _resilience_state
app.state.concurrency_limiter = _concurrency_limiter
app.state.timeout_policy = _timeout_policy
app.state.readiness_policy = _readiness_policy
app.state.readiness_service = _readiness_service
app.state.reliability_metrics = _reliability_metrics

# ---------------------------------------------------------------------------
# Phase 11 reliability middleware
#
# Starlette wraps later-added middleware around earlier-added middleware.
# This order produces:
#
# metrics -> lifecycle -> concurrency -> timeout -> endpoint
# ---------------------------------------------------------------------------

if settings.request_timeout_enabled:
    app.add_middleware(
        RequestTimeoutMiddleware,
        timeout_policy=_timeout_policy,
        resilience_state=_resilience_state,
        cancellation_grace_s=(
            settings.request_timeout_cancellation_grace_s
        ),
        emit_timeout_headers=(
            settings.request_timeout_emit_headers
        ),
    )

if settings.concurrency_control_enabled:
    app.add_middleware(
        ConcurrencyControlMiddleware,
        limiter=_concurrency_limiter,
        resilience_state=_resilience_state,
        wait_timeout_s=settings.concurrency_wait_timeout_s,
        retry_after_s=settings.concurrency_retry_after_s,
        emit_admission_headers=(
            settings.concurrency_emit_admission_headers
        ),
    )

if settings.lifecycle_guard_enabled:
    app.add_middleware(
        LifecycleGuardMiddleware,
        resilience_state=_resilience_state,
        endpoint_requirements=_lifecycle_requirements(),
        retry_after_s=settings.lifecycle_retry_after_s,
    )

if settings.metrics_enabled:
    app.middleware("http")(metrics_middleware)


# ---------------------------------------------------------------------------
# API routers
# ---------------------------------------------------------------------------

app.include_router(health_router)

if settings.metrics_enabled:
    app.include_router(metrics_router, include_in_schema=False)

app.include_router(
    graph_router,
    tags=["Graph"],
)
app.include_router(
    route_router,
    tags=["Route"],
)
app.include_router(matrix_router)
app.include_router(vrp_router)
app.include_router(dispatch_router)


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
        "liveness": "/health/live",
        "readiness": "/health/ready",
        "graph_stats": "/graph/stats",
        "metrics": "/metrics" if settings.metrics_enabled else None,
        "route": "/route",
        "route_compare": "/route/compare",
        "matrix": "/matrix",
        "vrp_greedy": "/vrp/greedy",
        "vrp_compare": "/vrp/compare",
        "vrp_advanced_compare": "/vrp/compare/advanced",
        "dispatch_compare": "/dispatch/compare",
        "dispatch_matrix_algorithms": [
            "haversine",
            "source_dijkstra",
        ],
        "phase11_goal": (
            "Production reliability, bounded concurrency, timeouts, "
            "Redis recovery, readiness, and graceful shutdown"
        ),
    }