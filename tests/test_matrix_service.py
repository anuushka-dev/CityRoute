# tests/test_matrix_service.py

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from app.models.matrix_model import (
    MatrixComputationResult,
    MatrixLocation,
    MatrixPairFailure,
    MatrixRequest,
)
from app.services.matrix_service import build_distance_matrix_response


def _payload(
    *,
    use_cache: bool = True,
    algorithm: str = "bidirectional_astar",
) -> MatrixRequest:
    return MatrixRequest(
        locations=[
            MatrixLocation(id="depot", lat=26.44, lon=80.30),
            MatrixLocation(id="stop_1", lat=26.45, lon=80.35),
            MatrixLocation(id="stop_2", lat=26.46, lon=80.33),
        ],
        algorithm=algorithm,
        use_cache=use_cache,
    )


def _fake_matrix_result() -> MatrixComputationResult:
    return MatrixComputationResult(
        matrix_distance_m=[
            [0.0, 1000.0, 2000.0],
            [1100.0, 0.0, 1500.0],
            [2100.0, 1400.0, 0.0],
        ],
        matrix_eta_s=[
            [0.0, 155.44, 310.88],
            [170.98, 0.0, 233.16],
            [326.42, 217.62, 0.0],
        ],
        pair_count=9,
        computed_pairs=9,
        failed_pairs=0,
        failures=[],
    )


def _cached_payload() -> dict[str, Any]:
    return {
        "status": "ok",
        "n": 3,
        "algorithm": "bidirectional_astar",
        "cache": {
            "enabled": True,
            "hit": False,
            "key": "old-cache-value",
            "ttl_seconds": 86400,
            "error": None,
        },
        "locations": [
            {"id": "depot", "lat": 26.44, "lon": 80.30},
            {"id": "stop_1", "lat": 26.45, "lon": 80.35},
            {"id": "stop_2", "lat": 26.46, "lon": 80.33},
        ],
        "matrix_distance_m": [
            [0.0, 1000.0, 2000.0],
            [1100.0, 0.0, 1500.0],
            [2100.0, 1400.0, 0.0],
        ],
        "matrix_eta_s": [
            [0.0, 155.44, 310.88],
            [170.98, 0.0, 233.16],
            [326.42, 217.62, 0.0],
        ],
        "pair_count": 9,
        "computed_pairs": 9,
        "failed_pairs": 0,
        "failures": [],
        "generation_time_ms": 999.0,
        "parallel_workers": 8,
    }


class FakeRedisCacheMiss:
    stored: dict[str, Any] | None = None

    def __init__(self, redis_url: str, ttl_seconds: int) -> None:
        self.redis_url = redis_url
        self.ttl_seconds = ttl_seconds

    def get_json(self, key: str) -> dict[str, Any] | None:
        return None

    def set_json(self, key: str, value: dict[str, Any]) -> bool:
        self.stored = {"key": key, "value": value}
        FakeRedisCacheMiss.stored = self.stored
        return True


class FakeRedisCacheHit:
    def __init__(self, redis_url: str, ttl_seconds: int) -> None:
        self.redis_url = redis_url
        self.ttl_seconds = ttl_seconds

    def get_json(self, key: str) -> dict[str, Any] | None:
        return _cached_payload()

    def set_json(self, key: str, value: dict[str, Any]) -> bool:
        raise AssertionError("set_json should not be called on cache hit")


class FakeRedisUnavailable:
    def __init__(self, redis_url: str, ttl_seconds: int) -> None:
        raise ConnectionError("redis unavailable in test")


def test_matrix_service_cache_miss_computes_and_writes_to_cache(monkeypatch):
    compute_calls = {"count": 0}

    def fake_build_distance_matrix(*, locations, graph, snap_index, algorithm, workers):
        compute_calls["count"] += 1
        assert len(locations) == 3
        assert algorithm == "bidirectional_astar"
        assert workers == 8
        assert graph is not None
        assert snap_index is not None
        return _fake_matrix_result()

    monkeypatch.setattr(
        "app.services.matrix_service.RedisCache",
        FakeRedisCacheMiss,
    )
    monkeypatch.setattr(
        "app.services.matrix_service.build_distance_matrix",
        fake_build_distance_matrix,
    )
    monkeypatch.setattr(
        "app.services.matrix_service.build_matrix_cache_key",
        lambda **kwargs: "matrix:v1:test-key",
    )

    response = build_distance_matrix_response(
        payload=_payload(use_cache=True),
        graph=object(),
        snap_index=object(),
    )

    assert response.status == "ok"
    assert response.n == 3
    assert response.algorithm == "bidirectional_astar"
    assert response.cache.enabled is True
    assert response.cache.hit is False
    assert response.cache.key == "matrix:v1:test-key"
    assert response.failed_pairs == 0
    assert response.computed_pairs == 9
    assert response.matrix_distance_m[0][0] == 0.0
    assert compute_calls["count"] == 1
    assert FakeRedisCacheMiss.stored is not None
    assert FakeRedisCacheMiss.stored["key"] == "matrix:v1:test-key"


