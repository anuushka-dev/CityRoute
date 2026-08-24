from __future__ import annotations

import argparse
import csv
import json
import operator
from pathlib import Path
from typing import Any


ROOT = Path.cwd()
EVIDENCE_ROOT = ROOT / ".phase12_evidence"

CLAIM_REGISTER_NAME = "claim_register.csv"
OUTPUT_NAME = "claim_verification.csv"

COMPARATORS = {
    "eq": operator.eq,
    "ne": operator.ne,
    "lt": operator.lt,
    "le": operator.le,
    "gt": operator.gt,
    "ge": operator.ge,
}


def newest_collection() -> Path:
    collections = sorted(
        EVIDENCE_ROOT.glob("collection_*"),
        key=lambda path: path.name,
        reverse=True,
    )
    if not collections:
        raise FileNotFoundError(
            "No Phase 12 collection found under .phase12_evidence."
        )
    return collections[0]


def normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip().lower()


def load_csv_index(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        return {
            normalize_path(row["relative_path"]): row
            for row in rows
            if row.get("relative_path")
        }


def load_json_with_known_encodings(path: Path) -> Any:
    raw = path.read_bytes()
    if not raw:
        raise ValueError("EMPTY_JSON")

    errors: list[str] = []
    for encoding in ("utf-8", "utf-8-sig", "utf-16"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError as exc:
            errors.append(f"{encoding}: {type(exc).__name__}: {exc}")
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            errors.append(f"{encoding}: {type(exc).__name__}: {exc}")

    raise ValueError("UNPARSEABLE_JSON: " + " | ".join(errors))


def load_json_pointer(document: Any, pointer: str) -> Any:
    if pointer in {"", "$"}:
        return document

    if not pointer.startswith("$."):
        raise ValueError(f"Unsupported JSON pointer: {pointer}")

    current = document
    parts = pointer[2:].split(".")

    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"Missing object key: {part}")
            current = current[part]
        elif isinstance(current, list):
            try:
                index = int(part)
            except ValueError as exc:
                raise KeyError(
                    f"List index is not numeric: {part}"
                ) from exc
            if index < 0 or index >= len(current):
                raise IndexError(
                    f"List index out of range: {part}"
                )
            current = current[index]
        else:
            raise KeyError(
                f"Cannot descend through scalar at: {part}"
            )

    return current


def parse_expected_value(raw: str) -> Any:
    value = raw.strip()
    if value == "":
        return None

    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def evaluate(
    observed: Any,
    expected: Any,
    operator_name: str,
    tolerance: str,
) -> tuple[bool, str]:
    operator_name = operator_name.strip().lower()

    if operator_name == "eq":
        tol = 0.0
        if tolerance.strip():
            try:
                tol = float(tolerance)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid numeric tolerance: {tolerance!r}"
                ) from exc

        if (
            isinstance(observed, (int, float))
            and not isinstance(observed, bool)
            and isinstance(expected, (int, float))
            and not isinstance(expected, bool)
        ):
            difference = abs(observed - expected)
            return (
                difference <= tol,
                f"|observed-expected|={difference} <= tolerance={tol}",
            )

        return (
            observed == expected and type(observed) is type(expected),
            f"observed={observed!r}, expected={expected!r}",
        )

    if operator_name not in COMPARATORS:
        raise ValueError(f"Unsupported operator: {operator_name}")

    try:
        passed = COMPARATORS[operator_name](observed, expected)
    except TypeError as exc:
        raise ValueError(
            f"Cannot compare observed={observed!r} "
            f"with expected={expected!r}"
        ) from exc

    return bool(passed), f"observed={observed!r}, expected={expected!r}"


def load_provenance(
    path: Path,
) -> set[tuple[str, str]]:
    if not path.exists():
        return set()

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        pairs: set[tuple[str, str]] = set()
        for row in rows:
            source = row.get("source_artifact", "")
            target = row.get("target_artifact", "")
            if source and target:
                pairs.add(
                    (normalize_path(source), normalize_path(target))
                )
        return pairs


def find_artifact(
    relative_path: str,
    inventory: dict[str, dict[str, str]],
) -> dict[str, str] | None:
    return inventory.get(normalize_path(relative_path))


