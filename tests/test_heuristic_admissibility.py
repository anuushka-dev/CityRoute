# tests/test_heuristic_admissibility.py

import networkx as nx
from fastapi.testclient import TestClient

from app.core.a_star import haversine_m
from app.main import app


def _dijkstra_weight(u, v, edge_data):
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


def test_haversine_heuristic_does_not_overestimate_sampled_real_graph_routes():
    with TestClient(app) as client:
        graph = client.app.state.graph
        nodes = list(graph.nodes)

        pairs = [
            (nodes[25], nodes[250]),
            (nodes[50], nodes[500]),
            (nodes[100], nodes[1000]),
            (nodes[200], nodes[2000]),
            (nodes[400], nodes[4000]),
            (nodes[800], nodes[6000]),
            (nodes[1200], nodes[7000]),
            (nodes[2400], nodes[8500]),
            (nodes[3600], nodes[10000]),
            (nodes[5000], nodes[12000]),
        ]

        checked = 0

        for start_node, end_node in pairs:
            try:
                road_distance = nx.shortest_path_length(
                    graph,
                    source=start_node,
                    target=end_node,
                    weight=_dijkstra_weight,
                )
            except nx.NetworkXNoPath:
                continue

            start_data = graph.nodes[start_node]
            end_data = graph.nodes[end_node]

            heuristic_distance = haversine_m(
                float(start_data["y"]),
                float(start_data["x"]),
                float(end_data["y"]),
                float(end_data["x"]),
            )

            assert heuristic_distance <= road_distance + 1e-6

            checked += 1

        assert checked >= 5
