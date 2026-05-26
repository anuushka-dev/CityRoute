# app/api/health.py
from time import perf_counter

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
def health(request: Request):
    started_at = getattr(request.app.state, "started_at", perf_counter())

    return {
        "status": "ok",
        "graph_loaded": getattr(request.app.state, "graph_loaded", False),
        "uptime_s": round(perf_counter() - started_at, 3),
    }