from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path.cwd()
PHASE12_ROOT = ROOT / ".phase12_evidence"
PHASE4_ROOT = ROOT / "benchmarks" / "phase4_results"

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


def ensure_artifact(relative_path: str) -> str:
    path = ROOT / relative_path

    if not path.exists():
        raise FileNotFoundError(
            f"Required Phase 4 artifact does not exist: {path}"
        )

    return relative_path.replace("\\", "/")


def build_claim(
    claim_id: str,
    text: str,
    artifact_path: str,
    json_pointer: str,
    operator: str,
    expected_value: str,
    *,
    tolerance: str = "",
    notes: str = "",
    provenance: str = "",
) -> dict[str, str]:
    return {
        "claim_id": claim_id,
        "phase": "phase4",
        "claim_text": text,
        "source_audit": "CityRoute Historical Phase 4 Evidence",
        "artifact_path": artifact_path,
        "json_pointer": json_pointer,
        "operator": operator,
        "expected_value": expected_value,
        "tolerance": tolerance,
        "provenance_source_artifact": provenance,
        "notes": notes,
    }


def build_claims(collection: Path) -> list[dict[str, str]]:
    manifest_hashes = (
        collection
        / "manifests"
        / "sha256_manifest.csv"
    )

    if not manifest_hashes.exists():
        raise FileNotFoundError(
            f"Missing SHA-256 manifest: {manifest_hashes}"
        )

    graph_stats = ensure_artifact(
        "benchmarks/phase4_results/phase4_docker_graph_stats.json"
    )
    health = ensure_artifact(
        "benchmarks/phase4_results/phase4_docker_health.json"
    )
    route_summary = ensure_artifact(
        "benchmarks/phase4_results/phase4_route_compare_summary.json"
    )
    benchmark = ensure_artifact(
        "benchmarks/phase4_results/phase4_bidirectional_astar_benchmark.json"
    )
    correctness = ensure_artifact(
        "benchmarks/phase4_results/phase4_bidirectional_astar_correctness_probe.json"
    )
    pytest_output = ensure_artifact(
        "benchmarks/phase4_results/phase4_full_pytest.txt"
    )

    claims: list[dict[str, str]] = []

    # ------------------------------------------------------------
    # GRAPH / DOCKER
    # ------------------------------------------------------------

    claims.extend(
        [
            build_claim(
                "P4-GRAPH-001",
                "The Phase 4 Docker graph was reported as loaded.",
                graph_stats,
                "$.graph_loaded",
                "eq",
                "true",
            ),
            build_claim(
                "P4-GRAPH-002",
                "The Phase 4 Docker graph contained 12969 nodes.",
                graph_stats,
                "$.nodes",
                "eq",
                "12969",
            ),
            build_claim(
                "P4-GRAPH-003",
                "The Phase 4 Docker graph contained 34996 edges.",
                graph_stats,
                "$.edges",
                "eq",
                "34996",
            ),
            build_claim(
                "P4-GRAPH-004",
                "The Phase 4 Docker graph was reported as weakly connected.",
                graph_stats,
                "$.is_weakly_connected",
                "eq",
                "true",
            ),
            build_claim(
                "P4-GRAPH-005",
                "The Phase 4 SNAP index was reported as loaded.",
                graph_stats,
                "$.snap_index_loaded",
                "eq",
                "true",
            ),
            build_claim(
                "P4-HEALTH-001",
                "The Phase 4 Docker health endpoint reported status ok.",
                health,
                "$.status",
                "eq",
                "ok",
            ),
            build_claim(
                "P4-HEALTH-002",
                "The Phase 4 Docker health artifact reported the graph as loaded.",
                health,
                "$.graph_loaded",
                "eq",
                "true",
            ),
        ]
    )

    # ------------------------------------------------------------
    # ROUTE-COMPARE API
    # ------------------------------------------------------------

    claims.extend(
        [
            build_claim(
                "P4-API-001",
                "The Phase 4 route-compare probe received a successful response.",
                route_summary,
                "$.status",
                "eq",
                "ok",
            ),
            build_claim(
                "P4-API-002",
                "The Phase 4 route-compare response contained an A* section.",
                route_summary,
                "$.verification.astar_section_present",
                "eq",
                "true",
            ),
            build_claim(
                "P4-API-003",
                "The Phase 4 route-compare response contained a Bidirectional A* section.",
                route_summary,
                "$.verification.bidirectional_astar_section_present",
                "eq",
                "true",
            ),
            build_claim(
                "P4-API-004",
                "The Phase 4 route-compare response contained a comparison section.",
                route_summary,
                "$.verification.comparison_section_present",
                "eq",
                "true",
            ),
            build_claim(
                "P4-API-005",
                "The Phase 4 route comparison reported matching distances between A* and Bidirectional A*.",
                route_summary,
                "$.comparison.same_distance",
                "eq",
                "true",
            ),
            build_claim(
                "P4-API-006",
                "The Phase 4 route comparison reported the distance delta within tolerance.",
                route_summary,
                "$.verification.distance_delta_within_tolerance",
                "eq",
                "true",
            ),
            build_claim(
                "P4-API-007",
                "The Phase 4 route comparison reported BallTree snapping.",
                route_summary,
                "$.verification.uses_balltree_snapping",
                "eq",
                "true",
            ),
            build_claim(
                "P4-API-008",
                "The Phase 4 Docker route-compare API was reported as working.",
                route_summary,
                "$.verification.docker_api_route_compare_working",
                "eq",
                "true",
            ),
        ]
    )

    # ------------------------------------------------------------
    # SINGLE-SAMPLE COMPARISON
    # ------------------------------------------------------------

    claims.extend(
        [
            build_claim(
                "P4-SAMPLE-001",
                "The Phase 4 sample route comparison reported zero distance delta.",
                route_summary,
                "$.comparison.distance_delta_m",
                "eq",
                "0",
                tolerance="0",
                notes=(
                    "This is a single sampled route comparison, not a "
                    "universal performance claim."
                ),
            ),
            build_claim(
                "P4-SAMPLE-002",
                "The Phase 4 sample route comparison reported Bidirectional A* faster than A*.",
                route_summary,
                "$.comparison.bidirectional_faster",
                "eq",
                "true",
                notes=(
                    "Single sample only; not generalized to all routes."
                ),
            ),
            build_claim(
                "P4-SAMPLE-003",
                "The Phase 4 sample route comparison reported 27.083% route-time reduction.",
                route_summary,
                "$.comparison.route_time_reduction_pct",
                "eq",
                "27.083",
                tolerance="0.001",
                notes=(
                    "Single sample only; not representative of the full "
                    "1000-measurement benchmark."
                ),
            ),
            build_claim(
                "P4-SAMPLE-004",
                "The Phase 4 sample route comparison reported 44.394% node-expansion reduction.",
                route_summary,
                "$.comparison.nodes_expanded_reduction_pct",
                "eq",
                "44.394",
                tolerance="0.001",
                notes=(
                    "Single sample only; not representative of every route."
                ),
            ),
        ]
    )

    # ------------------------------------------------------------
    # 1000-MEASUREMENT BIDIRECTIONAL-A* BENCHMARK
    # ------------------------------------------------------------

    claims.extend(
        [
            build_claim(
                "P4-BENCH-001",
                "The Phase 4 Bidirectional A* benchmark recorded 1000 successful route measurements.",
                benchmark,
                "$.successful_route_measurements",
                "eq",
                "1000",
            ),
            build_claim(
                "P4-BENCH-002",
                "The Phase 4 Bidirectional A* benchmark recorded zero real failures.",
                benchmark,
                "$.real_failures",
                "eq",
                "0",
            ),
            build_claim(
                "P4-BENCH-003",
                "The Phase 4 Bidirectional A* benchmark reported a 0.0% real failure rate.",
                benchmark,
                "$.real_failure_rate_pct",
                "eq",
                "0",
            ),
            build_claim(
                "P4-BENCH-004",
                "The Phase 4 Bidirectional A* benchmark recorded 8 no-path 404 cases.",
                benchmark,
                "$.no_path_404_skipped",
                "eq",
                "8",
                notes=(
                    "These are recorded as no-path cases and are distinct "
                    "from real benchmark failures."
                ),
            ),
            build_claim(
                "P4-BENCH-005",
                "The Phase 4 Bidirectional A* benchmark reported zero aggregate distance delta.",
                benchmark,
                "$.distance_delta_m.max",
                "eq",
                "0",
                tolerance="0",
                notes=(
                    "The aggregate artifact reports zero max distance delta."
                ),
            ),
        ]
    )

    # ------------------------------------------------------------
    # PERFORMANCE: BOUNDED, NOT UNIVERSAL
    # ------------------------------------------------------------

    claims.extend(
        [
            build_claim(
                "P4-PERF-001",
                "The Phase 4 benchmark reported a median node-expansion reduction of 15.642%.",
                benchmark,
                "$.nodes_expanded_reduction_pct.median",
                "eq",
                "15.642",
                tolerance="0.001",
                notes=(
                    "Median measured result; does not imply improvement "
                    "for every route."
                ),
            ),
            build_claim(
                "P4-PERF-002",
                "The Phase 4 benchmark reported a median route-time reduction of -40.861%.",
                benchmark,
                "$.route_time_reduction_pct.median",
                "eq",
                "-40.861",
                tolerance="0.001",
                notes=(
                    "Negative value indicates that the benchmark's route-time "
                    "reduction metric was negative at the median. This is "
                    "explicitly retained rather than converted into a "
                    "Bidirectional-A*-is-faster claim."
                ),
            ),
            build_claim(
                "P4-PERF-003",
                "The Phase 4 benchmark explicitly documented that Bidirectional A* should not be assumed to be always faster.",
                benchmark,
                "$.targets.benchmark_goal",
                "eq",
                (
                    "Compare A* vs Bidirectional A* timing and node expansion; "
                    "do not assume Bidirectional A* is always faster."
                ),
                notes=(
                    "This verifies the benchmark's stated scope rather than "
                    "a performance result."
                ),
            ),
        ]
    )

    # ------------------------------------------------------------
    # DEDICATED CORRECTNESS PROBE
    # ------------------------------------------------------------

    claims.extend(
        [
            build_claim(
                "P4-CORRECT-001",
                "The Phase 4 Bidirectional A* correctness probe executed 500 target checks.",
                correctness,
                "$.target_checks",
                "eq",
                "500",
            ),
            build_claim(
                "P4-CORRECT-002",
                "The Phase 4 Bidirectional A* correctness probe passed all 500 target checks.",
                correctness,
                "$.passed",
                "eq",
                "500",
            ),
            build_claim(
                "P4-CORRECT-003",
                "The Phase 4 Bidirectional A* correctness probe recorded zero failed checks.",
                correctness,
                "$.failed",
                "eq",
                "0",
            ),
            build_claim(
                "P4-CORRECT-004",
                "The Phase 4 Bidirectional A* correctness probe reported a 100% success rate.",
                correctness,
                "$.success_rate_pct",
                "eq",
                "100",
                tolerance="0.001",
            ),
            build_claim(
                "P4-CORRECT-005",
                "The Phase 4 Bidirectional A* correctness probe reported no errors.",
                correctness,
                "$.errors",
                "eq",
                "[]",
                notes=(
                    "Verifier support for array-valued equality is required. "
                    "If unsupported, this claim should be removed rather than "
                    "loosening the evidence standard."
                ),
            ),
        ]
    )

    # ------------------------------------------------------------
    # TEST SUITE
    # ------------------------------------------------------------

    claims.extend(
        [
            build_claim(
                "P4-TEST-001",
                "The recorded Phase 4 pytest run collected 81 tests.",
                pytest_output,
                "$.pytest.collected",
                "eq",
                "81",
                notes=(
                    "This artifact is plain text, so this claim requires a "
                    "verifier path capable of structured extraction from the "
                    "pytest console text. It is intentionally included only "
                    "if the verifier supports text-derived fields."
                ),
            ),
            build_claim(
                "P4-TEST-002",
                "The recorded Phase 4 pytest run reported 81 passed tests.",
                pytest_output,
                "$.pytest.passed",
                "eq",
                "81",
                notes=(
                    "Same text-artifact limitation as P4-TEST-001."
                ),
            ),
        ]
    )

    return claims


def main() -> None:
    print()
    print("===============================================")
    print(" CityRoute Phase 12 Phase 4 Claim Preparation")
    print("===============================================")
    print()

    collection = newest_collection()
    output = collection / "manifests" / "claim_register_phase4.csv"

    claims = build_claims(collection)

    with output.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=FIELDS,
        )
        writer.writeheader()
        writer.writerows(claims)

    print(f"Claims prepared: {len(claims)}")
    print()
    print("Output:")
    print(f"  {output}")
    print()
    print("Boundaries:")
    print("  - No universal Bidirectional-A* performance claim.")
    print("  - No universal mathematical correctness claim.")
    print("  - No claim that no-path pairs are benchmark failures.")
    print("  - Single-sample performance claims remain explicitly bounded.")
    print("  - Text-artifact claims require verifier support for structured text extraction.")
    print()
    print("No claims evaluated.")
    print("No Phase 4 artifacts modified.")
    print()


if __name__ == "__main__":
    main()