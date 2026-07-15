# app/utils/snap_index.py

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, radians
from time import perf_counter
from typing import Any, Literal, TypedDict

import numpy as np

try:
    from sklearn.neighbors import BallTree
except Exception as exc:
    BallTree = None
    BALLTREE_IMPORT_ERROR = exc
else:
    BALLTREE_IMPORT_ERROR = None


EARTH_RADIUS_M = 6_371_000.0


SnapMethod = Literal[
    "balltree",
    "linear_fallback",
]


class SnappedCoordinate(TypedDict):
    lat: float
    lon: float


class SnapQueryResult(TypedDict):
    nearest_node: int
    snapped: SnappedCoordinate
    snap_distance_m: float
    snap_method: SnapMethod


@dataclass(frozen=True)
class SnapIndex:

    node_ids: list[int]
    coordinates_rad: np.ndarray
    tree: Any | None
    build_time_ms: float
    method: SnapMethod
    import_error: str | None = None

    @property
    def node_count(self) -> int:
        return len(self.node_ids)

    @property
    def is_balltree(self) -> bool:
        return (
            self.method == "balltree"
            and self.tree is not None
        )


def build_snap_index(
    graph: Any,
) -> SnapIndex:

    start = perf_counter()

    if graph is None:
        raise ValueError(
            "Cannot build snap index: graph is None."
        )

    if not hasattr(graph, "nodes"):
        raise TypeError(
            "Cannot build snap index: graph must expose nodes()."
        )

    node_ids: list[int] = []
    coordinates_rad: list[list[float]] = []

    for node_id, data in graph.nodes(
        data=True
    ):
        lat = data.get("y")
        lon = data.get("x")

        if lat is None or lon is None:
            continue

        try:
            normalized_lat = float(lat)
            normalized_lon = float(lon)
            normalized_node_id = int(node_id)

        except (
            TypeError,
            ValueError,
            OverflowError,
        ):
            continue

        if not (
            isfinite(normalized_lat)
            and isfinite(normalized_lon)
        ):
            continue

        if not (
            -90.0
            <= normalized_lat
            <= 90.0
        ):
            continue

        if not (
            -180.0
            <= normalized_lon
            <= 180.0
        ):
            continue

        node_ids.append(
            normalized_node_id
        )

        coordinates_rad.append(
            [
                radians(normalized_lat),
                radians(normalized_lon),
            ]
        )

    if not node_ids:
        raise ValueError(
            "Cannot build snap index: graph has no valid "
            "nodes with finite x/y coordinates."
        )

    coordinates_array = np.asarray(
        coordinates_rad,
        dtype=np.float64,
    )

    if (
        coordinates_array.ndim != 2
        or coordinates_array.shape[1] != 2
    ):
        raise ValueError(
            "Cannot build snap index: coordinate matrix "
            "must have shape (n, 2)."
        )

    if BallTree is not None:
        tree = BallTree(
            coordinates_array,
            metric="haversine",
        )

        method: SnapMethod = "balltree"

        import_error = None

    else:
        tree = None

        method = "linear_fallback"

        import_error = (
            repr(BALLTREE_IMPORT_ERROR)
            if BALLTREE_IMPORT_ERROR
            is not None
            else "BallTree unavailable"
        )

    build_time_ms = _elapsed_ms(
        start
    )

    return SnapIndex(
        node_ids=node_ids,
        coordinates_rad=coordinates_array,
        tree=tree,
        build_time_ms=build_time_ms,
        method=method,
        import_error=import_error,
    )


