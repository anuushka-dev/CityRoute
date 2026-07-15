# benchmarks/phase_10/phase10_unreachable_pair_probe.py

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import networkx as nx

PHASE = "tier3_phase10"
BENCHMARK = "unreachable_pair"
ENDPOINT = "/dispatch/compare"

DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_DOCKER_BASE_URL = "http://127.0.0.1:8001"

DEFAULT_GRAPH_PATH = Path(
    "data/graphs/kanpur_central.graphml"
)

DEFAULT_ITERATIONS = 20
DEFAULT_CANDIDATE_LIMIT = 200
DEFAULT_TIMEOUT_SECONDS = 180.0


def percentile(
    values: list[float],
    percentile_value: float,
) -> float:
    if not values:
        return 0.0

    ordered = sorted(values)

    if len(ordered) == 1:
        return ordered[0]

    position = (
        percentile_value
        / 100.0
        * (len(ordered) - 1)
    )

    lower_index = math.floor(position)
    upper_index = math.ceil(position)

    if lower_index == upper_index:
        return ordered[lower_index]

    fraction = position - lower_index

    return (
        ordered[lower_index]
        * (1.0 - fraction)
        + ordered[upper_index]
        * fraction
    )


def summarize_values(
    values: list[float],
) -> dict[str, float | int]:
    if not values:
        return {
            "count": 0,
            "min": 0.0,
            "median": 0.0,
            "mean": 0.0,
            "p95": 0.0,
            "max": 0.0,
        }

    return {
        "count": len(values),
        "min": round(
            min(values),
            6,
        ),
        "median": round(
            statistics.median(values),
            6,
        ),
        "mean": round(
            statistics.fmean(values),
            6,
        ),
        "p95": round(
            percentile(
                values,
                95.0,
            ),
            6,
        ),
        "max": round(
            max(values),
            6,
        ),
    }


def node_coordinate(
    graph: nx.Graph,
    node: Any,
) -> tuple[float, float]:
    attributes = graph.nodes[node]

    raw_lon = attributes.get("x")
    raw_lat = attributes.get("y")

    if (
        raw_lat is None
        or raw_lon is None
    ):
        raise ValueError(
            f"Node {node!r} does not contain x/y coordinates."
        )

    lat = float(raw_lat)
    lon = float(raw_lon)

    if (
        not math.isfinite(lat)
        or not math.isfinite(lon)
    ):
        raise ValueError(
            f"Node {node!r} has non-finite coordinates."
        )

    if not -90.0 <= lat <= 90.0:
        raise ValueError(
            f"Node {node!r} has invalid latitude {lat}."
        )

    if not -180.0 <= lon <= 180.0:
        raise ValueError(
            f"Node {node!r} has invalid longitude {lon}."
        )

    return lat, lon


def build_payload(
    *,
    driver_lat: float,
    driver_lon: float,
    order_lat: float,
    order_lon: float,
    driver_id: str,
    order_id: str,
) -> dict[str, Any]:
    return {
        "drivers": [
            {
                "driver_id": driver_id,
                "lat": driver_lat,
                "lon": driver_lon,
                "current_load": 0,
                "max_capacity": 1,
            }
        ],
        "orders": [
            {
                "order_id": order_id,
                "pickup_lat": order_lat,
                "pickup_lon": order_lon,
            }
        ],
        "matrix_algorithm": "source_dijkstra",
        "use_cache": False,
        "load_penalty_m": 0.0,
        "slot_penalty_m": 0.0,
        "return_cost_breakdown": True,
    }


