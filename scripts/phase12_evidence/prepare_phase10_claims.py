from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


ROOT = Path.cwd()
PHASE10_DIR = ROOT / "benchmarks" / "phase_10"
EVIDENCE_DIR = PHASE10_DIR / "docker_results"
PHASE12_DIR = ROOT / ".phase12_evidence"


FIELDNAMES = [
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


def find_latest_passing_manifest() -> Path:
    manifests = sorted(
        EVIDENCE_DIR.glob("phase10_evidence_manifest_docker_*.json"),
        key=lambda p: p.name,
    )

    if not manifests:
        raise FileNotFoundError(
            "No Phase 10 evidence manifest JSON files found."
        )

    passing: list[Path] = []

    for path in manifests:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue

        final_acceptance = data.get("final_acceptance", {})

        if (
            final_acceptance.get("status") == "PASS"
            and final_acceptance.get("all_required_evidence_passed") is True
        ):
            passing.append(path)

    if not passing:
        raise RuntimeError(
            "No Phase 10 evidence manifest with passing final_acceptance "
            "was found."
        )

    return passing[-1]


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Unable to parse Phase 10 evidence manifest: {path}"
        ) from exc


def resolve_group(
    manifest: dict[str, Any],
    evidence_name: str,
) -> dict[str, Any]:
    groups = manifest.get("evidence_groups")

    if not isinstance(groups, list):
        raise RuntimeError(
            "Phase 10 manifest does not contain a valid evidence_groups list."
        )

    matches = [
        group
        for group in groups
        if isinstance(group, dict)
        and group.get("evidence_name") == evidence_name
    ]

    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one Phase 10 evidence group named "
            f"{evidence_name!r}; found {len(matches)}."
        )

    group = matches[0]

    if group.get("missing") is True:
        raise RuntimeError(
            f"Phase 10 evidence group {evidence_name!r} is marked missing."
        )

    return group


def normalize_repo_path(value: str) -> str:
    return value.replace("\\", "/")


def get_artifact_path(
    manifest: dict[str, Any],
    evidence_name: str,
    artifact_type: str,
) -> str:
    group = resolve_group(manifest, evidence_name)

    key = f"{artifact_type}_path"
    value = group.get(key)

    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(
            f"Evidence group {evidence_name!r} has no usable {key}."
        )

    return normalize_repo_path(value)


