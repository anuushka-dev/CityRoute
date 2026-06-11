# app/services/routing_service.py

from __future__ import annotations

from math import isclose
from time import perf_counter
from typing import Any

import networkx as nx
from fastapi import HTTPException

from app.core.a_star import astar_shortest_path
from app.core.bidirectional_a_star import bidirectional_astar_shortest_path
from app.core.eta import estimate_eta_seconds
from app.utils.node_snapper import snap_coordinate_to_graph


def _geometry_from_path(graph: nx.Graph, path: list[Any]) -> list[dict[str, float]]:
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

    except nx.NodeNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "Node not found",
                "message": str(exc),
                "start_node": start_node,
                "end_node": end_node,
            },
        ) from exc

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


def _summarize_astar_route(route_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "algorithm": "astar",
        "distance_m": route_result["distance_m"],
        "distance_km": route_result["distance_km"],
        "eta_seconds": route_result["eta_seconds"],
        "eta_minutes": route_result["eta_minutes"],
        "path_node_count": route_result["path_node_count"],
        "nodes_expanded": route_result["nodes_expanded"],
        "route_time_ms": route_result["route_time_ms"],
        "total_time_ms": route_result["total_time_ms"],
    }


def _summarize_bidirectional_route(
    *,
    graph: nx.Graph,
    bidirectional_result: Any,
) -> dict[str, Any]:
    distance_m = round(float(bidirectional_result.distance_m), 3)
    eta_seconds = estimate_eta_seconds(graph, bidirectional_result.path)
    geometry = _geometry_from_path(graph, bidirectional_result.path)

    return {
        "algorithm": "bidirectional_astar",
        "distance_m": distance_m,
        "distance_km": round(distance_m / 1000, 3),
        "eta_seconds": round(eta_seconds, 1),
        "eta_minutes": round(eta_seconds / 60, 2),
        "path_node_count": len(bidirectional_result.path),
        "nodes_expanded": bidirectional_result.nodes_expanded,
        "forward_nodes_expanded": bidirectional_result.forward_nodes_expanded,
        "backward_nodes_expanded": bidirectional_result.backward_nodes_expanded,
        "route_time_ms": bidirectional_result.route_time_ms,
        "meeting_node": bidirectional_result.meeting_node,
        "geometry": geometry,
    }


def _build_algorithm_comparison(
    *,
    astar_summary: dict[str, Any],
    bidirectional_summary: dict[str, Any],
) -> dict[str, Any]:
    astar_distance = float(astar_summary["distance_m"])
    bidirectional_distance = float(bidirectional_summary["distance_m"])

    astar_time = float(astar_summary["route_time_ms"])
    bidirectional_time = float(bidirectional_summary["route_time_ms"])

    astar_nodes = int(astar_summary["nodes_expanded"])
    bidirectional_nodes = int(bidirectional_summary["nodes_expanded"])

    distance_delta_m = round(abs(astar_distance - bidirectional_distance), 6)
    route_time_delta_ms = round(astar_time - bidirectional_time, 3)
    nodes_expanded_delta = astar_nodes - bidirectional_nodes

    if astar_nodes > 0:
        nodes_expanded_reduction_pct = round(
            (nodes_expanded_delta / astar_nodes) * 100,
            3,
        )
    else:
        nodes_expanded_reduction_pct = 0.0

    if astar_time > 0:
        route_time_reduction_pct = round(
            (route_time_delta_ms / astar_time) * 100,
            3,
        )
    else:
        route_time_reduction_pct = 0.0

    return {
        "distance_delta_m": distance_delta_m,
        "same_distance": isclose(
            astar_distance,
            bidirectional_distance,
            rel_tol=0,
            abs_tol=0.001,
        ),
        "astar_route_time_ms": astar_time,
        "bidirectional_route_time_ms": bidirectional_time,
        "route_time_delta_ms": route_time_delta_ms,
        "astar_faster": astar_time < bidirectional_time,
        "bidirectional_faster": bidirectional_time < astar_time,
        "astar_nodes_expanded": astar_nodes,
        "bidirectional_nodes_expanded": bidirectional_nodes,
        "nodes_expanded_delta": nodes_expanded_delta,
        "nodes_expanded_reduction_pct": nodes_expanded_reduction_pct,
        "route_time_reduction_pct": route_time_reduction_pct,
    }


def compare_routes(
    graph: nx.Graph | None,
    snap_index: Any,
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
) -> dict[str, Any]:
    """
    Compare Phase 3 A* against Phase 4 Bidirectional A*.

    Important:
    - This does not replace /route.
    - It reuses existing snapping.
    - It runs both algorithms on the same snapped start/end nodes.
    - NetworkX is still only used as the graph container here.
    """
    if graph is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Graph not loaded",
                "message": "Routing is unavailable because the road graph is not loaded.",
            },
        )

    compare_start = perf_counter()

    astar_route = compute_route(
        graph=graph,
        snap_index=snap_index,
        start_lat=start_lat,
        start_lon=start_lon,
        end_lat=end_lat,
        end_lon=end_lon,
    )

    start_node = int(astar_route["start"]["snapped_node"])
    end_node = int(astar_route["end"]["snapped_node"])

    try:
        bidirectional_result = bidirectional_astar_shortest_path(
            graph,
            start_node,
            end_node,
        )

    except nx.NodeNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "Node not found",
                "message": str(exc),
                "start_node": start_node,
                "end_node": end_node,
            },
        ) from exc

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

    astar_summary = _summarize_astar_route(astar_route)

    bidirectional_summary = _summarize_bidirectional_route(
        graph=graph,
        bidirectional_result=bidirectional_result,
    )

    comparison = _build_algorithm_comparison(
        astar_summary=astar_summary,
        bidirectional_summary=bidirectional_summary,
    )

    compare_total_time_ms = round((perf_counter() - compare_start) * 1000, 3)

    return {
        "status": "ok",
        "start": astar_route["start"],
        "end": astar_route["end"],
        "astar": astar_summary,
        "bidirectional_astar": bidirectional_summary,
        "comparison": comparison,
        "compare_total_time_ms": compare_total_time_ms,
    }