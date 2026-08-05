# app/api/health.py

from __future__ import annotations

from time import perf_counter

from fastapi import APIRouter, Request, Response, status

from app.infrastructure.resilience_state import ResilienceState
from app.schemas.health import (
    LegacyHealthResponse,
    LegacyHealthStatus,
    LivenessResponse,
    ReadinessComponents,
    ReadinessResponse,
)
from app.services.readiness_service import (
    ReadinessPolicy,
    ReadinessService,
)

router = APIRouter(
    tags=["health"],
)


def _uptime_s(request: Request) -> float:
    started_at = getattr(
        request.app.state,
        "started_at",
        perf_counter(),
    )

    try:
        uptime_s = perf_counter() - float(started_at)
    except (TypeError, ValueError):
        return 0.0

    return round(max(0.0, uptime_s), 3)


def _phase(request: Request) -> str:
    phase = str(
        getattr(
            request.app.state,
            "phase",
            "tier4_phase11",
        )
    ).strip()

    return phase or "tier4_phase11"


def _get_readiness_service(
    request: Request,
) -> ReadinessService | None:
    """
    Return the application readiness service.

    The normal Phase 11 integration stores a prebuilt service in:

        app.state.readiness_service

    The fallback construction supports focused tests where only
    `app.state.resilience_state` has been configured.
    """

    existing_service = getattr(
        request.app.state,
        "readiness_service",
        None,
    )

    if isinstance(existing_service, ReadinessService):
        return existing_service

    resilience_state = getattr(
        request.app.state,
        "resilience_state",
        None,
    )

    if not isinstance(resilience_state, ResilienceState):
        return None

    readiness_policy = getattr(
        request.app.state,
        "readiness_policy",
        None,
    )

    if not isinstance(readiness_policy, ReadinessPolicy):
        readiness_policy = ReadinessPolicy()

    return ReadinessService(
        resilience_state=resilience_state,
        phase=_phase(request),
        policy=readiness_policy,
    )


def _fallback_readiness(
    request: Request,
) -> ReadinessResponse:
    """
    Return a controlled not-ready response when Phase 11 state has not yet
    been initialized.

    Liveness remains successful because the API process is responsive, while
    readiness correctly blocks production traffic.
    """

    graph_loaded = bool(
        getattr(
            request.app.state,
            "graph_loaded",
            False,
        )
    )

    snap_index_ready = (
        getattr(
            request.app.state,
            "snap_index",
            None,
        )
        is not None
    )

    dispatch_adjacency_ready = (
        getattr(
            request.app.state,
            "dispatch_adjacency",
            None,
        )
        is not None
    )

    return ReadinessResponse(
        status="not_ready",
        ready=False,
        phase=_phase(request),
        uptime_s=_uptime_s(request),
        startup_complete=False,
        accepting_requests=False,
        shutting_down=False,
        components=ReadinessComponents(
            graph=(
                "ready"
                if graph_loaded
                else "not_initialized"
            ),
            snap_index=(
                "ready"
                if snap_index_ready
                else "not_initialized"
            ),
            dispatch_adjacency=(
                "ready"
                if dispatch_adjacency_ready
                else "not_initialized"
            ),
            redis="not_initialized",
        ),
        degraded_dependencies=[],
        failure_reasons=[
            "readiness_service_not_initialized",
        ],
    )


def _legacy_status(
    readiness: ReadinessResponse,
) -> LegacyHealthStatus:
    """
    Convert the Phase 11 readiness result into the original `/health`
    contract.
    """

    graph_loaded = readiness.components.graph == "ready"

    if readiness.shutting_down:
        return "shutting_down"

    if readiness.status == "degraded":
        return "degraded"

    if readiness.status == "not_ready":
        if (
            not readiness.startup_complete
            and not graph_loaded
        ):
            return "starting"

        return "degraded"

    if readiness.status == "ready" and graph_loaded:
        return "ok"

    return "degraded"


@router.get(
    "/health",
    response_model=LegacyHealthResponse,
    summary="Legacy CityRoute health check",
)
async def health(
    request: Request,
) -> LegacyHealthResponse:
    """
    Preserve the original CityRoute health response used by earlier phases.

    New orchestration and monitoring integrations should use:

        GET /health/live
        GET /health/ready
    """

    readiness_service = _get_readiness_service(request)

    if readiness_service is None:
        graph_loaded = bool(
            getattr(
                request.app.state,
                "graph_loaded",
                False,
            )
        )

        return LegacyHealthResponse(
            status=(
                "ok"
                if graph_loaded
                else "starting"
            ),
            graph_loaded=graph_loaded,
            uptime_s=_uptime_s(request),
        )

    readiness = await readiness_service.get_readiness()
    graph_loaded = readiness.components.graph == "ready"

    return LegacyHealthResponse(
        status=_legacy_status(readiness),
        graph_loaded=graph_loaded,
        uptime_s=readiness.uptime_s,
    )


@router.get(
    "/health/live",
    response_model=LivenessResponse,
    status_code=status.HTTP_200_OK,
    summary="CityRoute process liveness",
)
async def liveness(
    request: Request,
) -> LivenessResponse:
    """
    Confirm that the API process and event loop are responsive.

    Dependency failures, Redis outages, startup progress, overload, and
    readiness failures do not make a responsive process fail liveness.
    """

    return LivenessResponse(
        status="alive",
        phase=_phase(request),
        uptime_s=_uptime_s(request),
    )


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ReadinessResponse,
            "description": (
                "CityRoute is starting, shutting down, or missing a "
                "required runtime component."
            ),
        }
    },
    summary="CityRoute production readiness",
)
async def readiness(
    request: Request,
    response: Response,
) -> ReadinessResponse:
    """
    Report whether this worker can safely accept production traffic.

    Returns HTTP 200 for:

        ready
        degraded but operational

    Returns HTTP 503 for:

        startup incomplete
        required component unavailable
        request admission disabled
        graceful shutdown in progress
    """

    readiness_service = _get_readiness_service(request)

    if readiness_service is None:
        result = _fallback_readiness(request)
    else:
        result = await readiness_service.get_readiness()

    response.status_code = (
        status.HTTP_200_OK
        if result.ready
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )

    return result