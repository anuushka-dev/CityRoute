# benchmarks/heuristic_admissibility_probe.py

from __future__ import annotations

import os

import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import networkx as nx

from app.core.a_star import haversine_m
from app.services.graph_service import load_or_download_graph


RESULTS_DIR = Path("benchmarks/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def dijkstra_weight(u, v, edge_data):
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


def main() -> None:
    random.seed(42)

    target_pairs = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    max_attempts = target_pairs * 5

    graph, graph_stats = load_or_download_graph()
    if graph is None:
        raise RuntimeError("Graph failed to load. Cannot run heuristic probe.")

    nodes = list(graph.nodes)

    checked = 0
    no_path = 0
    overestimates = 0
    worst_overestimate_m = 0.0
    examples: list[dict] = []

    start_time = perf_counter()

    for _ in range(max_attempts):
        if checked >= target_pairs:
            break

        start_node = random.choice(nodes)
        end_node = random.choice(nodes)

        if start_node == end_node:
            continue

        try:
            road_distance = nx.shortest_path_length(
                graph,
                source=start_node,
                target=end_node,
                weight=dijkstra_weight,
            )
        except nx.NetworkXNoPath:
            no_path += 1
            continue

        start_data = graph.nodes[start_node]
        end_data = graph.nodes[end_node]

        heuristic_distance = haversine_m(
            float(start_data["y"]),
            float(start_data["x"]),
            float(end_data["y"]),
            float(end_data["x"]),
        )

        difference = heuristic_distance - road_distance

        if difference > 1e-6:
            overestimates += 1
            worst_overestimate_m = max(worst_overestimate_m, difference)

            if len(examples) < 20:
                examples.append(
                    {
                        "start_node": start_node,
                        "end_node": end_node,
                        "heuristic_distance_m": heuristic_distance,
                        "road_distance_m": road_distance,
                        "overestimate_m": difference,
                    }
                )

        checked += 1

    elapsed_s = round(perf_counter() - start_time, 3)

    result = {
        "benchmark": "phase3_heuristic_admissibility_probe",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "graph": {
            "city": graph_stats.get("city"),
            "nodes": graph_stats.get("nodes"),
            "edges": graph_stats.get("edges"),
            "is_weakly_connected": graph_stats.get("is_weakly_connected"),
        },
        "target_pairs": target_pairs,
        "checked": checked,
        "no_path_skipped": no_path,
        "overestimates": overestimates,
        "worst_overestimate_m": round(worst_overestimate_m, 6),
        "elapsed_s": elapsed_s,
        "examples": examples,
    }

    output_path = RESULTS_DIR / "phase3_heuristic_admissibility_probe.json"
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(json.dumps(result, indent=2))

    if checked < target_pairs:
        raise SystemExit(f"Only checked {checked}/{target_pairs} pairs.")

    if overestimates > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
