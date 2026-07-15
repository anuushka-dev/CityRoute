# benchmarks/phase_10/phase10_correctness_probe.py

from __future__ import annotations

import argparse
import itertools
import json
import math
import statistics
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import networkx as nx

PHASE = "tier3_phase10"
BENCHMARK = "correctness"
ENDPOINT = "/dispatch/compare"

DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_DOCKER_BASE_URL = "http://127.0.0.1:8001"

DEFAULT_GRAPH_PATH = Path(
    "data/graphs/kanpur_central.graphml"
)

DEFAULT_SIZES = (2, 3, 4, 5, 6)
DEFAULT_SCENARIOS = 3
DEFAULT_TIMEOUT_SECONDS = 180.0
DEFAULT_PAIR_TOLERANCE_M = 0.01
DEFAULT_MAX_BRUTEFORCE_SIZE = 8


def parse_sizes(
    raw_value: str,
) -> tuple[int, ...]:
    sizes: list[int] = []

    for item in raw_value.split(","):
        stripped = item.strip()

        if not stripped:
            continue

        size = int(stripped)

        if size < 1:
            raise argparse.ArgumentTypeError(
                "Every correctness size must be >= 1."
            )

        sizes.append(size)

    if not sizes:
        raise argparse.ArgumentTypeError(
            "At least one correctness size is required."
        )

    return tuple(sizes)


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

    lower_index = math.floor(
        position
    )

    upper_index = math.ceil(
        position
    )

    if lower_index == upper_index:
        return ordered[
            lower_index
        ]

    fraction = (
        position
        - lower_index
    )

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
            statistics.median(
                values
            ),
            6,
        ),
        "mean": round(
            statistics.fmean(
                values
            ),
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


def finite_nonnegative_float(
    value: Any,
) -> float | None:
    try:
        number = float(
            value
        )

    except (
        TypeError,
        ValueError,
    ):
        return None

    if (
        not math.isfinite(number)
        or number < 0.0
    ):
        return None

    return number


def node_coordinate(
    graph: nx.Graph,
    node: Any,
) -> tuple[float, float]:
    attributes = graph.nodes[
        node
    ]

    raw_lon = attributes.get(
        "x"
    )

    raw_lat = attributes.get(
        "y"
    )

    if (
        raw_lat is None
        or raw_lon is None
    ):
        raise ValueError(
            f"Node {node!r} does not contain x/y coordinates."
        )

    lat = float(
        raw_lat
    )

    lon = float(
        raw_lon
    )

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

    return (
        lat,
        lon,
    )


def load_oracle_graph(
    graph_path: Path,
) -> tuple[
    nx.Graph,
    nx.DiGraph,
    list[Any],
    dict[str, Any],
]:
    if not graph_path.exists():
        raise FileNotFoundError(
            f"GraphML file does not exist: {graph_path}"
        )

    load_started = (
        time.perf_counter()
    )

    raw_graph = nx.read_graphml(
        graph_path
    )

    graph_load_time_ms = (
        (
            time.perf_counter()
            - load_started
        )
        * 1000.0
    )

    if not raw_graph.is_directed():
        raise ValueError(
            "The Phase 10 correctness probe requires "
            "a directed road graph."
        )

    normalize_started = (
        time.perf_counter()
    )

    oracle_graph = nx.DiGraph()

    for node, attributes in (
        raw_graph.nodes(
            data=True
        )
    ):
        oracle_graph.add_node(
            node,
            **attributes,
        )

    skipped_edge_count = 0

    for (
        source,
        target,
        attributes,
    ) in raw_graph.edges(
        data=True
    ):
        length_m = (
            finite_nonnegative_float(
                attributes.get(
                    "length"
                )
            )
        )

        if length_m is None:
            skipped_edge_count += 1
            continue

        if oracle_graph.has_edge(
            source,
            target,
        ):
            existing_length = float(
                oracle_graph[
                    source
                ][
                    target
                ][
                    "length"
                ]
            )

            if (
                length_m
                < existing_length
            ):
                oracle_graph[
                    source
                ][
                    target
                ][
                    "length"
                ] = length_m

        else:
            oracle_graph.add_edge(
                source,
                target,
                length=length_m,
            )

    normalization_time_ms = (
        (
            time.perf_counter()
            - normalize_started
        )
        * 1000.0
    )

    scc_started = (
        time.perf_counter()
    )

    components = list(
        nx.strongly_connected_components(
            oracle_graph
        )
    )

    scc_time_ms = (
        (
            time.perf_counter()
            - scc_started
        )
        * 1000.0
    )

    if not components:
        raise ValueError(
            "The graph does not contain any strongly "
            "connected components."
        )

    largest_component = max(
        components,
        key=len,
    )

    coordinate_counts: Counter[
        tuple[float, float]
    ] = Counter()

    coordinate_by_node: dict[
        Any,
        tuple[float, float],
    ] = {}

    for node in largest_component:
        try:
            coordinate = (
                node_coordinate(
                    raw_graph,
                    node,
                )
            )

        except (
            TypeError,
            ValueError,
        ):
            continue

        normalized_coordinate = (
            round(
                coordinate[0],
                12,
            ),
            round(
                coordinate[1],
                12,
            ),
        )

        coordinate_by_node[
            node
        ] = coordinate

        coordinate_counts[
            normalized_coordinate
        ] += 1

    candidate_nodes = [
        node
        for node, coordinate
        in coordinate_by_node.items()
        if (
            coordinate_counts[
                (
                    round(
                        coordinate[0],
                        12,
                    ),
                    round(
                        coordinate[1],
                        12,
                    ),
                )
            ]
            == 1
        )
    ]

    candidate_nodes.sort(
        key=str
    )

    if not candidate_nodes:
        raise ValueError(
            "No uniquely positioned nodes were found "
            "inside the largest strongly connected component."
        )

    metadata = {
        "graph_path": str(
            graph_path
        ),
        "raw_node_count": (
            raw_graph.number_of_nodes()
        ),
        "raw_edge_count": (
            raw_graph.number_of_edges()
        ),
        "raw_directed": (
            raw_graph.is_directed()
        ),
        "raw_multigraph": (
            raw_graph.is_multigraph()
        ),
        "oracle_node_count": (
            oracle_graph.number_of_nodes()
        ),
        "oracle_edge_count": (
            oracle_graph.number_of_edges()
        ),
        "skipped_invalid_edge_count": (
            skipped_edge_count
        ),
        "strongly_connected_component_count": (
            len(components)
        ),
        "largest_strongly_connected_component_nodes": (
            len(
                largest_component
            )
        ),
        "unique_coordinate_candidate_count": (
            len(
                candidate_nodes
            )
        ),
        "graph_load_time_ms": round(
            graph_load_time_ms,
            6,
        ),
        "normalization_time_ms": round(
            normalization_time_ms,
            6,
        ),
        "scc_analysis_time_ms": round(
            scc_time_ms,
            6,
        ),
    }

    return (
        raw_graph,
        oracle_graph,
        candidate_nodes,
        metadata,
    )


def select_scenario_nodes(
    *,
    candidate_nodes: list[Any],
    size: int,
    scenario_index: int,
) -> tuple[
    list[Any],
    list[Any],
]:
    required = (
        size
        * 2
    )

    if len(
        candidate_nodes
    ) < required:
        raise ValueError(
            "Not enough candidate nodes to create "
            f"a {size}x{size} scenario."
        )

    candidate_count = len(
        candidate_nodes
    )

    start = (
        scenario_index
        * 997
        + size
        * 101
    ) % candidate_count

    stride = 97

    selected: list[Any] = []
    seen: set[Any] = set()

    cursor = start

    while (
        len(selected)
        < required
    ):
        node = candidate_nodes[
            cursor
        ]

        if node not in seen:
            seen.add(
                node
            )

            selected.append(
                node
            )

        cursor = (
            cursor
            + stride
        ) % candidate_count

        if (
            len(seen)
            == candidate_count
            and len(selected)
            < required
        ):
            raise ValueError(
                "Could not select enough unique scenario nodes."
            )

    driver_nodes = selected[
        :size
    ]

    order_nodes = selected[
        size:
    ]

    return (
        driver_nodes,
        order_nodes,
    )


def build_oracle_matrix(
    *,
    graph: nx.DiGraph,
    driver_nodes: list[Any],
    order_nodes: list[Any],
) -> tuple[
    list[list[float]],
    float,
]:
    started = (
        time.perf_counter()
    )

    matrix: list[
        list[float]
    ] = []

    for source in driver_nodes:
        distances = (
            nx.single_source_dijkstra_path_length(
                graph,
                source,
                weight="length",
            )
        )

        row: list[
            float
        ] = []

        for target in order_nodes:
            if target not in distances:
                raise ValueError(
                    "A supposedly strongly connected correctness "
                    f"pair is unreachable: {source!r} -> {target!r}"
                )

            row.append(
                float(
                    distances[
                        target
                    ]
                )
            )

        matrix.append(
            row
        )

    elapsed_ms = (
        (
            time.perf_counter()
            - started
        )
        * 1000.0
    )

    return (
        matrix,
        elapsed_ms,
    )


def brute_force_assignment(
    matrix: list[
        list[float]
    ],
) -> dict[str, Any]:
    size = len(
        matrix
    )

    if size == 0:
        raise ValueError(
            "Assignment matrix cannot be empty."
        )

    started = (
        time.perf_counter()
    )

    best_total = math.inf

    best_permutation: (
        tuple[int, ...]
        | None
    ) = None

    optimal_solution_count = 0

    for permutation in itertools.permutations(
        range(size)
    ):
        total = sum(
            matrix[
                driver_index
            ][
                order_index
            ]
            for (
                driver_index,
                order_index,
            ) in enumerate(
                permutation
            )
        )

        if (
            total
            < best_total
            - 1e-9
        ):
            best_total = total

            best_permutation = (
                permutation
            )

            optimal_solution_count = 1

        elif math.isclose(
            total,
            best_total,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            optimal_solution_count += 1

    elapsed_ms = (
        (
            time.perf_counter()
            - started
        )
        * 1000.0
    )

    if best_permutation is None:
        raise RuntimeError(
            "Brute-force assignment did not find a solution."
        )

    return {
        "total_cost": (
            best_total
        ),
        "permutation": list(
            best_permutation
        ),
        "optimal_solution_count": (
            optimal_solution_count
        ),
        "elapsed_ms": round(
            elapsed_ms,
            6,
        ),
    }


def build_single_pair_payload(
    *,
    driver_id: str,
    driver_lat: float,
    driver_lon: float,
    order_id: str,
    order_lat: float,
    order_lon: float,
) -> dict[str, Any]:
    return {
        "drivers": [
            {
                "driver_id": (
                    driver_id
                ),
                "lat": (
                    driver_lat
                ),
                "lon": (
                    driver_lon
                ),
                "current_load": 0,
                "max_capacity": 1,
            }
        ],
        "orders": [
            {
                "order_id": (
                    order_id
                ),
                "pickup_lat": (
                    order_lat
                ),
                "pickup_lon": (
                    order_lon
                ),
            }
        ],
        "matrix_algorithm": (
            "source_dijkstra"
        ),
        "use_cache": False,
        "load_penalty_m": 0.0,
        "slot_penalty_m": 0.0,
        "return_cost_breakdown": False,
    }


def build_batch_payload(
    *,
    raw_graph: nx.Graph,
    driver_nodes: list[Any],
    order_nodes: list[Any],
    scenario_label: str,
) -> tuple[
    dict[str, Any],
    list[str],
    list[str],
]:
    drivers: list[
        dict[str, Any]
    ] = []

    orders: list[
        dict[str, Any]
    ] = []

    driver_ids: list[
        str
    ] = []

    order_ids: list[
        str
    ] = []

    for index, node in enumerate(
        driver_nodes
    ):
        lat, lon = (
            node_coordinate(
                raw_graph,
                node,
            )
        )

        driver_id = (
            f"{scenario_label}_driver_"
            f"{index}"
        )

        driver_ids.append(
            driver_id
        )

        drivers.append(
            {
                "driver_id": (
                    driver_id
                ),
                "lat": lat,
                "lon": lon,
                "current_load": 0,
                "max_capacity": 1,
            }
        )

    for index, node in enumerate(
        order_nodes
    ):
        lat, lon = (
            node_coordinate(
                raw_graph,
                node,
            )
        )

        order_id = (
            f"{scenario_label}_order_"
            f"{index}"
        )

        order_ids.append(
            order_id
        )

        orders.append(
            {
                "order_id": (
                    order_id
                ),
                "pickup_lat": (
                    lat
                ),
                "pickup_lon": (
                    lon
                ),
            }
        )

    payload = {
        "drivers": drivers,
        "orders": orders,
        "matrix_algorithm": (
            "source_dijkstra"
        ),
        "use_cache": False,
        "load_penalty_m": 0.0,
        "slot_penalty_m": 0.0,
        "return_cost_breakdown": False,
    }

    return (
        payload,
        driver_ids,
        order_ids,
    )


def run_request(
    *,
    client: httpx.Client,
    endpoint_url: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    started = (
        time.perf_counter()
    )

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
            decoded = (
                response.json()
            )

        except ValueError as exc:
            return {
                "success": False,
                "status_code": (
                    response.status_code
                ),
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
                "status_code": (
                    response.status_code
                ),
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
            "status_code": (
                response.status_code
            ),
            "elapsed_ms": round(
                elapsed_ms,
                6,
            ),
            "error": (
                None
                if response.status_code
                == 200
                else response.text[
                    :1000
                ]
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
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
            "body": None,
        }


def validate_common_response(
    *,
    body: dict[str, Any],
    driver_count: int,
    order_count: int,
) -> list[str]:
    errors: list[str] = []

    if body.get(
        "status"
    ) != "ok":
        errors.append(
            "response status is not 'ok'"
        )

    if body.get(
        "phase"
    ) != PHASE:
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

    if (
        body.get(
            "driver_count"
        )
        != driver_count
    ):
        errors.append(
            "driver_count mismatch"
        )

    if (
        body.get(
            "order_count"
        )
        != order_count
    ):
        errors.append(
            "order_count mismatch"
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

    else:
        expected_pair_count = (
            driver_count
            * order_count
        )

        if (
            road_network.get(
                "pair_count"
            )
            != expected_pair_count
        ):
            errors.append(
                "road-network pair_count mismatch"
            )

        if (
            road_network.get(
                "reachable_pair_count"
            )
            != expected_pair_count
        ):
            errors.append(
                "reachable_pair_count mismatch"
            )

        if (
            road_network.get(
                "unreachable_pair_count"
            )
            != 0
        ):
            errors.append(
                "unexpected unreachable pairs"
            )

        if (
            road_network.get(
                "all_pairs_reachable"
            )
            is not True
        ):
            errors.append(
                "all_pairs_reachable is not true"
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


def extract_single_pair_cost(
    body: dict[str, Any],
) -> tuple[
    float | None,
    list[str],
]:
    errors = (
        validate_common_response(
            body=body,
            driver_count=1,
            order_count=1,
        )
    )

    hungarian = body.get(
        "hungarian"
    )

    if not isinstance(
        hungarian,
        dict,
    ):
        errors.append(
            "Hungarian result missing"
        )

        return (
            None,
            errors,
        )

    if (
        hungarian.get(
            "assigned_count"
        )
        != 1
    ):
        errors.append(
            "single-pair Hungarian assigned_count is not 1"
        )

    assignments = (
        hungarian.get(
            "assignments"
        )
    )

    if (
        not isinstance(
            assignments,
            list,
        )
        or len(
            assignments
        )
        != 1
    ):
        errors.append(
            "single-pair Hungarian assignment count is not 1"
        )

        return (
            None,
            errors,
        )

    assignment = assignments[
        0
    ]

    if not isinstance(
        assignment,
        dict,
    ):
        errors.append(
            "single-pair assignment is not an object"
        )

        return (
            None,
            errors,
        )

    raw_cost = assignment.get(
        "cost"
    )

    cost = (
        finite_nonnegative_float(
            raw_cost
        )
    )

    if cost is None:
        errors.append(
            "single-pair assignment cost is invalid"
        )

        return (
            None,
            errors,
        )

    total_cost = (
        finite_nonnegative_float(
            hungarian.get(
                "total_cost"
            )
        )
    )

    if total_cost is None:
        errors.append(
            "single-pair Hungarian total_cost is invalid"
        )

    elif not math.isclose(
        cost,
        total_cost,
        rel_tol=0.0,
        abs_tol=0.001,
    ):
        errors.append(
            "single-pair assignment cost does not "
            "match Hungarian total_cost"
        )

    return (
        cost,
        errors,
    )


def probe_matrix_cells(
    *,
    client: httpx.Client,
    endpoint_url: str,
    raw_graph: nx.Graph,
    driver_nodes: list[Any],
    order_nodes: list[Any],
    oracle_matrix: list[
        list[float]
    ],
    scenario_label: str,
    pair_tolerance_m: float,
) -> dict[str, Any]:
    api_matrix: list[
        list[
            float | None
        ]
    ] = []

    cell_records: list[
        dict[str, Any]
    ] = []

    mismatch_count = 0

    max_abs_error_m = 0.0

    for driver_index, driver_node in enumerate(
        driver_nodes
    ):
        driver_lat, driver_lon = (
            node_coordinate(
                raw_graph,
                driver_node,
            )
        )

        row: list[
            float | None
        ] = []

        for order_index, order_node in enumerate(
            order_nodes
        ):
            order_lat, order_lon = (
                node_coordinate(
                    raw_graph,
                    order_node,
                )
            )

            payload = (
                build_single_pair_payload(
                    driver_id=(
                        f"{scenario_label}_driver_"
                        f"{driver_index}"
                    ),
                    driver_lat=(
                        driver_lat
                    ),
                    driver_lon=(
                        driver_lon
                    ),
                    order_id=(
                        f"{scenario_label}_order_"
                        f"{order_index}"
                    ),
                    order_lat=(
                        order_lat
                    ),
                    order_lon=(
                        order_lon
                    ),
                )
            )

            request_result = (
                run_request(
                    client=client,
                    endpoint_url=(
                        endpoint_url
                    ),
                    payload=payload,
                )
            )

            body = (
                request_result.get(
                    "body"
                )
            )

            api_cost: (
                float
                | None
            ) = None

            validation_errors: list[
                str
            ] = []

            if isinstance(
                body,
                dict,
            ):
                (
                    api_cost,
                    validation_errors,
                ) = (
                    extract_single_pair_cost(
                        body
                    )
                )

            else:
                validation_errors.append(
                    "response body missing"
                )

            oracle_cost = float(
                oracle_matrix[
                    driver_index
                ][
                    order_index
                ]
            )

            abs_error_m: (
                float
                | None
            ) = None

            cost_match = False

            if api_cost is not None:
                abs_error_m = abs(
                    api_cost
                    - oracle_cost
                )

                max_abs_error_m = max(
                    max_abs_error_m,
                    abs_error_m,
                )

                cost_match = (
                    abs_error_m
                    <= pair_tolerance_m
                )

            cell_success = (
                request_result[
                    "success"
                ]
                and not validation_errors
                and cost_match
            )

            if not cell_success:
                mismatch_count += 1

            row.append(
                api_cost
            )

            cell_records.append(
                {
                    "driver_index": (
                        driver_index
                    ),
                    "order_index": (
                        order_index
                    ),
                    "driver_node": str(
                        driver_node
                    ),
                    "order_node": str(
                        order_node
                    ),
                    "status_code": (
                        request_result[
                            "status_code"
                        ]
                    ),
                    "elapsed_ms": (
                        request_result[
                            "elapsed_ms"
                        ]
                    ),
                    "request_success": (
                        request_result[
                            "success"
                        ]
                    ),
                    "oracle_cost_m": round(
                        oracle_cost,
                        9,
                    ),
                    "api_cost_m": (
                        round(
                            api_cost,
                            9,
                        )
                        if api_cost
                        is not None
                        else None
                    ),
                    "abs_error_m": (
                        round(
                            abs_error_m,
                            9,
                        )
                        if abs_error_m
                        is not None
                        else None
                    ),
                    "cost_match": (
                        cost_match
                    ),
                    "validation_errors": (
                        validation_errors
                    ),
                    "success": (
                        cell_success
                    ),
                }
            )

        api_matrix.append(
            row
        )

    return {
        "success": (
            mismatch_count
            == 0
        ),
        "cell_count": (
            len(
                cell_records
            )
        ),
        "success_count": sum(
            1
            for record
            in cell_records
            if record[
                "success"
            ]
        ),
        "mismatch_count": (
            mismatch_count
        ),
        "max_abs_error_m": round(
            max_abs_error_m,
            9,
        ),
        "api_matrix_m": (
            api_matrix
        ),
        "records": (
            cell_records
        ),
    }


def validate_assignment_result(
    *,
    body: dict[str, Any],
    algorithm_name: str,
    driver_ids: list[str],
    order_ids: list[str],
    oracle_matrix: list[
        list[float]
    ],
    pair_tolerance_m: float,
) -> dict[str, Any]:
    errors: list[
        str
    ] = []

    result = body.get(
        algorithm_name
    )

    if not isinstance(
        result,
        dict,
    ):
        return {
            "success": False,
            "validation_errors": [
                f"{algorithm_name} result missing"
            ],
        }

    assignments = result.get(
        "assignments"
    )

    if not isinstance(
        assignments,
        list,
    ):
        return {
            "success": False,
            "validation_errors": [
                f"{algorithm_name} assignments missing"
            ],
        }

    expected_count = min(
        len(
            driver_ids
        ),
        len(
            order_ids
        ),
    )

    if (
        result.get(
            "assigned_count"
        )
        != expected_count
    ):
        errors.append(
            f"{algorithm_name} assigned_count mismatch"
        )

    if (
        len(
            assignments
        )
        != expected_count
    ):
        errors.append(
            f"{algorithm_name} assignment list size mismatch"
        )

    driver_index_by_id = {
        driver_id: index
        for index, driver_id
        in enumerate(
            driver_ids
        )
    }

    order_index_by_id = {
        order_id: index
        for index, order_id
        in enumerate(
            order_ids
        )
    }

    seen_drivers: set[
        str
    ] = set()

    seen_orders: set[
        str
    ] = set()

    assignment_records: list[
        dict[str, Any]
    ] = []

    oracle_assignment_total = 0.0
    api_assignment_total = 0.0

    for assignment in assignments:
        if not isinstance(
            assignment,
            dict,
        ):
            errors.append(
                f"{algorithm_name} contains a non-object assignment"
            )

            continue

        driver_id = assignment.get(
            "driver_id"
        )

        order_id = assignment.get(
            "order_id"
        )

        if not isinstance(
            driver_id,
            str,
        ):
            errors.append(
                f"{algorithm_name} assignment has invalid driver_id"
            )

            continue

        if not isinstance(
            order_id,
            str,
        ):
            errors.append(
                f"{algorithm_name} assignment has invalid order_id"
            )

            continue

        if driver_id not in (
            driver_index_by_id
        ):
            errors.append(
                f"{algorithm_name} returned unknown driver_id "
                f"{driver_id!r}"
            )

            continue

        if order_id not in (
            order_index_by_id
        ):
            errors.append(
                f"{algorithm_name} returned unknown order_id "
                f"{order_id!r}"
            )

            continue

        if driver_id in (
            seen_drivers
        ):
            errors.append(
                f"{algorithm_name} assigned driver "
                f"{driver_id!r} more than once"
            )

        if order_id in (
            seen_orders
        ):
            errors.append(
                f"{algorithm_name} assigned order "
                f"{order_id!r} more than once"
            )

        seen_drivers.add(
            driver_id
        )

        seen_orders.add(
            order_id
        )

        driver_index = (
            driver_index_by_id[
                driver_id
            ]
        )

        order_index = (
            order_index_by_id[
                order_id
            ]
        )

        oracle_cost = float(
            oracle_matrix[
                driver_index
            ][
                order_index
            ]
        )

        api_cost = (
            finite_nonnegative_float(
                assignment.get(
                    "cost"
                )
            )
        )

        if api_cost is None:
            errors.append(
                f"{algorithm_name} assignment has invalid cost"
            )

            continue

        abs_error_m = abs(
            api_cost
            - oracle_cost
        )

        if (
            abs_error_m
            > pair_tolerance_m
        ):
            errors.append(
                f"{algorithm_name} assignment cost mismatch "
                f"for {driver_id!r} -> {order_id!r}: "
                f"api={api_cost}, oracle={oracle_cost}"
            )

        oracle_assignment_total += (
            oracle_cost
        )

        api_assignment_total += (
            api_cost
        )

        assignment_records.append(
            {
                "driver_id": (
                    driver_id
                ),
                "order_id": (
                    order_id
                ),
                "driver_index": (
                    driver_index
                ),
                "order_index": (
                    order_index
                ),
                "api_cost_m": (
                    api_cost
                ),
                "oracle_cost_m": (
                    oracle_cost
                ),
                "abs_error_m": (
                    abs_error_m
                ),
            }
        )

    reported_total = (
        finite_nonnegative_float(
            result.get(
                "total_cost"
            )
        )
    )

    total_tolerance_m = (
        pair_tolerance_m
        * max(
            expected_count,
            1,
        )
    )

    if reported_total is None:
        errors.append(
            f"{algorithm_name} total_cost is invalid"
        )

    elif (
        abs(
            reported_total
            - oracle_assignment_total
        )
        > total_tolerance_m
    ):
        errors.append(
            f"{algorithm_name} total_cost does not match "
            "the independent oracle cost of its assignments"
        )

    return {
        "success": (
            not errors
        ),
        "reported_total_cost_m": (
            reported_total
        ),
        "api_assignment_cost_sum_m": (
            api_assignment_total
        ),
        "oracle_assignment_cost_sum_m": (
            oracle_assignment_total
        ),
        "assignment_count": (
            len(
                assignments
            )
        ),
        "unique_driver_count": (
            len(
                seen_drivers
            )
        ),
        "unique_order_count": (
            len(
                seen_orders
            )
        ),
        "assignments": (
            assignment_records
        ),
        "validation_errors": (
            errors
        ),
    }


def run_batch_correctness(
    *,
    client: httpx.Client,
    endpoint_url: str,
    raw_graph: nx.Graph,
    driver_nodes: list[Any],
    order_nodes: list[Any],
    oracle_matrix: list[
        list[float]
    ],
    brute_force_result: dict[
        str,
        Any
    ],
    scenario_label: str,
    pair_tolerance_m: float,
) -> dict[str, Any]:
    (
        payload,
        driver_ids,
        order_ids,
    ) = build_batch_payload(
        raw_graph=raw_graph,
        driver_nodes=driver_nodes,
        order_nodes=order_nodes,
        scenario_label=(
            scenario_label
        ),
    )

    request_result = (
        run_request(
            client=client,
            endpoint_url=(
                endpoint_url
            ),
            payload=payload,
        )
    )

    body = (
        request_result.get(
            "body"
        )
    )

    common_errors: list[
        str
    ] = []

    if isinstance(
        body,
        dict,
    ):
        common_errors = (
            validate_common_response(
                body=body,
                driver_count=len(
                    driver_nodes
                ),
                order_count=len(
                    order_nodes
                ),
            )
        )

    else:
        common_errors.append(
            "response body missing"
        )

        body = {}

    greedy_validation = (
        validate_assignment_result(
            body=body,
            algorithm_name="greedy",
            driver_ids=driver_ids,
            order_ids=order_ids,
            oracle_matrix=(
                oracle_matrix
            ),
            pair_tolerance_m=(
                pair_tolerance_m
            ),
        )
    )

    hungarian_validation = (
        validate_assignment_result(
            body=body,
            algorithm_name=(
                "hungarian"
            ),
            driver_ids=driver_ids,
            order_ids=order_ids,
            oracle_matrix=(
                oracle_matrix
            ),
            pair_tolerance_m=(
                pair_tolerance_m
            ),
        )
    )

    oracle_optimal_cost = float(
        brute_force_result[
            "total_cost"
        ]
    )

    api_hungarian_total = (
        hungarian_validation.get(
            "reported_total_cost_m"
        )
    )

    total_tolerance_m = (
        pair_tolerance_m
        * max(
            len(
                driver_nodes
            ),
            1,
        )
    )

    optimality_gap_m: (
        float
        | None
    ) = None

    hungarian_matches_oracle_optimum = (
        False
    )

    if isinstance(
        api_hungarian_total,
        (
            int,
            float,
        ),
    ):
        optimality_gap_m = (
            float(
                api_hungarian_total
            )
            - oracle_optimal_cost
        )

        hungarian_matches_oracle_optimum = (
            abs(
                optimality_gap_m
            )
            <= total_tolerance_m
        )

    if (
        not hungarian_matches_oracle_optimum
    ):
        common_errors.append(
            "API Hungarian total cost does not match "
            "the independent brute-force optimum"
        )

    greedy_total = (
        greedy_validation.get(
            "reported_total_cost_m"
        )
    )

    api_non_regression = False

    if (
        isinstance(
            greedy_total,
            (
                int,
                float,
            ),
        )
        and isinstance(
            api_hungarian_total,
            (
                int,
                float,
            ),
        )
    ):
        api_non_regression = (
            float(
                api_hungarian_total
            )
            <= float(
                greedy_total
            )
            + total_tolerance_m
        )

    if not api_non_regression:
        common_errors.append(
            "Hungarian cost exceeds Greedy cost"
        )

    success = (
        request_result[
            "success"
        ]
        and not common_errors
        and greedy_validation[
            "success"
        ]
        and hungarian_validation[
            "success"
        ]
        and hungarian_matches_oracle_optimum
        and api_non_regression
    )

    return {
        "success": success,
        "status_code": (
            request_result[
                "status_code"
            ]
        ),
        "elapsed_ms": (
            request_result[
                "elapsed_ms"
            ]
        ),
        "request_error": (
            request_result[
                "error"
            ]
        ),
        "common_validation_errors": (
            common_errors
        ),
        "greedy": (
            greedy_validation
        ),
        "hungarian": (
            hungarian_validation
        ),
        "oracle_optimum": {
            "total_cost_m": (
                oracle_optimal_cost
            ),
            "permutation": (
                brute_force_result[
                    "permutation"
                ]
            ),
            "optimal_solution_count": (
                brute_force_result[
                    "optimal_solution_count"
                ]
            ),
            "bruteforce_time_ms": (
                brute_force_result[
                    "elapsed_ms"
                ]
            ),
        },
        "comparison": {
            "api_hungarian_total_cost_m": (
                api_hungarian_total
            ),
            "oracle_optimal_cost_m": (
                oracle_optimal_cost
            ),
            "optimality_gap_m": (
                optimality_gap_m
            ),
            "hungarian_matches_oracle_optimum": (
                hungarian_matches_oracle_optimum
            ),
            "hungarian_non_regression": (
                api_non_regression
            ),
        },
    }


def preflight(
    *,
    client: httpx.Client,
    base_url: str,
    graph_metadata: dict[
        str,
        Any
    ],
) -> dict[str, Any]:
    health_started = (
        time.perf_counter()
    )

    try:
        health_response = (
            client.get(
                f"{base_url}/health"
            )
        )

        health_elapsed_ms = (
            (
                time.perf_counter()
                - health_started
            )
            * 1000.0
        )

        health_payload: Any

        try:
            health_payload = (
                health_response.json()
            )

        except ValueError:
            health_payload = (
                health_response.text
            )

        stats_started = (
            time.perf_counter()
        )

        stats_response = (
            client.get(
                f"{base_url}/graph/stats"
            )
        )

        stats_elapsed_ms = (
            (
                time.perf_counter()
                - stats_started
            )
            * 1000.0
        )

        stats_payload: Any

        try:
            stats_payload = (
                stats_response.json()
            )

        except ValueError:
            stats_payload = (
                stats_response.text
            )

        graph_consistent = False

        if isinstance(
            stats_payload,
            dict,
        ):
            graph_consistent = (
                stats_payload.get(
                    "nodes"
                )
                == graph_metadata[
                    "raw_node_count"
                ]
                and stats_payload.get(
                    "edges"
                )
                == graph_metadata[
                    "raw_edge_count"
                ]
            )

        return {
            "success": (
                health_response.status_code
                == 200
                and stats_response.status_code
                == 200
                and graph_consistent
            ),
            "health": {
                "status_code": (
                    health_response.status_code
                ),
                "elapsed_ms": round(
                    health_elapsed_ms,
                    6,
                ),
                "payload": (
                    health_payload
                ),
            },
            "graph_stats": {
                "status_code": (
                    stats_response.status_code
                ),
                "elapsed_ms": round(
                    stats_elapsed_ms,
                    6,
                ),
                "payload": (
                    stats_payload
                ),
            },
            "graph_consistent": (
                graph_consistent
            ),
        }

    except Exception as exc:
        return {
            "success": False,
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
            "Validate Phase 10 road-dispatch costs and Hungarian "
            "optimality against independent graph and brute-force oracles."
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
        "--sizes",
        type=parse_sizes,
        default=DEFAULT_SIZES,
    )

    parser.add_argument(
        "--scenarios",
        type=int,
        default=DEFAULT_SCENARIOS,
    )

    parser.add_argument(
        "--pair-tolerance-m",
        type=float,
        default=(
            DEFAULT_PAIR_TOLERANCE_M
        ),
    )

    parser.add_argument(
        "--max-bruteforce-size",
        type=int,
        default=(
            DEFAULT_MAX_BRUTEFORCE_SIZE
        ),
    )

    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=(
            DEFAULT_TIMEOUT_SECONDS
        ),
    )

    args = parser.parse_args()

    if args.scenarios < 1:
        parser.error(
            "--scenarios must be >= 1"
        )

    if (
        not math.isfinite(
            args.pair_tolerance_m
        )
        or args.pair_tolerance_m
        < 0.0
    ):
        parser.error(
            "--pair-tolerance-m must be finite and >= 0"
        )

    if args.max_bruteforce_size < 1:
        parser.error(
            "--max-bruteforce-size must be >= 1"
        )

    for size in args.sizes:
        if (
            size
            > args.max_bruteforce_size
        ):
            parser.error(
                f"Size {size} exceeds --max-bruteforce-size "
                f"{args.max_bruteforce_size}."
            )

    if (
        not math.isfinite(
            args.timeout_seconds
        )
        or args.timeout_seconds
        <= 0.0
    ):
        parser.error(
            "--timeout-seconds must be finite and > 0"
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
            "phase10_correctness_raw_"
            f"{args.mode}_"
            f"{timestamp}.json"
        )
    )

    summary_path = (
        result_directory
        / (
            "phase10_correctness_summary_"
            f"{args.mode}_"
            f"{timestamp}.json"
        )
    )

    print("=" * 80)
    print(
        "CityRoute Phase 10 "
        "Independent Correctness Probe"
    )
    print("=" * 80)
    print(f"mode={args.mode}")
    print(f"base_url={base_url}")
    print(f"endpoint={ENDPOINT}")
    print(
        f"graph_path={args.graph_path}"
    )
    print(f"sizes={args.sizes}")
    print(
        f"scenarios={args.scenarios}"
    )
    print(
        "matrix_algorithm=source_dijkstra"
    )
    print("use_cache=False")
    print(
        "oracle=independent NetworkX Dijkstra "
        "+ brute-force assignment"
    )
    print(
        "pair_tolerance_m="
        f"{args.pair_tolerance_m}"
    )
    print("=" * 80)

    try:
        (
            raw_graph,
            oracle_graph,
            candidate_nodes,
            graph_metadata,
        ) = load_oracle_graph(
            args.graph_path
        )

    except Exception as exc:
        print(
            "ERROR: graph preparation failed: "
            f"{type(exc).__name__}: {exc}"
        )

        return 1

    print(
        "raw_graph_nodes="
        f"{graph_metadata['raw_node_count']}"
    )

    print(
        "raw_graph_edges="
        f"{graph_metadata['raw_edge_count']}"
    )

    print(
        "oracle_graph_edges="
        f"{graph_metadata['oracle_edge_count']}"
    )

    print(
        "largest_scc_nodes="
        f"{graph_metadata['largest_strongly_connected_component_nodes']}"
    )

    print(
        "candidate_nodes="
        f"{graph_metadata['unique_coordinate_candidate_count']}"
    )

    timeout = httpx.Timeout(
        args.timeout_seconds
    )

    scenario_records: list[
        dict[str, Any]
    ] = []

    with httpx.Client(
        timeout=timeout
    ) as client:
        preflight_result = (
            preflight(
                client=client,
                base_url=base_url,
                graph_metadata=(
                    graph_metadata
                ),
            )
        )

        print(
            f"preflight={preflight_result}"
        )

        if not preflight_result.get(
            "success",
            False,
        ):
            print(
                "ERROR: preflight failed or Docker graph "
                "does not match the local oracle GraphML."
            )

            return 1

        for size in args.sizes:
            print()
            print("-" * 80)
            print(f"size={size}")
            print("-" * 80)

            for scenario_number in range(
                1,
                args.scenarios + 1,
            ):
                scenario_index = (
                    (
                        size
                        * 100
                    )
                    + scenario_number
                )

                scenario_label = (
                    f"s{size}_"
                    f"case{scenario_number}"
                )

                (
                    driver_nodes,
                    order_nodes,
                ) = (
                    select_scenario_nodes(
                        candidate_nodes=(
                            candidate_nodes
                        ),
                        size=size,
                        scenario_index=(
                            scenario_index
                        ),
                    )
                )

                (
                    oracle_matrix,
                    oracle_matrix_time_ms,
                ) = build_oracle_matrix(
                    graph=oracle_graph,
                    driver_nodes=(
                        driver_nodes
                    ),
                    order_nodes=(
                        order_nodes
                    ),
                )

                brute_force_result = (
                    brute_force_assignment(
                        oracle_matrix
                    )
                )

                cell_probe = (
                    probe_matrix_cells(
                        client=client,
                        endpoint_url=(
                            endpoint_url
                        ),
                        raw_graph=(
                            raw_graph
                        ),
                        driver_nodes=(
                            driver_nodes
                        ),
                        order_nodes=(
                            order_nodes
                        ),
                        oracle_matrix=(
                            oracle_matrix
                        ),
                        scenario_label=(
                            scenario_label
                        ),
                        pair_tolerance_m=(
                            args.pair_tolerance_m
                        ),
                    )
                )

                batch_probe = (
                    run_batch_correctness(
                        client=client,
                        endpoint_url=(
                            endpoint_url
                        ),
                        raw_graph=(
                            raw_graph
                        ),
                        driver_nodes=(
                            driver_nodes
                        ),
                        order_nodes=(
                            order_nodes
                        ),
                        oracle_matrix=(
                            oracle_matrix
                        ),
                        brute_force_result=(
                            brute_force_result
                        ),
                        scenario_label=(
                            scenario_label
                        ),
                        pair_tolerance_m=(
                            args.pair_tolerance_m
                        ),
                    )
                )

                success = (
                    cell_probe[
                        "success"
                    ]
                    and batch_probe[
                        "success"
                    ]
                )

                scenario_record = {
                    "phase": PHASE,
                    "benchmark": (
                        BENCHMARK
                    ),
                    "size": size,
                    "scenario": (
                        scenario_number
                    ),
                    "scenario_label": (
                        scenario_label
                    ),
                    "success": success,
                    "driver_nodes": [
                        str(
                            node
                        )
                        for node
                        in driver_nodes
                    ],
                    "order_nodes": [
                        str(
                            node
                        )
                        for node
                        in order_nodes
                    ],
                    "oracle_matrix_m": (
                        oracle_matrix
                    ),
                    "oracle_matrix_time_ms": (
                        round(
                            oracle_matrix_time_ms,
                            6,
                        )
                    ),
                    "cell_probe": (
                        cell_probe
                    ),
                    "batch_probe": (
                        batch_probe
                    ),
                }

                scenario_records.append(
                    scenario_record
                )

                print(
                    f"scenario={scenario_number}/"
                    f"{args.scenarios} "
                    f"success={success} "
                    "cells="
                    f"{cell_probe['success_count']}/"
                    f"{cell_probe['cell_count']} "
                    "cell_mismatches="
                    f"{cell_probe['mismatch_count']} "
                    "max_abs_error_m="
                    f"{cell_probe['max_abs_error_m']} "
                    "hungarian_optimal="
                    f"{batch_probe['comparison']['hungarian_matches_oracle_optimum']} "
                    "optimality_gap_m="
                    f"{batch_probe['comparison']['optimality_gap_m']}"
                )

                if not success:
                    print(
                        "  batch_errors="
                        f"{batch_probe['common_validation_errors']}"
                    )

    successful_scenarios = [
        record
        for record
        in scenario_records
        if record[
            "success"
        ]
    ]

    failed_scenarios = [
        record
        for record
        in scenario_records
        if not record[
            "success"
        ]
    ]

    all_cell_records = [
        cell
        for scenario
        in scenario_records
        for cell
        in scenario[
            "cell_probe"
        ][
            "records"
        ]
    ]

    cell_success_count = sum(
        1
        for cell
        in all_cell_records
        if cell[
            "success"
        ]
    )

    cell_mismatch_count = (
        len(
            all_cell_records
        )
        - cell_success_count
    )

    max_abs_error_m = max(
        (
            float(
                cell[
                    "abs_error_m"
                ]
            )
            for cell
            in all_cell_records
            if cell[
                "abs_error_m"
            ]
            is not None
        ),
        default=0.0,
    )

    batch_success_count = sum(
        1
        for scenario
        in scenario_records
        if scenario[
            "batch_probe"
        ][
            "success"
        ]
    )

    optimality_pass_count = sum(
        1
        for scenario
        in scenario_records
        if scenario[
            "batch_probe"
        ][
            "comparison"
        ][
            "hungarian_matches_oracle_optimum"
        ]
    )

    non_regression_pass_count = sum(
        1
        for scenario
        in scenario_records
        if scenario[
            "batch_probe"
        ][
            "comparison"
        ][
            "hungarian_non_regression"
        ]
    )

    optimality_gaps = [
        abs(
            float(
                scenario[
                    "batch_probe"
                ][
                    "comparison"
                ][
                    "optimality_gap_m"
                ]
            )
        )
        for scenario
        in scenario_records
        if (
            scenario[
                "batch_probe"
            ][
                "comparison"
            ][
                "optimality_gap_m"
            ]
            is not None
        )
    ]

    cell_request_times = [
        float(
            cell[
                "elapsed_ms"
            ]
        )
        for cell
        in all_cell_records
        if cell[
            "request_success"
        ]
    ]

    batch_request_times = [
        float(
            scenario[
                "batch_probe"
            ][
                "elapsed_ms"
            ]
        )
        for scenario
        in scenario_records
        if scenario[
            "batch_probe"
        ][
            "status_code"
        ]
        == 200
    ]

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
            "base_url": (
                base_url
            ),
            "endpoint": (
                ENDPOINT
            ),
            "graph_path": str(
                args.graph_path
            ),
            "sizes": list(
                args.sizes
            ),
            "scenarios": (
                args.scenarios
            ),
            "pair_tolerance_m": (
                args.pair_tolerance_m
            ),
            "matrix_algorithm": (
                "source_dijkstra"
            ),
            "use_cache": False,
            "oracle": (
                "independent_networkx_dijkstra_"
                "plus_bruteforce_assignment"
            ),
        },
        "graph": (
            graph_metadata
        ),
        "preflight": (
            preflight_result
        ),
        "scenarios": (
            scenario_records
        ),
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
            "base_url": (
                base_url
            ),
            "endpoint": (
                ENDPOINT
            ),
            "graph_path": str(
                args.graph_path
            ),
            "sizes": list(
                args.sizes
            ),
            "scenarios": (
                args.scenarios
            ),
            "pair_tolerance_m": (
                args.pair_tolerance_m
            ),
            "matrix_algorithm": (
                "source_dijkstra"
            ),
            "use_cache": False,
        },
        "graph": (
            graph_metadata
        ),
        "graph_consistency_passed": (
            preflight_result.get(
                "graph_consistent",
                False,
            )
        ),
        "scenario_count": (
            len(
                scenario_records
            )
        ),
        "scenario_success_count": (
            len(
                successful_scenarios
            )
        ),
        "scenario_failure_count": (
            len(
                failed_scenarios
            )
        ),
        "scenario_success_rate_pct": round(
            (
                len(
                    successful_scenarios
                )
                / len(
                    scenario_records
                )
                * 100.0
            )
            if scenario_records
            else 0.0,
            3,
        ),
        "cell_case_count": (
            len(
                all_cell_records
            )
        ),
        "cell_success_count": (
            cell_success_count
        ),
        "cell_mismatch_count": (
            cell_mismatch_count
        ),
        "max_abs_road_cost_error_m": round(
            max_abs_error_m,
            9,
        ),
        "all_road_cost_cells_matched_oracle": (
            cell_mismatch_count
            == 0
        ),
        "batch_case_count": (
            len(
                scenario_records
            )
        ),
        "batch_success_count": (
            batch_success_count
        ),
        "hungarian_optimality_pass_count": (
            optimality_pass_count
        ),
        "expected_hungarian_optimality_pass_count": (
            len(
                scenario_records
            )
        ),
        "all_hungarian_results_matched_bruteforce_optimum": (
            optimality_pass_count
            == len(
                scenario_records
            )
        ),
        "hungarian_non_regression_pass_count": (
            non_regression_pass_count
        ),
        "expected_hungarian_non_regression_pass_count": (
            len(
                scenario_records
            )
        ),
        "all_hungarian_non_regression_checks_passed": (
            non_regression_pass_count
            == len(
                scenario_records
            )
        ),
        "absolute_optimality_gap_m": (
            summarize_values(
                optimality_gaps
            )
        ),
        "cell_request_elapsed_ms": (
            summarize_values(
                cell_request_times
            )
        ),
        "batch_request_elapsed_ms": (
            summarize_values(
                batch_request_times
            )
        ),
        "failed_scenarios": [
            {
                "size": (
                    scenario[
                        "size"
                    ]
                ),
                "scenario": (
                    scenario[
                        "scenario"
                    ]
                ),
                "cell_mismatch_count": (
                    scenario[
                        "cell_probe"
                    ][
                        "mismatch_count"
                    ]
                ),
                "batch_errors": (
                    scenario[
                        "batch_probe"
                    ][
                        "common_validation_errors"
                    ]
                ),
                "greedy_errors": (
                    scenario[
                        "batch_probe"
                    ][
                        "greedy"
                    ][
                        "validation_errors"
                    ]
                ),
                "hungarian_errors": (
                    scenario[
                        "batch_probe"
                    ][
                        "hungarian"
                    ][
                        "validation_errors"
                    ]
                ),
            }
            for scenario
            in failed_scenarios
        ],
        "interpretation_note": (
            "Each road-cost matrix cell is independently checked "
            "through a live 1x1 source_dijkstra API request against "
            "a NetworkX Dijkstra oracle built from the same GraphML. "
            "The full NxN API request is then checked against an "
            "independent brute-force assignment optimum. This probe "
            "uses uniquely positioned nodes from the largest strongly "
            "connected component so that all tested pairs are expected "
            "to be reachable."
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
        if not failed_scenarios
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )