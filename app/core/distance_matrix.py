# app/core/distance_matrix.py

from __future__ import annotations

import importlib
import math
from collections.abc import Callable, Sequence
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from app.core.graph_adjacency import (
    GraphAdjacency,
    build_graph_adjacency,
)
from app.core.multi_target_dijkstra import (
    multi_target_dijkstra,
)
from app.models.matrix_model import (
    MatrixComputationResult,
    MatrixLocation,
    MatrixPairFailure,
)
from app.utils.geo_validation import (
    validate_coordinates,
)
from app.utils.logger import get_logger
from app.utils.snap_index import (
    query_snap_index,
)

logger = get_logger(__name__)


DEFAULT_AVERAGE_SPEED_KMPH = 23.16


@dataclass(frozen=True)
class SnappedMatrixLocation:
    """
    One matrix input after snapping to the road graph.
    """

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
    """
    Result of one pairwise route computation.
    """

    from_index: int
    to_index: int

    distance_m: float | None
    eta_s: float | None

    error: str | None


def _distance_to_eta_s(
    distance_m: float,
) -> float:
    """
    Convert road distance into estimated travel time.

    The existing CityRoute average-speed assumption is preserved.
    """

    normalized_distance_m = float(
        distance_m
    )

    if not math.isfinite(
        normalized_distance_m
    ):
        raise ValueError(
            "distance_m must be finite."
        )

    if normalized_distance_m < 0:
        raise ValueError(
            "distance_m must be non-negative."
        )

    speed_mps = (
        DEFAULT_AVERAGE_SPEED_KMPH
        * 1000.0
        / 3600.0
    )

    return round(
        normalized_distance_m
        / speed_mps,
        3,
    )


def _extract_route_distance_m(
    result: Any,
) -> float:
    """
    Extract a distance value from supported routing-result contracts.
    """

    if hasattr(
        result,
        "distance_m",
    ):
        distance_m = float(
            result.distance_m
        )

    elif (
        isinstance(
            result,
            dict,
        )
        and "distance_m"
        in result
    ):
        distance_m = float(
            result[
                "distance_m"
            ]
        )

    elif (
        isinstance(
            result,
            tuple,
        )
        and len(
            result
        ) >= 2
    ):
        distance_m = float(
            result[
                1
            ]
        )

    else:
        raise TypeError(
            "Could not extract distance_m from route algorithm result. "
            "Expected .distance_m, {'distance_m': ...}, or "
            "tuple(path, distance_m, ...)."
        )

    if not math.isfinite(
        distance_m
    ):
        raise ValueError(
            "Routing algorithm returned a non-finite distance."
        )

    if distance_m < 0:
        raise ValueError(
            "Routing algorithm returned a negative distance."
        )

    return distance_m


def _load_algorithm_function(
    *,
    module_names: Sequence[str],
    function_names: Sequence[str],
) -> Callable[..., Any]:
    """
    Resolve one supported routing implementation dynamically.

    This preserves compatibility with the earlier CityRoute A* naming
    variants.
    """

    last_error: Exception | None = None

    for module_name in module_names:
        try:
            module = importlib.import_module(
                module_name
            )

        except Exception as exc:
            last_error = exc
            continue

        for function_name in function_names:
            candidate = getattr(
                module,
                function_name,
                None,
            )

            if callable(
                candidate
            ):
                return candidate

    raise RuntimeError(
        "Could not find routing algorithm function. "
        f"Tried modules={list(module_names)}, "
        f"functions={list(function_names)}. "
        f"Last import error={last_error}"
    )


def _call_algorithm_function(
    algorithm_fn: Callable[..., Any],
    graph: Any,
    start_node: int,
    end_node: int,
) -> Any:
    """
    Call an earlier routing implementation using supported CityRoute
    signatures.
    """

    call_attempts = (
        lambda: algorithm_fn(
            graph,
            start_node,
            end_node,
        ),
        lambda: algorithm_fn(
            G=graph,
            start=start_node,
            goal=end_node,
        ),
        lambda: algorithm_fn(
            graph=graph,
            start_node=start_node,
            end_node=end_node,
        ),
        lambda: algorithm_fn(
            graph=graph,
            source=start_node,
            target=end_node,
        ),
    )

    errors: list[str] = []

    for attempt in call_attempts:
        try:
            return attempt()

        except TypeError as exc:
            errors.append(
                str(
                    exc
                )
            )

    raise TypeError(
        "Could not call routing algorithm with supported signatures. "
        f"Errors={errors}"
    )


