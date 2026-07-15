# app/infrastructure/redis_cache.py

from __future__ import annotations

import json
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from app.utils.logger import get_logger

logger = get_logger(__name__)


DEFAULT_CACHE_TTL_SECONDS = 86_400
DEFAULT_SOCKET_TIMEOUT_SECONDS = 2.0


class RedisCache:
    """
    Shared CityRoute Redis cache wrapper.

    Supported payload contracts:

    JSON object cache:
        get_json()
        set_json()

    Raw text cache:
        get_text()
        set_text()

    Phase usage:

        Phase 5:
            distance-matrix JSON objects

        Phase 10:
            serialized road-dispatch matrix payloads

    Redis failures are intentionally allowed to propagate as RedisError so
    service layers can decide whether to fail closed or fail open.
    """

    def __init__(
        self,
        redis_url: str,
        ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        socket_timeout_s: float = DEFAULT_SOCKET_TIMEOUT_SECONDS,
    ) -> None:
        self.redis_url = _validate_redis_url(
            redis_url
        )

        self.ttl_seconds = _validate_ttl_seconds(
            ttl_seconds
        )

        self.socket_timeout_s = _validate_socket_timeout(
            socket_timeout_s
        )

        self.client: Redis = Redis.from_url(
            self.redis_url,
            decode_responses=True,
            socket_timeout=self.socket_timeout_s,
            socket_connect_timeout=self.socket_timeout_s,
        )

    def ping(self) -> bool:
        """
        Check whether Redis is reachable.

        Redis connection errors propagate as RedisError.
        """

        return bool(
            self.client.ping()
        )

    # ------------------------------------------------------------------
    # Raw text cache
    #
    # Used by Phase 10 road-dispatch matrix serialization.
    # ------------------------------------------------------------------

    def get_text(
        self,
        key: str,
    ) -> str | None:
        """
        Return one cached string value.

        Returns None on a normal cache miss.

        Redis failures propagate as RedisError.
        """

        normalized_key = _validate_key(
            key
        )

        raw_value = self.client.get(
            normalized_key
        )

        if raw_value is None:
            return None

        if not isinstance(
            raw_value,
            str,
        ):
            raise TypeError(
                "Redis cache value must be a string when "
                "decode_responses=True."
            )

        return raw_value

    def set_text(
        self,
        key: str,
        value: str,
        ttl_seconds: int | None = None,
    ) -> bool:
        """
        Store one string payload with an expiry.

        Phase 10 uses this for its serialized road-matrix payload.
        """

        normalized_key = _validate_key(
            key
        )

        if not isinstance(
            value,
            str,
        ):
            raise TypeError(
                "value must be a string."
            )

        effective_ttl = self._resolve_ttl(
            ttl_seconds
        )

        return bool(
            self.client.set(
                name=normalized_key,
                value=value,
                ex=effective_ttl,
            )
        )

    # ------------------------------------------------------------------
    # JSON object cache
    #
    # Existing Phase 5 behavior is preserved.
    # ------------------------------------------------------------------

    def get_json(
        self,
        key: str,
    ) -> dict[str, Any] | None:
        """
        Return one cached JSON object.

        Normal cache miss:
            None

        Corrupt JSON:
            delete the corrupt key
            return None

        Redis failure:
            propagate RedisError
        """

        normalized_key = _validate_key(
            key
        )

        try:
            raw_value = self.get_text(
                normalized_key
            )

            if raw_value is None:
                return None

            parsed = json.loads(
                raw_value
            )

            if not isinstance(
                parsed,
                dict,
            ):
                logger.warning(
                    (
                        "Redis key did not contain a JSON object | "
                        "key=%s | "
                        "type=%s"
                    ),
                    normalized_key,
                    type(
                        parsed
                    ).__name__,
                )

                self.delete(
                    normalized_key
                )

                return None

            return parsed

        except json.JSONDecodeError as exc:
            logger.warning(
                (
                    "Invalid JSON found in Redis cache | "
                    "key=%s | "
                    "error=%s"
                ),
                normalized_key,
                str(
                    exc
                ),
            )

            # Corrupt cache should not poison future requests.
            try:
                self.delete(
                    normalized_key
                )

            except RedisError as delete_exc:
                logger.warning(
                    (
                        "Failed to delete corrupt Redis cache entry | "
                        "key=%s | "
                        "error=%s"
                    ),
                    normalized_key,
                    str(
                        delete_exc
                    ),
                )

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
        Store one JSON object with an expiry.

        Existing Phase 5 behavior is preserved.
        """

        normalized_key = _validate_key(
            key
        )

        if not isinstance(
            value,
            dict,
        ):
            raise TypeError(
                "value must be a dictionary."
            )

        effective_ttl = self._resolve_ttl(
            ttl_seconds
        )

        payload = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
            allow_nan=False,
        )

        return self.set_text(
            normalized_key,
            payload,
            effective_ttl,
        )

    # ------------------------------------------------------------------
    # Shared cache operations
    # ------------------------------------------------------------------

    def delete(
        self,
        key: str,
    ) -> int:
        """
        Delete one Redis key.

        Returns the number of deleted keys.
        """

        normalized_key = _validate_key(
            key
        )

        return int(
            self.client.delete(
                normalized_key
            )
        )

    def exists(
        self,
        key: str,
    ) -> bool:
        """
        Return whether one Redis key currently exists.
        """

        normalized_key = _validate_key(
            key
        )

        return bool(
            self.client.exists(
                normalized_key
            )
        )

    def close(self) -> None:
        """
        Close the underlying Redis client connection pool.
        """

        self.client.close()

    def _resolve_ttl(
        self,
        ttl_seconds: int | None,
    ) -> int:
        if ttl_seconds is None:
            return self.ttl_seconds

        return _validate_ttl_seconds(
            ttl_seconds
        )


def _validate_redis_url(
    redis_url: str,
) -> str:
    if not isinstance(
        redis_url,
        str,
    ):
        raise TypeError(
            "redis_url must be a string."
        )

    normalized = redis_url.strip()

    if not normalized:
        raise ValueError(
            "redis_url must not be empty."
        )

    return normalized


def _validate_key(
    key: str,
) -> str:
    if not isinstance(
        key,
        str,
    ):
        raise TypeError(
            "Redis key must be a string."
        )

    normalized = key.strip()

    if not normalized:
        raise ValueError(
            "Redis key must not be empty."
        )

    return normalized


def _validate_ttl_seconds(
    ttl_seconds: int,
) -> int:
    if (
        isinstance(
            ttl_seconds,
            bool,
        )
        or not isinstance(
            ttl_seconds,
            int,
        )
    ):
        raise TypeError(
            "ttl_seconds must be an integer."
        )

    if ttl_seconds <= 0:
        raise ValueError(
            "ttl_seconds must be greater than zero."
        )

    return ttl_seconds


def _validate_socket_timeout(
    socket_timeout_s: float,
) -> float:
    if isinstance(
        socket_timeout_s,
        bool,
    ):
        raise TypeError(
            "socket_timeout_s must be numeric."
        )

    try:
        normalized = float(
            socket_timeout_s
        )

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise TypeError(
            "socket_timeout_s must be numeric."
        ) from exc

    if normalized <= 0:
        raise ValueError(
            "socket_timeout_s must be greater than zero."
        )

    return normalized


__all__ = [
    "DEFAULT_CACHE_TTL_SECONDS",
    "DEFAULT_SOCKET_TIMEOUT_SECONDS",
    "RedisCache",
]