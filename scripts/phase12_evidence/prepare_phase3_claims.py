from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path.cwd()
PHASE12_ROOT = ROOT / ".phase12_evidence"

FIELDS = [
    "claim_id",
    "phase",
    "claim_text",
    "source_audit",
    "artifact_path",
    "json_pointer",
    "operator",
    "expected_value",
    "tolerance",
    "provenance_source_artifact",
    "notes",
]


def newest_collection() -> Path:
    collections = sorted(
        PHASE12_ROOT.glob("collection_*"),
        key=lambda path: path.name,
        reverse=True,
    )

    if not collections:
        raise FileNotFoundError(
            "No Phase 12 evidence collection found."
        )

    return collections[0]


def existing(relative_path: str) -> str:
    path = ROOT / relative_path

    if not path.exists():
        raise FileNotFoundError(
            f"Required Phase 3 artifact not found: {path}"
        )

    return relative_path.replace("\\", "/")


def make_claim(
    claim_id: str,
    claim_text: str,
    artifact_path: str,
    json_pointer: str,
    operator: str,
    expected_value: str,
    *,
    tolerance: str = "",
    notes: str = "",
    provenance_source_artifact: str = "",
) -> dict[str, str]:
    return {
        "claim_id": claim_id,
        "phase": "phase3",
        "claim_text": claim_text,
        "source_audit": "CityRoute Tier 1 Phase 3 - Custom A* Routing",
        "artifact_path": artifact_path,
        "json_pointer": json_pointer,
        "operator": operator,
        "expected_value": expected_value,
        "tolerance": tolerance,
        "provenance_source_artifact": provenance_source_artifact,
        "notes": notes,
    }


