# app/api/graph.py

from fastapi import APIRouter, Request

from app.config import settings
from app.utils.geo_validation import validate_coordinates
from app.utils.node_snapper import snap_coordinate_to_graph

router = APIRouter(prefix="/graph")


@router.get("/stats")
def graph_stats(request: Request):
    return getattr(
        request.app.state,
        "graph_stats",
        {
            "city": settings.city_name,
            "graph_loaded": False,
            "nodes": 0,
            "edges": 0,
            "load_time_s": None,
            "graph_path": str(settings.graph_path),
            "graph_file_size_mb": None,
            "memory_mb": None,
        },
    )


@router.get("/validate")
def validate_graph_coordinate(lat: float, lon: float):
    validate_coordinates(lat, lon)

    return {
        "valid": True,
        "lat": lat,
        "lon": lon,
        "message": "Coordinate is valid and inside the loaded graph area.",
    }


@router.get("/snap")
def snap_graph_coordinate(request: Request, lat: float, lon: float):
    graph = getattr(request.app.state, "graph", None)

    snap_index = getattr(request.app.state, "snap_index", None)

    result = snap_coordinate_to_graph(
        graph=graph,
        snap_index=snap_index,
        lat=lat,
        lon=lon,
    )

    return {
        "status": "ok",
        "message": "Coordinate snapped to nearest graph node.",
        **result,
    }