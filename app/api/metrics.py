# app/api/metrics.py

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.core.concurrency_limiter import ConcurrencyLimiter
from app.infrastructure.redis_resilience import RedisRecoveryController
from app.infrastructure.resilience_state import ResilienceState
from app.observability.reliability_metrics import (
    ReliabilityMetrics,
    get_reliability_metrics,
)
from app.services.readiness_service import ReadinessService

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["observability"],
)


def _resolve_metrics(
    request: Request,
) -> ReliabilityMetrics:

    configured_metrics = getattr(
        request.app.state,
        "reliability_metrics",
        None,
    )

    if isinstance(configured_metrics, ReliabilityMetrics):
        return configured_metrics

    if configured_metrics is not None:
        logger.warning(
            "Ignoring invalid app.state.reliability_metrics value | "
            "type=%s",
            type(configured_metrics).__name__,
        )

    metrics = get_reliability_metrics()
    request.app.state.reliability_metrics = metrics

    return metrics


async def _refresh_reliability_gauges(
    request: Request,
    metrics: ReliabilityMetrics,
) -> None:

    resilience_state = getattr(
        request.app.state,
        "resilience_state",
        None,
    )

    if not isinstance(resilience_state, ResilienceState):
        logger.debug(
            "Skipping reliability gauge refresh because "
            "ResilienceState is not initialized"
        )
        return

    try:
        resilience_snapshot = await resilience_state.snapshot()
    except Exception:
        logger.exception(
            "Unable to capture resilience snapshot for metrics"
        )
        return

    limiter_snapshot = None
    concurrency_limiter = getattr(
        request.app.state,
        "concurrency_limiter",
        None,
    )

    if isinstance(concurrency_limiter, ConcurrencyLimiter):
        try:
            limiter_snapshot = await concurrency_limiter.snapshot()
        except Exception:
            logger.exception(
                "Unable to capture concurrency limiter snapshot"
            )

    redis_snapshot = None
    redis_controller = getattr(
        request.app.state,
        "redis_recovery_controller",
        None,
    )

    if not isinstance(
        redis_controller,
        RedisRecoveryController,
    ):
        redis_controller = getattr(
            request.app.state,
            "redis_resilience",
            None,
        )

    if isinstance(redis_controller, RedisRecoveryController):
        try:
            redis_snapshot = await redis_controller.snapshot()
        except Exception:
            logger.exception(
                "Unable to capture Redis reliability snapshot"
            )

    ready: bool | None = None
    readiness_service = getattr(
        request.app.state,
        "readiness_service",
        None,
    )

    if isinstance(readiness_service, ReadinessService):
        try:
            readiness = await readiness_service.get_readiness()
            ready = readiness.ready
        except Exception:
            logger.exception(
                "Unable to evaluate readiness while refreshing metrics"
            )

    try:
        metrics.refresh_gauges(
            resilience_snapshot=resilience_snapshot,
            limiter_snapshot=limiter_snapshot,
            redis_snapshot=redis_snapshot,
            ready=ready,
        )
    except Exception:
        logger.exception(
            "Unable to refresh CityRoute reliability gauges"
        )


@router.get(
    "/metrics",
    summary="CityRoute Prometheus metrics",
    description=(
        "Expose process, Python, and Phase 11 reliability metrics using "
        "the Prometheus text exposition format."
    ),
    response_class=Response,
)
async def metrics(
    request: Request,
) -> Response:

    reliability_metrics = _resolve_metrics(request)

    reliability_metrics.set_graph_loaded(
        bool(
            getattr(
                request.app.state,
                "graph_loaded",
                False,
            )
        )
    )

    reliability_metrics.set_snap_index_loaded(
        getattr(
            request.app.state,
            "snap_index",
            None,
        )
        is not None
    )

    await _refresh_reliability_gauges(
        request,
        reliability_metrics,
    )

    try:
        payload = generate_latest(
            reliability_metrics.registry
        )
    except Exception:
        logger.exception(
            "Unable to generate Prometheus metrics payload"
        )
        raise

    return Response(
        content=payload,
        status_code=200,
        headers={
            "Content-Type": CONTENT_TYPE_LATEST,
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


__all__ = [
    "metrics",
    "router",
]