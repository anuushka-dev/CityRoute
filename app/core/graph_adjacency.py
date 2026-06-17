# app/core/graph_adjacency.py

from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from time import perf_counter
from typing import Any


EARTH_RADIUS_M = 6_371_000


@dataclass(frozen=True)
class AdjacentEdge:

    neighbor: Any
    length_m: float


@dataclass(frozen=True)
class GraphAdjacency:

    adjacency: dict[Any, list[AdjacentEdge]]
    node_coordinates: dict[Any, tuple[float, float]]
    node_count: int
    edge_count: int
    directed: bool
    multigraph: bool
    build_time_ms: float

    def neighbors(self, node: Any) -> list[AdjacentEdge]:
        return self.adjacency.get(node, [])


def haversine_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:

    lat1_rad = radians(lat1)
    lon1_rad = radians(lon1)
    lat2_rad = radians(lat2)
    lon2_rad = radians(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = (
        sin(dlat / 2.0) ** 2
        + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2.0) ** 2
    )

    c = 2.0 * asin(sqrt(a))

    return EARTH_RADIUS_M * c


def _node_lat_lon(graph: Any, node: Any) -> tuple[float, float] | None:

    node_data = graph.nodes[node]

    lat = node_data.get("y")
    lon = node_data.get("x")

    if lat is None or lon is None:
        return None

    return float(lat), float(lon)


def _fallback_edge_length_m(graph: Any, u: Any, v: Any) -> float:

    u_coord = _node_lat_lon(graph, u)
    v_coord = _node_lat_lon(graph, v)

    if u_coord is None or v_coord is None:
        return 1.0

    return haversine_m(
        u_coord[0],
        u_coord[1],
        v_coord[0],
        v_coord[1],
    )


def _edge_length_from_data(
    *,
    graph: Any,
    u: Any,
    v: Any,
    edge_data: Any,
) -> float:

    lengths: list[float] = []

    if graph.is_multigraph():
        if isinstance(edge_data, dict):
            for one_edge_data in edge_data.values():
                if (
                    isinstance(one_edge_data, dict)
                    and one_edge_data.get("length") is not None
                ):
                    lengths.append(float(one_edge_data["length"]))

    else:
        if isinstance(edge_data, dict) and edge_data.get("length") is not None:
            lengths.append(float(edge_data["length"]))

    if lengths:
        return min(lengths)

    return _fallback_edge_length_m(graph, u, v)


def _iter_outgoing_edges(graph: Any):
    for u in graph.nodes:
        if graph.is_directed():
            neighbors = graph.successors(u)
        else:
            neighbors = graph.neighbors(u)

        for v in neighbors:
            edge_data = graph.get_edge_data(u, v)
            yield u, v, edge_data


def build_graph_adjacency(graph: Any) -> GraphAdjacency:
    started_at = perf_counter()

    adjacency: dict[Any, list[AdjacentEdge]] = {}
    node_coordinates: dict[Any, tuple[float, float]] = {}

    for node in graph.nodes:
        adjacency[node] = []

        coord = _node_lat_lon(graph, node)

        if coord is not None:
            node_coordinates[node] = coord

    edge_count = 0

    for u, v, edge_data in _iter_outgoing_edges(graph):
        if edge_data is None:
            continue

        length_m = _edge_length_from_data(
            graph=graph,
            u=u,
            v=v,
            edge_data=edge_data,
        )

        adjacency.setdefault(u, []).append(
            AdjacentEdge(
                neighbor=v,
                length_m=round(float(length_m), 3),
            )
        )

        edge_count += 1

    build_time_ms = round((perf_counter() - started_at) * 1000, 3)

    return GraphAdjacency(
        adjacency=adjacency,
        node_coordinates=node_coordinates,
        node_count=len(adjacency),
        edge_count=edge_count,
        directed=bool(graph.is_directed()),
        multigraph=bool(graph.is_multigraph()),
        build_time_ms=build_time_ms,
    )


def build_adjacency(graph: Any) -> GraphAdjacency:

    return build_graph_adjacency(graph)


def get_edge_count(adjacency: GraphAdjacency) -> int:

    return sum(len(edges) for edges in adjacency.adjacency.values())