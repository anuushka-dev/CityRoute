# app/services/matrix_service.py

from __future__ import annotations

from time import perf_counter
from typing import Any

from fastapi import HTTPException, status

from app.config import settings
from app.core.distance_matrix import build_distance_matrix
from app.infrastructure.redis_cache import RedisCache
from app.models.matrix_model import (
    SUPPORTED_MATRIX_ALGORITHMS,
    MatrixRequest,
    MatrixResponse,
)
from app.utils.logger import get_logger
from app.utils.matrix_cache_key import build_matrix_cache_key

logger = get_logger(__name__)


def _get_setting(name: str, default: Any) -> Any:
    return getattr(settings, name, default)


def _validate_matrix_request(payload: MatrixRequest) -> None:
    max_locations = int(_get_setting("matrix_max_locations", 25))

    if len(payload.locations) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "Not enough locations",
                "message": "Distance matrix requires at least 2 locations.",
                "received_count": len(payload.locations),
            },
        )

    if len(payload.locations) > max_locations:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "Too many locations",
                "message": f"Distance matrix supports at most {max_locations} locations.",
                "received_count": len(payload.locations),
                "max_locations": max_locations,
            },
        )

    supported_algorithms = set(SUPPORTED_MATRIX_ALGORITHMS)

    if payload.algorithm not in supported_algorithms:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "Unsupported matrix algorithm",
                "message": (
                    "Supported algorithms are: "
                    + ", ".join(sorted(supported_algorithms))
                    + "."
                ),
                "received_algorithm": payload.algorithm,
                "supported_algorithms": sorted(supported_algorithms),
            },
        )


def _build_cache_metadata(
    *,
    enabled: bool,
    hit: bool,
    key: str | None,
    ttl_seconds: int,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "hit": hit,
        "key": key,
        "ttl_seconds": ttl_seconds,
        "error": error,
    }


def build_distance_matrix_response(
    payload: MatrixRequest,
    graph: Any,
    snap_index: Any,
) -> MatrixResponse:
    started_at = perf_counter()

    _validate_matrix_request(payload)

    ttl_seconds = int(_get_setting("matrix_cache_ttl_seconds", 86_400))
    redis_url = str(_get_setting("redis_url", "redis://localhost:6379/0"))
    graph_path = str(_get_setting("graph_path", "unknown_graph"))
    workers = int(_get_setting("matrix_workers", 8))

    cache_enabled = bool(payload.use_cache)
    cache_key: str | None = None
    cache_error: str | None = None

    redis_cache: RedisCache | None = None

    if cache_enabled:
        cache_key = build_matrix_cache_key(
            locations=payload.locations,
            algorithm=payload.algorithm,
            graph_identity=graph_path,
        )

        try:
            redis_cache = RedisCache(
                redis_url=redis_url,
                ttl_seconds=ttl_seconds,
            )

            cached_payload = redis_cache.get_json(cache_key)

            if cached_payload is not None:
                logger.info(
                    "Matrix cache hit | n=%s | algorithm=%s | key=%s",
                    len(payload.locations),
                    payload.algorithm,
                    cache_key,
                )

                cached_payload["cache"] = _build_cache_metadata(
                    enabled=True,
                    hit=True,
                    key=cache_key,
                    ttl_seconds=ttl_seconds,
                )

                cached_payload["generation_time_ms"] = round(
                    (perf_counter() - started_at) * 1000,
                    3,
                )

                return MatrixResponse(**cached_payload)

            logger.info(
                "Matrix cache miss | n=%s | algorithm=%s | key=%s",
                len(payload.locations),
                payload.algorithm,
                cache_key,
            )

        except Exception as exc:
            cache_error = str(exc)
            redis_cache = None

            logger.warning(
                "Matrix cache unavailable | n=%s | algorithm=%s | error=%s",
                len(payload.locations),
                payload.algorithm,
                cache_error,
            )

    matrix_result = build_distance_matrix(
        locations=payload.locations,
        graph=graph,
        snap_index=snap_index,
        algorithm=payload.algorithm,
        workers=workers,
    )

    generation_time_ms = round((perf_counter() - started_at) * 1000, 3)

    response_payload: dict[str, Any] = {
        "status": "ok",
        "n": len(payload.locations),
        "algorithm": payload.algorithm,
        "cache": _build_cache_metadata(
            enabled=cache_enabled,
            hit=False,
            key=cache_key,
            ttl_seconds=ttl_seconds,
            error=cache_error,
        ),
        "locations": [
            location.model_dump()
            for location in payload.locations
        ],
        "matrix_distance_m": matrix_result.matrix_distance_m,
        "matrix_eta_s": matrix_result.matrix_eta_s,
        "pair_count": matrix_result.pair_count,
        "computed_pairs": matrix_result.computed_pairs,
        "failed_pairs": matrix_result.failed_pairs,
        "failures": [
            failure.model_dump()
            for failure in matrix_result.failures
        ],
        "generation_time_ms": generation_time_ms,
        "parallel_workers": workers,
    }

    if cache_enabled and redis_cache is not None and cache_key is not None:
        try:
            redis_cache.set_json(cache_key, response_payload)

            logger.info(
                "Matrix cached | n=%s | algorithm=%s | key=%s | ttl_seconds=%s",
                len(payload.locations),
                payload.algorithm,
                cache_key,
                ttl_seconds,
            )

        except Exception as exc:
            cache_write_error = str(exc)
            response_payload["cache"]["error"] = cache_write_error

            logger.warning(
                "Matrix cache write failed | n=%s | algorithm=%s | key=%s | error=%s",
                len(payload.locations),
                payload.algorithm,
                cache_key,
                cache_write_error,
            )

    logger.info(
        "Matrix generated | n=%s | pairs=%s | computed_pairs=%s | failed_pairs=%s | "
        "algorithm=%s | cache_enabled=%s | cache_hit=%s | workers=%s | time_ms=%s",
        len(payload.locations),
        matrix_result.pair_count,
        matrix_result.computed_pairs,
        matrix_result.failed_pairs,
        payload.algorithm,
        cache_enabled,
        False,
        workers,
        generation_time_ms,
    )

    return MatrixResponse(**response_payload)