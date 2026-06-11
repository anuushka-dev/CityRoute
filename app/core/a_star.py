# app/core/a_star.py

from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from math import asin, cos, radians, sin, sqrt
from time import perf_counter
from typing import Any

import networkx as nx


EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class AStarResult:
    path: list[int]
    distance_m: float
    nodes_expanded: int
    route_time_ms: float


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Spherical distance in meters.
    Used as A* heuristic.

    For road routing this is admissible because straight-line distance
    cannot be greater than real road distance.
    """
    lat1_rad = radians(lat1)
    lon1_rad = radians(lon1)
    lat2_rad = radians(lat2)
    lon2_rad = radians(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = (
        sin(dlat / 2) ** 2
        + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2) ** 2
    )
    c = 2 * asin(sqrt(a))
    return EARTH_RADIUS_M * c


def _node_lat_lon(graph: nx.Graph, node: int) -> tuple[float, float]:
    data = graph.nodes[node]
    return float(data["y"]), float(data["x"])


def _edge_length_m(graph: nx.Graph, u: int, v: int) -> float:
    """
    Returns shortest edge length between u and v.

    OSMnx usually gives a MultiDiGraph, so graph.get_edge_data(u, v)
    can be:
      {0: {"length": ...}, 1: {"length": ...}}
    For a normal DiGraph it can be:
      {"length": ...}
    """
    edge_data = graph.get_edge_data(u, v)

    if not edge_data:
        u_lat, u_lon = _node_lat_lon(graph, u)
        v_lat, v_lon = _node_lat_lon(graph, v)
        return haversine_m(u_lat, u_lon, v_lat, v_lon)

    # MultiDiGraph case
    if all(isinstance(value, dict) for value in edge_data.values()):
        lengths: list[float] = []
        for attrs in edge_data.values():
            length = attrs.get("length")
            if length is not None:
                lengths.append(float(length))

        if lengths:
            return min(lengths)

    # DiGraph case
    length = edge_data.get("length") if isinstance(edge_data, dict) else None
    if length is not None:
        return float(length)

    u_lat, u_lon = _node_lat_lon(graph, u)
    v_lat, v_lon = _node_lat_lon(graph, v)
    return haversine_m(u_lat, u_lon, v_lat, v_lon)


def reconstruct_path(came_from: dict[int, int], current: int) -> list[int]:
    path = [current]

    while current in came_from:
        current = came_from[current]
        path.append(current)

    path.reverse()
    return path


def astar_shortest_path(graph: nx.Graph, start_node: int, goal_node: int) -> AStarResult:
    """
    Custom A* implementation.

    Strict Phase 3 rule:
    - no nx.astar_path
    - no nx.shortest_path for routing
    - graph adjacency is traversed manually
    """
    start_time = perf_counter()

    if start_node not in graph:
        raise nx.NodeNotFound(f"Start node not found: {start_node}")

    if goal_node not in graph:
        raise nx.NodeNotFound(f"Goal node not found: {goal_node}")

    if start_node == goal_node:
        return AStarResult(
            path=[start_node],
            distance_m=0.0,
            nodes_expanded=0,
            route_time_ms=round((perf_counter() - start_time) * 1000, 3),
        )

    goal_lat, goal_lon = _node_lat_lon(graph, goal_node)
    start_lat, start_lon = _node_lat_lon(graph, start_node)

    open_heap: list[tuple[float, int, int]] = []
    counter = 0

    start_h = haversine_m(start_lat, start_lon, goal_lat, goal_lon)
    heappush(open_heap, (start_h, counter, start_node))

    came_from: dict[int, int] = {}
    g_score: dict[int, float] = {start_node: 0.0}
    closed: set[int] = set()

    nodes_expanded = 0

    while open_heap:
        _, _, current = heappop(open_heap)

        if current in closed:
            continue

        if current == goal_node:
            path = reconstruct_path(came_from, current)
            return AStarResult(
                path=path,
                distance_m=round(g_score[current], 3),
                nodes_expanded=nodes_expanded,
                route_time_ms=round((perf_counter() - start_time) * 1000, 3),
            )

        closed.add(current)
        nodes_expanded += 1

        for neighbor in graph.successors(current):
            if neighbor in closed:
                continue

            tentative_g = g_score[current] + _edge_length_m(graph, current, neighbor)

            if tentative_g >= g_score.get(neighbor, float("inf")):
                continue

            came_from[neighbor] = current
            g_score[neighbor] = tentative_g

            n_lat, n_lon = _node_lat_lon(graph, neighbor)
            h = haversine_m(n_lat, n_lon, goal_lat, goal_lon)
            f = tentative_g + h

            counter += 1
            heappush(open_heap, (f, counter, neighbor))

    raise nx.NetworkXNoPath(f"No path found between {start_node} and {goal_node}")