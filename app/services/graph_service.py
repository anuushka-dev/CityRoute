# app/services/graph_service.py

from __future__ import annotations

from time import perf_counter
from typing import Any

import networkx as nx
import osmnx as ox
import psutil

from app.config import settings
from app.utils.logger import get_logger


logger = get_logger(__name__)


def _get_memory_mb() -> float:
    """
    Return current process memory usage in MB.
    Useful for Phase 2 audit evidence and Docker/Railway monitoring.
    """
    process = psutil.Process()
    return round(process.memory_info().rss / 1024 / 1024, 2)


def _get_graph_file_size_mb() -> float | None:
    """
    Return GraphML file size in MB if the file exists.
    Useful for Phase 2 benchmark evidence.
    """
    if not settings.graph_path.exists():
        return None

    return round(settings.graph_path.stat().st_size / 1024 / 1024, 2)


def _get_connectivity_stats(graph: Any | None) -> dict[str, Any]:
    """
    Return weak-connectivity metadata for the loaded directed road graph.

    This does not replace Phase 3 route-level NetworkXNoPath handling.
    It only records whether the loaded graph is split into weakly connected
    components, so Phase 2 has honest disconnected-graph evidence.
    """
    if graph is None:
        return {
            "weakly_connected_components": 0,
            "largest_component_nodes": 0,
            "is_weakly_connected": False,
        }

    component_sizes = [len(component) for component in nx.weakly_connected_components(graph)]
    largest_component_nodes = max(component_sizes) if component_sizes else 0

    return {
        "weakly_connected_components": len(component_sizes),
        "largest_component_nodes": largest_component_nodes,
        "is_weakly_connected": len(component_sizes) == 1,
    }


def _build_graph_stats(
    *,
    graph: Any | None,
    graph_loaded: bool,
    load_time_s: float | None,
    error: str | None = None,
) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "city": settings.city_name,
        "graph_loaded": graph_loaded,
        "nodes": len(graph.nodes) if graph is not None else 0,
        "edges": len(graph.edges) if graph is not None else 0,
        "load_time_s": load_time_s,
        "graph_path": str(settings.graph_path),
        "graph_file_size_mb": _get_graph_file_size_mb(),
        "memory_mb": _get_memory_mb(),
    }

    stats.update(_get_connectivity_stats(graph))

    if error is not None:
        stats["error"] = error

    return stats


def _download_graph() -> Any:
    """
    Download either a smaller central Kanpur bbox graph or full city graph.
    For Phase 2, bbox graph is preferred because it reduces memory and startup time.
    """
    if settings.use_bbox_graph:
        logger.info(
            "Downloading bbox graph | north=%s south=%s east=%s west=%s",
            settings.bbox_north,
            settings.bbox_south,
            settings.bbox_east,
            settings.bbox_west,
        )

        bbox = (
            settings.bbox_west,
            settings.bbox_south,
            settings.bbox_east,
            settings.bbox_north,
        )

        return ox.graph_from_bbox(
            bbox,
            network_type="drive",
            simplify=True,
        )

    logger.info("Downloading full place graph for: %s", settings.city_name)

    return ox.graph_from_place(
        settings.city_name,
        network_type="drive",
        simplify=True,
    )


def load_or_download_graph() -> tuple[Any | None, dict[str, Any]]:
    start = perf_counter()

    try:
        settings.graph_dir.mkdir(parents=True, exist_ok=True)

        if settings.graph_path.exists():
            logger.info("Loading graph from GraphML: %s", settings.graph_path)
            graph = ox.load_graphml(settings.graph_path)
        else:
            logger.info("GraphML not found. Downloading graph for: %s", settings.city_name)

            graph = _download_graph()

            logger.info("Saving graph to GraphML: %s", settings.graph_path)
            ox.save_graphml(graph, settings.graph_path)

        load_time_s = round(perf_counter() - start, 3)

        stats = _build_graph_stats(
            graph=graph,
            graph_loaded=True,
            load_time_s=load_time_s,
        )

        logger.info(
            (
                "Graph ready | city=%s | nodes=%s | edges=%s | load_time_s=%s | "
                "file_size_mb=%s | memory_mb=%s | weakly_connected_components=%s | "
                "largest_component_nodes=%s | is_weakly_connected=%s"
            ),
            stats["city"],
            stats["nodes"],
            stats["edges"],
            stats["load_time_s"],
            stats["graph_file_size_mb"],
            stats["memory_mb"],
            stats["weakly_connected_components"],
            stats["largest_component_nodes"],
            stats["is_weakly_connected"],
        )

        return graph, stats

    except Exception as exc:
        load_time_s = round(perf_counter() - start, 3)
        error_message = f"{type(exc).__name__}: {exc}"

        logger.exception("Graph loading failed: %s", error_message)

        stats = _build_graph_stats(
            graph=None,
            graph_loaded=False,
            load_time_s=load_time_s,
            error=error_message,
        )

        return None, stats