def verify_claim(
    claim: dict[str, str],
    inventory: dict[str, dict[str, str]],
    hash_inventory: dict[str, dict[str, str]],
    provenance_edges: set[tuple[str, str]],
) -> dict[str, Any]:
    claim_id = claim["claim_id"]
    artifact_path = claim["artifact_path"]
    pointer = claim["json_pointer"].strip()
    provenance_source = claim.get(
        "provenance_source_artifact", ""
    ).strip()

    result: dict[str, Any] = {
        "claim_id": claim_id,
        "phase": claim["phase"],
        "claim_text": claim["claim_text"],
        "artifact_path": artifact_path,
        "json_pointer": pointer,
        "operator": claim["operator"],
        "expected_value": claim["expected_value"],
        "tolerance": claim.get("tolerance", ""),
        "observed_value": "",
        "artifact_sha256": "",
        "artifact_hash_status": "",
        "provenance_status": "",
        "verification_status": "",
        "verification_reason": "",
    }

    if not pointer:
        result["verification_status"] = "UNVERIFIED"
        result["verification_reason"] = (
            "JSON pointer is blank; exact field has not been resolved."
        )
        return result

    artifact = find_artifact(artifact_path, inventory)
    if artifact is None:
        result["verification_status"] = "UNVERIFIED"
        result["verification_reason"] = (
            "Referenced artifact is absent from collected benchmark inventory."
        )
        return result

    hash_record = hash_inventory.get(normalize_path(artifact_path))
    if hash_record is None:
        result["verification_status"] = "UNVERIFIED"
        result["verification_reason"] = (
            "Referenced artifact is absent from SHA-256 manifest."
        )
        return result

    result["artifact_sha256"] = hash_record.get("sha256", "")
    result["artifact_hash_status"] = hash_record.get("hash_status", "")

    if result["artifact_hash_status"] != "OK":
        result["verification_status"] = "UNVERIFIED"
        result["verification_reason"] = (
            "Artifact does not have a successful SHA-256 status."
        )
        return result

    if provenance_source:
        edge = (
            normalize_path(provenance_source),
            normalize_path(artifact_path),
        )
        result["provenance_status"] = (
            "PRESENT" if edge in provenance_edges else "NOT_FOUND"
        )
    else:
        result["provenance_status"] = "NOT_REQUIRED"

    full_path = Path(artifact["full_path"])
    if not full_path.exists():
        result["verification_status"] = "UNVERIFIED"
        result["verification_reason"] = (
            "Referenced artifact does not exist at verification time."
        )
        return result

    if full_path.suffix.lower() != ".json":
        result["verification_status"] = "UNVERIFIED"
        result["verification_reason"] = (
            "This verifier currently requires a JSON artifact."
        )
        return result

    try:
        document = load_json_with_known_encodings(full_path)
    except Exception as exc:
        result["verification_status"] = "UNVERIFIED"
        result["verification_reason"] = (
            f"Unable to parse artifact: {exc}"
        )
        return result

    try:
        observed = load_json_pointer(document, pointer)
    except Exception as exc:
        result["verification_status"] = "UNVERIFIED"
        result["verification_reason"] = (
            f"JSON pointer could not be resolved: {exc}"
        )
        return result

    expected = parse_expected_value(claim["expected_value"])

    result["observed_value"] = json.dumps(
        observed,
        ensure_ascii=False,
        sort_keys=True,
    )

    try:
        passed, explanation = evaluate(
            observed,
            expected,
            claim["operator"],
            claim.get("tolerance", ""),
        )
    except Exception as exc:
        result["verification_status"] = "UNVERIFIED"
        result["verification_reason"] = (
            f"Comparison could not be performed: {exc}"
        )
        return result

    if passed:
        result["verification_status"] = "VERIFIED"
        result["verification_reason"] = explanation
    else:
        result["verification_status"] = "CONTRADICTED"
        result["verification_reason"] = explanation

    return result

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify a CityRoute Phase 12 claim register."
    )

    parser.add_argument(
        "--claim-register",
        type=Path,
        required=True,
        help="Phase-specific claim register CSV.",
    )

    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Phase-specific verification CSV.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    collection = newest_collection()
    manifests = collection / "manifests"

    claim_register_path = args.claim_register
    output_path = args.output

    inventory_path = manifests / "benchmark_inventory.csv"
    hash_path = manifests / "sha256_manifest.csv"
    provenance_path = manifests / "provenance_edges.csv"

    if not claim_register_path.exists():
        template_path = manifests / "claim_register_TEMPLATE.csv"
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
        with template_path.open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            csv.DictWriter(handle, fieldnames=fields).writeheader()

        print()
        print("===============================================")
        print(" CityRoute Phase 12 Claim Verification")
        print("===============================================")
        print()
        print("Claim register does not exist.")
        print(f"Created template: {template_path}")
        print("No claims were invented.")
        print("No benchmark claims were evaluated.")
        print()
        return

    for required_path in (
        inventory_path,
        hash_path,
    ):
        if not required_path.exists():
            raise FileNotFoundError(
                f"Missing required manifest: {required_path}"
            )

    inventory = load_csv_index(inventory_path)
    hash_inventory = load_csv_index(hash_path)
    provenance_edges = load_provenance(provenance_path)

    with claim_register_path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        claims = list(csv.DictReader(handle))

    if not claims:
        raise ValueError(
            "claim_register.csv contains no claims."
        )

    required_columns = {
        "claim_id",
        "phase",
        "claim_text",
        "source_audit",
        "artifact_path",
        "json_pointer",
        "operator",
        "expected_value",
    }
    missing = required_columns - set(claims[0].keys())
    if missing:
        raise ValueError(
            "claim_register.csv is missing required columns: "
            + ", ".join(sorted(missing))
        )

    results = [
        verify_claim(
            claim,
            inventory,
            hash_inventory,
            provenance_edges,
        )
        for claim in claims
    ]

    fieldnames = [
        "claim_id",
        "phase",
        "claim_text",
        "artifact_path",
        "json_pointer",
        "operator",
        "expected_value",
        "tolerance",
        "observed_value",
        "artifact_sha256",
        "artifact_hash_status",
        "provenance_status",
        "verification_status",
        "verification_reason",
    ]

    with output_path.open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
        )
        writer.writeheader()
        writer.writerows(results)

    from collections import Counter

    statuses = Counter(
        result["verification_status"]
        for result in results
    )

    print()
    print("===============================================")
    print(" CityRoute Phase 12 Claim Verification")
    print("===============================================")
    print()
    print(f"Claims evaluated: {len(results)}")
    print()
    print("Verification status:")
    for status, count in sorted(statuses.items()):
        print(f"  {status}: {count}")
    print()
    print(f"Output: {output_path}")
    print()
    print("No evidence artifacts were modified.")
    print("No new claims were invented.")
    print("No audit verdicts were inferred.")
    print()


if __name__ == "__main__":
    main()