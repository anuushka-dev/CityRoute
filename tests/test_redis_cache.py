# tests/test_redis_cache.py

from __future__ import annotations

import pytest
from redis.exceptions import RedisError

import app.infrastructure.redis_cache as redis_cache_module
from app.infrastructure.redis_cache import RedisCache


class FakeRedisClient:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.deleted_keys: list[str] = []
        self.closed = False
        self.ping_result = True

    def ping(self) -> bool:
        return self.ping_result

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, name: str, value: str, ex: int) -> bool:
        self.values[name] = value
        self.values[f"{name}:ttl"] = str(ex)
        return True

    def delete(self, key: str) -> int:
        self.deleted_keys.append(key)

        if key in self.values:
            del self.values[key]
            return 1

        return 0

    def close(self) -> None:
        self.closed = True


class FailingRedisClient:
    def ping(self) -> bool:
        raise RedisError("redis ping failed")

    def get(self, key: str):
        raise RedisError("redis get failed")

    def set(self, name: str, value: str, ex: int) -> bool:
        raise RedisError("redis set failed")

    def delete(self, key: str) -> int:
        raise RedisError("redis delete failed")

    def close(self) -> None:
        pass


def _patch_redis_client(monkeypatch, fake_client):
    monkeypatch.setattr(
        redis_cache_module.Redis,
        "from_url",
        staticmethod(lambda *args, **kwargs: fake_client),
    )


def test_redis_cache_ping_success(monkeypatch):
    fake_client = FakeRedisClient()
    _patch_redis_client(monkeypatch, fake_client)

    cache = RedisCache(
        redis_url="redis://localhost:6379/0",
        ttl_seconds=60,
    )

    assert cache.ping() is True


def test_redis_cache_get_json_returns_none_for_missing_key(monkeypatch):
    fake_client = FakeRedisClient()
    _patch_redis_client(monkeypatch, fake_client)

    cache = RedisCache(
        redis_url="redis://localhost:6379/0",
        ttl_seconds=60,
    )

    assert cache.get_json("missing-key") is None


def test_redis_cache_set_json_and_get_json_round_trip(monkeypatch):
    fake_client = FakeRedisClient()
    _patch_redis_client(monkeypatch, fake_client)

    cache = RedisCache(
        redis_url="redis://localhost:6379/0",
        ttl_seconds=120,
    )

    payload = {
        "status": "ok",
        "n": 2,
        "matrix_distance_m": [
            [0.0, 1000.0],
            [1100.0, 0.0],
        ],
    }

    assert cache.set_json("matrix:test", payload) is True

    assert fake_client.values["matrix:test:ttl"] == "120"

    restored = cache.get_json("matrix:test")

    assert restored == payload


def test_redis_cache_set_json_allows_custom_ttl(monkeypatch):
    fake_client = FakeRedisClient()
    _patch_redis_client(monkeypatch, fake_client)

    cache = RedisCache(
        redis_url="redis://localhost:6379/0",
        ttl_seconds=120,
    )

    assert cache.set_json(
        "matrix:test",
        {"status": "ok"},
        ttl_seconds=999,
    ) is True

    assert fake_client.values["matrix:test:ttl"] == "999"


def test_redis_cache_get_json_deletes_corrupt_json(monkeypatch):
    fake_client = FakeRedisClient()
    fake_client.values["matrix:bad"] = "{not-valid-json"
    _patch_redis_client(monkeypatch, fake_client)

    cache = RedisCache(
        redis_url="redis://localhost:6379/0",
        ttl_seconds=60,
    )

    result = cache.get_json("matrix:bad")

    assert result is None
    assert "matrix:bad" in fake_client.deleted_keys


def test_redis_cache_get_json_rejects_non_object_json(monkeypatch):
    fake_client = FakeRedisClient()
    fake_client.values["matrix:list"] = "[1, 2, 3]"
    _patch_redis_client(monkeypatch, fake_client)

    cache = RedisCache(
        redis_url="redis://localhost:6379/0",
        ttl_seconds=60,
    )

    with pytest.raises(ValueError):
        cache.get_json("matrix:list")


def test_redis_cache_delete_existing_key(monkeypatch):
    fake_client = FakeRedisClient()
    fake_client.values["matrix:test"] = '{"status":"ok"}'
    _patch_redis_client(monkeypatch, fake_client)

    cache = RedisCache(
        redis_url="redis://localhost:6379/0",
        ttl_seconds=60,
    )

    deleted_count = cache.delete("matrix:test")

    assert deleted_count == 1
    assert "matrix:test" in fake_client.deleted_keys
    assert "matrix:test" not in fake_client.values


def test_redis_cache_delete_missing_key(monkeypatch):
    fake_client = FakeRedisClient()
    _patch_redis_client(monkeypatch, fake_client)

    cache = RedisCache(
        redis_url="redis://localhost:6379/0",
        ttl_seconds=60,
    )

    deleted_count = cache.delete("missing-key")

    assert deleted_count == 0
    assert "missing-key" in fake_client.deleted_keys


def test_redis_cache_close_closes_client(monkeypatch):
    fake_client = FakeRedisClient()
    _patch_redis_client(monkeypatch, fake_client)

    cache = RedisCache(
        redis_url="redis://localhost:6379/0",
        ttl_seconds=60,
    )

    cache.close()

    assert fake_client.closed is True


def test_redis_cache_raises_redis_error_on_ping_failure(monkeypatch):
    fake_client = FailingRedisClient()
    _patch_redis_client(monkeypatch, fake_client)

    cache = RedisCache(
        redis_url="redis://localhost:6379/0",
        ttl_seconds=60,
    )

    with pytest.raises(RedisError):
        cache.ping()


def test_redis_cache_raises_redis_error_on_get_failure(monkeypatch):
    fake_client = FailingRedisClient()
    _patch_redis_client(monkeypatch, fake_client)

    cache = RedisCache(
        redis_url="redis://localhost:6379/0",
        ttl_seconds=60,
    )

    with pytest.raises(RedisError):
        cache.get_json("matrix:test")


def test_redis_cache_raises_redis_error_on_set_failure(monkeypatch):
    fake_client = FailingRedisClient()
    _patch_redis_client(monkeypatch, fake_client)

    cache = RedisCache(
        redis_url="redis://localhost:6379/0",
        ttl_seconds=60,
    )

    with pytest.raises(RedisError):
        cache.set_json("matrix:test", {"status": "ok"})