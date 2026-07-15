# app/core/graph_adjacency.py

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from time import perf_counter
from typing import Any

EARTH_RADIUS_M = 6_371_000.0

# Preserves the existing Phase 5 behavior when:
# - an edge has no usable "length" attribute, and
# - one or both endpoint coordinates are unavailable.
#
# Real OSM road graphs should normally provide edge lengths.
MISSING_COORDINATE_FALLBACK_EDGE_LENGTH_M = 1.0


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

    def neighbors(
        self,
        node: Any,
    ) -> list[AdjacentEdge]:

        return self.adjacency.get(
            node,
            [],
        )

    def has_node(
        self,
        node: Any,
    ) -> bool:
        """Return whether the node exists in the adjacency structure."""

        return node in self.adjacency

    def coordinates(
        self,
        node: Any,
    ) -> tuple[float, float] | None:
        """Return `(latitude, longitude)` when available."""

        return self.node_coordinates.get(
            node
        )


def haversine_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:

    normalized_lat1 = float(lat1)
    normalized_lon1 = float(lon1)
    normalized_lat2 = float(lat2)
    normalized_lon2 = float(lon2)

    _validate_lat_lon(
        lat=normalized_lat1,
        lon=normalized_lon1,
        name="first coordinate",
    )

    _validate_lat_lon(
        lat=normalized_lat2,
        lon=normalized_lon2,
        name="second coordinate",
    )

    lat1_rad = radians(
        normalized_lat1
    )

    lon1_rad = radians(
        normalized_lon1
    )

    lat2_rad = radians(
        normalized_lat2
    )

    lon2_rad = radians(
        normalized_lon2
    )

    dlat = (
        lat2_rad
        - lat1_rad
    )

    dlon = (
        lon2_rad
        - lon1_rad
    )

    haversine_a = (
        sin(
            dlat / 2.0
        )
        ** 2
        + cos(
            lat1_rad
        )
        * cos(
            lat2_rad
        )
        * sin(
            dlon / 2.0
        )
        ** 2
    )

    # Floating-point protection.
    haversine_a = min(
        1.0,
        max(
            0.0,
            haversine_a,
        ),
    )

    haversine_c = (
        2.0
        * asin(
            sqrt(
                haversine_a
            )
        )
    )

    return (
        EARTH_RADIUS_M
        * haversine_c
    )


