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

    output = manifests / "claim_register_phase9_1.csv"

    source_artifact = (
        "benchmarks/phase_9_1/local_results/"
        "phase91_dispatch_source_dijkstra_summary_local_20260709_140040.json"
    )

    cache_artifact = (
        "benchmarks/phase_9_1/local_results/"
        "phase91_dispatch_cache_summary_local_20260709_140153.json"
    )

    integration_artifact = (
        "benchmarks/phase_9_1/local_results/"
        "phase91_full_integration_summary_local_20260709_142743.json"
    )

    claims = [
        # ---------------------------------------------------------
        # Source-Dijkstra service-level integration
        # ---------------------------------------------------------
        {
            "claim_id": "P91-SD-001",
            "phase": "phase9_1",
            "claim_text": (
                "The Phase 9.1 Source-Dijkstra service probe "
                "recorded 100 benchmark cases."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": source_artifact,
            "json_pointer": "$.case_count",
            "operator": "eq",
            "expected_value": "100",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": (
                "Service-level probe using an injected internal builder."
            ),
        },
        {
            "claim_id": "P91-SD-002",
            "phase": "phase9_1",
            "claim_text": (
                "The Phase 9.1 Source-Dijkstra service probe "
                "recorded 100 successful cases."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": source_artifact,
            "json_pointer": "$.success_count",
            "operator": "eq",
            "expected_value": "100",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": "",
        },
        {
            "claim_id": "P91-SD-003",
            "phase": "phase9_1",
            "claim_text": (
                "The Phase 9.1 Source-Dijkstra service probe "
                "recorded zero failed cases."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": source_artifact,
            "json_pointer": "$.failure_count",
            "operator": "eq",
            "expected_value": "0",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": "",
        },
        {
            "claim_id": "P91-SD-004",
            "phase": "phase9_1",
            "claim_text": (
                "The Phase 9.1 Source-Dijkstra service probe "
                "reported that Source-Dijkstra was used in all cases."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": source_artifact,
            "json_pointer": "$.quality_flags.all_source_dijkstra_used",
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": "",
        },
        {
            "claim_id": "P91-SD-005",
            "phase": "phase9_1",
            "claim_text": (
                "The Phase 9.1 Source-Dijkstra service probe "
                "reported one builder call per case."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": source_artifact,
            "json_pointer": "$.quality_flags.all_builder_called_once",
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": "",
        },
        {
            "claim_id": "P91-SD-006",
            "phase": "phase9_1",
            "claim_text": (
                "The Phase 9.1 Source-Dijkstra service probe "
                "reported non-regression in all cases."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": source_artifact,
            "json_pointer": "$.quality_flags.all_non_regression",
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": "",
        },
        {
            "claim_id": "P91-SD-007",
            "phase": "phase9_1",
            "claim_text": (
                "The Phase 9.1 Source-Dijkstra service probe "
                "reported all assignment counts valid."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": source_artifact,
            "json_pointer": "$.quality_flags.all_assignment_counts_valid",
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": "",
        },
        {
            "claim_id": "P91-SD-008",
            "phase": "phase9_1",
            "claim_text": (
                "The Phase 9.1 Source-Dijkstra service probe "
                "reported all capacity counts valid."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": source_artifact,
            "json_pointer": "$.quality_flags.all_capacity_counts_valid",
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": "",
        },

        # ---------------------------------------------------------
        # Service-level cache behavior
        # ---------------------------------------------------------
        {
            "claim_id": "P91-CACHE-001",
            "phase": "phase9_1",
            "claim_text": (
                "The Phase 9.1 cache probe recorded 50 cache-test cycles."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": cache_artifact,
            "json_pointer": "$.cycle_count",
            "operator": "eq",
            "expected_value": "50",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": (
                "Service-level probe with an in-process fake backend."
            ),
        },
        {
            "claim_id": "P91-CACHE-002",
            "phase": "phase9_1",
            "claim_text": (
                "The Phase 9.1 cache probe recorded 100 requests."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": cache_artifact,
            "json_pointer": "$.request_count",
            "operator": "eq",
            "expected_value": "100",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": "",
        },
        {
            "claim_id": "P91-CACHE-003",
            "phase": "phase9_1",
            "claim_text": (
                "The Phase 9.1 cache probe recorded 50 cache hits."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": cache_artifact,
            "json_pointer": "$.cache_hit_count",
            "operator": "eq",
            "expected_value": "50",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": "",
        },
        {
            "claim_id": "P91-CACHE-004",
            "phase": "phase9_1",
            "claim_text": (
                "The Phase 9.1 cache probe recorded a 50% cache-hit rate."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": cache_artifact,
            "json_pointer": "$.cache_hit_rate_pct",
            "operator": "eq",
            "expected_value": "50",
            "tolerance": "0.001",
            "provenance_source_artifact": "",
            "notes": "",
        },
        {
            "claim_id": "P91-CACHE-005",
            "phase": "phase9_1",
            "claim_text": (
                "The Phase 9.1 cache probe reported all first requests "
                "as misses."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": cache_artifact,
            "json_pointer": "$.quality_flags.all_first_requests_miss",
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": "",
        },
        {
            "claim_id": "P91-CACHE-006",
            "phase": "phase9_1",
            "claim_text": (
                "The Phase 9.1 cache probe reported all second requests "
                "as hits."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": cache_artifact,
            "json_pointer": "$.quality_flags.all_second_requests_hit",
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": "",
        },
        {
            "claim_id": "P91-CACHE-007",
            "phase": "phase9_1",
            "claim_text": (
                "The Phase 9.1 cache probe reported stable cache keys."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": cache_artifact,
            "json_pointer": "$.quality_flags.all_cache_keys_stable",
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": "",
        },
        {
            "claim_id": "P91-CACHE-008",
            "phase": "phase9_1",
            "claim_text": (
                "The Phase 9.1 cache probe reported that the builder "
                "was not called again on a cache hit."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": cache_artifact,
            "json_pointer": (
                "$.quality_flags.all_builder_not_called_on_hit"
            ),
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": (
                "This is service-level cache behavior, not Redis proof."
            ),
        },

        # ---------------------------------------------------------
        # Final full integration
        # ---------------------------------------------------------
        {
            "claim_id": "P91-INT-001",
            "phase": "phase9_1",
            "claim_text": (
                "The final Phase 9.1 full-integration probe executed "
                "6 integration checks."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": integration_artifact,
            "json_pointer": "$.check_count",
            "operator": "eq",
            "expected_value": "6",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": (
                "Authoritative final run: 20260709_142743."
            ),
        },
        {
            "claim_id": "P91-INT-002",
            "phase": "phase9_1",
            "claim_text": (
                "The final Phase 9.1 full-integration probe "
                "recorded 6 successful checks."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": integration_artifact,
            "json_pointer": "$.success_count",
            "operator": "eq",
            "expected_value": "6",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": "",
        },
        {
            "claim_id": "P91-INT-003",
            "phase": "phase9_1",
            "claim_text": (
                "The final Phase 9.1 full-integration probe "
                "recorded zero failed checks."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": integration_artifact,
            "json_pointer": "$.failure_count",
            "operator": "eq",
            "expected_value": "0",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": "",
        },
        {
            "claim_id": "P91-INT-004",
            "phase": "phase9_1",
            "claim_text": (
                "The final Phase 9.1 full-integration probe "
                "reported 100% success."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": integration_artifact,
            "json_pointer": "$.success_rate_pct",
            "operator": "eq",
            "expected_value": "100",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": "",
        },
        {
            "claim_id": "P91-INT-005",
            "phase": "phase9_1",
            "claim_text": (
                "The final Phase 9.1 integration probe reported "
                "all integration checks successful."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": integration_artifact,
            "json_pointer": "$.quality_flags.all_checks_successful",
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": "",
        },
        {
            "claim_id": "P91-INT-006",
            "phase": "phase9_1",
            "claim_text": (
                "The final Phase 9.1 integration probe reported "
                "the Haversine dispatch path working."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": integration_artifact,
            "json_pointer": "$.quality_flags.dispatch_haversine_ok",
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": "",
        },
        {
            "claim_id": "P91-INT-007",
            "phase": "phase9_1",
            "claim_text": (
                "The final Phase 9.1 integration probe reported "
                "Haversine dispatch non-regression."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": integration_artifact,
            "json_pointer": (
                "$.quality_flags.dispatch_haversine_non_regression"
            ),
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": "",
        },
        {
            "claim_id": "P91-INT-008",
            "phase": "phase9_1",
            "claim_text": (
                "The final Phase 9.1 integration probe reported "
                "that the Source-Dijkstra API was correctly blocked "
                "until its real internal builder is wired."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": integration_artifact,
            "json_pointer": (
                "$.quality_flags.dispatch_source_dijkstra_status_expected"
            ),
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": (
                "This is intentionally a bounded claim. It does not "
                "claim successful live Source-Dijkstra API execution."
            ),
        },
        {
            "claim_id": "P91-INT-009",
            "phase": "phase9_1",
            "claim_text": (
                "The final Phase 9.1 integration probe acknowledged "
                "the Source-Dijkstra API as intentionally blocked."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": integration_artifact,
            "json_pointer": (
                "$.quality_flags.source_dijkstra_api_blocked_acknowledged"
            ),
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": "",
        },
        {
            "claim_id": "P91-INT-010",
            "phase": "phase9_1",
            "claim_text": (
                "The final Phase 9.1 integration probe reported "
                "the expected Source-Dijkstra API response state as valid."
            ),
            "source_audit": "Phase 9.1 evidence collection",
            "artifact_path": integration_artifact,
            "json_pointer": "$.quality_flags.source_dijkstra_api_ok",
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": "",
            "notes": (
                "This means the expected blocked-state behavior passed; "
                "it is not evidence of a successful live Source-Dijkstra call."
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
    print(" CityRoute Phase 12 Phase 9.1 Claim Preparation")
    print("===============================================")
    print()
    print(f"Claims prepared: {len(claims)}")
    print()
    print(f"Output:")
    print(f"  {output}")
    print()
    print("Excluded from acceptance register:")
    print("  - earlier full integration run 20260709_142217")
    print("  - any claim that real Redis was proven")
    print("  - any claim that live Source-Dijkstra API execution succeeded")
    print()
    print("No claims evaluated.")
    print("No Phase 9.1 benchmark artifacts modified.")
    print()


if __name__ == "__main__":
    main()