def test_matrix_service_cache_hit_returns_cached_response_without_computing(monkeypatch):
    def fake_build_distance_matrix(**kwargs):
        raise AssertionError("build_distance_matrix should not run on cache hit")

    monkeypatch.setattr(
        "app.services.matrix_service.RedisCache",
        FakeRedisCacheHit,
    )
    monkeypatch.setattr(
        "app.services.matrix_service.build_distance_matrix",
        fake_build_distance_matrix,
    )
    monkeypatch.setattr(
        "app.services.matrix_service.build_matrix_cache_key",
        lambda **kwargs: "matrix:v1:test-key",
    )

    response = build_distance_matrix_response(
        payload=_payload(use_cache=True),
        graph=object(),
        snap_index=object(),
    )

    assert response.status == "ok"
    assert response.cache.enabled is True
    assert response.cache.hit is True
    assert response.cache.key == "matrix:v1:test-key"
    assert response.computed_pairs == 9
    assert response.failed_pairs == 0


def test_matrix_service_cache_disabled_computes_without_redis(monkeypatch):
    compute_calls = {"count": 0}

    def fake_build_distance_matrix(*, locations, graph, snap_index, algorithm, workers):
        compute_calls["count"] += 1
        return _fake_matrix_result()

    def fake_redis_cache(*args, **kwargs):
        raise AssertionError("RedisCache should not be created when use_cache=False")

    monkeypatch.setattr(
        "app.services.matrix_service.RedisCache",
        fake_redis_cache,
    )
    monkeypatch.setattr(
        "app.services.matrix_service.build_distance_matrix",
        fake_build_distance_matrix,
    )

    response = build_distance_matrix_response(
        payload=_payload(use_cache=False),
        graph=object(),
        snap_index=object(),
    )

    assert response.status == "ok"
    assert response.cache.enabled is False
    assert response.cache.hit is False
    assert response.cache.key is None
    assert response.failed_pairs == 0
    assert compute_calls["count"] == 1


def test_matrix_service_redis_unavailable_falls_back_to_compute(monkeypatch):
    compute_calls = {"count": 0}

    def fake_build_distance_matrix(*, locations, graph, snap_index, algorithm, workers):
        compute_calls["count"] += 1
        return _fake_matrix_result()

    monkeypatch.setattr(
        "app.services.matrix_service.RedisCache",
        FakeRedisUnavailable,
    )
    monkeypatch.setattr(
        "app.services.matrix_service.build_distance_matrix",
        fake_build_distance_matrix,
    )
    monkeypatch.setattr(
        "app.services.matrix_service.build_matrix_cache_key",
        lambda **kwargs: "matrix:v1:test-key",
    )

    response = build_distance_matrix_response(
        payload=_payload(use_cache=True),
        graph=object(),
        snap_index=object(),
    )

    assert response.status == "ok"
    assert response.cache.enabled is True
    assert response.cache.hit is False
    assert response.cache.key == "matrix:v1:test-key"
    assert response.cache.error is not None
    assert "redis unavailable" in response.cache.error
    assert compute_calls["count"] == 1


def test_matrix_service_rejects_less_than_two_locations():
    payload = MatrixRequest(
        locations=[
            MatrixLocation(id="only_one", lat=26.44, lon=80.30),
        ],
        algorithm="bidirectional_astar",
        use_cache=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        build_distance_matrix_response(
            payload=payload,
            graph=object(),
            snap_index=object(),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error"] == "Not enough locations"


def test_matrix_service_rejects_unsupported_algorithm():
    payload = MatrixRequest(
        locations=[
            MatrixLocation(id="depot", lat=26.44, lon=80.30),
            MatrixLocation(id="stop_1", lat=26.45, lon=80.35),
        ],
        algorithm="wrong_algorithm",
        use_cache=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        build_distance_matrix_response(
            payload=payload,
            graph=object(),
            snap_index=object(),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error"] == "Unsupported matrix algorithm"


def test_matrix_service_rejects_more_than_max_locations(monkeypatch):
    locations = [
        MatrixLocation(id=f"stop_{index}", lat=26.44, lon=80.30)
        for index in range(26)
    ]

    payload = MatrixRequest(
        locations=locations,
        algorithm="bidirectional_astar",
        use_cache=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        build_distance_matrix_response(
            payload=payload,
            graph=object(),
            snap_index=object(),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error"] == "Too many locations"
    assert exc_info.value.detail["max_locations"] == 25


def test_matrix_service_preserves_pair_failures(monkeypatch):
    def fake_build_distance_matrix(*, locations, graph, snap_index, algorithm, workers):
        return MatrixComputationResult(
            matrix_distance_m=[
                [0.0, None],
                [1200.0, 0.0],
            ],
            matrix_eta_s=[
                [0.0, None],
                [186.528, 0.0],
            ],
            pair_count=4,
            computed_pairs=3,
            failed_pairs=1,
            failures=[
                MatrixPairFailure(
                    from_index=0,
                    to_index=1,
                    from_id="depot",
                    to_id="stop_1",
                    error="No path found",
                )
            ],
        )

    payload = MatrixRequest(
        locations=[
            MatrixLocation(id="depot", lat=26.44, lon=80.30),
            MatrixLocation(id="stop_1", lat=26.45, lon=80.35),
        ],
        algorithm="bidirectional_astar",
        use_cache=False,
    )

    monkeypatch.setattr(
        "app.services.matrix_service.build_distance_matrix",
        fake_build_distance_matrix,
    )

    response = build_distance_matrix_response(
        payload=payload,
        graph=object(),
        snap_index=object(),
    )

    assert response.status == "ok"
    assert response.pair_count == 4
    assert response.computed_pairs == 3
    assert response.failed_pairs == 1
    assert response.matrix_distance_m[0][1] is None
    assert response.failures[0].error == "No path found"