def run_request(
    *,
    client: httpx.Client,
    endpoint_url: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()

    try:
        response = client.post(
            endpoint_url,
            json=payload,
        )

        elapsed_ms = (
            (
                time.perf_counter()
                - started
            )
            * 1000.0
        )

        try:
            decoded = response.json()

        except ValueError as exc:
            return {
                "success": False,
                "status_code": response.status_code,
                "elapsed_ms": round(
                    elapsed_ms,
                    6,
                ),
                "error": (
                    "Response was not valid JSON: "
                    f"{exc}"
                ),
                "body": None,
            }

        if not isinstance(
            decoded,
            dict,
        ):
            return {
                "success": False,
                "status_code": response.status_code,
                "elapsed_ms": round(
                    elapsed_ms,
                    6,
                ),
                "error": (
                    "Response JSON is not an object."
                ),
                "body": None,
            }

        return {
            "success": (
                response.status_code
                == 200
            ),
            "status_code": response.status_code,
            "elapsed_ms": round(
                elapsed_ms,
                6,
            ),
            "error": (
                None
                if response.status_code == 200
                else response.text[:1000]
            ),
            "body": decoded,
        }

    except Exception as exc:
        elapsed_ms = (
            (
                time.perf_counter()
                - started
            )
            * 1000.0
        )

        return {
            "success": False,
            "status_code": 0,
            "elapsed_ms": round(
                elapsed_ms,
                6,
            ),
            "error": (
                f"{type(exc).__name__}: {exc}"
            ),
            "body": None,
        }


def extract_algorithm_result(
    body: dict[str, Any],
    algorithm_name: str,
) -> dict[str, Any]:
    result = body.get(
        algorithm_name
    )

    if not isinstance(
        result,
        dict,
    ):
        return {
            "assigned_count": None,
            "total_cost": None,
            "assignment_count": None,
            "assignments": None,
        }

    assignments = result.get(
        "assignments"
    )

    assignment_count = (
        len(assignments)
        if isinstance(
            assignments,
            list,
        )
        else None
    )

    return {
        "assigned_count": result.get(
            "assigned_count"
        ),
        "total_cost": result.get(
            "total_cost"
        ),
        "assignment_count": (
            assignment_count
        ),
        "assignments": assignments,
    }


def extract_road_network(
    body: dict[str, Any],
) -> dict[str, Any]:
    road_network = body.get(
        "road_network"
    )

    if not isinstance(
        road_network,
        dict,
    ):
        return {}

    return {
        "matrix_source": (
            road_network.get(
                "matrix_source"
            )
        ),
        "pair_count": (
            road_network.get(
                "pair_count"
            )
        ),
        "reachable_pair_count": (
            road_network.get(
                "reachable_pair_count"
            )
        ),
        "unreachable_pair_count": (
            road_network.get(
                "unreachable_pair_count"
            )
        ),
        "all_pairs_reachable": (
            road_network.get(
                "all_pairs_reachable"
            )
        ),
        "source_search_count": (
            road_network.get(
                "source_search_count"
            )
        ),
        "unique_driver_node_count": (
            road_network.get(
                "unique_driver_node_count"
            )
        ),
        "unique_order_node_count": (
            road_network.get(
                "unique_order_node_count"
            )
        ),
        "snap_time_ms": (
            road_network.get(
                "snap_time_ms"
            )
        ),
        "matrix_build_time_ms": (
            road_network.get(
                "matrix_build_time_ms"
            )
        ),
        "total_time_ms": (
            road_network.get(
                "total_time_ms"
            )
        ),
        "unreachable_pairs": (
            road_network.get(
                "unreachable_pairs"
            )
        ),
    }


def validate_common_response(
    body: dict[str, Any],
) -> list[str]:
    errors: list[str] = []

    if body.get("status") != "ok":
        errors.append(
            "response status is not 'ok'"
        )

    if body.get("phase") != PHASE:
        errors.append(
            "unexpected phase: "
            f"{body.get('phase')!r}"
        )

    if (
        body.get(
            "matrix_algorithm"
        )
        != "source_dijkstra"
    ):
        errors.append(
            "matrix_algorithm is not "
            "'source_dijkstra'"
        )

    if body.get("driver_count") != 1:
        errors.append(
            "driver_count is not 1"
        )

    if body.get("order_count") != 1:
        errors.append(
            "order_count is not 1"
        )

    road_network = body.get(
        "road_network"
    )

    if not isinstance(
        road_network,
        dict,
    ):
        errors.append(
            "road_network telemetry missing"
        )

    comparison = body.get(
        "comparison"
    )

    if not isinstance(
        comparison,
        dict,
    ):
        errors.append(
            "comparison section missing"
        )

    elif (
        comparison.get(
            "hungarian_non_regression"
        )
        is not True
    ):
        errors.append(
            "Hungarian non-regression failed"
        )

    return errors


def validate_unreachable_response(
    body: dict[str, Any],
) -> list[str]:
    errors = validate_common_response(
        body
    )

    road_network = body.get(
        "road_network"
    )

    if isinstance(
        road_network,
        dict,
    ):
        if (
            road_network.get(
                "pair_count"
            )
            != 1
        ):
            errors.append(
                "unreachable request pair_count is not 1"
            )

        if (
            road_network.get(
                "reachable_pair_count"
            )
            != 0
        ):
            errors.append(
                "unreachable request reachable_pair_count "
                "is not 0"
            )

        if (
            road_network.get(
                "unreachable_pair_count"
            )
            != 1
        ):
            errors.append(
                "unreachable request unreachable_pair_count "
                "is not 1"
            )

        if (
            road_network.get(
                "all_pairs_reachable"
            )
            is not False
        ):
            errors.append(
                "unreachable request all_pairs_reachable "
                "is not false"
            )

    if (
        body.get(
            "assigned_order_count"
        )
        != 0
    ):
        errors.append(
            "unreachable order was assigned"
        )

    if (
        body.get(
            "unassigned_order_count"
        )
        != 1
    ):
        errors.append(
            "unreachable request unassigned_order_count "
            "is not 1"
        )

    for algorithm_name in (
        "greedy",
        "hungarian",
    ):
        algorithm_result = body.get(
            algorithm_name
        )

        if not isinstance(
            algorithm_result,
            dict,
        ):
            errors.append(
                f"{algorithm_name} result missing"
            )

            continue

        if (
            algorithm_result.get(
                "assigned_count"
            )
            != 0
        ):
            errors.append(
                f"{algorithm_name} assigned "
                "the unreachable pair"
            )

        assignments = algorithm_result.get(
            "assignments"
        )

        if (
            isinstance(
                assignments,
                list,
            )
            and assignments
        ):
            errors.append(
                f"{algorithm_name} returned assignments "
                "for the unreachable pair"
            )

    return errors


def validate_reachable_response(
    body: dict[str, Any],
) -> list[str]:
    errors = validate_common_response(
        body
    )

    road_network = body.get(
        "road_network"
    )

    if isinstance(
        road_network,
        dict,
    ):
        if (
            road_network.get(
                "pair_count"
            )
            != 1
        ):
            errors.append(
                "reachable control pair_count is not 1"
            )

        if (
            road_network.get(
                "reachable_pair_count"
            )
            != 1
        ):
            errors.append(
                "reachable control reachable_pair_count "
                "is not 1"
            )

        if (
            road_network.get(
                "unreachable_pair_count"
            )
            != 0
        ):
            errors.append(
                "reachable control unreachable_pair_count "
                "is not 0"
            )

        if (
            road_network.get(
                "all_pairs_reachable"
            )
            is not True
        ):
            errors.append(
                "reachable control all_pairs_reachable "
                "is not true"
            )

    if (
        body.get(
            "assigned_order_count"
        )
        != 1
    ):
        errors.append(
            "reachable control order was not assigned"
        )

    if (
        body.get(
            "unassigned_order_count"
        )
        != 0
    ):
        errors.append(
            "reachable control unassigned_order_count "
            "is not 0"
        )

    for algorithm_name in (
        "greedy",
        "hungarian",
    ):
        algorithm_result = body.get(
            algorithm_name
        )

        if not isinstance(
            algorithm_result,
            dict,
        ):
            errors.append(
                f"{algorithm_name} result missing"
            )

            continue

        if (
            algorithm_result.get(
                "assigned_count"
            )
            != 1
        ):
            errors.append(
                f"{algorithm_name} did not assign "
                "the reachable control pair"
            )

        assignments = algorithm_result.get(
            "assignments"
        )

        if (
            isinstance(
                assignments,
                list,
            )
            and len(assignments) != 1
        ):
            errors.append(
                f"{algorithm_name} reachable assignment "
                "count is not 1"
            )

    return errors


def load_graph_and_cross_scc_edges(
    graph_path: Path,
) -> tuple[
    nx.Graph,
    dict[Any, int],
    list[tuple[Any, Any]],
    dict[str, Any],
]:
    if not graph_path.exists():
        raise FileNotFoundError(
            f"GraphML file does not exist: {graph_path}"
        )

    started = time.perf_counter()

    graph = nx.read_graphml(
        graph_path
    )

    load_time_ms = (
        (
            time.perf_counter()
            - started
        )
        * 1000.0
    )

    if not graph.is_directed():
        raise ValueError(
            "The Phase 10 unreachable-pair probe "
            "requires a directed graph."
        )

    scc_started = time.perf_counter()

    strongly_connected_components = list(
        nx.strongly_connected_components(
            graph
        )
    )

    scc_time_ms = (
        (
            time.perf_counter()
            - scc_started
        )
        * 1000.0
    )

    component_by_node: dict[
        Any,
        int,
    ] = {}

    for component_index, members in enumerate(
        strongly_connected_components
    ):
        for node in members:
            component_by_node[
                node
            ] = component_index

    cross_scc_edges: list[
        tuple[Any, Any]
    ] = []

    seen_pairs: set[
        tuple[Any, Any]
    ] = set()

    for source, target in graph.edges():
        if (
            component_by_node[source]
            == component_by_node[target]
        ):
            continue

        pair = (
            source,
            target,
        )

        if pair in seen_pairs:
            continue

        try:
            node_coordinate(
                graph,
                source,
            )

            node_coordinate(
                graph,
                target,
            )

        except (
            TypeError,
            ValueError,
        ):
            continue

        seen_pairs.add(
            pair
        )

        cross_scc_edges.append(
            pair
        )

    graph_metadata = {
        "graph_path": str(
            graph_path
        ),
        "node_count": (
            graph.number_of_nodes()
        ),
        "edge_count": (
            graph.number_of_edges()
        ),
        "directed": (
            graph.is_directed()
        ),
        "multigraph": (
            graph.is_multigraph()
        ),
        "graph_load_time_ms": round(
            load_time_ms,
            6,
        ),
        "strongly_connected_component_count": (
            len(
                strongly_connected_components
            )
        ),
        "largest_strongly_connected_component_nodes": (
            max(
                (
                    len(component)
                    for component
                    in strongly_connected_components
                ),
                default=0,
            )
        ),
        "scc_analysis_time_ms": round(
            scc_time_ms,
            6,
        ),
        "cross_scc_edge_candidate_count": (
            len(
                cross_scc_edges
            )
        ),
    }

    return (
        graph,
        component_by_node,
        cross_scc_edges,
        graph_metadata,
    )


def verify_candidate(
    *,
    client: httpx.Client,
    endpoint_url: str,
    graph: nx.Graph,
    component_by_node: dict[Any, int],
    edge_source: Any,
    edge_target: Any,
) -> dict[str, Any]:
    source_lat, source_lon = (
        node_coordinate(
            graph,
            edge_source,
        )
    )

    target_lat, target_lon = (
        node_coordinate(
            graph,
            edge_target,
        )
    )

    # The original graph contains:
    #
    #     edge_source -> edge_target
    #
    # and the two nodes belong to different SCCs.
    #
    # Therefore:
    #
    #     edge_source -> edge_target = reachable
    #     edge_target -> edge_source = unreachable
    #
    # Otherwise both nodes would belong to the same SCC.

    unreachable_payload = build_payload(
        driver_lat=target_lat,
        driver_lon=target_lon,
        order_lat=source_lat,
        order_lon=source_lon,
        driver_id="driver_unreachable",
        order_id="order_unreachable",
    )

    reachable_payload = build_payload(
        driver_lat=source_lat,
        driver_lon=source_lon,
        order_lat=target_lat,
        order_lon=target_lon,
        driver_id="driver_reachable",
        order_id="order_reachable",
    )

    unreachable_request = run_request(
        client=client,
        endpoint_url=endpoint_url,
        payload=unreachable_payload,
    )

    reachable_request = run_request(
        client=client,
        endpoint_url=endpoint_url,
        payload=reachable_payload,
    )

    unreachable_body = (
        unreachable_request.get(
            "body"
        )
    )

    reachable_body = (
        reachable_request.get(
            "body"
        )
    )

    unreachable_errors: list[
        str
    ] = []

    reachable_errors: list[
        str
    ] = []

    if isinstance(
        unreachable_body,
        dict,
    ):
        unreachable_errors = (
            validate_unreachable_response(
                unreachable_body
            )
        )

    else:
        unreachable_errors.append(
            "unreachable response body missing"
        )

    if isinstance(
        reachable_body,
        dict,
    ):
        reachable_errors = (
            validate_reachable_response(
                reachable_body
            )
        )

    else:
        reachable_errors.append(
            "reachable response body missing"
        )

    verified = (
        unreachable_request[
            "success"
        ]
        and reachable_request[
            "success"
        ]
        and not unreachable_errors
        and not reachable_errors
    )

    return {
        "verified": verified,
        "graph_edge": {
            "source_node": str(
                edge_source
            ),
            "target_node": str(
                edge_target
            ),
            "source_component": (
                component_by_node[
                    edge_source
                ]
            ),
            "target_component": (
                component_by_node[
                    edge_target
                ]
            ),
            "source_lat": source_lat,
            "source_lon": source_lon,
            "target_lat": target_lat,
            "target_lon": target_lon,
        },
        "expected_directionality": {
            "reachable": (
                f"{edge_source} -> "
                f"{edge_target}"
            ),
            "unreachable": (
                f"{edge_target} -> "
                f"{edge_source}"
            ),
        },
        "unreachable_probe": {
            "request": (
                unreachable_request
            ),
            "validation_errors": (
                unreachable_errors
            ),
        },
        "reachable_probe": {
            "request": (
                reachable_request
            ),
            "validation_errors": (
                reachable_errors
            ),
        },
        "payloads": {
            "unreachable": (
                unreachable_payload
            ),
            "reachable": (
                reachable_payload
            ),
        },
    }


def discover_verified_pair(
    *,
    client: httpx.Client,
    endpoint_url: str,
    graph: nx.Graph,
    component_by_node: dict[Any, int],
    candidate_edges: list[
        tuple[Any, Any]
    ],
    candidate_limit: int,
) -> tuple[
    dict[str, Any] | None,
    list[dict[str, Any]],
]:
    attempts: list[
        dict[str, Any]
    ] = []

    for attempt_index, (
        edge_source,
        edge_target,
    ) in enumerate(
        candidate_edges[
            :candidate_limit
        ],
        start=1,
    ):
        result = verify_candidate(
            client=client,
            endpoint_url=endpoint_url,
            graph=graph,
            component_by_node=(
                component_by_node
            ),
            edge_source=edge_source,
            edge_target=edge_target,
        )

        attempts.append(
            {
                "attempt": attempt_index,
                "source_node": str(
                    edge_source
                ),
                "target_node": str(
                    edge_target
                ),
                "verified": (
                    result[
                        "verified"
                    ]
                ),
                "unreachable_status_code": (
                    result[
                        "unreachable_probe"
                    ][
                        "request"
                    ][
                        "status_code"
                    ]
                ),
                "reachable_status_code": (
                    result[
                        "reachable_probe"
                    ][
                        "request"
                    ][
                        "status_code"
                    ]
                ),
                "unreachable_validation_errors": (
                    result[
                        "unreachable_probe"
                    ][
                        "validation_errors"
                    ]
                ),
                "reachable_validation_errors": (
                    result[
                        "reachable_probe"
                    ][
                        "validation_errors"
                    ]
                ),
            }
        )

        if result["verified"]:
            return result, attempts

    return None, attempts


def build_iteration_record(
    *,
    iteration: int,
    unreachable_result: dict[str, Any],
    reachable_result: dict[str, Any],
) -> dict[str, Any]:
    unreachable_body = (
        unreachable_result.get(
            "body"
        )
    )

    reachable_body = (
        reachable_result.get(
            "body"
        )
    )

    if not isinstance(
        unreachable_body,
        dict,
    ):
        unreachable_body = {}

    if not isinstance(
        reachable_body,
        dict,
    ):
        reachable_body = {}

    unreachable_errors = (
        validate_unreachable_response(
            unreachable_body
        )
        if unreachable_body
        else [
            "unreachable response body missing"
        ]
    )

    reachable_errors = (
        validate_reachable_response(
            reachable_body
        )
        if reachable_body
        else [
            "reachable response body missing"
        ]
    )

    unreachable_greedy = (
        extract_algorithm_result(
            unreachable_body,
            "greedy",
        )
    )

    unreachable_hungarian = (
        extract_algorithm_result(
            unreachable_body,
            "hungarian",
        )
    )

    reachable_greedy = (
        extract_algorithm_result(
            reachable_body,
            "greedy",
        )
    )

    reachable_hungarian = (
        extract_algorithm_result(
            reachable_body,
            "hungarian",
        )
    )

    success = (
        unreachable_result[
            "success"
        ]
        and reachable_result[
            "success"
        ]
        and not unreachable_errors
        and not reachable_errors
    )

    return {
        "phase": PHASE,
        "benchmark": BENCHMARK,
        "iteration": iteration,
        "success": success,
        "unreachable_direction": {
            "status_code": (
                unreachable_result[
                    "status_code"
                ]
            ),
            "elapsed_ms": (
                unreachable_result[
                    "elapsed_ms"
                ]
            ),
            "error": (
                unreachable_result[
                    "error"
                ]
            ),
            "validation_errors": (
                unreachable_errors
            ),
            "assigned_order_count": (
                unreachable_body.get(
                    "assigned_order_count"
                )
            ),
            "unassigned_order_count": (
                unreachable_body.get(
                    "unassigned_order_count"
                )
            ),
            "greedy": (
                unreachable_greedy
            ),
            "hungarian": (
                unreachable_hungarian
            ),
            "road_network": (
                extract_road_network(
                    unreachable_body
                )
            ),
        },
        "reachable_control": {
            "status_code": (
                reachable_result[
                    "status_code"
                ]
            ),
            "elapsed_ms": (
                reachable_result[
                    "elapsed_ms"
                ]
            ),
            "error": (
                reachable_result[
                    "error"
                ]
            ),
            "validation_errors": (
                reachable_errors
            ),
            "assigned_order_count": (
                reachable_body.get(
                    "assigned_order_count"
                )
            ),
            "unassigned_order_count": (
                reachable_body.get(
                    "unassigned_order_count"
                )
            ),
            "greedy": (
                reachable_greedy
            ),
            "hungarian": (
                reachable_hungarian
            ),
            "road_network": (
                extract_road_network(
                    reachable_body
                )
            ),
        },
        "safety": {
            "unreachable_pair_not_assigned_by_greedy": (
                unreachable_greedy[
                    "assigned_count"
                ]
                == 0
            ),
            "unreachable_pair_not_assigned_by_hungarian": (
                unreachable_hungarian[
                    "assigned_count"
                ]
                == 0
            ),
            "reachable_pair_assigned_by_greedy": (
                reachable_greedy[
                    "assigned_count"
                ]
                == 1
            ),
            "reachable_pair_assigned_by_hungarian": (
                reachable_hungarian[
                    "assigned_count"
                ]
                == 1
            ),
            "directionality_preserved": (
                unreachable_body.get(
                    "assigned_order_count"
                )
                == 0
                and reachable_body.get(
                    "assigned_order_count"
                )
                == 1
            ),
        },
    }


def preflight(
    *,
    client: httpx.Client,
    base_url: str,
) -> dict[str, Any]:
    started = time.perf_counter()

    try:
        response = client.get(
            f"{base_url}/health"
        )

        elapsed_ms = (
            (
                time.perf_counter()
                - started
            )
            * 1000.0
        )

        try:
            payload: Any = (
                response.json()
            )

        except ValueError:
            payload = response.text

        return {
            "success": (
                response.status_code
                == 200
            ),
            "status_code": (
                response.status_code
            ),
            "elapsed_ms": round(
                elapsed_ms,
                6,
            ),
            "payload": payload,
        }

    except Exception as exc:
        return {
            "success": False,
            "status_code": 0,
            "elapsed_ms": 0.0,
            "error": (
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
        }


def save_json(
    *,
    path: Path,
    payload: Any,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Probe Phase 10 handling of a real "
            "directed unreachable driver-order pair."
        )
    )

    parser.add_argument(
        "--mode",
        choices=(
            "local",
            "docker",
        ),
        default="docker",
    )

    parser.add_argument(
        "--base-url",
        default=None,
    )

    parser.add_argument(
        "--graph-path",
        type=Path,
        default=DEFAULT_GRAPH_PATH,
    )

    parser.add_argument(
        "--iterations",
        type=int,
        default=DEFAULT_ITERATIONS,
    )

    parser.add_argument(
        "--candidate-limit",
        type=int,
        default=DEFAULT_CANDIDATE_LIMIT,
    )

    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
    )

    args = parser.parse_args()

    if args.iterations < 1:
        parser.error(
            "--iterations must be >= 1"
        )

    if args.candidate_limit < 1:
        parser.error(
            "--candidate-limit must be >= 1"
        )

    if (
        not math.isfinite(
            args.timeout_seconds
        )
        or args.timeout_seconds
        <= 0.0
    ):
        parser.error(
            "--timeout-seconds must be "
            "finite and > 0"
        )

    base_url = (
        args.base_url
        or (
            DEFAULT_DOCKER_BASE_URL
            if args.mode
            == "docker"
            else DEFAULT_LOCAL_BASE_URL
        )
    ).rstrip("/")

    endpoint_url = (
        f"{base_url}"
        f"{ENDPOINT}"
    )

    timestamp = datetime.now(
        UTC
    ).strftime(
        "%Y%m%d_%H%M%S"
    )

    result_directory = (
        Path("benchmarks")
        / "phase_10"
        / f"{args.mode}_results"
    )

    raw_path = (
        result_directory
        / (
            "phase10_unreachable_pair_raw_"
            f"{args.mode}_"
            f"{timestamp}.json"
        )
    )

    summary_path = (
        result_directory
        / (
            "phase10_unreachable_pair_summary_"
            f"{args.mode}_"
            f"{timestamp}.json"
        )
    )

    print("=" * 80)
    print(
        "CityRoute Phase 10 "
        "Unreachable Directed Pair Probe"
    )
    print("=" * 80)
    print(f"mode={args.mode}")
    print(f"base_url={base_url}")
    print(f"endpoint={ENDPOINT}")
    print(
        f"graph_path={args.graph_path}"
    )
    print(
        f"iterations={args.iterations}"
    )
    print(
        "matrix_algorithm=source_dijkstra"
    )
    print("use_cache=False")
    print("=" * 80)

    try:
        (
            graph,
            component_by_node,
            candidate_edges,
            graph_metadata,
        ) = load_graph_and_cross_scc_edges(
            args.graph_path
        )

    except Exception as exc:
        print(
            "ERROR: graph analysis failed: "
            f"{type(exc).__name__}: {exc}"
        )

        return 1

    print(
        "graph_nodes="
        f"{graph_metadata['node_count']}"
    )

    print(
        "graph_edges="
        f"{graph_metadata['edge_count']}"
    )

    print(
        "strongly_connected_components="
        f"{graph_metadata['strongly_connected_component_count']}"
    )

    print(
        "cross_scc_edge_candidates="
        f"{graph_metadata['cross_scc_edge_candidate_count']}"
    )

    if not candidate_edges:
        print(
            "ERROR: no cross-SCC directed edges "
            "were found."
        )

        return 1

    timeout = httpx.Timeout(
        args.timeout_seconds
    )

    records: list[
        dict[str, Any]
    ] = []

    discovery_attempts: list[
        dict[str, Any]
    ] = []

    verified_pair: (
        dict[str, Any]
        | None
    ) = None

    with httpx.Client(
        timeout=timeout
    ) as client:
        health = preflight(
            client=client,
            base_url=base_url,
        )

        print(
            f"health_preflight={health}"
        )

        if not health.get(
            "success",
            False,
        ):
            print(
                "ERROR: health preflight failed."
            )

            return 1

        print()
        print(
            "Searching for a live API-verified "
            "directed unreachable pair..."
        )

        (
            verified_pair,
            discovery_attempts,
        ) = discover_verified_pair(
            client=client,
            endpoint_url=endpoint_url,
            graph=graph,
            component_by_node=(
                component_by_node
            ),
            candidate_edges=(
                candidate_edges
            ),
            candidate_limit=(
                args.candidate_limit
            ),
        )

        if verified_pair is None:
            print(
                "ERROR: no candidate produced the "
                "expected live API directionality "
                f"within {args.candidate_limit} attempts."
            )

            failure_payload = {
                "phase": PHASE,
                "benchmark": BENCHMARK,
                "created_at_utc": (
                    datetime.now(
                        UTC
                    ).isoformat()
                ),
                "configuration": {
                    "mode": args.mode,
                    "base_url": base_url,
                    "endpoint": ENDPOINT,
                    "graph_path": str(
                        args.graph_path
                    ),
                    "candidate_limit": (
                        args.candidate_limit
                    ),
                },
                "graph": graph_metadata,
                "health_preflight": health,
                "candidate_search_attempts": (
                    discovery_attempts
                ),
                "verified_pair_found": False,
            }

            save_json(
                path=raw_path,
                payload=failure_payload,
            )

            save_json(
                path=summary_path,
                payload=failure_payload,
            )

            return 1

        graph_edge = (
            verified_pair[
                "graph_edge"
            ]
        )

        print(
            "Verified graph boundary:"
        )

        print(
            "  graph edge reachable: "
            f"{graph_edge['source_node']} -> "
            f"{graph_edge['target_node']}"
        )

        print(
            "  reverse unreachable: "
            f"{graph_edge['target_node']} -> "
            f"{graph_edge['source_node']}"
        )

        unreachable_payload = (
            verified_pair[
                "payloads"
            ][
                "unreachable"
            ]
        )

        reachable_payload = (
            verified_pair[
                "payloads"
            ][
                "reachable"
            ]
        )

        print()
        print(
            "Running measured directionality iterations..."
        )

        for iteration in range(
            1,
            args.iterations + 1,
        ):
            # Alternate request order to reduce
            # systematic first/second request bias.
            if iteration % 2 == 1:
                unreachable_result = (
                    run_request(
                        client=client,
                        endpoint_url=(
                            endpoint_url
                        ),
                        payload=(
                            unreachable_payload
                        ),
                    )
                )

                reachable_result = (
                    run_request(
                        client=client,
                        endpoint_url=(
                            endpoint_url
                        ),
                        payload=(
                            reachable_payload
                        ),
                    )
                )

            else:
                reachable_result = (
                    run_request(
                        client=client,
                        endpoint_url=(
                            endpoint_url
                        ),
                        payload=(
                            reachable_payload
                        ),
                    )
                )

                unreachable_result = (
                    run_request(
                        client=client,
                        endpoint_url=(
                            endpoint_url
                        ),
                        payload=(
                            unreachable_payload
                        ),
                    )
                )

            record = build_iteration_record(
                iteration=iteration,
                unreachable_result=(
                    unreachable_result
                ),
                reachable_result=(
                    reachable_result
                ),
            )

            records.append(
                record
            )

            print(
                f"iteration={iteration}/"
                f"{args.iterations} "
                f"success={record['success']} "
                "unreachable_assigned="
                f"{record['unreachable_direction']['assigned_order_count']} "
                "reachable_assigned="
                f"{record['reachable_control']['assigned_order_count']} "
                "greedy_safe="
                f"{record['safety']['unreachable_pair_not_assigned_by_greedy']} "
                "hungarian_safe="
                f"{record['safety']['unreachable_pair_not_assigned_by_hungarian']}"
            )

            if not record["success"]:
                print(
                    "  unreachable_errors="
                    f"{record['unreachable_direction']['validation_errors']}"
                )

                print(
                    "  reachable_errors="
                    f"{record['reachable_control']['validation_errors']}"
                )

    successful_records = [
        record
        for record in records
        if record["success"]
    ]

    failed_records = [
        record
        for record in records
        if not record["success"]
    ]

    unreachable_times = [
        float(
            record[
                "unreachable_direction"
            ][
                "elapsed_ms"
            ]
        )
        for record in successful_records
    ]

    reachable_times = [
        float(
            record[
                "reachable_control"
            ][
                "elapsed_ms"
            ]
        )
        for record in successful_records
    ]

    greedy_safe_count = sum(
        1
        for record in records
        if (
            record[
                "safety"
            ][
                "unreachable_pair_not_assigned_by_greedy"
            ]
        )
    )

    hungarian_safe_count = sum(
        1
        for record in records
        if (
            record[
                "safety"
            ][
                "unreachable_pair_not_assigned_by_hungarian"
            ]
        )
    )

    directionality_pass_count = sum(
        1
        for record in records
        if (
            record[
                "safety"
            ][
                "directionality_preserved"
            ]
        )
    )

    raw_payload = {
        "phase": PHASE,
        "benchmark": BENCHMARK,
        "created_at_utc": (
            datetime.now(
                UTC
            ).isoformat()
        ),
        "configuration": {
            "mode": args.mode,
            "base_url": base_url,
            "endpoint": ENDPOINT,
            "graph_path": str(
                args.graph_path
            ),
            "iterations": (
                args.iterations
            ),
            "candidate_limit": (
                args.candidate_limit
            ),
            "matrix_algorithm": (
                "source_dijkstra"
            ),
            "use_cache": False,
            "timeout_seconds": (
                args.timeout_seconds
            ),
        },
        "graph": graph_metadata,
        "health_preflight": health,
        "candidate_search_attempts": (
            discovery_attempts
        ),
        "verified_pair": {
            "graph_edge": (
                verified_pair[
                    "graph_edge"
                ]
            ),
            "expected_directionality": (
                verified_pair[
                    "expected_directionality"
                ]
            ),
        },
        "records": records,
    }

    summary_payload = {
        "phase": PHASE,
        "benchmark": BENCHMARK,
        "created_at_utc": (
            datetime.now(
                UTC
            ).isoformat()
        ),
        "configuration": {
            "mode": args.mode,
            "base_url": base_url,
            "endpoint": ENDPOINT,
            "graph_path": str(
                args.graph_path
            ),
            "iterations": (
                args.iterations
            ),
            "matrix_algorithm": (
                "source_dijkstra"
            ),
            "use_cache": False,
        },
        "graph": graph_metadata,
        "verified_pair_found": True,
        "candidate_attempt_count": (
            len(
                discovery_attempts
            )
        ),
        "verified_pair": {
            "graph_edge": (
                verified_pair[
                    "graph_edge"
                ]
            ),
            "expected_directionality": (
                verified_pair[
                    "expected_directionality"
                ]
            ),
        },
        "case_count": len(
            records
        ),
        "success_count": len(
            successful_records
        ),
        "failure_count": len(
            failed_records
        ),
        "success_rate_pct": round(
            (
                len(
                    successful_records
                )
                / len(records)
                * 100.0
            )
            if records
            else 0.0,
            3,
        ),
        "greedy_forbidden_pair_safety_count": (
            greedy_safe_count
        ),
        "expected_greedy_safety_count": (
            len(records)
        ),
        "hungarian_forbidden_pair_safety_count": (
            hungarian_safe_count
        ),
        "expected_hungarian_safety_count": (
            len(records)
        ),
        "directionality_pass_count": (
            directionality_pass_count
        ),
        "expected_directionality_pass_count": (
            len(records)
        ),
        "all_greedy_forbidden_pairs_rejected": (
            greedy_safe_count
            == len(records)
        ),
        "all_hungarian_forbidden_pairs_rejected": (
            hungarian_safe_count
            == len(records)
        ),
        "all_directionality_checks_passed": (
            directionality_pass_count
            == len(records)
        ),
        "unreachable_request_elapsed_ms": (
            summarize_values(
                unreachable_times
            )
        ),
        "reachable_control_elapsed_ms": (
            summarize_values(
                reachable_times
            )
        ),
        "failed_cases": [
            {
                "iteration": (
                    record[
                        "iteration"
                    ]
                ),
                "unreachable_validation_errors": (
                    record[
                        "unreachable_direction"
                    ][
                        "validation_errors"
                    ]
                ),
                "reachable_validation_errors": (
                    record[
                        "reachable_control"
                    ][
                        "validation_errors"
                    ]
                ),
            }
            for record in failed_records
        ],
        "interpretation_note": (
            "The probe identifies a real directed edge whose endpoints "
            "belong to different strongly connected components. The "
            "edge direction is therefore reachable while the reverse "
            "direction is unreachable. The live source_dijkstra API "
            "must reject the unreachable driver-order pair for both "
            "Greedy and Hungarian assignment while successfully "
            "assigning the reachable reverse control."
        ),
    }

    save_json(
        path=raw_path,
        payload=raw_payload,
    )

    save_json(
        path=summary_path,
        payload=summary_payload,
    )

    print()
    print("=" * 80)
    print("FINAL SUMMARY")
    print("=" * 80)

    print(
        json.dumps(
            summary_payload,
            indent=2,
        )
    )

    print()
    print(
        f"raw_output={raw_path}"
    )

    print(
        f"summary_output={summary_path}"
    )

    return (
        0
        if not failed_records
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )