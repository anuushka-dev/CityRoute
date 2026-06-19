# app/api/vrp.py

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas.vrp import GreedyRouteRequest, GreedyRouteResponse
from app.services.greedy_service import (
    GreedyNoPathError,
    GreedyServiceError,
    solve_greedy_baseline,
)

router = APIRouter(prefix="/vrp", tags=["VRP"])


@router.post("/greedy", response_model=GreedyRouteResponse)
def greedy_vrp(
    payload: GreedyRouteRequest,
    request: Request,
) -> GreedyRouteResponse:
    """
    Tier 2 Phase 6 — Greedy Baseline.

    Uses Phase 5 matrix distances and runs the from-scratch
    nearest-neighbor greedy algorithm.
    """

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
                "message": "BallTree snap index is required before greedy VRP can run.",
            },
        )

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