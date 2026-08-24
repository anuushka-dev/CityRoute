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

output = manifests / "claim_register_phase7_7_1.csv"


CLAIMS = [
    {
        "claim_id": "P7-VRP-001",
        "phase": "phase7",
        "claim_text": (
            "The Docker 24-stop open-route 2-Opt benchmark "
            "preserved non-regression against the Greedy baseline."
        ),
        "source_audit": "CityRoute Tier 2 Phase 7 / 7.1 Formal Audit",
        "artifact_path": (
            "benchmarks/phase_7/docker_results/"
            "phase7_2opt_benchmark_24_stops_open.json"
        ),
        "json_pointer": "",
        "operator": "eq",
        "expected_value": "true",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": (
            "Audit explicitly identifies all_non_regression=true "
            "as the acceptance condition. Exact JSON pointer must "
            "be discovered from raw artifact."
        ),
    },
    {
        "claim_id": "P7-VRP-002",
        "phase": "phase7",
        "claim_text": (
            "The Docker 24-stop open-route 2-Opt benchmark "
            "reported 24 route legs."
        ),
        "source_audit": "CityRoute Tier 2 Phase 7 / 7.1 Formal Audit",
        "artifact_path": (
            "benchmarks/phase_7/docker_results/"
            "phase7_2opt_benchmark_24_stops_open.json"
        ),
        "json_pointer": "",
        "operator": "eq",
        "expected_value": "24",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": (
            "Audit acceptance criterion: open-route legs = stop_count."
        ),
    },
    {
        "claim_id": "P7-VRP-003",
        "phase": "phase7",
        "claim_text": (
            "The Docker 24-stop return-to-start 2-Opt benchmark "
            "reported 25 route legs."
        ),
        "source_audit": "CityRoute Tier 2 Phase 7 / 7.1 Formal Audit",
        "artifact_path": (
            "benchmarks/phase_7/docker_results/"
            "phase7_2opt_benchmark_24_stops_return_to_start.json"
        ),
        "json_pointer": "",
        "operator": "eq",
        "expected_value": "25",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": (
            "Audit acceptance criterion: return-route legs = stop_count + 1."
        ),
    },
    {
        "claim_id": "P7-VRP-004",
        "phase": "phase7",
        "claim_text": (
            "The Docker 24-stop open-route 2-Opt benchmark reports "
            "a recorded improvement_pct field."
        ),
        "source_audit": "CityRoute Tier 2 Phase 7 / 7.1 Formal Audit",
        "artifact_path": (
            "benchmarks/phase_7/docker_results/"
            "phase7_2opt_benchmark_24_stops_open.json"
        ),
        "json_pointer": "",
        "operator": "eq",
        "expected_value": "__FIELD_PRESENT__",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": (
            "This is a structural claim. The current verifier may "
            "need a field-presence extension after discovery."
        ),
    },
    {
        "claim_id": "P7-VRP-005",
        "phase": "phase7",
        "claim_text": (
            "The Docker 24-stop open-route 2-Opt benchmark reports "
            "the two-opt swap count and iteration count."
        ),
        "source_audit": "CityRoute Tier 2 Phase 7 / 7.1 Formal Audit",
        "artifact_path": (
            "benchmarks/phase_7/docker_results/"
            "phase7_2opt_benchmark_24_stops_open.json"
        ),
        "json_pointer": "",
        "operator": "eq",
        "expected_value": "__FIELDS_PRESENT__",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": (
            "Audit names two_opt_swaps_applied and "
            "two_opt_iterations. Exact raw paths must be discovered."
        ),
    },
    {
        "claim_id": "P7-VRP-006",
        "phase": "phase7",
        "claim_text": (
            "The Docker 24-stop return-to-start 2-Opt benchmark "
            "is represented in the accepted Phase 7 evidence set."
        ),
        "source_audit": "CityRoute Tier 2 Phase 7 / 7.1 Formal Audit",
        "artifact_path": (
            "benchmarks/phase_7/docker_results/"
            "phase7_2opt_benchmark_24_stops_return_to_start.json"
        ),
        "json_pointer": "$",
        "operator": "ne",
        "expected_value": "null",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": (
            "Basic artifact-presence claim. Exact benchmark fields "
            "will be separately audited."
        ),
    },
    {
        "claim_id": "P7-CACHE-001",
        "phase": "phase7_1",
        "claim_text": (
            "The official Phase 7.1 accepted Docker run reports "
            "a cache_status of hit."
        ),
        "source_audit": "CityRoute Tier 2 Phase 7 / 7.1 Formal Audit",
        "artifact_path": (
            "benchmarks/phase_7_1/docker_results/"
            "phase7_1_cache_observability_docker_71a95ee0.json"
        ),
        "json_pointer": "",
        "operator": "eq",
        "expected_value": "hit",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": (
            "Official latest accepted run from audit. Exact JSON "
            "pointer must be discovered."
        ),
    },
    {
        "claim_id": "P7-CACHE-002",
        "phase": "phase7_1",
        "claim_text": (
            "The official Phase 7.1 accepted Docker run reports "
            "cache_hits equal to 1."
        ),
        "source_audit": "CityRoute Tier 2 Phase 7 / 7.1 Formal Audit",
        "artifact_path": (
            "benchmarks/phase_7_1/docker_results/"
            "phase7_1_cache_observability_docker_71a95ee0.json"
        ),
        "json_pointer": "",
        "operator": "eq",
        "expected_value": "1",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": "",
    },
    {
        "claim_id": "P7-CACHE-003",
        "phase": "phase7_1",
        "claim_text": (
            "The official Phase 7.1 accepted Docker run reports "
            "cache_misses equal to 0."
        ),
        "source_audit": "CityRoute Tier 2 Phase 7 / 7.1 Formal Audit",
        "artifact_path": (
            "benchmarks/phase_7_1/docker_results/"
            "phase7_1_cache_observability_docker_71a95ee0.json"
        ),
        "json_pointer": "",
        "operator": "eq",
        "expected_value": "0",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": "",
    },
    {
        "claim_id": "P7-CACHE-004",
        "phase": "phase7_1",
        "claim_text": (
            "The official Phase 7.1 accepted Docker run reports "
            "cold-to-warm matrix generation speedup of 107.099x."
        ),
        "source_audit": "CityRoute Tier 2 Phase 7 / 7.1 Formal Audit",
        "artifact_path": (
            "benchmarks/phase_7_1/docker_results/"
            "phase7_1_cache_observability_docker_71a95ee0.json"
        ),
        "json_pointer": "",
        "operator": "eq",
        "expected_value": "107.099",
        "tolerance": "0.001",
        "provenance_source_artifact": "",
        "notes": (
            "Official accepted run, not supporting run 59cc8d64."
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
print(" CityRoute Phase 12 Phase 7 + 7.1 Claim Prep")
print("===============================================")
print()
print(f"Claims prepared: {len(CLAIMS)}")
print()
print("Output:")
print(f"  {output}")
print()
print("No claims evaluated.")
print("No benchmark artifacts modified.")
print()