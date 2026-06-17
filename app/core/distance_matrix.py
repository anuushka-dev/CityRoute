# app/core/distance_matrix.py

from __future__ import annotations

import importlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable

from app.core.graph_adjacency import build_graph_adjacency
from app.core.multi_target_dijkstra import multi_target_dijkstra
from app.models.matrix_model import (
    MatrixComputationResult,
    MatrixLocation,
    MatrixPairFailure,
)
from app.utils.geo_validation import validate_coordinates
from app.utils.logger import get_logger
from app.utils.snap_index import query_snap_index

logger = get_logger(__name__)

DEFAULT_AVERAGE_SPEED_KMPH = 23.16


@dataclass(frozen=True)
class SnappedMatrixLocation:
    index: int
    id: str
    input_lat: float
    input_lon: float
    node_id: int
    snapped_lat: float
    snapped_lon: float
    snap_distance_m: float


@dataclass(frozen=True)
class PairRouteResult:
    from_index: int
    to_index: int
    distance_m: float | None
    eta_s: float | None
    error: str | None


def _distance_to_eta_s(distance_m: float) -> float:
    speed_mps = DEFAULT_AVERAGE_SPEED_KMPH * 1000 / 3600
    return round(distance_m / speed_mps, 3)


def _extract_route_distance_m(result: Any) -> float:
    if hasattr(result, "distance_m"):
        return float(result.distance_m)

    if isinstance(result, dict) and "distance_m" in result:
        return float(result["distance_m"])

    if isinstance(result, tuple) and len(result) >= 2:
        return float(result[1])

    raise TypeError(
        "Could not extract distance_m from route algorithm result. "
        "Expected .distance_m, {'distance_m': ...}, or tuple(path, distance_m, ...)."
    )


def _load_algorithm_function(
    *,
    module_names: list[str],
    function_names: list[str],
) -> Callable[..., Any]:
    last_error: Exception | None = None

    for module_name in module_names:
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            last_error = exc
            continue

        for function_name in function_names:
            candidate = getattr(module, function_name, None)

            if callable(candidate):
                return candidate

    raise RuntimeError(
        "Could not find routing algorithm function. "
        f"Tried modules={module_names}, functions={function_names}. "
        f"Last import error={last_error}"
    )


def _call_algorithm_function(
    algorithm_fn: Callable[..., Any],
    graph: Any,
    start_node: int,
    end_node: int,
) -> Any:
    call_attempts = (
        lambda: algorithm_fn(graph, start_node, end_node),
        lambda: algorithm_fn(G=graph, start=start_node, goal=end_node),
        lambda: algorithm_fn(graph=graph, start_node=start_node, end_node=end_node),
        lambda: algorithm_fn(graph=graph, source=start_node, target=end_node),
    )

    errors: list[str] = []

    for attempt in call_attempts:
        try:
            return attempt()
        except TypeError as exc:
            errors.append(str(exc))

    raise TypeError(
        "Could not call routing algorithm with supported signatures. "
        f"Errors={errors}"
    )


def _get_algorithm_runner(algorithm: str) -> Callable[[Any, int, int], Any]:
    normalized = algorithm.strip().lower()

    if normalized == "astar":
        algorithm_fn = _load_algorithm_function(
            module_names=["app.core.a_star", "app.core.astar"],
            function_names=[
                "astar_shortest_path",
                "a_star_shortest_path",
                "a_star",
                "astar",
                "a_star_search",
                "astar_search",
                "run_a_star",
                "find_shortest_path",
            ],
        )

        return lambda graph, start_node, end_node: _call_algorithm_function(
            algorithm_fn,
            graph,
            start_node,
            end_node,
        )

    if normalized == "bidirectional_astar":
        algorithm_fn = _load_algorithm_function(
            module_names=[
                "app.core.bidirectional_a_star",
                "app.core.bidirectional_astar",
                "app.core.bi_a_star",
            ],
            function_names=[
                "bidirectional_astar_shortest_path",
                "bidirectional_a_star_shortest_path",
                "bidirectional_a_star",
                "bidirectional_astar",
                "bidirectional_a_star_search",
                "bidirectional_astar_search",
                "bi_a_star",
                "run_bidirectional_a_star",
            ],
        )

        return lambda graph, start_node, end_node: _call_algorithm_function(
            algorithm_fn,
            graph,
            start_node,
            end_node,
        )

    raise ValueError(f"Unsupported matrix algorithm: {algorithm}")


