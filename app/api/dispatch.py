# app/api/dispatch.py

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.schemas.dispatch import DispatchCompareRequest, DispatchCompareResponse
from app.services.dispatch_service import compare_dispatch_assignments

router = APIRouter(prefix="/dispatch", tags=["Dispatch"])


@router.post(
    "/compare",
    response_model=DispatchCompareResponse,
    status_code=status.HTTP_200_OK,
)
def compare_dispatch(request: DispatchCompareRequest) -> DispatchCompareResponse:

    try:
        return compare_dispatch_assignments(request)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


__all__ = [
    "router",
]