def build_claims() -> list[dict[str, str]]:
    correctness_summary = existing(
        "benchmarks/phase3_docker_results/"
        "phase3_astar_correctness_summary.json"
    )
    route_benchmark = existing(
        "benchmarks/phase3_docker_results/"
        "phase3_astar_route_benchmark.json"
    )
    routeable_summary = existing(
        "benchmarks/phase3_docker_results/"
        "phase3_routeable_benchmark_summary.json"
    )
    concurrent_summary = existing(
        "benchmarks/phase3_docker_results/"
        "phase3_concurrent_summary.json"
    )
    heuristic_summary = existing(
        "benchmarks/phase3_docker_results/"
        "phase3_heuristic_summary.json"
    )
    route_latency = existing(
        "benchmarks/phase3_docker_results/"
        "phase3_route_latency_summary.json"
    )
    snap_latency = existing(
        "benchmarks/phase3_docker_results/"
        "phase3_snap_latency_summary.json"
    )
    graph_stats = existing(
        "benchmarks/phase3_docker_results/"
        "phase3_docker_graph_stats.json"
    )
    health = existing(
        "benchmarks/phase3_docker_results/"
        "phase3_docker_health.json"
    )
    connectivity = existing(
        "benchmarks/phase3_docker_results/"
        "phase3_connectivity_audit.json"
    )

    return [
        # ========================================================
        # CORRECTNESS
        # ========================================================
        make_claim(
            "P3-CORRECT-001",
            "The Phase 3 Docker A* correctness probe checked 500 target cases.",
            correctness_summary,
            "$.target_checks",
            "eq",
            "500",
        ),
        make_claim(
            "P3-CORRECT-002",
            "The Phase 3 Docker A* correctness probe passed all 500 target cases.",
            correctness_summary,
            "$.passed",
            "eq",
            "500",
        ),
        make_claim(
            "P3-CORRECT-003",
            "The Phase 3 Docker A* correctness probe recorded zero failed cases.",
            correctness_summary,
            "$.failed",
            "eq",
            "0",
        ),
        make_claim(
            "P3-CORRECT-004",
            "The Phase 3 Docker A* correctness probe reported a 100% success rate.",
            correctness_summary,
            "$.success_rate_pct",
            "eq",
            "100",
            tolerance="0.001",
            notes=(
                "Empirical result for the 500 checked cases; "
                "not a universal mathematical proof of A* correctness."
            ),
        ),
        make_claim(
            "P3-CORRECT-005",
            "The Phase 3 Docker A* correctness probe skipped zero no-path cases.",
            correctness_summary,
            "$.no_path_skipped",
            "eq",
            "0",
        ),

        # ========================================================
        # ROUTE BENCHMARK
        # ========================================================
        make_claim(
            "P3-ROUTE-001",
            "The Phase 3 Docker A* benchmark recorded 1000 successful route measurements.",
            routeable_summary,
            "$.successful_route_measurements",
            "eq",
            "1000",
        ),
        make_claim(
            "P3-ROUTE-002",
            "The Phase 3 Docker routeable benchmark recorded 1008 attempted requests.",
            routeable_summary,
            "$.attempted_requests",
            "eq",
            "1008",
        ),
        make_claim(
            "P3-ROUTE-003",
            "The Phase 3 Docker routeable benchmark skipped 8 no-path 404 cases.",
            routeable_summary,
            "$.no_path_404_skipped",
            "eq",
            "8",
            notes=(
                "These are explicitly distinguished from real benchmark failures."
            ),
        ),
        make_claim(
            "P3-ROUTE-004",
            "The Phase 3 Docker routeable benchmark recorded zero real failures.",
            routeable_summary,
            "$.real_failures",
            "eq",
            "0",
        ),
        make_claim(
            "P3-ROUTE-005",
            "The Phase 3 Docker routeable benchmark reported a 0.0% real failure rate.",
            routeable_summary,
            "$.real_failure_rate_pct",
            "eq",
            "0",
            tolerance="0.001",
        ),
        make_claim(
            "P3-ROUTE-006",
            "The Phase 3 Docker routeable benchmark reported a 0.794% no-path rate.",
            routeable_summary,
            "$.no_path_rate_pct",
            "eq",
            "0.794",
            tolerance="0.001",
            notes=(
                "This is the observed benchmark no-path rate, not a service failure rate."
            ),
        ),
        make_claim(
            "P3-ROUTE-007",
            "The Phase 3 Docker A* benchmark recorded three zero-distance successes.",
            routeable_summary,
            "$.zero_distance_successes",
            "eq",
            "3",
        ),

        # ========================================================
        # CONCURRENCY
        # ========================================================
        make_claim(
            "P3-CONCURRENT-001",
            "The Phase 3 Docker concurrency probe used 10 workers.",
            concurrent_summary,
            "$.workers",
            "eq",
            "10",
        ),
        make_claim(
            "P3-CONCURRENT-002",
            "The Phase 3 Docker concurrency probe executed 10 requests.",
            concurrent_summary,
            "$.total_requests",
            "eq",
            "10",
        ),
        make_claim(
            "P3-CONCURRENT-003",
            "The Phase 3 Docker concurrency probe completed all 10 requests successfully.",
            concurrent_summary,
            "$.successful_requests",
            "eq",
            "10",
        ),
        make_claim(
            "P3-CONCURRENT-004",
            "The Phase 3 Docker concurrency probe recorded zero failed requests.",
            concurrent_summary,
            "$.failed_requests",
            "eq",
            "0",
        ),

        # ========================================================
        # HEURISTIC
        # ========================================================
        make_claim(
            "P3-HEURISTIC-001",
            "The Phase 3 Docker heuristic probe targeted 10000 pairs.",
            heuristic_summary,
            "$.target_pairs",
            "eq",
            "10000",
        ),
        make_claim(
            "P3-HEURISTIC-002",
            "The Phase 3 Docker heuristic probe checked 10000 pairs.",
            heuristic_summary,
            "$.checked",
            "eq",
            "10000",
        ),
        make_claim(
            "P3-HEURISTIC-003",
            "The Phase 3 Docker heuristic probe skipped 18 no-path cases.",
            heuristic_summary,
            "$.no_path_skipped",
            "eq",
            "18",
        ),
        make_claim(
            "P3-HEURISTIC-004",
            "The Phase 3 Docker heuristic probe recorded zero overestimates.",
            heuristic_summary,
            "$.overestimates",
            "eq",
            "0",
        ),
        make_claim(
            "P3-HEURISTIC-005",
            "The Phase 3 Docker heuristic probe recorded a worst overestimate of 0.0 metres.",
            heuristic_summary,
            "$.worst_overestimate_m",
            "eq",
            "0",
            tolerance="0",
            notes=(
                "Empirical result for the tested pairs; "
                "not a universal mathematical admissibility proof."
            ),
        ),

        # ========================================================
        # ROUTE LATENCY
        # ========================================================
        make_claim(
            "P3-LATENCY-001",
            "The Phase 3 Docker route latency median was 9.892 ms.",
            route_latency,
            "$.median",
            "eq",
            "9.892",
            tolerance="0.001",
        ),
        make_claim(
            "P3-LATENCY-002",
            "The Phase 3 Docker route latency p95 was 44.371 ms.",
            route_latency,
            "$.p95",
            "eq",
            "44.371",
            tolerance="0.001",
        ),
        make_claim(
            "P3-LATENCY-003",
            "The Phase 3 Docker route latency p99 was 87.893 ms.",
            route_latency,
            "$.p99",
            "eq",
            "87.893",
            tolerance="0.001",
        ),
        make_claim(
            "P3-LATENCY-004",
            "The Phase 3 Docker route latency maximum was 106.064 ms.",
            route_latency,
            "$.max",
            "eq",
            "106.064",
            tolerance="0.001",
        ),

        # ========================================================
        # SNAP LATENCY
        # ========================================================
        make_claim(
            "P3-SNAP-001",
            "The Phase 3 Docker snap latency median was 0.569 ms.",
            snap_latency,
            "$.median",
            "eq",
            "0.569",
            tolerance="0.001",
        ),
        make_claim(
            "P3-SNAP-002",
            "The Phase 3 Docker snap latency p95 was 0.798 ms.",
            snap_latency,
            "$.p95",
            "eq",
            "0.798",
            tolerance="0.001",
        ),
        make_claim(
            "P3-SNAP-003",
            "The Phase 3 Docker snap latency p99 was 0.961 ms.",
            snap_latency,
            "$.p99",
            "eq",
            "0.961",
            tolerance="0.001",
        ),
        make_claim(
            "P3-SNAP-004",
            "The Phase 3 Docker snap latency maximum was 1.304 ms.",
            snap_latency,
            "$.max",
            "eq",
            "1.304",
            tolerance="0.001",
        ),

        # ========================================================
        # GRAPH
        # ========================================================
        make_claim(
            "P3-GRAPH-001",
            "The Phase 3 Docker graph was reported as loaded.",
            graph_stats,
            "$.graph_loaded",
            "eq",
            "true",
        ),
        make_claim(
            "P3-GRAPH-002",
            "The Phase 3 Docker graph contained 12969 nodes.",
            graph_stats,
            "$.nodes",
            "eq",
            "12969",
        ),
        make_claim(
            "P3-GRAPH-003",
            "The Phase 3 Docker graph contained 34996 edges.",
            graph_stats,
            "$.edges",
            "eq",
            "34996",
        ),
        make_claim(
            "P3-GRAPH-004",
            "The Phase 3 Docker graph had one weakly connected component.",
            graph_stats,
            "$.weakly_connected_components",
            "eq",
            "1",
        ),
        make_claim(
            "P3-GRAPH-005",
            "The largest weakly connected component contained all 12969 graph nodes.",
            graph_stats,
            "$.largest_component_nodes",
            "eq",
            "12969",
        ),
        make_claim(
            "P3-GRAPH-006",
            "The Phase 3 Docker graph was reported as weakly connected.",
            graph_stats,
            "$.is_weakly_connected",
            "eq",
            "true",
        ),
        make_claim(
            "P3-GRAPH-007",
            "The Phase 3 Docker SNAP index was reported as loaded.",
            graph_stats,
            "$.snap_index_loaded",
            "eq",
            "true",
        ),

        # ========================================================
        # HEALTH
        # ========================================================
        make_claim(
            "P3-HEALTH-001",
            "The Phase 3 Docker health artifact reported status ok.",
            health,
            "$.status",
            "eq",
            "ok",
        ),
        make_claim(
            "P3-HEALTH-002",
            "The Phase 3 Docker health artifact reported the graph as loaded.",
            health,
            "$.graph_loaded",
            "eq",
            "true",
        ),

        # ========================================================
        # CONNECTIVITY
        # ========================================================
        make_claim(
            "P3-CONNECT-001",
            "The Phase 3 connectivity audit reported one weakly connected component.",
            connectivity,
            "$.weakly_connected_components",
            "eq",
            "1",
            notes=(
                "Artifact is UTF-16-LE with BOM. Current content is valid JSON "
                "and its SHA-256 matches the Phase 12 collection."
            ),
        ),
        make_claim(
            "P3-CONNECT-002",
            "The Phase 3 connectivity audit reported that the largest weak component contains all 12969 nodes.",
            connectivity,
            "$.largest_weak_component_nodes",
            "eq",
            "12969",
            notes=(
                "UTF-16-LE+BOM JSON; do not interpret weak connectivity as "
                "universal directed reachability."
            ),
        ),
        make_claim(
            "P3-CONNECT-003",
            "The Phase 3 connectivity audit reported 12 strongly connected components.",
            connectivity,
            "$.strongly_connected_components",
            "eq",
            "12",
        ),
        make_claim(
            "P3-CONNECT-004",
            "The largest strongly connected component contained 12948 nodes.",
            connectivity,
            "$.largest_strong_component_nodes",
            "eq",
            "12948",
        ),
    ]


def main() -> None:
    collection = newest_collection()
    output = collection / "manifests" / "claim_register_phase3.csv"

    claims = build_claims()

    with output.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(claims)

    print()
    print("===============================================")
    print(" CityRoute Phase 12 Phase 3 Claim Preparation")
    print("===============================================")
    print()
    print(f"Claims prepared: {len(claims)}")
    print()
    print("Output:")
    print(f"  {output}")
    print()
    print("Boundaries:")
    print("  - No universal mathematical correctness claim.")
    print("  - No universal heuristic admissibility claim.")
    print("  - No claim that weak connectivity implies directed reachability.")
    print("  - No latency SLO claim is created.")
    print("  - No duplicate historical result tree is treated as an independent run.")
    print("  - Connectivity artifact is retained in its original encoding.")
    print()
    print("No claims evaluated.")
    print("No Phase 3 benchmark artifacts modified.")
    print()


if __name__ == "__main__":
    main()