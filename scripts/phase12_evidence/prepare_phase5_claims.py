from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path.cwd()

EVIDENCE_ROOT = ROOT / ".phase12_evidence"

COLLECTIONS = sorted(
    EVIDENCE_ROOT.glob("collection_*"),
    key=lambda p: p.name,
    reverse=True,
)

if not COLLECTIONS:
    raise SystemExit("No Phase 12 collection found.")

COLLECTION = COLLECTIONS[0]

MANIFESTS = COLLECTION / "manifests"

OUTPUT = MANIFESTS / "claim_register.csv"


CLAIMS = [
    {
        "claim_id": "P5-CACHE-001",
        "phase": "phase5",
        "claim_text": (
            "Normal benchmark Redis cache-hit medians remain "
            "under the 20 ms target."
        ),
        "source_audit": "CityRoute Tier 2 Phase 5 Audit",
        "artifact_path": (
            "benchmarks/phase5/local_results/"
            "phase5_cache_probe_15x15.json"
        ),
        "json_pointer": "",
        "operator": "lt",
        "expected_value": "20",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": (
            "Candidate claim only. Exact JSON field must be "
            "resolved before verification. Audit reports 15x15 "
            "local cache-hit median 11.426 ms."
        ),
    },
    {
        "claim_id": "P5-CACHE-002",
        "phase": "phase5",
        "claim_text": (
            "Docker normal benchmark Redis cache-hit median "
            "remains under the 20 ms target."
        ),
        "source_audit": "CityRoute Tier 2 Phase 5 Audit",
        "artifact_path": (
            "benchmarks/phase5/docker_results/"
            "phase5_cache_probe_15x15.json"
        ),
        "json_pointer": "",
        "operator": "lt",
        "expected_value": "20",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": (
            "Candidate claim only. Exact JSON field must be "
            "resolved before verification. Audit reports 15x15 "
            "Docker cache-hit median 8.114 ms."
        ),
    },
    {
        "claim_id": "P5-CORRECTNESS-001",
        "phase": "phase5",
        "claim_text": (
            "The 15x15 local matrix correctness benchmark reports "
            "zero route mismatches."
        ),
        "source_audit": "CityRoute Tier 2 Phase 5 Audit",
        "artifact_path": (
            "benchmarks/phase5/local_results/"
            "phase5_matrix_correctness_15x15.json"
        ),
        "json_pointer": "",
        "operator": "eq",
        "expected_value": "0",
        "tolerance": "0",
        "provenance_source_artifact": "",
        "notes": (
            "Candidate claim only. Exact JSON field must be "
            "resolved before verification."
        ),
    },
    {
        "claim_id": "P5-CORRECTNESS-002",
        "phase": "phase5",
        "claim_text": (
            "The 15x15 Docker matrix correctness benchmark reports "
            "zero route mismatches."
        ),
        "source_audit": "CityRoute Tier 2 Phase 5 Audit",
        "artifact_path": (
            "benchmarks/phase5/docker_results/"
            "phase5_matrix_correctness_15x15.json"
        ),
        "json_pointer": "",
        "operator": "eq",
        "expected_value": "0",
        "tolerance": "0",
        "provenance_source_artifact": "",
        "notes": (
            "Candidate claim only. Exact JSON field must be "
            "resolved before verification."
        ),
    },
    {
        "claim_id": "P5-THREADING-001",
        "phase": "phase5",
        "claim_text": (
            "The original local threaded pairwise matrix approach "
            "did not achieve the 4x speedup target at 15x15."
        ),
        "source_audit": "CityRoute Tier 2 Phase 5 Audit",
        "artifact_path": (
            "benchmarks/phase5/local_results/"
            "phase5_parallel_vs_serial_15x15.json"
        ),
        "json_pointer": "",
        "operator": "lt",
        "expected_value": "4",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": (
            "Candidate claim only. Exact speedup field must be "
            "resolved before verification. Audit reports 0.674x."
        ),
    },
    {
        "claim_id": "P5-THREADING-002",
        "phase": "phase5",
        "claim_text": (
            "The original Docker threaded pairwise matrix approach "
            "did not achieve the 4x speedup target at 15x15."
        ),
        "source_audit": "CityRoute Tier 2 Phase 5 Audit",
        "artifact_path": (
            "benchmarks/phase5/docker_results/"
            "phase5_parallel_vs_serial_15x15.json"
        ),
        "json_pointer": "",
        "operator": "lt",
        "expected_value": "4",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": (
            "Candidate claim only. Exact speedup field must be "
            "resolved before verification. Audit reports 0.688x."
        ),
    },
    {
        "claim_id": "P5-SDIJKSTRA-001",
        "phase": "phase5",
        "claim_text": (
            "Source-Dijkstra achieved at least 4x speedup over "
            "bidirectional A* at 15x15 locally."
        ),
        "source_audit": "CityRoute Tier 2 Phase 5 Audit",
        "artifact_path": (
            "benchmarks/phase5_1/local_results/"
            "phase5_1_algorithm_comparison_15x15.json"
        ),
        "json_pointer": "",
        "operator": "ge",
        "expected_value": "4",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": (
            "Candidate claim only. Exact speedup field must be "
            "resolved before verification. Audit reports 6.677x."
        ),
    },
    {
        "claim_id": "P5-SDIJKSTRA-002",
        "phase": "phase5",
        "claim_text": (
            "Source-Dijkstra achieved at least 4x speedup over "
            "bidirectional A* at 15x15 in Docker."
        ),
        "source_audit": "CityRoute Tier 2 Phase 5 Audit",
        "artifact_path": (
            "benchmarks/phase5_1/docker_results/"
            "phase5_1_algorithm_comparison_15x15.json"
        ),
        "json_pointer": "",
        "operator": "ge",
        "expected_value": "4",
        "tolerance": "",
        "provenance_source_artifact": "",
        "notes": (
            "Candidate claim only. Exact speedup field must be "
            "resolved before verification. Audit reports 6.832x."
        ),
    },
    {
        "claim_id": "P5-SDIJKSTRA-CORRECT-001",
        "phase": "phase5",
        "claim_text": (
            "The 15x15 local Source-Dijkstra correctness test "
            "reports zero matrix mismatches."
        ),
        "source_audit": "CityRoute Tier 2 Phase 5 Audit",
        "artifact_path": (
            "benchmarks/phase5_1/local_results/"
            "phase5_1_source_dijkstra_correctness_15x15.json"
        ),
        "json_pointer": "",
        "operator": "eq",
        "expected_value": "0",
        "tolerance": "0",
        "provenance_source_artifact": "",
        "notes": (
            "Candidate claim only. Exact mismatch field must be "
            "resolved before verification."
        ),
    },
    {
        "claim_id": "P5-SDIJKSTRA-CORRECT-002",
        "phase": "phase5",
        "claim_text": (
            "The 15x15 Docker Source-Dijkstra correctness test "
            "reports zero matrix mismatches."
        ),
        "source_audit": "CityRoute Tier 2 Phase 5 Audit",
        "artifact_path": (
            "benchmarks/phase5_1/docker_results/"
            "phase5_1_source_dijkstra_correctness_15x15.json"
        ),
        "json_pointer": "",
        "operator": "eq",
        "expected_value": "0",
        "tolerance": "0",
        "provenance_source_artifact": "",
        "notes": (
            "Candidate claim only. Exact mismatch field must be "
            "resolved before verification."
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


with OUTPUT.open(
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
print(" CityRoute Phase 12 Phase 5 Claim Preparation")
print("===============================================")
print()
print(f"Claims prepared: {len(CLAIMS)}")
print()
print(f"Output:")
print(f"  {OUTPUT}")
print()
print(
    "IMPORTANT: json_pointer is intentionally blank."
)
print(
    "No claim is ready for verification until the exact"
)
print(
    "JSON field is resolved from the actual artifact."
)
print()