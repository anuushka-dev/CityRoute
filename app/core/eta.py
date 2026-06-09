# app/core/eta.py

from __future__ import annotations

from typing import Any

import networkx as nx


DEFAULT_SPEED_KMPH = 25.0

SPEED_BY_HIGHWAY_KMPH = {
    "motorway": 80.0,
    "trunk": 65.0,
    "primary": 50.0,
    "secondary": 40.0,
    "tertiary": 35.0,
    "unclassified": 25.0,
    "residential": 22.0,
    "service": 15.0,
    "living_street": 10.0,
}


def _normalize_highway(value: Any) -> str | None:
    if isinstance(value, list) and value:
        return str(value[0])

    if value is None:
        return None

    return str(value)


def _best_edge_attrs(graph: nx.Graph, u: int, v: int) -> dict[str, Any]:
    edge_data = graph.get_edge_data(u, v)

    if not edge_data:
        return {}

    # MultiDiGraph case
    if all(isinstance(value, dict) for value in edge_data.values()):
        best_attrs: dict[str, Any] | None = None
        best_length = float("inf")

        for attrs in edge_data.values():
            length = float(attrs.get("length", float("inf")))
            if length < best_length:
                best_length = length
                best_attrs = attrs

        return best_attrs or {}

    # DiGraph case
    return edge_data if isinstance(edge_data, dict) else {}


def estimate_eta_seconds(graph: nx.Graph, path: list[int]) -> float:
    """
    Formula-based ETA:
    ETA = sum(edge_length / road_type_speed)

    This is intentionally honest:
    - no live traffic claim
    - no Google Maps claim
    - speed profile is configurable later
    """
    if len(path) < 2:
        return 0.0

    total_seconds = 0.0

    for u, v in zip(path, path[1:]):
        attrs = _best_edge_attrs(graph, u, v)

        length_m = float(attrs.get("length", 0.0))
        highway = _normalize_highway(attrs.get("highway"))
        speed_kmph = SPEED_BY_HIGHWAY_KMPH.get(highway, DEFAULT_SPEED_KMPH)

        speed_mps = speed_kmph * 1000 / 3600
        if speed_mps <= 0:
            speed_mps = DEFAULT_SPEED_KMPH * 1000 / 3600

        total_seconds += length_m / speed_mps

    return total_seconds