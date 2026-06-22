# app/utils/matrix_cache_key.py

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.models.matrix_model import MatrixLocation

MATRIX_CACHE_SCHEMA_VERSION = "v1"


def _normalize_graph_identity(graph_identity: str) -> str:
    """
    Convert graph path/name into a stable short identity.

    Example:
        data/graphs/kanpur_central.graphml -> kanpur_central.graphml
    """

    if not graph_identity:
        return "unknown_graph"

    return Path(str(graph_identity)).name.replace("\\", "/")


def _normalize_location(location: MatrixLocation) -> dict[str, object]:
    """
    Normalize one location for cache hashing.

    Important:
    - round lat/lon to 6 decimals
    - preserve location id
    - preserve order in final payload

    6 decimals is around 0.11 meters precision, which is enough for GPS cache keys.
    """

    return {
        "id": location.id.strip(),
        "lat": round(float(location.lat), 6),
        "lon": round(float(location.lon), 6),
    }


def build_matrix_cache_key(
    *,
    locations: list[MatrixLocation],
    algorithm: str,
    graph_identity: str,
) -> str:
    """
    Build stable Redis key for one distance matrix request.

    The key changes when:
    - graph file changes
    - algorithm changes
    - location order changes
    - any coordinate changes after rounding
    - schema version changes

    The location order MUST be preserved because matrix row/column order matters.
    """

    normalized_graph = _normalize_graph_identity(graph_identity)
    normalized_algorithm = algorithm.strip().lower()

    cache_payload = {
        "schema_version": MATRIX_CACHE_SCHEMA_VERSION,
        "graph": normalized_graph,
        "algorithm": normalized_algorithm,
        "locations": [_normalize_location(location) for location in locations],
    }

    payload_json = json.dumps(
        cache_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )

    digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

    return (
        f"matrix:{MATRIX_CACHE_SCHEMA_VERSION}:"
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
    Return only the SHA256 fingerprint.

    Useful for tests and benchmark logs where the full Redis key is too long.
    """

    key = build_matrix_cache_key(
        locations=locations,
        algorithm=algorithm,
        graph_identity=graph_identity,
    )

    return key.rsplit(":", maxsplit=1)[-1]