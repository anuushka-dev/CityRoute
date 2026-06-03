# app/utils/node_snapper.py

from __future__ import annotations

from time import perf_counter
from typing import Any

import osmnx as ox
from fastapi import HTTPException

from app.utils.geo_validation import validate_coordinates


def snap_coordinate_to_graph(
    *,
    graph: Any,
    lat: float,
    lon: float,
) -> dict[str, Any]:
    """
    Snap a GPS coordinate to the nearest node in the loaded OSMnx graph.

    Important:
    - OSMnx nearest_nodes expects X=longitude and Y=latitude.
    - Validation runs before snapping.
    - If graph is not loaded, return 503 instead of crashing.
    """

    validate_coordinates(lat, lon)

    if graph is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Graph not loaded",
                "message": "CityRoute graph is not loaded yet.",
            },
        )

    start = perf_counter()

    try:
        nearest_node = ox.distance.nearest_nodes(
            graph,
            X=lon,
            Y=lat,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Node snapping failed",
                "message": str(exc),
            },
        ) from exc

    snap_time_ms = round((perf_counter() - start) * 1000, 3)

    node_data = graph.nodes[nearest_node]

    snapped_lat = node_data.get("y")
    snapped_lon = node_data.get("x")

    if snapped_lat is None or snapped_lon is None:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Invalid graph node data",
                "message": "Nearest node does not contain x/y coordinates.",
                "nearest_node": nearest_node,
            },
        )

    return {
        "input": {
            "lat": lat,
            "lon": lon,
        },
        "nearest_node": int(nearest_node),
        "snapped": {
            "lat": float(snapped_lat),
            "lon": float(snapped_lon),
        },
        "snap_time_ms": snap_time_ms,
    }