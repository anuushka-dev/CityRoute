# tests/test_astar_correctness.py

from math import isclose

import networkx as nx
from fastapi.testclient import TestClient

from app.core.a_star import astar_shortest_path
from app.main import app


def _dijkstra_weight(u, v, edge_data):
    """
    Match CityRoute A* edge behavior.

    For OSMnx MultiDiGraph, NetworkX gives edge_data like:
    {0: {"length": ...}, 1: {"length": ...}}

    CityRoute A* chooses the shortest parallel edge.
    This Dijkstra baseline must do the same.
    """
    if not edge_data:
        return 0.0

    if all(isinstance(value, dict) for value in edge_data.values()):
        lengths = [
            float(attrs["length"])
            for attrs in edge_data.values()
            if "length" in attrs
        ]
        return min(lengths) if lengths else 0.0

    return float(edge_data.get("length", 0.0))


def test_astar_matches_dijkstra_for_known_docker_route_nodes():
    with TestClient(app) as client:
        graph = client.app.state.graph

        # From your Docker /route evidence:
        # start: lat=26.44 lon=80.30 -> 5317312245
        # end:   lat=26.45 lon=80.35 -> 6288159135
        start_node = 5317312245
        end_node = 6288159135

        assert start_node in graph
        assert end_node in graph

        astar_result = astar_shortest_path(graph, start_node, end_node)

        dijkstra_distance = nx.shortest_path_length(
            graph,
            source=start_node,
            target=end_node,
            weight=_dijkstra_weight,
        )

    assert astar_result.path[0] == start_node
    assert astar_result.path[-1] == end_node
    assert isclose(astar_result.distance_m, dijkstra_distance, rel_tol=0, abs_tol=1e-3)


def test_astar_matches_dijkstra_on_deterministic_real_graph_pairs():
    with TestClient(app) as client:
        graph = client.app.state.graph
        nodes = list(graph.nodes)

        assert len(nodes) > 1000

        indexes = [
            (10, 500),
            (100, 1000),
            (250, 2500),
            (700, 3000),
            (1200, 4500),
            (2000, 6500),
            (3500, 8000),
            (5000, 10000),
            (7500, 12000),
            (9000, 11000),
        ]

        checked = 0

        for start_index, end_index in indexes:
            start_node = nodes[start_index]
            end_node = nodes[end_index]

            try:
                astar_result = astar_shortest_path(graph, start_node, end_node)

                dijkstra_distance = nx.shortest_path_length(
                    graph,
                    source=start_node,
                    target=end_node,
                    weight=_dijkstra_weight,
                )
            except nx.NetworkXNoPath:
                continue

            assert astar_result.path[0] == start_node
            assert astar_result.path[-1] == end_node
            assert isclose(
                astar_result.distance_m,
                dijkstra_distance,
                rel_tol=0,
                abs_tol=1e-3,
            )

            checked += 1

        assert checked >= 5
