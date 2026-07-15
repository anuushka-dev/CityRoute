# app/utils/matrix_cache_key.py

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Sequence
from pathlib import Path

from app.models.matrix_model import MatrixLocation

# ---------------------------------------------------------------------------
# Phase 5 square distance-matrix cache contract
# ---------------------------------------------------------------------------

MATRIX_CACHE_SCHEMA_VERSION = "v1"


# ---------------------------------------------------------------------------
# Phase 10 rectangular road-dispatch matrix cache contract
#
# Kept separate from the Phase 5 cache schema because these payloads have
# different shapes and meanings:
#
# Phase 5:
#     locations x locations
#
# Phase 10:
#     driver_nodes x order_nodes
# ---------------------------------------------------------------------------

DISPATCH_ROAD_MATRIX_CACHE_SCHEMA_VERSION = "v1"
DISPATCH_ROAD_MATRIX_CACHE_NAMESPACE = "dispatch_road_matrix"


DispatchRoadMatrixCacheKeyBuilder = Callable[
    [Sequence[int], Sequence[int], float],
    str,
]


# ---------------------------------------------------------------------------
# Shared normalization helpers
# ---------------------------------------------------------------------------


def _normalize_graph_identity(
    graph_identity: str,
) -> str:
    """
    Convert a graph path/name into a stable short identity.

    Examples:

        data/graphs/kanpur_central.graphml
            -> kanpur_central.graphml

        data\\graphs\\kanpur_central.graphml
            -> kanpur_central.graphml

    The slash normalization makes the result stable across Windows and
    Linux/Docker path formats.
    """

    if not graph_identity:
        return "unknown_graph"

    normalized_path = (
        str(graph_identity)
        .strip()
        .replace("\\", "/")
    )

    if not normalized_path:
        return "unknown_graph"

    # Keep Path for compatibility with the existing implementation while
    # normalizing Windows separators first for cross-platform consistency.
    return Path(normalized_path).name


def _normalize_algorithm(
    algorithm: str,
) -> str:
    normalized = str(algorithm).strip().lower()

    if not normalized:
        raise ValueError(
            "algorithm must not be empty."
        )

    return normalized


