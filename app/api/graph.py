# app/api/graph.py

from fastapi import APIRouter, Request
from app.config import settings

router = APIRouter(prefix="/graph")


@router.get("/stats")
def graph_stats(request: Request):
    return getattr(
        request.app.state,
        "graph_stats",
        {
            "city": settings.city_name,
            "graph_loaded": False,
            "nodes": 0,
            "edges": 0,
            "load_time_s": None,
            "graph_path": str(settings.graph_path),
            "memory_mb": None,
        },
    )