def _node_lat_lon(
    graph: Any,
    node: Any,
) -> tuple[float, float] | None:


    try:
        node_data = graph.nodes[
            node
        ]

    except Exception:
        return None

    lat = node_data.get(
        "y"
    )

    lon = node_data.get(
        "x"
    )

    if (
        lat is None
        or lon is None
    ):
        return None

    try:
        normalized_lat = float(
            lat
        )

        normalized_lon = float(
            lon
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None

    if not (
        math.isfinite(
            normalized_lat
        )
        and math.isfinite(
            normalized_lon
        )
    ):
        return None

    if not (
        -90.0
        <= normalized_lat
        <= 90.0
    ):
        return None

    if not (
        -180.0
        <= normalized_lon
        <= 180.0
    ):
        return None

    return (
        normalized_lat,
        normalized_lon,
    )


def _fallback_edge_length_m(
    graph: Any,
    u: Any,
    v: Any,
) -> float:

    u_coord = _node_lat_lon(
        graph,
        u,
    )

    v_coord = _node_lat_lon(
        graph,
        v,
    )

    if (
        u_coord is None
        or v_coord is None
    ):
        return (
            MISSING_COORDINATE_FALLBACK_EDGE_LENGTH_M
        )

    return haversine_m(
        u_coord[0],
        u_coord[1],
        v_coord[0],
        v_coord[1],
    )


def _normalize_edge_length(
    value: Any,
) -> float | None:

    if (
        value is None
        or isinstance(
            value,
            bool,
        )
    ):
        return None

    try:
        length_m = float(
            value
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None

    if not math.isfinite(
        length_m
    ):
        return None

    if length_m < 0:
        return None

    return length_m


def _edge_length_from_data(
    *,
    graph: Any,
    u: Any,
    v: Any,
    edge_data: Any,
) -> float:

    lengths: list[float] = []

    if graph.is_multigraph():
        if isinstance(
            edge_data,
            dict,
        ):
            for one_edge_data in (
                edge_data.values()
            ):
                if not isinstance(
                    one_edge_data,
                    dict,
                ):
                    continue

                normalized_length = (
                    _normalize_edge_length(
                        one_edge_data.get(
                            "length"
                        )
                    )
                )

                if (
                    normalized_length
                    is not None
                ):
                    lengths.append(
                        normalized_length
                    )

    else:
        if isinstance(
            edge_data,
            dict,
        ):
            normalized_length = (
                _normalize_edge_length(
                    edge_data.get(
                        "length"
                    )
                )
            )

            if (
                normalized_length
                is not None
            ):
                lengths.append(
                    normalized_length
                )

    if lengths:
        return min(
            lengths
        )

    return _fallback_edge_length_m(
        graph,
        u,
        v,
    )


def _iter_outgoing_edges(
    graph: Any,
) -> Iterator[
    tuple[
        Any,
        Any,
        Any,
    ]
]:

    directed = bool(
        graph.is_directed()
    )

    for u in graph.nodes:
        neighbors = (
            graph.successors(u)
            if directed
            else graph.neighbors(u)
        )

        for v in neighbors:
            edge_data = (
                graph.get_edge_data(
                    u,
                    v,
                )
            )

            yield (
                u,
                v,
                edge_data,
            )


def build_graph_adjacency(
    graph: Any,
) -> GraphAdjacency:
    started_at = perf_counter()

    _validate_graph(
        graph
    )

    adjacency: dict[
        Any,
        list[AdjacentEdge],
    ] = {}

    node_coordinates: dict[
        Any,
        tuple[float, float],
    ] = {}

    # ------------------------------------------------------------------
    # 1. Register every graph node.
    #
    # Nodes with no outgoing edges must still exist in the adjacency map.
    # ------------------------------------------------------------------

    for node in graph.nodes:
        adjacency[
            node
        ] = []

        coordinate = (
            _node_lat_lon(
                graph,
                node,
            )
        )

        if coordinate is not None:
            node_coordinates[
                node
            ] = coordinate

    # ------------------------------------------------------------------
    # 2. Build outgoing adjacency arcs.
    # ------------------------------------------------------------------

    edge_count = 0

    for (
        u,
        v,
        edge_data,
    ) in _iter_outgoing_edges(
        graph
    ):
        if edge_data is None:
            continue

        length_m = (
            _edge_length_from_data(
                graph=graph,
                u=u,
                v=v,
                edge_data=edge_data,
            )
        )

        normalized_length_m = (
            _normalize_edge_length(
                length_m
            )
        )

        if (
            normalized_length_m
            is None
        ):
            raise ValueError(
                "Cannot build graph adjacency: "
                "invalid edge length for "
                f"edge ({u!r}, {v!r})."
            )

        adjacency.setdefault(
            u,
            [],
        ).append(
            AdjacentEdge(
                neighbor=v,
                # Preserve the existing CityRoute Phase 5
                # millimeter-level edge normalization.
                length_m=round(
                    normalized_length_m,
                    3,
                ),
            )
        )

        edge_count += 1

    build_time_ms = _elapsed_ms(
        started_at
    )

    return GraphAdjacency(
        adjacency=adjacency,
        node_coordinates=node_coordinates,
        node_count=len(
            adjacency
        ),
        edge_count=edge_count,
        directed=bool(
            graph.is_directed()
        ),
        multigraph=bool(
            graph.is_multigraph()
        ),
        build_time_ms=build_time_ms,
    )


def build_adjacency(
    graph: Any,
) -> GraphAdjacency:

    return build_graph_adjacency(
        graph
    )


def get_edge_count(
    adjacency: GraphAdjacency,
) -> int:

    return sum(
        len(edges)
        for edges
        in adjacency.adjacency.values()
    )


def _validate_graph(
    graph: Any,
) -> None:
    """Validate the minimum NetworkX-style graph interface required."""

    if graph is None:
        raise ValueError(
            "Cannot build graph adjacency: graph is None."
        )

    required_attributes = (
        "nodes",
        "get_edge_data",
        "is_directed",
        "is_multigraph",
    )

    for attribute in required_attributes:
        if not hasattr(
            graph,
            attribute,
        ):
            raise TypeError(
                "Cannot build graph adjacency: "
                f"graph is missing {attribute!r}."
            )

    if not (
        hasattr(
            graph,
            "successors",
        )
        or hasattr(
            graph,
            "neighbors",
        )
    ):
        raise TypeError(
            "Cannot build graph adjacency: graph must expose "
            "successors() or neighbors()."
        )


def _validate_lat_lon(
    *,
    lat: float,
    lon: float,
    name: str,
) -> None:
    if not (
        math.isfinite(lat)
        and math.isfinite(lon)
    ):
        raise ValueError(
            f"{name} must contain finite coordinates."
        )

    if not (
        -90.0
        <= lat
        <= 90.0
    ):
        raise ValueError(
            f"{name} latitude must be between -90 and 90."
        )

    if not (
        -180.0
        <= lon
        <= 180.0
    ):
        raise ValueError(
            f"{name} longitude must be between -180 and 180."
        )


def _elapsed_ms(
    started_at: float,
) -> float:
    return round(
        (
            perf_counter()
            - started_at
        )
        * 1000.0,
        3,
    )


__all__ = [
    "EARTH_RADIUS_M",
    "MISSING_COORDINATE_FALLBACK_EDGE_LENGTH_M",
    "AdjacentEdge",
    "GraphAdjacency",
    "build_adjacency",
    "build_graph_adjacency",
    "get_edge_count",
    "haversine_m",
]