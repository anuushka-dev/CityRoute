# benchmarks/bidirectional_astar_correctness_probe.py

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from math import isclose
from pathlib import Path
from typing import Any

import networkx as nx
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.a_star import astar_shortest_path  # noqa: E402
from app.core.bidirectional_a_star import bidirectional_astar_shortest_path  # noqa: E402
from app.main import app  # noqa: E402


DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "benchmarks"
    / "phase4_results"
    / "phase4_bidirectional_astar_correctness_probe.json"
)

DISTANCE_TOLERANCE_M = 0.001


def _dijkstra_weight(u: Any, v: Any, edge_data: dict[str, Any]) -> float:
    """
    Match CityRoute edge-length behavior.

    For MultiDiGraph parallel edges, CityRoute chooses the shortest edge length.
    This Dijkstra oracle must do the same.
    """
    if not edge_data:
        return 0.0

    if all(isinstance(value, dict) for value in edge_data.values()):
        lengths = [
            float(attrs["length"])
            for attrs in edge_data.values()
            if isinstance(attrs, dict) and "length" in attrs
        ]
        return min(lengths) if lengths else 0.0

    return float(edge_data.get("length", 0.0))


def _graph_metadata(graph: nx.Graph) -> dict[str, Any]:
    return {
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "is_directed": graph.is_directed(),
        "is_multigraph": graph.is_multigraph(),
        "is_weakly_connected": (
            nx.is_weakly_connected(graph) if graph.is_directed() else nx.is_connected(graph)
        ),
    }


def run_probe(
    *,
    target_checks: int,
    max_attempts: int,
    seed: int,
    output_path: Path,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    random.seed(seed)

    passed = 0
    failed = 0
    no_path_skipped = 0
    attempts = 0

    errors: list[dict[str, Any]] = []

    with TestClient(app) as client:
        graph = client.app.state.graph

        nodes = list(graph.nodes)

        if len(nodes) < 2:
            raise RuntimeError("Graph must contain at least two nodes.")

        while passed < target_checks and attempts < max_attempts:
            attempts += 1

            start_node = random.choice(nodes)
            end_node = random.choice(nodes)

            try:
                astar_result = astar_shortest_path(
                    graph,
                    start_node,
                    end_node,
                )

                bidirectional_result = bidirectional_astar_shortest_path(
                    graph,
                    start_node,
                    end_node,
                )

                dijkstra_distance = nx.shortest_path_length(
                    graph,
                    source=start_node,
                    target=end_node,
                    weight=_dijkstra_weight,
                )

            except nx.NetworkXNoPath:
                no_path_skipped += 1
                continue

            except Exception as exc:
                failed += 1
                errors.append(
                    {
                        "attempt": attempts,
                        "start_node": start_node,
                        "end_node": end_node,
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
                continue

            astar_distance = float(astar_result.distance_m)
            bidirectional_distance = float(bidirectional_result.distance_m)
            dijkstra_distance = float(dijkstra_distance)

            bidirectional_matches_astar = isclose(
                bidirectional_distance,
                astar_distance,
                rel_tol=0,
                abs_tol=DISTANCE_TOLERANCE_M,
            )

            bidirectional_matches_dijkstra = isclose(
                bidirectional_distance,
                dijkstra_distance,
                rel_tol=0,
                abs_tol=DISTANCE_TOLERANCE_M,
            )

            path_valid = (
                bidirectional_result.path
                and bidirectional_result.path[0] == start_node
                and bidirectional_result.path[-1] == end_node
            )

            if (
                bidirectional_matches_astar
                and bidirectional_matches_dijkstra
                and path_valid
            ):
                passed += 1
            else:
                failed += 1
                errors.append(
                    {
                        "attempt": attempts,
                        "start_node": start_node,
                        "end_node": end_node,
                        "astar_distance_m": astar_distance,
                        "bidirectional_distance_m": bidirectional_distance,
                        "dijkstra_distance_m": dijkstra_distance,
                        "distance_delta_vs_astar_m": round(
                            abs(astar_distance - bidirectional_distance),
                            6,
                        ),
                        "distance_delta_vs_dijkstra_m": round(
                            abs(dijkstra_distance - bidirectional_distance),
                            6,
                        ),
                        "path_valid": path_valid,
                        "bidirectional_path_start": (
                            bidirectional_result.path[0]
                            if bidirectional_result.path
                            else None
                        ),
                        "bidirectional_path_end": (
                            bidirectional_result.path[-1]
                            if bidirectional_result.path
                            else None
                        ),
                    }
                )

            if attempts % 100 == 0:
                print(
                    "Attempts="
                    f"{attempts} | passed={passed} | failed={failed} | "
                    f"no_path={no_path_skipped}"
                )

        elapsed_s = round(time.perf_counter() - started_at, 3)

        result = {
            "benchmark": "phase4_bidirectional_astar_correctness_probe",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "graph": _graph_metadata(graph),
            "target_checks": target_checks,
            "passed": passed,
            "failed": failed,
            "no_path_skipped": no_path_skipped,
            "attempts": attempts,
            "max_attempts": max_attempts,
            "distance_tolerance_m": DISTANCE_TOLERANCE_M,
            "success_rate_pct": (
                round((passed / target_checks) * 100, 3)
                if target_checks
                else 0.0
            ),
            "elapsed_s": elapsed_s,
            "errors": errors,
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 4 correctness probe for Bidirectional A* against "
            "existing A* and Dijkstra."
        )
    )

    parser.add_argument(
        "target_checks",
        nargs="?",
        type=int,
        default=500,
        help="Number of successful routeable pairs to verify.",
    )

    parser.add_argument(
        "max_attempts",
        nargs="?",
        type=int,
        default=2500,
        help="Maximum sampled pairs before stopping.",
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for repeatable sampling.",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output JSON file path.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    result = run_probe(
        target_checks=args.target_checks,
        max_attempts=args.max_attempts,
        seed=args.seed,
        output_path=args.output,
    )

    print(json.dumps(result, indent=2))

    if result["passed"] != result["target_checks"] or result["failed"] != 0:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())