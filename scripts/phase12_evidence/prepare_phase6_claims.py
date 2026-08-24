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
output = manifests / "claim_register.csv"


CLAIMS = [
    {
        "claim_id": "P6-OPEN-001",
        "phase": "phase6",
        "claim_text": (
            "The Docker 24-stop open-route load probe recorded "
            "20 successful requests."
        ),
        "source_audit": "CityRoute Tier 2 Phase 6 Formal Audit",
        "artifact_path": (
            "benchmarks/phase_6/docker_results/"
            "phase6_greedy_load_probe_24_stops_open_docker.json"
        ),
        "json_pointer": "",
        "operator": "eq",
        "expected_value": "20",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": (
            "Exact JSON field must be discovered from the artifact."
        ),
    },
    {
        "claim_id": "P6-OPEN-002",
        "phase": "phase6",
        "claim_text": (
            "The Docker 24-stop open-route load probe had "
            "0 failed requests."
        ),
        "source_audit": "CityRoute Tier 2 Phase 6 Formal Audit",
        "artifact_path": (
            "benchmarks/phase_6/docker_results/"
            "phase6_greedy_load_probe_24_stops_open_docker.json"
        ),
        "json_pointer": "",
        "operator": "eq",
        "expected_value": "0",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": "",
    },
    {
        "claim_id": "P6-OPEN-003",
        "phase": "phase6",
        "claim_text": (
            "The Docker 24-stop open-route load probe recorded "
            "100% success rate."
        ),
        "source_audit": "CityRoute Tier 2 Phase 6 Formal Audit",
        "artifact_path": (
            "benchmarks/phase_6/docker_results/"
            "phase6_greedy_load_probe_24_stops_open_docker.json"
        ),
        "json_pointer": "",
        "operator": "eq",
        "expected_value": "100",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": "",
    },
    {
        "claim_id": "P6-OPEN-004",
        "phase": "phase6",
        "claim_text": (
            "The Docker 24-stop open-route load probe recorded "
            "20 valid optimized route orders."
        ),
        "source_audit": "CityRoute Tier 2 Phase 6 Formal Audit",
        "artifact_path": (
            "benchmarks/phase_6/docker_results/"
            "phase6_greedy_load_probe_24_stops_open_docker.json"
        ),
        "json_pointer": "",
        "operator": "eq",
        "expected_value": "20",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": (
            "The audit reports valid order checks; exact raw field "
            "must be discovered."
        ),
    },
    {
        "claim_id": "P6-RETURN-001",
        "phase": "phase6",
        "claim_text": (
            "The Docker 24-stop return-to-start load probe recorded "
            "20 successful requests."
        ),
        "source_audit": "CityRoute Tier 2 Phase 6 Formal Audit",
        "artifact_path": (
            "benchmarks/phase_6/docker_results/"
            "phase6_greedy_load_probe_24_stops_return_to_start_docker.json"
        ),
        "json_pointer": "",
        "operator": "eq",
        "expected_value": "20",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": "",
    },
    {
        "claim_id": "P6-RETURN-002",
        "phase": "phase6",
        "claim_text": (
            "The Docker 24-stop return-to-start load probe recorded "
            "0 failed requests."
        ),
        "source_audit": "CityRoute Tier 2 Phase 6 Formal Audit",
        "artifact_path": (
            "benchmarks/phase_6/docker_results/"
            "phase6_greedy_load_probe_24_stops_return_to_start_docker.json"
        ),
        "json_pointer": "",
        "operator": "eq",
        "expected_value": "0",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": "",
    },
    {
        "claim_id": "P6-RETURN-003",
        "phase": "phase6",
        "claim_text": (
            "The Docker 24-stop return-to-start load probe recorded "
            "100% success rate."
        ),
        "source_audit": "CityRoute Tier 2 Phase 6 Formal Audit",
        "artifact_path": (
            "benchmarks/phase_6/docker_results/"
            "phase6_greedy_load_probe_24_stops_return_to_start_docker.json"
        ),
        "json_pointer": "",
        "operator": "eq",
        "expected_value": "100",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": "",
    },
    {
        "claim_id": "P6-EDGE-001",
        "phase": "phase6",
        "claim_text": (
            "The Docker Phase 6.1 edge-case suite passed all "
            "seven defined cases."
        ),
        "source_audit": "CityRoute Tier 2 Phase 6 Formal Audit",
        "artifact_path": (
            "benchmarks/phase_6/docker_results/"
            "phase6_greedy_edge_cases_docker.json"
        ),
        "json_pointer": "",
        "operator": "eq",
        "expected_value": "true",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": (
            "The audit reports all_cases_passed=true."
        ),
    },
    {
        "claim_id": "P6-EDGE-002",
        "phase": "phase6",
        "claim_text": (
            "The Docker Phase 6.1 edge-case suite recorded "
            "zero failed cases."
        ),
        "source_audit": "CityRoute Tier 2 Phase 6 Formal Audit",
        "artifact_path": (
            "benchmarks/phase_6/docker_results/"
            "phase6_greedy_edge_cases_docker.json"
        ),
        "json_pointer": "",
        "operator": "eq",
        "expected_value": "0",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": "",
    },
    {
        "claim_id": "P6-BOUNDARY-001",
        "phase": "phase6",
        "claim_text": (
            "The Docker 24-stop open-route probe rejected the "
            "invalid 25-stop request with HTTP 422."
        ),
        "source_audit": "CityRoute Tier 2 Phase 6 Formal Audit",
        "artifact_path": (
            "benchmarks/phase_6/docker_results/"
            "phase6_greedy_load_probe_24_stops_open_docker.json"
        ),
        "json_pointer": "",
        "operator": "eq",
        "expected_value": "422",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": (
            "Exact JSON representation of invalid-limit response "
            "must be discovered."
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
print(" CityRoute Phase 12 Phase 6 Claim Preparation")
print("===============================================")
print()
print(f"Claims prepared: {len(CLAIMS)}")
print()
print("Output:")
print(f"  {output}")
print()
print("json_pointer intentionally left blank.")
print("No claims have been evaluated.")
print("No benchmark evidence was modified.")
print()