def query_snap_index(
    *,
    graph: Any,
    snap_index: SnapIndex,
    lat: float,
    lon: float,
) -> SnapQueryResult:

    normalized_lat, normalized_lon = (
        _validate_query_coordinate(
            lat=lat,
            lon=lon,
        )
    )

    _validate_snap_index(
        snap_index
    )

    if graph is None:
        raise ValueError(
            "Cannot query snap index: graph is None."
        )

    if snap_index.method == "balltree":
        nearest_index, distance_m = (
            _query_with_balltree(
                snap_index=snap_index,
                lat=normalized_lat,
                lon=normalized_lon,
            )
        )

    elif (
        snap_index.method
        == "linear_fallback"
    ):
        nearest_index, distance_m = (
            _query_with_linear_fallback(
                snap_index=snap_index,
                lat=normalized_lat,
                lon=normalized_lon,
            )
        )

    else:
        raise ValueError(
            "Unsupported snap-index method: "
            f"{snap_index.method!r}."
        )

    nearest_node = int(
        snap_index.node_ids[
            nearest_index
        ]
    )

    try:
        node_data = graph.nodes[
            nearest_node
        ]

    except Exception as exc:
        raise ValueError(
            "Nearest node returned by snap index "
            f"is not available in graph: {nearest_node}."
        ) from exc

    snapped_lat = node_data.get(
        "y"
    )

    snapped_lon = node_data.get(
        "x"
    )

    if (
        snapped_lat is None
        or snapped_lon is None
    ):
        raise ValueError(
            f"Nearest node {nearest_node} "
            "does not contain x/y coordinates."
        )

    try:
        normalized_snapped_lat = float(
            snapped_lat
        )

        normalized_snapped_lon = float(
            snapped_lon
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as exc:
        raise ValueError(
            f"Nearest node {nearest_node} "
            "contains invalid x/y coordinates."
        ) from exc

    if not (
        isfinite(
            normalized_snapped_lat
        )
        and isfinite(
            normalized_snapped_lon
        )
    ):
        raise ValueError(
            f"Nearest node {nearest_node} "
            "contains non-finite x/y coordinates."
        )

    return {
        "nearest_node": nearest_node,
        "snapped": {
            "lat": normalized_snapped_lat,
            "lon": normalized_snapped_lon,
        },
        "snap_distance_m": distance_m,
        "snap_method": snap_index.method,
    }


def query_nearest_node_id(
    *,
    snap_index: SnapIndex,
    lat: float,
    lon: float,
) -> int:

    normalized_lat, normalized_lon = (
        _validate_query_coordinate(
            lat=lat,
            lon=lon,
        )
    )

    _validate_snap_index(
        snap_index
    )

    if snap_index.method == "balltree":
        nearest_index, _ = (
            _query_with_balltree(
                snap_index=snap_index,
                lat=normalized_lat,
                lon=normalized_lon,
            )
        )

    elif (
        snap_index.method
        == "linear_fallback"
    ):
        nearest_index, _ = (
            _query_with_linear_fallback(
                snap_index=snap_index,
                lat=normalized_lat,
                lon=normalized_lon,
            )
        )

    else:
        raise ValueError(
            "Unsupported snap-index method: "
            f"{snap_index.method!r}."
        )

    return int(
        snap_index.node_ids[
            nearest_index
        ]
    )


def _query_with_balltree(
    *,
    snap_index: SnapIndex,
    lat: float,
    lon: float,
) -> tuple[int, float]:

    if snap_index.tree is None:
        raise ValueError(
            "BallTree snap index is not available."
        )

    query_point = np.asarray(
        [
            [
                radians(lat),
                radians(lon),
            ]
        ],
        dtype=np.float64,
    )

    distance_rad, index = (
        snap_index.tree.query(
            query_point,
            k=1,
        )
    )

    nearest_index = int(
        index[0][0]
    )

    distance_m = round(
        float(
            distance_rad[0][0]
        )
        * EARTH_RADIUS_M,
        3,
    )

    return (
        nearest_index,
        distance_m,
    )


def _query_with_linear_fallback(
    *,
    snap_index: SnapIndex,
    lat: float,
    lon: float,
) -> tuple[int, float]:

    query_lat = radians(
        lat
    )

    query_lon = radians(
        lon
    )

    coords = (
        snap_index.coordinates_rad
    )

    dlat = (
        coords[:, 0]
        - query_lat
    )

    dlon = (
        coords[:, 1]
        - query_lon
    )

    haversine_a = (
        np.sin(
            dlat / 2.0
        )
        ** 2
        + np.cos(
            query_lat
        )
        * np.cos(
            coords[:, 0]
        )
        * np.sin(
            dlon / 2.0
        )
        ** 2
    )

    # Floating-point arithmetic can very slightly push values above 1.0,
    # which would otherwise make arcsin(sqrt(a)) return NaN.
    haversine_a = np.clip(
        haversine_a,
        0.0,
        1.0,
    )

    haversine_c = (
        2.0
        * np.arcsin(
            np.sqrt(
                haversine_a
            )
        )
    )

    nearest_index = int(
        np.argmin(
            haversine_c
        )
    )

    distance_m = round(
        float(
            haversine_c[
                nearest_index
            ]
        )
        * EARTH_RADIUS_M,
        3,
    )

    return (
        nearest_index,
        distance_m,
    )


def _validate_query_coordinate(
    *,
    lat: float,
    lon: float,
) -> tuple[float, float]:

    if (
        isinstance(lat, bool)
        or isinstance(lon, bool)
    ):
        raise TypeError(
            "Latitude and longitude must be numeric."
        )

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
    ) as exc:
        raise TypeError(
            "Latitude and longitude must be numeric."
        ) from exc

    if not isfinite(
        normalized_lat
    ):
        raise ValueError(
            "Latitude must be finite."
        )

    if not isfinite(
        normalized_lon
    ):
        raise ValueError(
            "Longitude must be finite."
        )

    if not (
        -90.0
        <= normalized_lat
        <= 90.0
    ):
        raise ValueError(
            "Latitude must be between -90 and 90."
        )

    if not (
        -180.0
        <= normalized_lon
        <= 180.0
    ):
        raise ValueError(
            "Longitude must be between -180 and 180."
        )

    return (
        normalized_lat,
        normalized_lon,
    )


def _validate_snap_index(
    snap_index: SnapIndex,
) -> None:

    if not isinstance(
        snap_index,
        SnapIndex,
    ):
        raise TypeError(
            "snap_index must be a SnapIndex instance."
        )

    if not snap_index.node_ids:
        raise ValueError(
            "Snap index contains no graph nodes."
        )

    coordinates = (
        snap_index.coordinates_rad
    )

    if (
        coordinates.ndim != 2
        or coordinates.shape[1] != 2
    ):
        raise ValueError(
            "Snap index coordinate matrix must "
            "have shape (n, 2)."
        )

    if (
        coordinates.shape[0]
        != len(
            snap_index.node_ids
        )
    ):
        raise ValueError(
            "Snap index node IDs and coordinate "
            "rows are inconsistent."
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
    "SnapIndex",
    "SnapMethod",
    "SnapQueryResult",
    "SnappedCoordinate",
    "build_snap_index",
    "query_nearest_node_id",
    "query_snap_index",
]