def _build_payload_digest(
    payload: dict[str, object],
) -> str:
    """
    Build a deterministic SHA256 digest from one canonical JSON payload.
    """

    payload_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )

    return hashlib.sha256(
        payload_json.encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------
# Phase 5 square matrix cache key
# ---------------------------------------------------------------------------


def _normalize_location(
    location: MatrixLocation,
) -> dict[str, object]:
    """
    Normalize one Phase 5 matrix location for cache hashing.

    Important:
    - round lat/lon to 6 decimals
    - preserve location id
    - preserve order in final payload

    Six decimal places is approximately sub-meter GPS precision and is
    sufficient for the existing CityRoute matrix cache contract.
    """

    return {
        "id": location.id.strip(),
        "lat": round(
            float(location.lat),
            6,
        ),
        "lon": round(
            float(location.lon),
            6,
        ),
    }


def build_matrix_cache_key(
    *,
    locations: list[MatrixLocation],
    algorithm: str,
    graph_identity: str,
) -> str:
    """
    Build the stable Redis key for one Phase 5 square distance matrix.

    The key changes when:
    - graph identity changes
    - algorithm changes
    - location order changes
    - location coordinates change after normalization
    - cache schema version changes

    Location order must be preserved because matrix row/column order matters.
    """

    normalized_graph = _normalize_graph_identity(
        graph_identity
    )

    normalized_algorithm = _normalize_algorithm(
        algorithm
    )

    cache_payload: dict[str, object] = {
        "schema_version": MATRIX_CACHE_SCHEMA_VERSION,
        "graph": normalized_graph,
        "algorithm": normalized_algorithm,
        "locations": [
            _normalize_location(location)
            for location in locations
        ],
    }

    digest = _build_payload_digest(
        cache_payload
    )

    return (
        f"matrix:"
        f"{MATRIX_CACHE_SCHEMA_VERSION}:"
        f"{normalized_graph}:"
        f"{normalized_algorithm}:"
        f"{digest}"
    )


def build_matrix_cache_fingerprint(
    *,
    locations: list[MatrixLocation],
    algorithm: str,
    graph_identity: str,
) -> str:
    """
    Return only the SHA256 fingerprint for a Phase 5 matrix request.

    Useful for tests and benchmark logs where the complete Redis key is
    unnecessarily long.
    """

    key = build_matrix_cache_key(
        locations=locations,
        algorithm=algorithm,
        graph_identity=graph_identity,
    )

    return key.rsplit(
        ":",
        maxsplit=1,
    )[-1]


# ---------------------------------------------------------------------------
# Phase 10 rectangular road-dispatch matrix cache key
# ---------------------------------------------------------------------------


def build_dispatch_road_matrix_cache_key(
    driver_nodes: Sequence[int],
    order_nodes: Sequence[int],
    unreachable_cost_m: float,
    *,
    graph_identity: str = "unknown_graph",
    algorithm: str = "source_dijkstra",
) -> str:
    """
    Build a deterministic Redis key for a Phase 10 road-dispatch matrix.

    Matrix shape:

        driver_nodes x order_nodes

    The key changes when:
    - graph identity changes
    - matrix algorithm changes
    - driver-node order changes
    - order-node order changes
    - unreachable-cost policy changes
    - Phase 10 cache schema version changes

    Driver and order ordering is intentionally preserved because:

        row i    -> driver i
        column j -> order j

    Therefore:

        drivers=[10, 20]
        orders=[30, 40]

    is not the same matrix contract as:

        drivers=[20, 10]
        orders=[30, 40]
    """

    normalized_driver_nodes = _normalize_node_sequence(
        name="driver_nodes",
        nodes=driver_nodes,
    )

    normalized_order_nodes = _normalize_node_sequence(
        name="order_nodes",
        nodes=order_nodes,
    )

    normalized_unreachable_cost_m = (
        _normalize_unreachable_cost(
            unreachable_cost_m
        )
    )

    normalized_graph = _normalize_graph_identity(
        graph_identity
    )

    normalized_algorithm = _normalize_algorithm(
        algorithm
    )

    cache_payload: dict[str, object] = {
        "schema_version": (
            DISPATCH_ROAD_MATRIX_CACHE_SCHEMA_VERSION
        ),
        "matrix_kind": "driver_x_order",
        "graph": normalized_graph,
        "algorithm": normalized_algorithm,
        "driver_nodes": list(
            normalized_driver_nodes
        ),
        "order_nodes": list(
            normalized_order_nodes
        ),
        "unreachable_cost_m": (
            normalized_unreachable_cost_m
        ),
    }

    digest = _build_payload_digest(
        cache_payload
    )

    return (
        f"{DISPATCH_ROAD_MATRIX_CACHE_NAMESPACE}:"
        f"{DISPATCH_ROAD_MATRIX_CACHE_SCHEMA_VERSION}:"
        f"{normalized_graph}:"
        f"{normalized_algorithm}:"
        f"{digest}"
    )


def build_dispatch_road_matrix_cache_fingerprint(
    driver_nodes: Sequence[int],
    order_nodes: Sequence[int],
    unreachable_cost_m: float,
    *,
    graph_identity: str = "unknown_graph",
    algorithm: str = "source_dijkstra",
) -> str:
    """
    Return only the SHA256 fingerprint for a Phase 10 road-dispatch matrix.
    """

    key = build_dispatch_road_matrix_cache_key(
        driver_nodes,
        order_nodes,
        unreachable_cost_m,
        graph_identity=graph_identity,
        algorithm=algorithm,
    )

    return key.rsplit(
        ":",
        maxsplit=1,
    )[-1]


def make_dispatch_road_matrix_cache_key_builder(
    *,
    graph_identity: str,
    algorithm: str = "source_dijkstra",
) -> DispatchRoadMatrixCacheKeyBuilder:
    """
    Create a cache-key builder compatible with:

        DispatchRoadMatrixDependencies.cache_key_builder

    This factory binds the graph identity and algorithm once while preserving
    the three-argument callable expected by the Phase 10 road-matrix service.

    Example:

        cache_key_builder = (
            make_dispatch_road_matrix_cache_key_builder(
                graph_identity="data/graphs/kanpur_central.graphml",
            )
        )

    The returned callable accepts:

        driver_nodes
        order_nodes
        unreachable_cost_m
    """

    normalized_graph = _normalize_graph_identity(
        graph_identity
    )

    normalized_algorithm = _normalize_algorithm(
        algorithm
    )

    def cache_key_builder(
        driver_nodes: Sequence[int],
        order_nodes: Sequence[int],
        unreachable_cost_m: float,
    ) -> str:
        return build_dispatch_road_matrix_cache_key(
            driver_nodes,
            order_nodes,
            unreachable_cost_m,
            graph_identity=normalized_graph,
            algorithm=normalized_algorithm,
        )

    return cache_key_builder


# ---------------------------------------------------------------------------
# Phase 10 validation helpers
# ---------------------------------------------------------------------------


def _normalize_node_sequence(
    *,
    name: str,
    nodes: Sequence[int],
) -> tuple[int, ...]:
    if isinstance(
        nodes,
        (str, bytes, bytearray),
    ):
        raise TypeError(
            f"{name} must be a sequence of integer graph node IDs."
        )

    normalized = tuple(nodes)

    if not normalized:
        raise ValueError(
            f"{name} must contain at least one graph node."
        )

    for index, node_id in enumerate(
        normalized
    ):
        if (
            isinstance(node_id, bool)
            or not isinstance(node_id, int)
        ):
            raise TypeError(
                f"{name}[{index}] must be an integer graph node ID; "
                f"received {type(node_id).__name__}."
            )

    return normalized


def _normalize_unreachable_cost(
    unreachable_cost_m: float,
) -> float:
    if isinstance(
        unreachable_cost_m,
        bool,
    ):
        raise TypeError(
            "unreachable_cost_m must be numeric."
        )

    try:
        normalized = float(
            unreachable_cost_m
        )
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise TypeError(
            "unreachable_cost_m must be numeric."
        ) from exc

    if not math.isfinite(
        normalized
    ):
        raise ValueError(
            "unreachable_cost_m must be finite."
        )

    if normalized <= 0:
        raise ValueError(
            "unreachable_cost_m must be greater than zero."
        )

    return normalized


__all__ = [
    "DISPATCH_ROAD_MATRIX_CACHE_NAMESPACE",
    "DISPATCH_ROAD_MATRIX_CACHE_SCHEMA_VERSION",
    "DispatchRoadMatrixCacheKeyBuilder",
    "MATRIX_CACHE_SCHEMA_VERSION",
    "build_dispatch_road_matrix_cache_fingerprint",
    "build_dispatch_road_matrix_cache_key",
    "build_matrix_cache_fingerprint",
    "build_matrix_cache_key",
    "make_dispatch_road_matrix_cache_key_builder",
]