def _get_algorithm_runner(
    algorithm: str,
) -> Callable[
    [Any, int, int],
    Any,
]:
    """
    Resolve the pairwise routing implementation.
    """

    normalized = (
        algorithm
        .strip()
        .lower()
    )

    if normalized == "astar":
        algorithm_fn = (
            _load_algorithm_function(
                module_names=[
                    "app.core.a_star",
                    "app.core.astar",
                ],
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
        )

        return (
            lambda graph, start_node, end_node:
            _call_algorithm_function(
                algorithm_fn,
                graph,
                start_node,
                end_node,
            )
        )

    if (
        normalized
        == "bidirectional_astar"
    ):
        algorithm_fn = (
            _load_algorithm_function(
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
        )

        return (
            lambda graph, start_node, end_node:
            _call_algorithm_function(
                algorithm_fn,
                graph,
                start_node,
                end_node,
            )
        )

    raise ValueError(
        "Unsupported matrix algorithm: "
        f"{algorithm}"
    )


def _snap_locations_once(
    *,
    locations: Sequence[
        MatrixLocation
    ],
    graph: Any,
    snap_index: Any,
) -> list[
    SnappedMatrixLocation
]:
    """
    Snap every input location exactly once.

    Duplicate coordinates inside the same request reuse the previous snap
    result, avoiding unnecessary repeated BallTree queries.
    """

    snapped_locations: list[
        SnappedMatrixLocation
    ] = []

    snap_cache: dict[
        tuple[float, float],
        tuple[
            int,
            float,
            float,
            float,
        ],
    ] = {}

    for (
        index,
        location,
    ) in enumerate(
        locations
    ):
        validate_coordinates(
            location.lat,
            location.lon,
        )

        input_lat = float(
            location.lat
        )

        input_lon = float(
            location.lon
        )

        coordinate_key = (
            input_lat,
            input_lon,
        )

        if coordinate_key in snap_cache:
            (
                node_id,
                snapped_lat,
                snapped_lon,
                snap_distance_m,
            ) = snap_cache[
                coordinate_key
            ]

        else:
            snap_result = (
                query_snap_index(
                    graph=graph,
                    snap_index=snap_index,
                    lat=input_lat,
                    lon=input_lon,
                )
            )

            node_id = int(
                snap_result[
                    "nearest_node"
                ]
            )

            snapped_lat = float(
                snap_result[
                    "snapped"
                ][
                    "lat"
                ]
            )

            snapped_lon = float(
                snap_result[
                    "snapped"
                ][
                    "lon"
                ]
            )

            snap_distance_m = float(
                snap_result[
                    "snap_distance_m"
                ]
            )

            snap_cache[
                coordinate_key
            ] = (
                node_id,
                snapped_lat,
                snapped_lon,
                snap_distance_m,
            )

        snapped_locations.append(
            SnappedMatrixLocation(
                index=index,
                id=location.id,
                input_lat=input_lat,
                input_lon=input_lon,
                node_id=node_id,
                snapped_lat=snapped_lat,
                snapped_lon=snapped_lon,
                snap_distance_m=(
                    snap_distance_m
                ),
            )
        )

    return snapped_locations


def _compute_one_pair(
    *,
    graph: Any,
    route_runner: Callable[
        [Any, int, int],
        Any,
    ],
    from_location: SnappedMatrixLocation,
    to_location: SnappedMatrixLocation,
) -> PairRouteResult:
    """
    Compute one pairwise route.

    Same snapped node always has zero road distance, even when the two
    matrix locations occupy different input indices.
    """

    if (
        from_location.index
        == to_location.index
        or from_location.node_id
        == to_location.node_id
    ):
        return PairRouteResult(
            from_index=(
                from_location.index
            ),
            to_index=(
                to_location.index
            ),
            distance_m=0.0,
            eta_s=0.0,
            error=None,
        )

    try:
        route_result = (
            route_runner(
                graph,
                from_location.node_id,
                to_location.node_id,
            )
        )

        distance_m = round(
            _extract_route_distance_m(
                route_result
            ),
            3,
        )

        return PairRouteResult(
            from_index=(
                from_location.index
            ),
            to_index=(
                to_location.index
            ),
            distance_m=distance_m,
            eta_s=_distance_to_eta_s(
                distance_m
            ),
            error=None,
        )

    except Exception as exc:
        return PairRouteResult(
            from_index=(
                from_location.index
            ),
            to_index=(
                to_location.index
            ),
            distance_m=None,
            eta_s=None,
            error=str(
                exc
            ),
        )


def _build_source_dijkstra_matrix(
    *,
    locations: Sequence[
        MatrixLocation
    ],
    graph: Any,
    snapped_locations: Sequence[
        SnappedMatrixLocation
    ],
    adjacency: GraphAdjacency | None = None,
) -> MatrixComputationResult:
    """
    Build the optimized source-wise Dijkstra matrix.

    Phase 5 optimization:

        old:
            N x N pairwise route searches

        optimized:
            one multi-target Dijkstra run
            per unique snapped source node

    Phase 10 improvement:

        an already-built GraphAdjacency may be injected so the application
        can reuse startup adjacency instead of rebuilding it per request.
    """

    started_at = perf_counter()

    location_count = len(
        snapped_locations
    )

    matrix_distance_m: list[
        list[
            float | None
        ]
    ] = [
        [
            None
            for _ in range(
                location_count
            )
        ]
        for _ in range(
            location_count
        )
    ]

    matrix_eta_s: list[
        list[
            float | None
        ]
    ] = [
        [
            None
            for _ in range(
                location_count
            )
        ]
        for _ in range(
            location_count
        )
    ]

    failures: list[
        MatrixPairFailure
    ] = []

    computed_pairs = 0

    # Reuse Phase 10 startup adjacency when supplied.
    effective_adjacency = (
        adjacency
        if adjacency is not None
        else build_graph_adjacency(
            graph
        )
    )

    unique_nodes = tuple(
        dict.fromkeys(
            location.node_id
            for location
            in snapped_locations
        )
    )

    distance_by_source: dict[
        int,
        dict[
            int,
            float | None,
        ],
    ] = {}

    nodes_expanded_total = 0

    for source_node in unique_nodes:
        # Same-node distance is known without running Dijkstra.
        source_distances: dict[
            int,
            float | None,
        ] = {
            source_node: 0.0,
        }

        target_nodes = set(
            unique_nodes
        )

        target_nodes.discard(
            source_node
        )

        if target_nodes:
            result = (
                multi_target_dijkstra(
                    adjacency=(
                        effective_adjacency
                    ),
                    source_node=(
                        source_node
                    ),
                    target_nodes=(
                        target_nodes
                    ),
                )
            )

            source_distances.update(
                {
                    int(
                        target_node
                    ): distance_m
                    for (
                        target_node,
                        distance_m,
                    ) in (
                        result
                        .target_distances_m
                        .items()
                    )
                }
            )

            nodes_expanded_total += (
                result.nodes_expanded
            )

        distance_by_source[
            source_node
        ] = source_distances

    for from_location in (
        snapped_locations
    ):
        for to_location in (
            snapped_locations
        ):
            from_index = (
                from_location.index
            )

            to_index = (
                to_location.index
            )

            if (
                from_location.node_id
                == to_location.node_id
            ):
                distance_m: (
                    float | None
                ) = 0.0

            else:
                distance_m = (
                    distance_by_source[
                        from_location.node_id
                    ].get(
                        to_location.node_id
                    )
                )

                if distance_m is not None:
                    distance_m = round(
                        float(
                            distance_m
                        ),
                        3,
                    )

            if distance_m is None:
                failures.append(
                    MatrixPairFailure(
                        from_index=(
                            from_index
                        ),
                        to_index=(
                            to_index
                        ),
                        from_id=(
                            locations[
                                from_index
                            ].id
                        ),
                        to_id=(
                            locations[
                                to_index
                            ].id
                        ),
                        error=(
                            "No path found between "
                            "snapped nodes "
                            f"{from_location.node_id} "
                            "and "
                            f"{to_location.node_id}"
                        ),
                    )
                )

                continue

            matrix_distance_m[
                from_index
            ][
                to_index
            ] = distance_m

            matrix_eta_s[
                from_index
            ][
                to_index
            ] = (
                _distance_to_eta_s(
                    distance_m
                )
            )

            computed_pairs += 1

    failed_pairs = len(
        failures
    )

    elapsed_ms = _elapsed_ms(
        started_at
    )

    logger.info(
        (
            "Distance matrix core complete | "
            "n=%s | "
            "pair_count=%s | "
            "computed_pairs=%s | "
            "failed_pairs=%s | "
            "algorithm=%s | "
            "source_runs=%s | "
            "nodes_expanded_total=%s | "
            "adjacency_reused=%s | "
            "adjacency_build_time_ms=%s | "
            "time_ms=%s"
        ),
        location_count,
        (
            location_count
            * location_count
        ),
        computed_pairs,
        failed_pairs,
        "source_dijkstra",
        len(
            unique_nodes
        ),
        nodes_expanded_total,
        adjacency is not None,
        (
            effective_adjacency
            .build_time_ms
        ),
        elapsed_ms,
    )

    return MatrixComputationResult(
        matrix_distance_m=(
            matrix_distance_m
        ),
        matrix_eta_s=(
            matrix_eta_s
        ),
        pair_count=(
            location_count
            * location_count
        ),
        computed_pairs=(
            computed_pairs
        ),
        failed_pairs=(
            failed_pairs
        ),
        failures=failures,
    )


def _build_pairwise_matrix(
    *,
    locations: Sequence[
        MatrixLocation
    ],
    graph: Any,
    snapped_locations: Sequence[
        SnappedMatrixLocation
    ],
    algorithm: str,
    workers: int,
) -> MatrixComputationResult:
    """
    Build a matrix using independent pairwise route searches.

    Preserved for A* and bidirectional A* comparison/evidence.
    """

    started_at = perf_counter()

    location_count = len(
        snapped_locations
    )

    effective_workers = max(
        1,
        min(
            int(
                workers
            ),
            max(
                1,
                location_count
                * location_count,
            ),
        ),
    )

    route_runner = (
        _get_algorithm_runner(
            algorithm
        )
    )

    matrix_distance_m: list[
        list[
            float | None
        ]
    ] = [
        [
            None
            for _ in range(
                location_count
            )
        ]
        for _ in range(
            location_count
        )
    ]

    matrix_eta_s: list[
        list[
            float | None
        ]
    ] = [
        [
            None
            for _ in range(
                location_count
            )
        ]
        for _ in range(
            location_count
        )
    ]

    failures: list[
        MatrixPairFailure
    ] = []

    computed_pairs = 0

    pair_jobs = [
        (
            from_location,
            to_location,
        )
        for from_location
        in snapped_locations
        for to_location
        in snapped_locations
    ]

    with ThreadPoolExecutor(
        max_workers=effective_workers
    ) as executor:
        future_to_pair = {
            executor.submit(
                _compute_one_pair,
                graph=graph,
                route_runner=(
                    route_runner
                ),
                from_location=(
                    from_location
                ),
                to_location=(
                    to_location
                ),
            ): (
                from_location,
                to_location,
            )
            for (
                from_location,
                to_location,
            ) in pair_jobs
        }

        for future in as_completed(
            future_to_pair
        ):
            (
                from_location,
                to_location,
            ) = future_to_pair[
                future
            ]

            try:
                pair_result = (
                    future.result()
                )

            except Exception as exc:
                pair_result = (
                    PairRouteResult(
                        from_index=(
                            from_location
                            .index
                        ),
                        to_index=(
                            to_location
                            .index
                        ),
                        distance_m=None,
                        eta_s=None,
                        error=str(
                            exc
                        ),
                    )
                )

            matrix_distance_m[
                pair_result.from_index
            ][
                pair_result.to_index
            ] = (
                pair_result.distance_m
            )

            matrix_eta_s[
                pair_result.from_index
            ][
                pair_result.to_index
            ] = (
                pair_result.eta_s
            )

            if (
                pair_result.error
                is None
            ):
                computed_pairs += 1

            else:
                failures.append(
                    MatrixPairFailure(
                        from_index=(
                            pair_result
                            .from_index
                        ),
                        to_index=(
                            pair_result
                            .to_index
                        ),
                        from_id=(
                            locations[
                                pair_result
                                .from_index
                            ].id
                        ),
                        to_id=(
                            locations[
                                pair_result
                                .to_index
                            ].id
                        ),
                        error=(
                            pair_result.error
                        ),
                    )
                )

    failed_pairs = len(
        failures
    )

    elapsed_ms = _elapsed_ms(
        started_at
    )

    logger.info(
        (
            "Distance matrix core complete | "
            "n=%s | "
            "pair_count=%s | "
            "computed_pairs=%s | "
            "failed_pairs=%s | "
            "algorithm=%s | "
            "workers=%s | "
            "time_ms=%s"
        ),
        location_count,
        (
            location_count
            * location_count
        ),
        computed_pairs,
        failed_pairs,
        algorithm,
        effective_workers,
        elapsed_ms,
    )

    return MatrixComputationResult(
        matrix_distance_m=(
            matrix_distance_m
        ),
        matrix_eta_s=(
            matrix_eta_s
        ),
        pair_count=(
            location_count
            * location_count
        ),
        computed_pairs=(
            computed_pairs
        ),
        failed_pairs=(
            failed_pairs
        ),
        failures=failures,
    )


def build_distance_matrix(
    *,
    locations: list[
        MatrixLocation
    ],
    graph: Any,
    snap_index: Any,
    algorithm: str = "bidirectional_astar",
    workers: int = 8,
    adjacency: GraphAdjacency | None = None,
) -> MatrixComputationResult:
    """
    Build a CityRoute distance matrix.

    Supported algorithms:

        astar
        bidirectional_astar
        source_dijkstra

    Phase 10 addition:

        adjacency

    may optionally receive an already-built GraphAdjacency.

    It is used only by source_dijkstra and allows the application to reuse
    startup graph adjacency instead of rebuilding it for every request.

    Existing callers remain backward compatible because the new argument is
    optional.
    """

    if graph is None:
        raise ValueError(
            "Cannot build distance matrix: graph is None."
        )

    if snap_index is None:
        raise ValueError(
            "Cannot build distance matrix: snap_index is None."
        )

    if not locations:
        raise ValueError(
            "Cannot build distance matrix: locations must not be empty."
        )

    normalized_algorithm = (
        algorithm
        .strip()
        .lower()
    )

    if not normalized_algorithm:
        raise ValueError(
            "Matrix algorithm must not be empty."
        )

    snapped_locations = (
        _snap_locations_once(
            locations=locations,
            graph=graph,
            snap_index=snap_index,
        )
    )

    if (
        normalized_algorithm
        == "source_dijkstra"
    ):
        return (
            _build_source_dijkstra_matrix(
                locations=locations,
                graph=graph,
                snapped_locations=(
                    snapped_locations
                ),
                adjacency=adjacency,
            )
        )

    return _build_pairwise_matrix(
        locations=locations,
        graph=graph,
        snapped_locations=(
            snapped_locations
        ),
        algorithm=(
            normalized_algorithm
        ),
        workers=workers,
    )


def _elapsed_ms(
    started_at: float,
) -> float:
    return round(
        (
            perf_counter()
            - started_at
        )
        * 1000.0,
        3,
    )


__all__ = [
    "DEFAULT_AVERAGE_SPEED_KMPH",
    "PairRouteResult",
    "SnappedMatrixLocation",
    "build_distance_matrix",
]