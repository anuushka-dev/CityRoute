from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path.cwd()
EVIDENCE_ROOT = ROOT / ".phase12_evidence"


collections = sorted(
    EVIDENCE_ROOT.glob("collection_*"),
    key=lambda p: p.name,
    reverse=True,
)

if not collections:
    raise SystemExit("No Phase 12 collection found.")

collection = collections[0]
manifests = collection / "manifests"

output = (
    manifests
    / "claim_register_phase8.csv"
)


CLAIMS = [
    {
        "claim_id": "P8-OPEN-001",
        "phase": "phase8",
        "claim_text": (
            "The Phase 8 Docker open-route LNS benchmark "
            "had successful results in all four tested size groups."
        ),
        "source_audit": "CityRoute Phase 8 LNS Evidence",
        "artifact_path": (
            "benchmarks/phase_8/docker_results/"
            "phase8_lns_benchmark_summary_docker_open_20260702_134528.json"
        ),
        "json_pointer": "$.overall.all_groups_have_success",
        "operator": "eq",
        "expected_value": "true",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": (
            "Uses the actual LNS Docker open-route summary."
        ),
    },
    {
        "claim_id": "P8-OPEN-002",
        "phase": "phase8",
        "claim_text": (
            "The Phase 8 Docker open-route LNS benchmark "
            "reported non-regression for all successful groups."
        ),
        "source_audit": "CityRoute Phase 8 LNS Evidence",
        "artifact_path": (
            "benchmarks/phase_8/docker_results/"
            "phase8_lns_benchmark_summary_docker_open_20260702_134528.json"
        ),
        "json_pointer": "$.overall.all_successes_lns_non_regression",
        "operator": "eq",
        "expected_value": "true",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": "",
    },
    {
        "claim_id": "P8-OPEN-003",
        "phase": "phase8",
        "claim_text": (
            "The Phase 8 Docker 24-stop open-route LNS group "
            "recorded 5 successful attempts."
        ),
        "source_audit": "CityRoute Phase 8 LNS Evidence",
        "artifact_path": (
            "benchmarks/phase_8/docker_results/"
            "phase8_lns_benchmark_summary_docker_open_20260702_134528.json"
        ),
        "json_pointer": (
            "$.group_summaries.24_stops_open.success_count"
        ),
        "operator": "eq",
        "expected_value": "5",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": "",
    },
    {
        "claim_id": "P8-OPEN-004",
        "phase": "phase8",
        "claim_text": (
            "The Phase 8 Docker 24-stop open-route LNS benchmark "
            "reported 13.611% median improvement over Greedy."
        ),
        "source_audit": "CityRoute Phase 8 LNS Evidence",
        "artifact_path": (
            "benchmarks/phase_8/docker_results/"
            "phase8_lns_benchmark_summary_docker_open_20260702_134528.json"
        ),
        "json_pointer": (
            "$.group_summaries.24_stops_open."
            "lns_vs_greedy_improvement_pct.median"
        ),
        "operator": "eq",
        "expected_value": "13.611",
        "tolerance": "0.001",
        "provenance_source_artifact": "",
        "notes": "",
    },
    {
        "claim_id": "P8-OPEN-005",
        "phase": "phase8",
        "claim_text": (
            "The Phase 8 Docker 24-stop open-route LNS benchmark "
            "reported 3.11% median improvement over 2-Opt."
        ),
        "source_audit": "CityRoute Phase 8 LNS Evidence",
        "artifact_path": (
            "benchmarks/phase_8/docker_results/"
            "phase8_lns_benchmark_summary_docker_open_20260702_134528.json"
        ),
        "json_pointer": (
            "$.group_summaries.24_stops_open."
            "lns_vs_two_opt_improvement_pct.median"
        ),
        "operator": "eq",
        "expected_value": "3.11",
        "tolerance": "0.001",
        "provenance_source_artifact": "",
        "notes": "",
    },
    {
        "claim_id": "P8-RETURN-001",
        "phase": "phase8",
        "claim_text": (
            "The Phase 8 Docker return-to-start LNS benchmark "
            "had successful results in all four tested size groups."
        ),
        "source_audit": "CityRoute Phase 8 LNS Evidence",
        "artifact_path": (
            "benchmarks/phase_8/docker_results/"
            "phase8_lns_benchmark_summary_docker_return_20260702_134538.json"
        ),
        "json_pointer": "$.overall.all_groups_have_success",
        "operator": "eq",
        "expected_value": "true",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": "",
    },
    {
        "claim_id": "P8-RETURN-002",
        "phase": "phase8",
        "claim_text": (
            "The Phase 8 Docker 24-stop return-to-start LNS group "
            "recorded 5 successful attempts."
        ),
        "source_audit": "CityRoute Phase 8 LNS Evidence",
        "artifact_path": (
            "benchmarks/phase_8/docker_results/"
            "phase8_lns_benchmark_summary_docker_return_20260702_134538.json"
        ),
        "json_pointer": (
            "$.group_summaries.24_stops_return.success_count"
        ),
        "operator": "eq",
        "expected_value": "5",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": "",
    },
    {
        "claim_id": "P8-RETURN-003",
        "phase": "phase8",
        "claim_text": (
            "The Phase 8 Docker 24-stop return-to-start LNS "
            "benchmark reported 12.284% median improvement over Greedy."
        ),
        "source_audit": "CityRoute Phase 8 LNS Evidence",
        "artifact_path": (
            "benchmarks/phase_8/docker_results/"
            "phase8_lns_benchmark_summary_docker_return_20260702_134538.json"
        ),
        "json_pointer": (
            "$.group_summaries.24_stops_return."
            "lns_vs_greedy_improvement_pct.median"
        ),
        "operator": "eq",
        "expected_value": "12.284",
        "tolerance": "0.001",
        "provenance_source_artifact": "",
        "notes": "",
    },
    {
        "claim_id": "P8-RETURN-004",
        "phase": "phase8",
        "claim_text": (
            "The Phase 8 Docker 24-stop return-to-start LNS "
            "benchmark reported 2.952% median improvement over 2-Opt."
        ),
        "source_audit": "CityRoute Phase 8 LNS Evidence",
        "artifact_path": (
            "benchmarks/phase_8/docker_results/"
            "phase8_lns_benchmark_summary_docker_return_20260702_134538.json"
        ),
        "json_pointer": (
            "$.group_summaries.24_stops_return."
            "lns_vs_two_opt_improvement_pct.median"
        ),
        "operator": "eq",
        "expected_value": "2.952",
        "tolerance": "0.001",
        "provenance_source_artifact": "",
        "notes": "",
    },
    {
        "claim_id": "P8-GAP-001",
        "phase": "phase8",
        "claim_text": (
            "The Phase 8 Docker exact-small-case optimality-gap "
            "benchmark reported all six cases successful."
        ),
        "source_audit": "CityRoute Phase 8 LNS Optimality Gap Evidence",
        "artifact_path": (
            "benchmarks/phase_8/docker_results/"
            "phase8_lns_optimality_gap_summary_docker_20260702_135443.json"
        ),
        "json_pointer": "$.quality_flags.all_cases_successful",
        "operator": "eq",
        "expected_value": "true",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": "",
    },
    {
        "claim_id": "P8-GAP-002",
        "phase": "phase8",
        "claim_text": (
            "The Phase 8 Docker exact-small-case optimality-gap "
            "benchmark reported that all LNS results were at or "
            "above the exact optimum."
        ),
        "source_audit": "CityRoute Phase 8 LNS Optimality Gap Evidence",
        "artifact_path": (
            "benchmarks/phase_8/docker_results/"
            "phase8_lns_optimality_gap_summary_docker_20260702_135443.json"
        ),
        "json_pointer": "$.quality_flags.all_lns_at_or_above_exact",
        "operator": "eq",
        "expected_value": "true",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": (
            "This does not claim global optimality for arbitrary N; "
            "it refers only to the six exact-small cases in this artifact."
        ),
    },
    {
        "claim_id": "P8-GAP-003",
        "phase": "phase8",
        "claim_text": (
            "The Phase 8 Docker exact-small-case optimality-gap "
            "benchmark reported LNS worst optimality gap of 0.0%."
        ),
        "source_audit": "CityRoute Phase 8 LNS Optimality Gap Evidence",
        "artifact_path": (
            "benchmarks/phase_8/docker_results/"
            "phase8_lns_optimality_gap_summary_docker_20260702_135443.json"
        ),
        "json_pointer": "$.gap_summary_pct.lns_worst",
        "operator": "eq",
        "expected_value": "0",
        "tolerance": "0",
        "provenance_source_artifact": "",
        "notes": (
            "Only the six exact-small cases represented in this artifact."
        ),
    },
]


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
    writer.writerows(CLAIMS)


print()
print("===============================================")
print(" CityRoute Phase 12 Phase 8 Claim Preparation")
print("===============================================")
print()
print(f"Claims prepared: {len(CLAIMS)}")
print()
print("Output:")
print(f"  {output}")
print()
print(
    "The two zero-byte Phase 8 combined_raw artifacts "
    "are intentionally excluded."
)
print(
    "No claims evaluated."
)
print(
    "No benchmark artifacts modified."
)
print()