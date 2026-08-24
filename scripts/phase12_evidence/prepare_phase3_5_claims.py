from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path.cwd()
PHASE12_ROOT = ROOT / ".phase12_evidence"
OUTPUT_NAME = "claim_register_phase3_5.csv"

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
            f"Required Phase 3.5 artifact not found: {path}"
        )
    return relative_path.replace("\\", "/")


def make_claim(
    claim_id: str,
    text: str,
    artifact: str,
    pointer: str,
    operator: str,
    expected: str,
    *,
    tolerance: str = "",
    notes: str = "",
) -> dict[str, str]:
    return {
        "claim_id": claim_id,
        "phase": "phase3_5",
        "claim_text": text,
        "source_audit": "CityRoute Historical Phase 3.5 Route Map Evidence",
        "artifact_path": artifact,
        "json_pointer": pointer,
        "operator": operator,
        "expected_value": expected,
        "tolerance": tolerance,
        "provenance_source_artifact": "",
        "notes": notes,
    }


def main() -> None:
    collection = newest_collection()
    output = collection / "manifests" / OUTPUT_NAME

    summary = existing(
        "benchmarks/maps/phase3_5_route_map_summary.json"
    )
    response = existing(
        "benchmarks/maps/phase3_5_route_response.json"
    )

    claims = [
        make_claim(
            "P35-ROUTE-001",
            "The Phase 3.5 route-map probe recorded a successful route response.",
            summary,
            "$.status",
            "eq",
            "ok",
        ),
        make_claim(
            "P35-ROUTE-002",
            "The Phase 3.5 route response used A*.",
            summary,
            "$.algorithm",
            "eq",
            "astar",
        ),
        make_claim(
            "P35-ROUTE-003",
            "The Phase 3.5 route distance was 6428.798 metres.",
            summary,
            "$.distance_m",
            "eq",
            "6428.798",
            tolerance="0.001",
        ),
        make_claim(
            "P35-ROUTE-004",
            "The Phase 3.5 route contained 77 path nodes.",
            summary,
            "$.path_node_count",
            "eq",
            "77",
        ),
        make_claim(
            "P35-ROUTE-005",
            "The Phase 3.5 route geometry contained 77 points.",
            summary,
            "$.geometry_points",
            "eq",
            "77",
        ),
        make_claim(
            "P35-ROUTE-006",
            "The Phase 3.5 route response was received successfully by the probe.",
            summary,
            "$.verification.route_response_received",
            "eq",
            "true",
        ),
        make_claim(
            "P35-ROUTE-007",
            "The Phase 3.5 route geometry was present.",
            summary,
            "$.verification.geometry_present",
            "eq",
            "true",
        ),
        make_claim(
            "P35-SNAP-001",
            "The Phase 3.5 start coordinate was snapped using BallTree.",
            summary,
            "$.start_snap_method",
            "eq",
            "balltree",
        ),
        make_claim(
            "P35-SNAP-002",
            "The Phase 3.5 end coordinate was snapped using BallTree.",
            summary,
            "$.end_snap_method",
            "eq",
            "balltree",
        ),
        make_claim(
            "P35-MAP-001",
            "The Phase 3.5 route-map probe generated the HTML map artifact.",
            summary,
            "$.verification.map_html_generated",
            "eq",
            "true",
        ),
        make_claim(
            "P35-MAP-002",
            "The Phase 3.5 map used geometry from the route endpoint response.",
            summary,
            "$.verification.uses_route_endpoint_geometry",
            "eq",
            "true",
        ),
        make_claim(
            "P35-MAP-003",
            "The Phase 3.5 map probe did not recompute the route after receiving the endpoint response.",
            summary,
            "$.verification.recomputed_route",
            "eq",
            "false",
        ),
        make_claim(
            "P35-RESPONSE-001",
            "The Phase 3.5 route response reported status ok.",
            response,
            "$.status",
            "eq",
            "ok",
        ),
        make_claim(
            "P35-RESPONSE-002",
            "The Phase 3.5 route response reported A* as its algorithm.",
            response,
            "$.algorithm",
            "eq",
            "astar",
        ),
        make_claim(
            "P35-RESPONSE-003",
            "The Phase 3.5 route response contained 77 geometry points.",
            response,
            "$.geometry.length",
            "eq",
            "77",
            notes=(
                "Included only if the verifier supports array-length "
                "expressions; otherwise remove rather than infer."
            ),
        ),
        make_claim(
            "P35-RESPONSE-004",
            "The Phase 3.5 route response recorded BallTree snapping for the start.",
            response,
            "$.start.snap_method",
            "eq",
            "balltree",
        ),
        make_claim(
            "P35-RESPONSE-005",
            "The Phase 3.5 route response recorded BallTree snapping for the end.",
            response,
            "$.end.snap_method",
            "eq",
            "balltree",
        ),
        make_claim(
            "P35-RESPONSE-006",
            "The Phase 3.5 route response recorded the same start snapped node as the map summary.",
            response,
            "$.start.snapped_node",
            "eq",
            "5317312245",
        ),
        make_claim(
            "P35-RESPONSE-007",
            "The Phase 3.5 route response recorded the same end snapped node as the map summary.",
            response,
            "$.end.snapped_node",
            "eq",
            "6288159135",
        ),
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
        writer.writerows(claims)

    print()
    print("===============================================")
    print(" CityRoute Phase 12 Phase 3.5 Claim Preparation")
    print("===============================================")
    print()
    print(f"Claims prepared: {len(claims)}")
    print()
    print("Output:")
    print(f"  {output}")
    print()
    print("Boundaries:")
    print("  - No universal A* optimality claim.")
    print("  - No claim of manual visual browser inspection.")
    print("  - No independent re-computation of the route.")
    print("  - HTML generation is verified from recorded evidence.")
    print()
    print("No claims evaluated.")
    print("No Phase 3.5 artifacts modified.")
    print()


if __name__ == "__main__":
    main()