def _snap_locations_once(
    *,
    locations: list[MatrixLocation],
    graph: Any,
    snap_index: Any,
) -> list[SnappedMatrixLocation]:
    snapped_locations: list[SnappedMatrixLocation] = []

    for index, location in enumerate(locations):
        validate_coordinates(location.lat, location.lon)

        snap_result = query_snap_index(
            graph=graph,
            snap_index=snap_index,
            lat=location.lat,
            lon=location.lon,
        )

        if isinstance(snap_result, dict):
            node_id = int(snap_result["nearest_node"])
            snapped_lat = float(snap_result["snapped"]["lat"])
            snapped_lon = float(snap_result["snapped"]["lon"])
            snap_distance_m = float(snap_result["snap_distance_m"])
        else:
            node_id = int(snap_result.nearest_node)
            snapped_lat = float(snap_result.snapped_lat)
            snapped_lon = float(snap_result.snapped_lon)
            snap_distance_m = float(snap_result.snap_distance_m)

        snapped_locations.append(
            SnappedMatrixLocation(
                index=index,
                id=location.id,
                input_lat=float(location.lat),
                input_lon=float(location.lon),
                node_id=node_id,
                snapped_lat=snapped_lat,
                snapped_lon=snapped_lon,
                snap_distance_m=snap_distance_m,
            )
        )

    return snapped_locations


def _compute_one_pair(
    *,
    graph: Any,
    route_runner: Callable[[Any, int, int], Any],
    from_location: SnappedMatrixLocation,
    to_location: SnappedMatrixLocation,
) -> PairRouteResult:
    if from_location.index == to_location.index:
        return PairRouteResult(
            from_index=from_location.index,
            to_index=to_location.index,
            distance_m=0.0,
            eta_s=0.0,
            error=None,
        )

    try:
        route_result = route_runner(
            graph,
            from_location.node_id,
            to_location.node_id,
        )

        distance_m = round(_extract_route_distance_m(route_result), 3)

        return PairRouteResult(
            from_index=from_location.index,
            to_index=to_location.index,
            distance_m=distance_m,
            eta_s=_distance_to_eta_s(distance_m),
            error=None,
        )

    except Exception as exc:
        return PairRouteResult(
            from_index=from_location.index,
            to_index=to_location.index,
            distance_m=None,
            eta_s=None,
            error=str(exc),
        )


def _build_source_dijkstra_matrix(
    *,
    locations: list[MatrixLocation],
    graph: Any,
    snapped_locations: list[SnappedMatrixLocation],
) -> MatrixComputationResult:
    """
    Phase 5.1 optimized matrix builder.

    Old path:
        N × N pairwise A*/Bidirectional A* searches.

    New path:
        one multi-target Dijkstra run per unique snapped source node.
    """

    started_at = perf_counter()

    n = len(snapped_locations)

    matrix_distance_m: list[list[float | None]] = [
        [None for _ in range(n)] for _ in range(n)
    ]
    matrix_eta_s: list[list[float | None]] = [
        [None for _ in range(n)] for _ in range(n)
    ]

    failures: list[MatrixPairFailure] = []
    computed_pairs = 0

    adjacency = build_graph_adjacency(graph)

    unique_nodes = list(
        dict.fromkeys(location.node_id for location in snapped_locations)
    )

    target_nodes = set(unique_nodes)

    distance_by_source: dict[int, dict[int, float | None]] = {}
    nodes_expanded_total = 0

    for source_node in unique_nodes:
        result = multi_target_dijkstra(
            adjacency=adjacency,
            source_node=source_node,
            target_nodes=target_nodes,
        )

        distance_by_source[source_node] = result.target_distances_m
        nodes_expanded_total += result.nodes_expanded

    for from_location in snapped_locations:
        for to_location in snapped_locations:
            from_index = from_location.index
            to_index = to_location.index

            if from_index == to_index or from_location.node_id == to_location.node_id:
                distance_m: float | None = 0.0
            else:
                distance_m = distance_by_source[from_location.node_id].get(
                    to_location.node_id
                )

                if distance_m is not None:
                    distance_m = round(float(distance_m), 3)

            if distance_m is None:
                failures.append(
                    MatrixPairFailure(
                        from_index=from_index,
                        to_index=to_index,
                        from_id=locations[from_index].id,
                        to_id=locations[to_index].id,
                        error=(
                            "No path found between snapped nodes "
                            f"{from_location.node_id} and {to_location.node_id}"
                        ),
                    )
                )
                continue

            matrix_distance_m[from_index][to_index] = distance_m
            matrix_eta_s[from_index][to_index] = _distance_to_eta_s(distance_m)
            computed_pairs += 1

    failed_pairs = len(failures)
    elapsed_ms = round((perf_counter() - started_at) * 1000, 3)

    logger.info(
        "Distance matrix core complete | n=%s | pair_count=%s | computed_pairs=%s | "
        "failed_pairs=%s | algorithm=%s | source_runs=%s | nodes_expanded_total=%s | "
        "adjacency_build_time_ms=%s | time_ms=%s",
        n,
        n * n,
        computed_pairs,
        failed_pairs,
        "source_dijkstra",
        len(unique_nodes),
        nodes_expanded_total,
        adjacency.build_time_ms,
        elapsed_ms,
    )

    return MatrixComputationResult(
        matrix_distance_m=matrix_distance_m,
        matrix_eta_s=matrix_eta_s,
        pair_count=n * n,
        computed_pairs=computed_pairs,
        failed_pairs=failed_pairs,
        failures=failures,
    )


