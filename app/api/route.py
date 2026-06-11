# app/api/route.py

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.config import settings
from app.services.routing_service import compare_routes, compute_route


router = APIRouter(prefix="/route")


def _bbox() -> dict[str, float]:
    return {
        "south": float(getattr(settings, "bbox_south", 26.43)),
        "north": float(getattr(settings, "bbox_north", 26.50)),
        "west": float(getattr(settings, "bbox_west", 80.28)),
        "east": float(getattr(settings, "bbox_east", 80.38)),
    }


def _validate_coordinate(lat: float, lon: float, label: str) -> None:
    bbox = _bbox()

    if not (-90 <= lat <= 90):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Invalid latitude",
                "message": f"{label}_lat must be between -90 and 90.",
                "received": {"lat": lat, "lon": lon},
            },
        )

    if not (-180 <= lon <= 180):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Invalid longitude",
                "message": f"{label}_lon must be between -180 and 180.",
                "received": {"lat": lat, "lon": lon},
            },
        )

    inside_bbox = (
        bbox["south"] <= lat <= bbox["north"]
        and bbox["west"] <= lon <= bbox["east"]
    )

    if not inside_bbox:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Coordinate outside loaded graph area",
                "message": f"{label} coordinate is outside the loaded graph bounding box.",
                "received": {"lat": lat, "lon": lon},
                "allowed_bbox": bbox,
            },
        )


@router.get("/compare")
def route_compare(
    request: Request,
    start_lat: float = Query(..., description="Start latitude"),
    start_lon: float = Query(..., description="Start longitude"),
    end_lat: float = Query(..., description="End latitude"),
    end_lon: float = Query(..., description="End longitude"),
):
    """
    Compare Phase 3 A* with Phase 4 Bidirectional A*.

    This endpoint does not replace /route.
    It runs both algorithms on the same snapped start/end nodes.
    """
    _validate_coordinate(start_lat, start_lon, "start")
    _validate_coordinate(end_lat, end_lon, "end")

    graph = getattr(request.app.state, "graph", None)
    snap_index = getattr(request.app.state, "snap_index", None)

    return compare_routes(
        graph=graph,
        snap_index=snap_index,
        start_lat=start_lat,
        start_lon=start_lon,
        end_lat=end_lat,
        end_lon=end_lon,
    )


@router.get("")
def route(
    request: Request,
    start_lat: float = Query(..., description="Start latitude"),
    start_lon: float = Query(..., description="Start longitude"),
    end_lat: float = Query(..., description="End latitude"),
    end_lon: float = Query(..., description="End longitude"),
):
    _validate_coordinate(start_lat, start_lon, "start")
    _validate_coordinate(end_lat, end_lon, "end")

    graph = getattr(request.app.state, "graph", None)
    snap_index = getattr(request.app.state, "snap_index", None)

    return compute_route(
        graph=graph,
        snap_index=snap_index,
        start_lat=start_lat,
        start_lon=start_lon,
        end_lat=end_lat,
        end_lon=end_lon,
    )