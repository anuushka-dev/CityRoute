# tests/test_matrix_cache_key.py

from __future__ import annotations

from app.models.matrix_model import MatrixLocation
from app.utils.matrix_cache_key import (
    MATRIX_CACHE_SCHEMA_VERSION,
    build_matrix_cache_fingerprint,
    build_matrix_cache_key,
)


def _locations() -> list[MatrixLocation]:
    return [
        MatrixLocation(id="depot", lat=26.44, lon=80.30),
        MatrixLocation(id="stop_1", lat=26.45, lon=80.35),
        MatrixLocation(id="stop_2", lat=26.46, lon=80.33),
    ]


def test_matrix_cache_key_is_stable_for_same_input():
    key_1 = build_matrix_cache_key(
        locations=_locations(),
        algorithm="bidirectional_astar",
        graph_identity="data/graphs/kanpur_central.graphml",
    )

    key_2 = build_matrix_cache_key(
        locations=_locations(),
        algorithm="bidirectional_astar",
        graph_identity="data/graphs/kanpur_central.graphml",
    )

    assert key_1 == key_2
    assert key_1.startswith(
        f"matrix:{MATRIX_CACHE_SCHEMA_VERSION}:kanpur_central.graphml:bidirectional_astar:"
    )


def test_matrix_cache_key_changes_when_location_order_changes():
    original_locations = _locations()
    reordered_locations = [
        original_locations[1],
        original_locations[0],
        original_locations[2],
    ]

    key_1 = build_matrix_cache_key(
        locations=original_locations,
        algorithm="bidirectional_astar",
        graph_identity="data/graphs/kanpur_central.graphml",
    )

    key_2 = build_matrix_cache_key(
        locations=reordered_locations,
        algorithm="bidirectional_astar",
        graph_identity="data/graphs/kanpur_central.graphml",
    )

    assert key_1 != key_2


def test_matrix_cache_key_changes_when_algorithm_changes():
    key_1 = build_matrix_cache_key(
        locations=_locations(),
        algorithm="astar",
        graph_identity="data/graphs/kanpur_central.graphml",
    )

    key_2 = build_matrix_cache_key(
        locations=_locations(),
        algorithm="bidirectional_astar",
        graph_identity="data/graphs/kanpur_central.graphml",
    )

    assert key_1 != key_2
    assert ":astar:" in key_1
    assert ":bidirectional_astar:" in key_2


def test_matrix_cache_key_changes_when_graph_changes():
    key_1 = build_matrix_cache_key(
        locations=_locations(),
        algorithm="bidirectional_astar",
        graph_identity="data/graphs/kanpur_central.graphml",
    )

    key_2 = build_matrix_cache_key(
        locations=_locations(),
        algorithm="bidirectional_astar",
        graph_identity="data/graphs/lucknow.graphml",
    )

    assert key_1 != key_2
    assert ":kanpur_central.graphml:" in key_1
    assert ":lucknow.graphml:" in key_2


def test_matrix_cache_key_rounds_coordinates_to_six_decimals():
    locations_a = [
        MatrixLocation(id="depot", lat=26.4400001, lon=80.3000001),
        MatrixLocation(id="stop_1", lat=26.4500001, lon=80.3500001),
    ]

    locations_b = [
        MatrixLocation(id="depot", lat=26.4400002, lon=80.3000002),
        MatrixLocation(id="stop_1", lat=26.4500002, lon=80.3500002),
    ]

    key_a = build_matrix_cache_key(
        locations=locations_a,
        algorithm="bidirectional_astar",
        graph_identity="data/graphs/kanpur_central.graphml",
    )

    key_b = build_matrix_cache_key(
        locations=locations_b,
        algorithm="bidirectional_astar",
        graph_identity="data/graphs/kanpur_central.graphml",
    )

    assert key_a == key_b


def test_matrix_cache_key_changes_when_coordinate_changes_beyond_rounding():
    locations_a = [
        MatrixLocation(id="depot", lat=26.440000, lon=80.300000),
        MatrixLocation(id="stop_1", lat=26.450000, lon=80.350000),
    ]

    locations_b = [
        MatrixLocation(id="depot", lat=26.440010, lon=80.300000),
        MatrixLocation(id="stop_1", lat=26.450000, lon=80.350000),
    ]

    key_a = build_matrix_cache_key(
        locations=locations_a,
        algorithm="bidirectional_astar",
        graph_identity="data/graphs/kanpur_central.graphml",
    )

    key_b = build_matrix_cache_key(
        locations=locations_b,
        algorithm="bidirectional_astar",
        graph_identity="data/graphs/kanpur_central.graphml",
    )

    assert key_a != key_b


def test_matrix_cache_fingerprint_returns_sha256_digest_only():
    fingerprint = build_matrix_cache_fingerprint(
        locations=_locations(),
        algorithm="bidirectional_astar",
        graph_identity="data/graphs/kanpur_central.graphml",
    )

    assert len(fingerprint) == 64
    assert all(char in "0123456789abcdef" for char in fingerprint)


def test_matrix_cache_key_normalizes_windows_graph_path():
    key = build_matrix_cache_key(
        locations=_locations(),
        algorithm="bidirectional_astar",
        graph_identity=r"data\graphs\kanpur_central.graphml",
    )

    assert ":kanpur_central.graphml:" in key
    assert "\\" not in key