def build_claims(
    manifest: dict[str, Any],
    manifest_path: Path,
) -> list[dict[str, str]]:
    road_dispatch_summary = get_artifact_path(
        manifest,
        "road_dispatch",
        "summary",
    )

    haversine_summary = get_artifact_path(
        manifest,
        "haversine_vs_road",
        "summary",
    )

    dispatch_cache_summary = get_artifact_path(
        manifest,
        "dispatch_cache",
        "summary",
    )

    unreachable_summary = get_artifact_path(
        manifest,
        "unreachable_pair",
        "summary",
    )

    correctness_summary = get_artifact_path(
        manifest,
        "correctness",
        "summary",
    )

    load_summary = get_artifact_path(
        manifest,
        "load",
        "summary",
    )

    source_audit = "CityRoute Tier 3 Phase 10 Evidence Collector"
    manifest_repo_path = normalize_repo_path(
        str(manifest_path.relative_to(ROOT))
    )

    return [
        # ---------------------------------------------------------
        # ROAD DISPATCH
        # ---------------------------------------------------------
        {
            "claim_id": "P10-ROAD-001",
            "phase": "phase_10",
            "claim_text": (
                "The Docker Phase 10 road-dispatch benchmark "
                "recorded 80 benchmark cases."
            ),
            "source_audit": source_audit,
            "artifact_path": road_dispatch_summary,
            "json_pointer": "$.case_count",
            "operator": "eq",
            "expected_value": "80",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": (
                "Exact group selected from the strict passing Phase 10 "
                "evidence manifest."
            ),
        },
        {
            "claim_id": "P10-ROAD-002",
            "phase": "phase_10",
            "claim_text": (
                "The Docker Phase 10 road-dispatch benchmark "
                "recorded 80 successful cases."
            ),
            "source_audit": source_audit,
            "artifact_path": road_dispatch_summary,
            "json_pointer": "$.success_count",
            "operator": "eq",
            "expected_value": "80",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-ROAD-003",
            "phase": "phase_10",
            "claim_text": (
                "The Docker Phase 10 road-dispatch benchmark "
                "recorded zero failed cases."
            ),
            "source_audit": source_audit,
            "artifact_path": road_dispatch_summary,
            "json_pointer": "$.failure_count",
            "operator": "eq",
            "expected_value": "0",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-ROAD-004",
            "phase": "phase_10",
            "claim_text": (
                "The Docker Phase 10 road-dispatch benchmark "
                "reported a 100% success rate."
            ),
            "source_audit": source_audit,
            "artifact_path": road_dispatch_summary,
            "json_pointer": "$.success_rate_pct",
            "operator": "eq",
            "expected_value": "100",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },

        # ---------------------------------------------------------
        # HAVERSINE VS ROAD
        # ---------------------------------------------------------
        {
            "claim_id": "P10-HAV-001",
            "phase": "phase_10",
            "claim_text": (
                "The Docker Phase 10 Haversine-vs-road benchmark "
                "recorded 80 benchmark cases."
            ),
            "source_audit": source_audit,
            "artifact_path": haversine_summary,
            "json_pointer": "$.case_count",
            "operator": "eq",
            "expected_value": "80",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-HAV-002",
            "phase": "phase_10",
            "claim_text": (
                "The Docker Phase 10 Haversine-vs-road benchmark "
                "recorded 80 successful cases."
            ),
            "source_audit": source_audit,
            "artifact_path": haversine_summary,
            "json_pointer": "$.success_count",
            "operator": "eq",
            "expected_value": "80",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-HAV-003",
            "phase": "phase_10",
            "claim_text": (
                "The Docker Phase 10 Haversine-vs-road benchmark "
                "recorded zero failed cases."
            ),
            "source_audit": source_audit,
            "artifact_path": haversine_summary,
            "json_pointer": "$.failure_count",
            "operator": "eq",
            "expected_value": "0",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-HAV-004",
            "phase": "phase_10",
            "claim_text": (
                "The Docker Phase 10 Haversine-vs-road benchmark "
                "reported a 100% success rate."
            ),
            "source_audit": source_audit,
            "artifact_path": haversine_summary,
            "json_pointer": "$.success_rate_pct",
            "operator": "eq",
            "expected_value": "100",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": (
                "This claim concerns execution success only; it does not "
                "claim that Haversine is more or less accurate than road cost."
            ),
        },

        # ---------------------------------------------------------
        # DISPATCH CACHE
        # ---------------------------------------------------------
        {
            "claim_id": "P10-CACHE-001",
            "phase": "phase_10",
            "claim_text": (
                "The Docker Phase 10 dispatch-cache benchmark "
                "recorded 40 cache cycles."
            ),
            "source_audit": source_audit,
            "artifact_path": dispatch_cache_summary,
            "json_pointer": "$.cycle_count",
            "operator": "eq",
            "expected_value": "40",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-CACHE-002",
            "phase": "phase_10",
            "claim_text": (
                "The Docker Phase 10 dispatch-cache benchmark "
                "recorded 40 successful cycles."
            ),
            "source_audit": source_audit,
            "artifact_path": dispatch_cache_summary,
            "json_pointer": "$.success_count",
            "operator": "eq",
            "expected_value": "40",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-CACHE-003",
            "phase": "phase_10",
            "claim_text": (
                "The Docker Phase 10 dispatch-cache benchmark "
                "recorded zero failed cycles."
            ),
            "source_audit": source_audit,
            "artifact_path": dispatch_cache_summary,
            "json_pointer": "$.failure_count",
            "operator": "eq",
            "expected_value": "0",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-CACHE-004",
            "phase": "phase_10",
            "claim_text": (
                "The Docker Phase 10 dispatch-cache benchmark "
                "recorded 40 cold misses."
            ),
            "source_audit": source_audit,
            "artifact_path": dispatch_cache_summary,
            "json_pointer": "$.cold_miss_count",
            "operator": "eq",
            "expected_value": "40",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-CACHE-005",
            "phase": "phase_10",
            "claim_text": (
                "The Docker Phase 10 dispatch-cache benchmark "
                "recorded 80 warm hits."
            ),
            "source_audit": source_audit,
            "artifact_path": dispatch_cache_summary,
            "json_pointer": "$.warm_hit_count",
            "operator": "eq",
            "expected_value": "80",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-CACHE-006",
            "phase": "phase_10",
            "claim_text": (
                "All measured cold cache requests missed."
            ),
            "source_audit": source_audit,
            "artifact_path": dispatch_cache_summary,
            "json_pointer": "$.all_cold_requests_missed",
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-CACHE-007",
            "phase": "phase_10",
            "claim_text": (
                "All measured warm cache requests hit."
            ),
            "source_audit": source_audit,
            "artifact_path": dispatch_cache_summary,
            "json_pointer": "$.all_warm_requests_hit",
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-CACHE-008",
            "phase": "phase_10",
            "claim_text": (
                "All measured warm-cache outputs were identical."
            ),
            "source_audit": source_audit,
            "artifact_path": dispatch_cache_summary,
            "json_pointer": "$.all_warm_outputs_identical",
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },

        # ---------------------------------------------------------
        # UNREACHABLE DIRECTED PAIR
        # ---------------------------------------------------------
        {
            "claim_id": "P10-UNREACH-001",
            "phase": "phase_10",
            "claim_text": (
                "The Docker Phase 10 unreachable-pair benchmark "
                "found a verified directed unreachable pair."
            ),
            "source_audit": source_audit,
            "artifact_path": unreachable_summary,
            "json_pointer": "$.verified_pair_found",
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-UNREACH-002",
            "phase": "phase_10",
            "claim_text": (
                "The Docker Phase 10 unreachable-pair benchmark "
                "recorded 20 successful cases."
            ),
            "source_audit": source_audit,
            "artifact_path": unreachable_summary,
            "json_pointer": "$.success_count",
            "operator": "eq",
            "expected_value": "20",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-UNREACH-003",
            "phase": "phase_10",
            "claim_text": (
                "The Docker Phase 10 unreachable-pair benchmark "
                "recorded zero failed cases."
            ),
            "source_audit": source_audit,
            "artifact_path": unreachable_summary,
            "json_pointer": "$.failure_count",
            "operator": "eq",
            "expected_value": "0",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-UNREACH-004",
            "phase": "phase_10",
            "claim_text": (
                "All greedy forbidden-pair checks were rejected."
            ),
            "source_audit": source_audit,
            "artifact_path": unreachable_summary,
            "json_pointer": "$.all_greedy_forbidden_pairs_rejected",
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-UNREACH-005",
            "phase": "phase_10",
            "claim_text": (
                "All Hungarian forbidden-pair checks were rejected."
            ),
            "source_audit": source_audit,
            "artifact_path": unreachable_summary,
            "json_pointer": "$.all_hungarian_forbidden_pairs_rejected",
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-UNREACH-006",
            "phase": "phase_10",
            "claim_text": (
                "All Phase 10 directed-pair directionality checks passed."
            ),
            "source_audit": source_audit,
            "artifact_path": unreachable_summary,
            "json_pointer": "$.all_directionality_checks_passed",
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },

        # ---------------------------------------------------------
        # CORRECTNESS
        # ---------------------------------------------------------
        {
            "claim_id": "P10-CORRECT-001",
            "phase": "phase_10",
            "claim_text": (
                "The Docker Phase 10 correctness benchmark "
                "passed 15 scenarios."
            ),
            "source_audit": source_audit,
            "artifact_path": correctness_summary,
            "json_pointer": "$.scenario_success_count",
            "operator": "eq",
            "expected_value": "15",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-CORRECT-002",
            "phase": "phase_10",
            "claim_text": (
                "The Docker Phase 10 correctness benchmark "
                "tested 270 road-cost cells."
            ),
            "source_audit": source_audit,
            "artifact_path": correctness_summary,
            "json_pointer": "$.cell_case_count",
            "operator": "eq",
            "expected_value": "270",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-CORRECT-003",
            "phase": "phase_10",
            "claim_text": (
                "The Docker Phase 10 correctness benchmark "
                "reported zero road-cost cell mismatches."
            ),
            "source_audit": source_audit,
            "artifact_path": correctness_summary,
            "json_pointer": "$.cell_mismatch_count",
            "operator": "eq",
            "expected_value": "0",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-CORRECT-004",
            "phase": "phase_10",
            "claim_text": (
                "All tested road-cost cells matched the oracle."
            ),
            "source_audit": source_audit,
            "artifact_path": correctness_summary,
            "json_pointer": "$.all_road_cost_cells_matched_oracle",
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-CORRECT-005",
            "phase": "phase_10",
            "claim_text": (
                "All tested Hungarian results matched brute-force optimum."
            ),
            "source_audit": source_audit,
            "artifact_path": correctness_summary,
            "json_pointer": (
                "$.all_hungarian_results_matched_bruteforce_optimum"
            ),
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": (
                "Finite tested cases only; not a claim of universal "
                "algorithmic proof for all possible future inputs."
            ),
        },
        {
            "claim_id": "P10-CORRECT-006",
            "phase": "phase_10",
            "claim_text": (
                "All tested Hungarian non-regression checks passed."
            ),
            "source_audit": source_audit,
            "artifact_path": correctness_summary,
            "json_pointer": (
                "$.all_hungarian_non_regression_checks_passed"
            ),
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },

        # ---------------------------------------------------------
        # LOAD
        # ---------------------------------------------------------
        {
            "claim_id": "P10-LOAD-001",
            "phase": "phase_10",
            "claim_text": (
                "The Docker Phase 10 load benchmark recorded "
                "480 total requests."
            ),
            "source_audit": source_audit,
            "artifact_path": load_summary,
            "json_pointer": "$.total_request_count",
            "operator": "eq",
            "expected_value": "480",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-LOAD-002",
            "phase": "phase_10",
            "claim_text": (
                "The Docker Phase 10 load benchmark recorded "
                "480 successful requests."
            ),
            "source_audit": source_audit,
            "artifact_path": load_summary,
            "json_pointer": "$.success_count",
            "operator": "eq",
            "expected_value": "480",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-LOAD-003",
            "phase": "phase_10",
            "claim_text": (
                "The Docker Phase 10 load benchmark recorded "
                "zero failed requests."
            ),
            "source_audit": source_audit,
            "artifact_path": load_summary,
            "json_pointer": "$.failure_count",
            "operator": "eq",
            "expected_value": "0",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-LOAD-004",
            "phase": "phase_10",
            "claim_text": (
                "The Docker Phase 10 load benchmark reported a "
                "100% overall success rate."
            ),
            "source_audit": source_audit,
            "artifact_path": load_summary,
            "json_pointer": "$.success_rate_pct",
            "operator": "eq",
            "expected_value": "100",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
        {
            "claim_id": "P10-LOAD-005",
            "phase": "phase_10",
            "claim_text": (
                "The Docker Phase 10 load benchmark reported all "
                "Hungarian non-regression checks passed."
            ),
            "source_audit": source_audit,
            "artifact_path": load_summary,
            "json_pointer": "$.all_hungarian_non_regression_checks_passed",
            "operator": "eq",
            "expected_value": "true",
            "tolerance": "",
            "provenance_source_artifact": manifest_repo_path,
            "notes": "",
        },
    ]