def _build_pairwise_matrix(
    *,
    locations: list[MatrixLocation],
    graph: Any,
    snapped_locations: list[SnappedMatrixLocation],
    algorithm: str,
    workers: int,
) -> MatrixComputationResult:
    started_at = perf_counter()

    n = len(snapped_locations)
    effective_workers = max(1, min(int(workers), n * n))

    route_runner = _get_algorithm_runner(algorithm)

    matrix_distance_m: list[list[float | None]] = [
        [None for _ in range(n)] for _ in range(n)
    ]
    matrix_eta_s: list[list[float | None]] = [
        [None for _ in range(n)] for _ in range(n)
    ]

    failures: list[MatrixPairFailure] = []
    computed_pairs = 0

    pair_jobs = [
        (from_location, to_location)
        for from_location in snapped_locations
        for to_location in snapped_locations
    ]

    with ThreadPoolExecutor(max_workers=effective_workers) as executor:
        future_to_pair = {
            executor.submit(
                _compute_one_pair,
                graph=graph,
                route_runner=route_runner,
                from_location=from_location,
                to_location=to_location,
            ): (from_location, to_location)
            for from_location, to_location in pair_jobs
        }

        for future in as_completed(future_to_pair):
            from_location, to_location = future_to_pair[future]

            try:
                pair_result = future.result()
            except Exception as exc:
                pair_result = PairRouteResult(
                    from_index=from_location.index,
                    to_index=to_location.index,
                    distance_m=None,
                    eta_s=None,
                    error=str(exc),
                )

            matrix_distance_m[pair_result.from_index][pair_result.to_index] = (
                pair_result.distance_m
            )
            matrix_eta_s[pair_result.from_index][pair_result.to_index] = (
                pair_result.eta_s
            )

            if pair_result.error is None:
                computed_pairs += 1
            else:
                failures.append(
                    MatrixPairFailure(
                        from_index=pair_result.from_index,
                        to_index=pair_result.to_index,
                        from_id=locations[pair_result.from_index].id,
                        to_id=locations[pair_result.to_index].id,
                        error=pair_result.error,
                    )
                )

    failed_pairs = len(failures)
    elapsed_ms = round((perf_counter() - started_at) * 1000, 3)

    logger.info(
        "Distance matrix core complete | n=%s | pair_count=%s | computed_pairs=%s | "
        "failed_pairs=%s | algorithm=%s | workers=%s | time_ms=%s",
        n,
        n * n,
        computed_pairs,
        failed_pairs,
        algorithm,
        effective_workers,
        elapsed_ms,
    )

    return MatrixComputationResult(
        matrix_distance_m=matrix_distance_m,
        matrix_eta_s=matrix_eta_s,
        pair_count=n * n,
        computed_pairs=computed_pairs,
        failed_pairs=failed_pairs,
        failures=failures,
    )


def build_distance_matrix(
    *,
    locations: list[MatrixLocation],
    graph: Any,
    snap_index: Any,
    algorithm: str = "bidirectional_astar",
    workers: int = 8,
) -> MatrixComputationResult:
    normalized_algorithm = algorithm.strip().lower()

    snapped_locations = _snap_locations_once(
        locations=locations,
        graph=graph,
        snap_index=snap_index,
    )

    if normalized_algorithm == "source_dijkstra":
        return _build_source_dijkstra_matrix(
            locations=locations,
            graph=graph,
            snapped_locations=snapped_locations,
        )

    return _build_pairwise_matrix(
        locations=locations,
        graph=graph,
        snapped_locations=snapped_locations,
        algorithm=normalized_algorithm,
        workers=workers,
    )