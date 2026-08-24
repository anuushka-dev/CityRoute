from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path.cwd()
EVIDENCE_ROOT = ROOT / ".phase12_evidence"


def newest_collection() -> Path:
    collections = sorted(
        EVIDENCE_ROOT.glob("collection_*"),
        key=lambda p: p.name,
        reverse=True,
    )

    if not collections:
        raise FileNotFoundError(
            "No Phase 12 collection found."
        )

    return collections[0]


def main() -> None:
    collection = newest_collection()
    manifests = collection / "manifests"

    output = (
        manifests
        / "claim_register_phase9.csv"
    )

    # These are limited to claims directly supported by
    # the Phase 9 dispatch benchmark evidence already identified.
    claims = [
        {
            "claim_id": "P9-DISPATCH-001",
            "phase": "phase9",
            "claim_text": (
                "The Docker Phase 9 /dispatch/compare benchmark "
                "completed 80 benchmark cases successfully."
            ),
            "source_audit": "CityRoute Tier 3 Phase 9 Evidence",
            "artifact_path": (
                "benchmarks/phase_9/docker_results/"
                "phase9_dispatch_endpoint_raw_docker_20260707_141255.json"
            ),
            "json_pointer": "",
            "operator": "eq",
            "expected_value": "80",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": (
                "Exact raw JSON field must be discovered before "
                "verification."
            ),
        },
        {
            "claim_id": "P9-DISPATCH-002",
            "phase": "phase9",
            "claim_text": (
                "The Docker Phase 9 /dispatch/compare benchmark "
                "recorded 80 successful cases."
            ),
            "source_audit": "CityRoute Tier 3 Phase 9 Evidence",
            "artifact_path": (
                "benchmarks/phase_9/docker_results/"
                "phase9_dispatch_endpoint_raw_docker_20260707_141255.json"
            ),
            "json_pointer": "",
            "operator": "eq",
            "expected_value": "80",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": "",
        },
        {
            "claim_id": "P9-DISPATCH-003",
            "phase": "phase9",
            "claim_text": (
                "The Docker Phase 9 /dispatch/compare benchmark "
                "recorded zero failed cases."
            ),
            "source_audit": "CityRoute Tier 3 Phase 9 Evidence",
            "artifact_path": (
                "benchmarks/phase_9/docker_results/"
                "phase9_dispatch_endpoint_raw_docker_20260707_141255.json"
            ),
            "json_pointer": "",
            "operator": "eq",
            "expected_value": "0",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": "",
        },
        {
            "claim_id": "P9-DISPATCH-004",
            "phase": "phase9",
            "claim_text": (
                "The Docker Phase 9 /dispatch/compare benchmark "
                "reported 100% overall success rate."
            ),
            "source_audit": "CityRoute Tier 3 Phase 9 Evidence",
            "artifact_path": (
                "benchmarks/phase_9/docker_results/"
                "phase9_dispatch_endpoint_summary_docker_20260707_141255.json"
            ),
            "json_pointer": "",
            "operator": "eq",
            "expected_value": "100",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": "",
        },
        {
            "claim_id": "P9-DISPATCH-005",
            "phase": "phase9",
            "claim_text": (
                "The Docker Phase 9 /dispatch/compare benchmark "
                "tested four dispatch sizes: 5, 10, 25, and 50."
            ),
            "source_audit": "CityRoute Tier 3 Phase 9 Evidence",
            "artifact_path": (
                "benchmarks/phase_9/docker_results/"
                "phase9_dispatch_endpoint_raw_docker_20260707_141255.json"
            ),
            "json_pointer": "",
            "operator": "eq",
            "expected_value": "__STRUCTURE__",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": (
                "Do not verify until the actual JSON representation "
                "of sizes is inspected."
            ),
        },
        {
            "claim_id": "P9-DISPATCH-006",
            "phase": "phase9",
            "claim_text": (
                "The Docker Phase 9 50x50 dispatch benchmark "
                "reported all requests successful."
            ),
            "source_audit": "CityRoute Tier 3 Phase 9 Evidence",
            "artifact_path": (
                "benchmarks/phase_9/docker_results/"
                "phase9_dispatch_endpoint_summary_docker_20260707_141255.json"
            ),
            "json_pointer": "",
            "operator": "eq",
            "expected_value": "20",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": (
                "Expected successful iteration count from the benchmark "
                "configuration; exact summary field must be resolved."
            ),
        },
        {
            "claim_id": "P9-DISPATCH-007",
            "phase": "phase9",
            "claim_text": (
                "The Docker Phase 9 50x50 dispatch benchmark "
                "reported all assignment counts valid."
            ),
            "source_audit": "CityRoute Tier 3 Phase 9 Evidence",
            "artifact_path": (
                "benchmarks/phase_9/docker_results/"
                "phase9_dispatch_endpoint_summary_docker_20260707_141255.json"
            ),
            "json_pointer": "",
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": (
                "Exact quality-flag field must be discovered."
            ),
        },
        {
            "claim_id": "P9-DISPATCH-008",
            "phase": "phase9",
            "claim_text": (
                "The Docker Phase 9 50x50 dispatch benchmark "
                "reported all capacity counts valid."
            ),
            "source_audit": "CityRoute Tier 3 Phase 9 Evidence",
            "artifact_path": (
                "benchmarks/phase_9/docker_results/"
                "phase9_dispatch_endpoint_summary_docker_20260707_141255.json"
            ),
            "json_pointer": "",
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": (
                "Exact quality-flag field must be discovered."
            ),
        },
        {
            "claim_id": "P9-DISPATCH-009",
            "phase": "phase9",
            "claim_text": (
                "The Docker Phase 9 50x50 dispatch benchmark "
                "reported a median request time below 500 ms."
            ),
            "source_audit": "CityRoute Tier 3 Phase 9 Evidence",
            "artifact_path": (
                "benchmarks/phase_9/docker_results/"
                "phase9_dispatch_endpoint_summary_docker_20260707_141255.json"
            ),
            "json_pointer": "",
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": (
                "The existing evidence summary indicates this acceptance "
                "flag; exact JSON pointer must be discovered."
            ),
        },
        {
            "claim_id": "P9-DISPATCH-010",
            "phase": "phase9",
            "claim_text": (
                "The Docker Phase 9 25x25 dispatch benchmark "
                "reported a median request time below 250 ms."
            ),
            "source_audit": "CityRoute Tier 3 Phase 9 Evidence",
            "artifact_path": (
                "benchmarks/phase_9/docker_results/"
                "phase9_dispatch_endpoint_summary_docker_20260707_141255.json"
            ),
            "json_pointer": "",
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": (
                "The existing evidence summary indicates this acceptance "
                "flag; exact JSON pointer must be discovered."
            ),
        },
    ]

    fields = [
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
            fieldnames=fields,
        )

        writer.writeheader()
        writer.writerows(claims)

    print()
    print("===============================================")
    print(" CityRoute Phase 12 Phase 9 Claim Preparation")
    print("===============================================")
    print()
    print(f"Claims prepared: {len(claims)}")
    print()
    print("Output:")
    print(f"  {output}")
    print()
    print("No claims evaluated.")
    print("No Phase 9 artifacts modified.")
    print()
    print(
        "Phase 9.1 is intentionally NOT included in this register."
    )
    print()


if __name__ == "__main__":
    main()