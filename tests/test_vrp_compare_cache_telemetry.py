# tests/test_vrp_compare_cache_telemetry.py

from __future__ import annotations

import asyncio
from typing import Any

from app.services.vrp_compare_service import compute_vrp_compare

BASE_MATRIX_RESPONSE = {
    "status": "ok",
    "n": 3,
    "algorithm": "source_dijkstra",
    "locations": [
        {"id": "depot", "lat": 26.4499, "lon": 80.3319},
        {"id": "stop_0", "lat": 26.4600, "lon": 80.3400},
        {"id": "stop_1", "lat": 26.4550, "lon": 80.3250},
    ],
    "matrix_distance_m": [
        [0.0, 10.0, 20.0],
        [10.0, 0.0, 5.0],
        [20.0, 5.0, 0.0],
    ],
    "matrix_eta_s": [
        [0.0, 10.0, 20.0],
        [10.0, 0.0, 5.0],
        [20.0, 5.0, 0.0],
    ],
    "pair_count": 9,
    "computed_pairs": 9,
    "failed_pairs": 0,
    "failures": [],
    "generation_time_ms": 12.5,
    "parallel_workers": 8,
}


def test_vrp_compare_maps_nested_matrix_cache_hit_to_phase71_fields() -> None:
    def fake_matrix_service(payload: dict[str, Any]) -> dict[str, Any]:
        response = dict(BASE_MATRIX_RESPONSE)
        response["cache"] = {
            "enabled": True,
            "hit": True,
            "key": "fake-cache-key",
            "ttl_seconds": 86400,
            "error": None,
        }
        return response

    result = asyncio.run(
        compute_vrp_compare(
            depot={"id": "depot", "lat": 26.4499, "lon": 80.3319},
            stops=[
                {"id": "stop_0", "lat": 26.4600, "lon": 80.3400},
                {"id": "stop_1", "lat": 26.4550, "lon": 80.3250},
            ],
            matrix_service=fake_matrix_service,
            matrix_algorithm="source_dijkstra",
            use_cache=True,
        )
    )

    assert result["cache_used"] is True
    assert result["cache_status"] == "hit"
    assert result["cache_hits"] == 1
    assert result["cache_misses"] == 0


def test_vrp_compare_maps_nested_matrix_cache_miss_to_phase71_fields() -> None:
    def fake_matrix_service(payload: dict[str, Any]) -> dict[str, Any]:
        response = dict(BASE_MATRIX_RESPONSE)
        response["cache"] = {
            "enabled": True,
            "hit": False,
            "key": "fake-cache-key",
            "ttl_seconds": 86400,
            "error": None,
        }
        return response

    result = asyncio.run(
        compute_vrp_compare(
            depot={"id": "depot", "lat": 26.4499, "lon": 80.3319},
            stops=[
                {"id": "stop_0", "lat": 26.4600, "lon": 80.3400},
                {"id": "stop_1", "lat": 26.4550, "lon": 80.3250},
            ],
            matrix_service=fake_matrix_service,
            matrix_algorithm="source_dijkstra",
            use_cache=True,
        )
    )

    assert result["cache_used"] is True
    assert result["cache_status"] == "miss"
    assert result["cache_hits"] == 0
    assert result["cache_misses"] == 1


def test_vrp_compare_maps_disabled_matrix_cache_to_phase71_fields() -> None:
    def fake_matrix_service(payload: dict[str, Any]) -> dict[str, Any]:
        response = dict(BASE_MATRIX_RESPONSE)
        response["cache"] = {
            "enabled": False,
            "hit": False,
            "key": None,
            "ttl_seconds": 86400,
            "error": None,
        }
        return response

    result = asyncio.run(
        compute_vrp_compare(
            depot={"id": "depot", "lat": 26.4499, "lon": 80.3319},
            stops=[
                {"id": "stop_0", "lat": 26.4600, "lon": 80.3400},
                {"id": "stop_1", "lat": 26.4550, "lon": 80.3250},
            ],
            matrix_service=fake_matrix_service,
            matrix_algorithm="source_dijkstra",
            use_cache=False,
        )
    )

    assert result["cache_used"] is False
    assert result["cache_status"] == "disabled"
    assert result["cache_hits"] == 0
    assert result["cache_misses"] == 0