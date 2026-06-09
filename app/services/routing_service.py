# app/services/routing_service.py

from __future__ import annotations

from time import perf_counter
from typing import Any

import networkx as nx
from fastapi import HTTPException

from app.core.a_star import astar_shortest_path
from app.core.eta import estimate_eta_seconds
from app.utils.node_snapper import snap_coordinate_to_graph


def _geometry_from_path(graph: nx.Graph, path: list[int]) -> list[dict[str, float]]:
    geometry: list[dict[str, float]] = []

    for node in path:
        node_data = graph.nodes[node]
        geometry.append(
            {
                "lat": float(node_data["y"]),
                "lon": float(node_data["x"]),
            }
        )

    return geometry


def _snap_to_node(
    graph: nx.Graph,
    snap_index: Any,
    lat: float,
    lon: float,
) -> dict[str, Any]:
    return snap_coordinate_to_graph(
        graph=graph,
        lat=lat,
        lon=lon,
        snap_index=snap_index,
    )


def compute_route(
    graph: nx.Graph | None,
    snap_index: Any,
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
) -> dict[str, Any]:
    if graph is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Graph not loaded",
                "message": "Routing is unavailable because the road graph is not loaded.",
            },
        )

    total_start = perf_counter()

    start_snap = _snap_to_node(graph, snap_index, start_lat, start_lon)
    end_snap = _snap_to_node(graph, snap_index, end_lat, end_lon)

    start_node = int(start_snap["nearest_node"])
    end_node = int(end_snap["nearest_node"])

    try:
        route_result = astar_shortest_path(graph, start_node, end_node)
    except nx.NetworkXNoPath as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "No path found",
                "message": str(exc),
                "start_node": start_node,
                "end_node": end_node,
            },
        ) from exc

    eta_seconds = estimate_eta_seconds(graph, route_result.path)
    geometry = _geometry_from_path(graph, route_result.path)

    total_time_ms = round((perf_counter() - total_start) * 1000, 3)

    return {
        "status": "ok",
        "algorithm": "astar",
        "start": {
            "input": {"lat": start_lat, "lon": start_lon},
            "snapped_node": start_node,
            "snapped": start_snap["snapped"],
            "snap_distance_m": start_snap.get("snap_distance_m"),
            "snap_method": start_snap.get("snap_method"),
            "snap_time_ms": start_snap.get("snap_time_ms"),
        },
        "end": {
            "input": {"lat": end_lat, "lon": end_lon},
            "snapped_node": end_node,
            "snapped": end_snap["snapped"],
            "snap_distance_m": end_snap.get("snap_distance_m"),
            "snap_method": end_snap.get("snap_method"),
            "snap_time_ms": end_snap.get("snap_time_ms"),
        },
        "distance_m": route_result.distance_m,
        "distance_km": round(route_result.distance_m / 1000, 3),
        "eta_seconds": round(eta_seconds, 1),
        "eta_minutes": round(eta_seconds / 60, 2),
        "path_node_count": len(route_result.path),
        "nodes_expanded": route_result.nodes_expanded,
        "route_time_ms": route_result.route_time_ms,
        "total_time_ms": total_time_ms,
        "geometry": geometry,
    }