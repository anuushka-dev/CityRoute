# benchmarks/astar_correctness_probe.py

from __future__ import annotations
import os
import json
import random
from datetime import datetime, timezone
from math import isclose
from pathlib import Path
from time import perf_counter

import networkx as nx

from app.core.a_star import astar_shortest_path
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

    graph, graph_stats = load_or_download_graph()
    if graph is None:
        raise RuntimeError("Graph failed to load. Cannot run correctness probe.")

    nodes = list(graph.nodes)
    target_checks = 500
    max_attempts = 2500

    passed = 0
    failed = 0
    no_path = 0
    errors: list[dict] = []

    start_time = perf_counter()

    for _ in range(max_attempts):
        if passed + failed >= target_checks:
            break

        start_node = random.choice(nodes)
        end_node = random.choice(nodes)

        if start_node == end_node:
            continue

        try:
            astar_result = astar_shortest_path(graph, start_node, end_node)

            dijkstra_distance = nx.shortest_path_length(
                graph,
                source=start_node,
                target=end_node,
                weight=dijkstra_weight,
            )

            if isclose(astar_result.distance_m, dijkstra_distance, rel_tol=0, abs_tol=1e-3):
                passed += 1
            else:
                failed += 1
                errors.append(
                    {
                        "start_node": start_node,
                        "end_node": end_node,
                        "astar_distance_m": astar_result.distance_m,
                        "dijkstra_distance_m": dijkstra_distance,
                        "difference_m": astar_result.distance_m - dijkstra_distance,
                    }
                )

        except nx.NetworkXNoPath:
            no_path += 1
            continue

    elapsed_s = round(perf_counter() - start_time, 3)

    result = {
        "benchmark": "phase3_astar_correctness_probe",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "graph": {
            "city": graph_stats.get("city"),
            "nodes": graph_stats.get("nodes"),
            "edges": graph_stats.get("edges"),
            "is_weakly_connected": graph_stats.get("is_weakly_connected"),
        },
        "target_checks": target_checks,
        "passed": passed,
        "failed": failed,
        "no_path_skipped": no_path,
        "max_attempts": max_attempts,
        "elapsed_s": elapsed_s,
        "distance_tolerance_m": 0.001,
        "success_rate_pct": round((passed / target_checks) * 100, 3) if target_checks else 0,
        "errors": errors[:20],
    }

    output_path = RESULTS_DIR / "phase3_astar_correctness_probe.json"
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(json.dumps(result, indent=2))

    if failed > 0:
        raise SystemExit(1)

    if passed < target_checks:
        raise SystemExit(f"Only completed {passed}/{target_checks} checks.")


if __name__ == "__main__":
    main()