def write_register(
    output: Path,
    claims: list[dict[str, str]],
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=FIELDNAMES,
        )
        writer.writeheader()
        writer.writerows(claims)


def main() -> None:
    print()
    print("===============================================")
    print(" CityRoute Phase 12 Phase 10 Claim Preparation")
    print("===============================================")
    print()

    manifest_path = find_latest_passing_manifest()
    manifest = load_manifest(manifest_path)

    final_acceptance = manifest.get("final_acceptance", {})

    if final_acceptance.get("status") != "PASS":
        raise RuntimeError(
            "Selected manifest does not have final_acceptance.status=PASS."
        )

    claims = build_claims(manifest, manifest_path)

    collections = sorted(
        PHASE12_DIR.glob("collection_*"),
        key=lambda p: p.name,
        reverse=True,
    )

    if not collections:
        raise FileNotFoundError(
            "No Phase 12 evidence collection found."
        )

    manifests_dir = collections[0] / "manifests"

    output = manifests_dir / "claim_register_phase10.csv"

    write_register(output, claims)

    group_names = [
        group.get("evidence_name")
        for group in manifest.get("evidence_groups", [])
        if isinstance(group, dict)
    ]

    print(f"Authoritative manifest:")
    print(f"  {manifest_path}")
    print()

    print("Final acceptance from manifest:")
    print(f"  status: {final_acceptance.get('status')}")
    print(
        "  all_required_evidence_passed: "
        f"{final_acceptance.get('all_required_evidence_passed')}"
    )
    print(
        "  expected_group_count: "
        f"{final_acceptance.get('expected_group_count')}"
    )
    print(
        "  passed_group_count: "
        f"{final_acceptance.get('passed_group_count')}"
    )
    print(
        "  missing_group_count: "
        f"{final_acceptance.get('missing_group_count')}"
    )
    print(
        "  failed_group_count: "
        f"{final_acceptance.get('failed_group_count')}"
    )
    print()

    print("Evidence groups discovered:")
    for name in group_names:
        print(f"  {name}")
    print()

    print(f"Claims prepared: {len(claims)}")
    print()
    print("Output:")
    print(f"  {output}")
    print()
    print("Important boundaries:")
    print("  - No universal mathematical correctness claim.")
    print("  - No unlimited-scale production-readiness claim.")
    print("  - No latency SLO claim is created without a specific field.")
    print("  - No benchmark result was interpreted or modified.")
    print()
    print("No claims evaluated.")
    print("No Phase 10 benchmark artifacts modified.")
    print()


if __name__ == "__main__":
    main()