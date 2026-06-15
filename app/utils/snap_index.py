# app/utils/snap_index.py

from __future__ import annotations

from dataclasses import dataclass
from math import radians
from time import perf_counter
from typing import Any

import numpy as np

try:
    from sklearn.neighbors import BallTree
except Exception as exc:
    BallTree = None
    BALLTREE_IMPORT_ERROR = exc
else:
    BALLTREE_IMPORT_ERROR = None


EARTH_RADIUS_M = 6_371_000


@dataclass(frozen=True)
class SnapIndex:
    node_ids: list[int]
    coordinates_rad: np.ndarray
    tree: Any | None
    build_time_ms: float
    method: str
    import_error: str | None = None


def build_snap_index(graph: Any) -> SnapIndex:
    start = perf_counter()

    node_ids: list[int] = []
    coordinates_rad: list[list[float]] = []

    for node_id, data in graph.nodes(data=True):
        lat = data.get("y")
        lon = data.get("x")

        if lat is None or lon is None:
            continue

        node_ids.append(int(node_id))
        coordinates_rad.append([radians(float(lat)), radians(float(lon))])

    if not node_ids:
        raise ValueError("Cannot build snap index: graph has no nodes with x/y coordinates.")

    coordinates_array = np.array(coordinates_rad, dtype=float)

    if BallTree is not None:
        tree = BallTree(coordinates_array, metric="haversine")
        method = "balltree"
        import_error = None
    else:
        tree = None
        method = "linear_fallback"
        import_error = repr(BALLTREE_IMPORT_ERROR)

    build_time_ms = round((perf_counter() - start) * 1000, 3)

    return SnapIndex(
        node_ids=node_ids,
        coordinates_rad=coordinates_array,
        tree=tree,
        build_time_ms=build_time_ms,
        method=method,
        import_error=import_error,
    )


def _query_with_balltree(
    *,
    snap_index: SnapIndex,
    lat: float,
    lon: float,
) -> tuple[int, float]:
    if snap_index.tree is None:
        raise ValueError("BallTree snap index is not available.")

    query_point = np.array([[radians(lat), radians(lon)]], dtype=float)

    distance_rad, index = snap_index.tree.query(query_point, k=1)

    nearest_index = int(index[0][0])
    distance_m = round(float(distance_rad[0][0]) * EARTH_RADIUS_M, 3)

    return nearest_index, distance_m


def _query_with_linear_fallback(
    *,
    snap_index: SnapIndex,
    lat: float,
    lon: float,
) -> tuple[int, float]:
    query_lat = radians(lat)
    query_lon = radians(lon)

    coords = snap_index.coordinates_rad

    dlat = coords[:, 0] - query_lat
    dlon = coords[:, 1] - query_lon

    haversine_a = (
        np.sin(dlat / 2.0) ** 2
        + np.cos(query_lat) * np.cos(coords[:, 0]) * np.sin(dlon / 2.0) ** 2
    )

    haversine_c = 2.0 * np.arcsin(np.sqrt(haversine_a))

    nearest_index = int(np.argmin(haversine_c))
    distance_m = round(float(haversine_c[nearest_index]) * EARTH_RADIUS_M, 3)

    return nearest_index, distance_m


def query_snap_index(
    *,
    graph: Any,
    snap_index: SnapIndex,
    lat: float,
    lon: float,
) -> dict[str, Any]:
    if snap_index.method == "balltree":
        nearest_index, distance_m = _query_with_balltree(
            snap_index=snap_index,
            lat=lat,
            lon=lon,
        )
    else:
        nearest_index, distance_m = _query_with_linear_fallback(
            snap_index=snap_index,
            lat=lat,
            lon=lon,
        )

    nearest_node = snap_index.node_ids[nearest_index]
    node_data = graph.nodes[nearest_node]

    snapped_lat = node_data.get("y")
    snapped_lon = node_data.get("x")

    if snapped_lat is None or snapped_lon is None:
        raise ValueError(f"Nearest node {nearest_node} does not contain x/y coordinates.")

    return {
        "nearest_node": nearest_node,
        "snapped": {
            "lat": float(snapped_lat),
            "lon": float(snapped_lon),
        },
        "snap_distance_m": distance_m,
        "snap_method": snap_index.method,
    }