# app/utils/snap_index.py

from __future__ import annotations

from dataclasses import dataclass
from math import radians
from time import perf_counter
from typing import Any

import numpy as np
from sklearn.neighbors import BallTree


EARTH_RADIUS_M = 6_371_000


@dataclass(frozen=True)
class SnapIndex:
    """
    Precomputed spatial index for fast GPS -> nearest graph node lookup.

    BallTree uses haversine distance, so coordinates are stored as:
    [latitude_radians, longitude_radians]
    """

    node_ids: list[int]
    coordinates_rad: np.ndarray
    tree: BallTree
    build_time_ms: float


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

    coordinates_array = np.array(coordinates_rad)

    tree = BallTree(coordinates_array, metric="haversine")

    build_time_ms = round((perf_counter() - start) * 1000, 3)

    return SnapIndex(
        node_ids=node_ids,
        coordinates_rad=coordinates_array,
        tree=tree,
        build_time_ms=build_time_ms,
    )


def query_snap_index(
    *,
    graph: Any,
    snap_index: SnapIndex,
    lat: float,
    lon: float,
) -> dict[str, Any]:
    query_point = np.array([[radians(lat), radians(lon)]])

    distance_rad, index = snap_index.tree.query(query_point, k=1)

    nearest_index = int(index[0][0])
    nearest_node = snap_index.node_ids[nearest_index]
    distance_m = round(float(distance_rad[0][0]) * EARTH_RADIUS_M, 3)

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
    }