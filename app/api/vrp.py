# app/api/vrp.py

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from starlette.concurrency import run_in_threadpool

from app.models.matrix_model import MatrixRequest
from app.schemas.vrp import GreedyRouteRequest, GreedyRouteResponse
from app.schemas.vrp_compare import VrpCompareRequest, VrpCompareResponse
from app.services.greedy_service import (
    GreedyNoPathError,
    GreedyServiceError,
    solve_greedy_baseline,
)
from app.services.matrix_service import build_distance_matrix_response
from app.services.vrp_compare_service import (
    VrpCompareServiceError,
    compute_vrp_compare,
)

router = APIRouter(prefix="/vrp", tags=["VRP"])


def _ensure_graph_ready(request: Request) -> None:
    graph_loaded = getattr(request.app.state, "graph_loaded", False)
    graph = getattr(request.app.state, "graph", None)
    snap_index = getattr(request.app.state, "snap_index", None)

    if not graph_loaded or graph is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "Graph not loaded",
                "message": "CityRoute graph is not ready. Try again after startup completes.",
            },
        )

    if snap_index is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "Snap index not loaded",
                "message": "BallTree snap index is required before VRP can run.",
            },
        )


async def _matrix_service_adapter(
    matrix_payload: dict[str, Any],
    request: Request,
) -> Any:
    """
    Adapter between Phase 7 /vrp/compare and Phase 5 matrix generation.

    Uses the same canonical Phase 5 matrix service function used by /matrix.
    """
    graph = getattr(request.app.state, "graph", None)
    snap_index = getattr(request.app.state, "snap_index", None)

    if graph is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "Graph not loaded",
                "message": "Graph is required for matrix generation.",
            },
        )

    if snap_index is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "Snap index not loaded",
                "message": "Snap index is required for matrix generation.",
            },
        )

    matrix_request = MatrixRequest(**matrix_payload)

    return await run_in_threadpool(
        build_distance_matrix_response,
        matrix_request,
        graph,
        snap_index,
    )


@router.post("/greedy", response_model=GreedyRouteResponse)
def greedy_vrp(
    payload: GreedyRouteRequest,
    request: Request,
) -> GreedyRouteResponse:
    _ensure_graph_ready(request)

    try:
        return solve_greedy_baseline(
            payload=payload,
            request=request,
        )

    except GreedyNoPathError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "No route found",
                "message": str(exc),
            },
        ) from exc

    except GreedyServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "Invalid greedy VRP request",
                "message": str(exc),
            },
        ) from exc


@router.post("/compare", response_model=VrpCompareResponse)
async def compare_vrp(
    payload: VrpCompareRequest,
    request: Request,
) -> dict[str, Any]:
    _ensure_graph_ready(request)

    try:
        return await compute_vrp_compare(
            depot=payload.start,
            stops=payload.stops,
            matrix_service=lambda matrix_payload: _matrix_service_adapter(
                matrix_payload,
                request,
            ),
            matrix_algorithm=payload.matrix_algorithm,
            use_cache=payload.use_cache,
            ttl_seconds=payload.ttl_seconds,
            return_to_start=payload.return_to_start,
            two_opt_max_iterations=payload.two_opt_max_iterations,
            improvement_tolerance_m=payload.improvement_tolerance_m,
            keep_trace=payload.keep_trace,
        )

    # IMPORTANT:
    # Preserve FastAPI/Phase 5 HTTP errors exactly.
    # Example: coordinate outside graph should remain 422, not become fake 500.
    except HTTPException:
        raise

    except VrpCompareServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "Invalid VRP compare request",
                "message": str(exc),
            },
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "Invalid VRP compare input",
                "message": str(exc),
            },
        ) from exc

    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "VRP compare dependency unavailable",
                "message": str(exc),
            },
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "VRP compare internal error",
                "message": str(exc),
                "type": type(exc).__name__,
            },
        ) from exc