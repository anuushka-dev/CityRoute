# app/utils/route_map.py

from __future__ import annotations

from pathlib import Path
from typing import Any

import folium


def _require_route_geometry(route_result: dict[str, Any]) -> list[dict[str, float]]:
    geometry = route_result.get("geometry")

    if not isinstance(geometry, list):
        raise ValueError("Route result must contain a geometry list.")

    if len(geometry) < 2:
        raise ValueError("Route geometry must contain at least 2 points.")

    for index, point in enumerate(geometry):
        if not isinstance(point, dict):
            raise ValueError(f"Geometry point {index} must be a dictionary.")

        if "lat" not in point or "lon" not in point:
            raise ValueError(f"Geometry point {index} must contain lat and lon.")

    return geometry


def _lat_lon_tuple(point: dict[str, Any]) -> tuple[float, float]:
    return float(point["lat"]), float(point["lon"])


def _route_center(geometry: list[dict[str, float]]) -> tuple[float, float]:
    latitudes = [float(point["lat"]) for point in geometry]
    longitudes = [float(point["lon"]) for point in geometry]

    center_lat = sum(latitudes) / len(latitudes)
    center_lon = sum(longitudes) / len(longitudes)

    return center_lat, center_lon


def _route_summary_html(route_result: dict[str, Any]) -> str:
    distance_km = route_result.get("distance_km")
    eta_minutes = route_result.get("eta_minutes")
    path_node_count = route_result.get("path_node_count")
    nodes_expanded = route_result.get("nodes_expanded")
    route_time_ms = route_result.get("route_time_ms")
    total_time_ms = route_result.get("total_time_ms")
    algorithm = route_result.get("algorithm", "unknown")

    return f"""
    <h4>CityRoute Phase 3.5 Route Verification</h4>
    <b>Algorithm:</b> {algorithm}<br>
    <b>Distance:</b> {distance_km} km<br>
    <b>ETA:</b> {eta_minutes} min<br>
    <b>Path nodes:</b> {path_node_count}<br>
    <b>Nodes expanded:</b> {nodes_expanded}<br>
    <b>A* route time:</b> {route_time_ms} ms<br>
    <b>Total time:</b> {total_time_ms} ms<br>
    """


def generate_route_map(
    route_result: dict[str, Any],
    output_path: str | Path,
    *,
    zoom_start: int = 14,
) -> Path:
    """
    Generate an HTML Folium map for a CityRoute /route response.

    This is Phase 3.5 visual verification only.
    It does not recompute the route.
    It uses the geometry already returned by the /route endpoint.
    """
    geometry = _require_route_geometry(route_result)
    output = Path(output_path)

    output.parent.mkdir(parents=True, exist_ok=True)

    route_coordinates = [_lat_lon_tuple(point) for point in geometry]
    center = _route_center(geometry)

    route_map = folium.Map(
        location=center,
        zoom_start=zoom_start,
        control_scale=True,
    )

    folium.PolyLine(
        locations=route_coordinates,
        weight=6,
        opacity=0.85,
        tooltip="A* route geometry",
    ).add_to(route_map)

    start_point = route_coordinates[0]
    end_point = route_coordinates[-1]

    start_popup = route_result.get("start", {})
    end_popup = route_result.get("end", {})

    folium.Marker(
        location=start_point,
        popup=folium.Popup(
            f"""
            <b>Start</b><br>
            Snapped node: {start_popup.get("snapped_node")}<br>
            Snap distance: {start_popup.get("snap_distance_m")} m<br>
            Snap method: {start_popup.get("snap_method")}
            """,
            max_width=300,
        ),
        tooltip="Start",
    ).add_to(route_map)

    folium.Marker(
        location=end_point,
        popup=folium.Popup(
            f"""
            <b>End</b><br>
            Snapped node: {end_popup.get("snapped_node")}<br>
            Snap distance: {end_popup.get("snap_distance_m")} m<br>
            Snap method: {end_popup.get("snap_method")}
            """,
            max_width=300,
        ),
        tooltip="End",
    ).add_to(route_map)

    folium.Marker(
        location=center,
        popup=folium.Popup(_route_summary_html(route_result), max_width=400),
        tooltip="Route summary",
    ).add_to(route_map)

    route_map.fit_bounds(route_coordinates)

    route_map.save(str(output))

    return output