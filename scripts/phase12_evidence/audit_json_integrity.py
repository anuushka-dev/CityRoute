from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


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


def try_parse_json(
    path: Path,
) -> tuple[str, str, str]:
    """
    Return:

        (parse_status, encoding, error_message)

    The parser attempts common JSON encodings before classifying
    an artifact as invalid.
    """

    raw = path.read_bytes()

    if not raw:
        return (
            "EMPTY",
            "none",
            "",
        )

    attempts = [
        ("utf-8", "PARSE_OK_UTF8"),
        ("utf-8-sig", "PARSE_OK_UTF8_BOM"),
        ("utf-16-le", "PARSE_OK_UTF16_LE"),
        ("utf-16-be", "PARSE_OK_UTF16_BE"),
    ]

    errors: list[str] = []

    for encoding, success_status in attempts:

        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError as exc:
            errors.append(
                f"{encoding}: UnicodeDecodeError: {exc}"
            )
            continue

        try:
            json.loads(text)

            return (
                success_status,
                encoding,
                "",
            )

        except json.JSONDecodeError as exc:
            errors.append(
                f"{encoding}: JSONDecodeError: {exc}"
            )

    # At least one decoding worked but JSON remained invalid.
    if any(
        "JSONDecodeError" in error
        for error in errors
    ):
        return (
            "INVALID_JSON",
            "unknown",
            " | ".join(errors),
        )

    return (
        "ENCODING_ERROR",
        "unknown",
        " | ".join(errors),
    )


def main() -> None:

    collection = newest_collection()
    manifests = collection / "manifests"

    inventory_path = (
        manifests / "benchmark_inventory.csv"
    )

    hash_path = (
        manifests / "sha256_manifest.csv"
    )

    output_path = (
        manifests / "json_integrity_report.csv"
    )

    if not inventory_path.exists():
        raise FileNotFoundError(
            f"Missing inventory: {inventory_path}"
        )

    if not hash_path.exists():
        raise FileNotFoundError(
            f"Missing SHA manifest: {hash_path}"
        )

    with inventory_path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        inventory = list(
            csv.DictReader(f)
        )

    with hash_path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        hashes = {
            row["relative_path"]
            .replace("\\", "/")
            .lower(): row
            for row in csv.DictReader(f)
        }

    rows: list[dict[str, Any]] = []

    for entry in inventory:

        if entry["extension"].lower() != ".json":
            continue

        relative_path = entry["relative_path"]
        path = Path(entry["full_path"])

        hash_row = hashes.get(
            relative_path
            .replace("\\", "/")
            .lower(),
            {},
        )

        result = {
            "relative_path": relative_path,
            "full_path": str(path),
            "size_bytes": entry["length_bytes"],
            "sha256": hash_row.get(
                "sha256",
                "",
            ),
            "hash_status": hash_row.get(
                "hash_status",
                "",
            ),
            "parse_status": "",
            "detected_encoding": "",
            "error_message": "",
        }

        if not path.exists():

            result["parse_status"] = "MISSING"

            rows.append(result)
            continue

        (
            status,
            encoding,
            error_message,
        ) = try_parse_json(path)

        result["parse_status"] = status
        result["detected_encoding"] = encoding
        result["error_message"] = error_message

        rows.append(result)

    fieldnames = [
        "relative_path",
        "full_path",
        "size_bytes",
        "sha256",
        "hash_status",
        "parse_status",
        "detected_encoding",
        "error_message",
    ]

    with output_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
        )

        writer.writeheader()
        writer.writerows(rows)

    status_counts = Counter(
        row["parse_status"]
        for row in rows
    )

    encoding_counts = Counter(
        row["detected_encoding"]
        for row in rows
        if row["detected_encoding"]
        != "unknown"
    )

    print()
    print("===============================================")
    print(" CityRoute Phase 12 JSON Integrity Audit v0.2")
    print("===============================================")
    print()

    print(
        f"JSON artifacts inspected: {len(rows)}"
    )

    print()
    print("Parse status:")

    for status, count in sorted(
        status_counts.items()
    ):
        print(
            f"  {status}: {count}"
        )

    print()
    print("Detected encodings:")

    for encoding, count in sorted(
        encoding_counts.items()
    ):
        print(
            f"  {encoding}: {count}"
        )

    print()
    print("Output:")
    print(f"  {output_path}")

    print()
    print(
        "No evidence artifacts were modified."
    )
    print()


if __name__ == "__main__":
    main()