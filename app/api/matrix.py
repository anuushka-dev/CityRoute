# app/api/matrix.py

from fastapi import APIRouter, HTTPException, Request, status
from starlette.concurrency import run_in_threadpool

from app.models.matrix_model import MatrixRequest, MatrixResponse
from app.services.matrix_service import build_distance_matrix_response

router = APIRouter(prefix="/matrix", tags=["Matrix"])


@router.post(
    "",
    response_model=MatrixResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate an N×N road-distance matrix",
    description=(
        "Generates a directed N×N distance/ETA matrix between GPS locations. "
        "Uses the loaded road graph, BallTree snapping, A*/Bidirectional A*, "
        "parallel computation, and optional Redis caching."
    ),
)
async def create_distance_matrix(
    payload: MatrixRequest,
    request: Request,
) -> MatrixResponse:

    graph_loaded = getattr(request.app.state, "graph_loaded", False)
    graph = getattr(request.app.state, "graph", None)
    snap_index = getattr(request.app.state, "snap_index", None)

    if not graph_loaded or graph is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "Graph not loaded",
                "message": "Distance matrix cannot be generated until the road graph is loaded.",
            },
        )

    if snap_index is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "Snap index not loaded",
                "message": "Distance matrix requires the BallTree snap index to be available.",
            },
        )

    return await run_in_threadpool(
        build_distance_matrix_response,
        payload,
        graph,
        snap_index,
    )