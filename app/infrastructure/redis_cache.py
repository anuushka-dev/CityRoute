# app/infrastructure/redis_cache.py

from __future__ import annotations

import json
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from app.utils.logger import get_logger

logger = get_logger(__name__)


class RedisCache:
    """
    Small synchronous Redis JSON cache wrapper for Phase 5.

    Used by:
        app/services/matrix_service.py

    Responsibilities:
    - connect to Redis
    - get JSON by key
    - set JSON with TTL
    - fail clearly when Redis is unavailable

    This class does NOT know anything about:
    - routing
    - A*
    - distance matrices
    - FastAPI request objects
    """

    def __init__(
        self,
        redis_url: str,
        ttl_seconds: int = 86_400,
        socket_timeout_s: float = 2.0,
    ) -> None:
        self.redis_url = redis_url
        self.ttl_seconds = ttl_seconds

        self.client: Redis = Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_timeout=socket_timeout_s,
            socket_connect_timeout=socket_timeout_s,
        )

    def ping(self) -> bool:
        """
        Verify Redis connection.

        Returns:
            True if Redis replies to PING.

        Raises:
            RedisError if Redis is unavailable.
        """
        return bool(self.client.ping())

    def get_json(self, key: str) -> dict[str, Any] | None:
        """
        Read a JSON object from Redis.

        Returns:
            dict if key exists and contains valid JSON object
            None if key does not exist

        Raises:
            RedisError for Redis connection/runtime errors.
            ValueError if stored value is not a JSON object.
        """

        try:
            raw_value = self.client.get(key)

            if raw_value is None:
                return None

            parsed = json.loads(raw_value)

            if not isinstance(parsed, dict):
                raise ValueError(f"Redis key {key!r} did not contain a JSON object.")

            return parsed

        except json.JSONDecodeError as exc:
            logger.warning(
                "Invalid JSON found in Redis cache | key=%s | error=%s",
                key,
                str(exc),
            )

            # Corrupt cache should not poison future requests.
            self.delete(key)
            return None

        except RedisError:
            raise

    def set_json(
        self,
        key: str,
        value: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> bool:
        """
        Store a JSON object in Redis with TTL.

        Returns:
            True if Redis accepts the write.

        Raises:
            RedisError for Redis connection/runtime errors.
        """

        effective_ttl = ttl_seconds if ttl_seconds is not None else self.ttl_seconds

        payload = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )

        return bool(
            self.client.set(
                name=key,
                value=payload,
                ex=effective_ttl,
            )
        )

    def delete(self, key: str) -> int:
        """
        Delete a key from Redis.

        Returns:
            Number of deleted keys.
        """
        return int(self.client.delete(key))

    def close(self) -> None:
        """
        Close Redis connection pool.
        """
        self.client.close()