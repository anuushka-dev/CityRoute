# app/api/dispatch.py

from __future__ import annotations

from typing import Any

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    status,
)

from app.schemas.dispatch import (
    DispatchCompareRequest,
    DispatchCompareResponse,
)
from app.services.dispatch_road_matrix_service import (
    DispatchRoadMatrixDependencies,
    DispatchRoadMatrixServiceError,
)
from app.services.dispatch_service import (
    compare_dispatch_assignments,
)

router = APIRouter(
    prefix="/dispatch",
    tags=["Dispatch"],
)


@router.post(
    "/compare",
    response_model=DispatchCompareResponse,
    status_code=status.HTTP_200_OK,
    summary=(
        "Compare greedy and Hungarian "
        "dispatch assignments"
    ),
    description=(
        "Compares greedy and Hungarian driver-to-order "
        "assignments using either straight-line Haversine "
        "distance or real directed road-network "
        "source-Dijkstra costs."
    ),
)
async def compare_dispatch(
    http_request: Request,
    payload: DispatchCompareRequest,
) -> DispatchCompareResponse:

    road_matrix_dependencies: (
        DispatchRoadMatrixDependencies
        | None
    ) = None

    # ------------------------------------------------------------------
    # 1. Resolve Phase 10 live road-network infrastructure only when the
    #    client explicitly requests source_dijkstra.
    # ------------------------------------------------------------------

    if (
        payload.matrix_algorithm
        == "source_dijkstra"
    ):
        road_matrix_dependencies = (
            _require_road_matrix_dependencies(
                http_request
            )
        )

    # ------------------------------------------------------------------
    # 2. Resolve runtime service configuration.
    #
    # Defaults preserve compatibility when these app.state fields are not
    # explicitly configured by main.py.
    # ------------------------------------------------------------------

    cache_ttl_seconds = (
        _get_positive_int_state(
            http_request,
            "dispatch_cache_ttl_seconds",
            default=86_400,
        )
    )

    unreachable_cost_m = (
        _get_positive_float_state(
            http_request,
            "dispatch_unreachable_cost_m",
            default=1_000_000_000.0,
        )
    )

    fail_open_on_cache_error = bool(
        getattr(
            http_request.app.state,
            "dispatch_fail_open_on_cache_error",
            True,
        )
    )

    # ------------------------------------------------------------------
    # 3. Run dispatch comparison.
    # ------------------------------------------------------------------

    try:
        return await compare_dispatch_assignments(
            payload,
            road_matrix_dependencies=(
                road_matrix_dependencies
            ),
            cache_ttl_seconds=(
                cache_ttl_seconds
            ),
            unreachable_cost_m=(
                unreachable_cost_m
            ),
            fail_open_on_cache_error=(
                fail_open_on_cache_error
            ),
        )

    except (
        DispatchRoadMatrixServiceError
    ) as exc:
        # Graph/snap/Dijkstra/cache infrastructure failure.
        raise HTTPException(
            status_code=(
                status
                .HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=str(
                exc
            ),
        ) from exc

    except (
        ValueError,
        TypeError,
    ) as exc:
        # Domain validation or invalid dispatch configuration.
        raise HTTPException(
            status_code=(
                status
                .HTTP_400_BAD_REQUEST
            ),
            detail=str(
                exc
            ),
        ) from exc


def _require_road_matrix_dependencies(
    http_request: Request,
) -> DispatchRoadMatrixDependencies:

    app_state = (
        http_request.app.state
    )

    road_matrix_ready = bool(
        getattr(
            app_state,
            "dispatch_road_matrix_ready",
            False,
        )
    )

    dependencies = getattr(
        app_state,
        "dispatch_road_matrix_dependencies",
        None,
    )

    road_matrix_error = getattr(
        app_state,
        "dispatch_road_matrix_error",
        None,
    )

    if (
        not road_matrix_ready
        or dependencies is None
    ):
        detail = (
            "Real road-network dispatch infrastructure "
            "is not available."
        )

        if road_matrix_error:
            detail = (
                f"{detail} "
                f"reason={road_matrix_error}"
            )

        raise HTTPException(
            status_code=(
                status
                .HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=detail,
        )

    if not isinstance(
        dependencies,
        DispatchRoadMatrixDependencies,
    ):
        raise HTTPException(
            status_code=(
                status
                .HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=(
                "Real road-network dispatch infrastructure "
                "is misconfigured. "
                "reason=invalid_dispatch_road_matrix_dependencies"
            ),
        )

    return dependencies


def _get_positive_int_state(
    http_request: Request,
    attribute_name: str,
    *,
    default: int,
) -> int:

    raw_value: Any = getattr(
        http_request.app.state,
        attribute_name,
        default,
    )

    if (
        isinstance(
            raw_value,
            bool,
        )
        or not isinstance(
            raw_value,
            int,
        )
        or raw_value <= 0
    ):
        raise HTTPException(
            status_code=(
                status
                .HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=(
                "Dispatch runtime configuration is invalid. "
                f"reason={attribute_name}"
            ),
        )

    return raw_value


def _get_positive_float_state(
    http_request: Request,
    attribute_name: str,
    *,
    default: float,
) -> float:

    raw_value: Any = getattr(
        http_request.app.state,
        attribute_name,
        default,
    )

    if isinstance(
        raw_value,
        bool,
    ):
        raise HTTPException(
            status_code=(
                status
                .HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=(
                "Dispatch runtime configuration is invalid. "
                f"reason={attribute_name}"
            ),
        )

    try:
        value = float(
            raw_value
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as exc:
        raise HTTPException(
            status_code=(
                status
                .HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=(
                "Dispatch runtime configuration is invalid. "
                f"reason={attribute_name}"
            ),
        ) from exc

    if (
        value <= 0.0
        or value != value
        or value in (
            float("inf"),
            float("-inf"),
        )
    ):
        raise HTTPException(
            status_code=(
                status
                .HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=(
                "Dispatch runtime configuration is invalid. "
                f"reason={attribute_name}"
            ),
        )

    return value


__all__ = [
    "router",
]