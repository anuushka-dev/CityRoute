from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path.cwd()
EVIDENCE_ROOT = ROOT / ".phase12_evidence"


def newest_collection() -> Path:
    collections = sorted(
        EVIDENCE_ROOT.glob("collection_*"),
        key=lambda path: path.name,
        reverse=True,
    )

    if not collections:
        raise FileNotFoundError("No Phase 12 collection found.")

    return collections[0]


def inspect_bytes(path: Path) -> dict[str, str]:
    raw = path.read_bytes()

    first_32 = raw[:32]

    preview_hex = first_32.hex(" ")

    try:
        utf8_text = raw.decode("utf-8")
        utf8_status = "decode_ok"
    except UnicodeDecodeError as exc:
        utf8_text = ""
        utf8_status = f"decode_error: {exc}"

    try:
        latin1_text = raw.decode("latin-1")
        latin1_status = "decode_ok"
    except UnicodeDecodeError as exc:
        latin1_text = ""
        latin1_status = f"decode_error: {exc}"

    stripped = raw.lstrip()

    looks_jsonish = (
        stripped.startswith(b"{")
        or stripped.startswith(b"[")
        or stripped.startswith(b"\xef\xbb\xbf{")
        or stripped.startswith(b"\xef\xbb\xbf[")
    )

    return {
        "size_bytes": str(len(raw)),
        "first_32_hex": preview_hex,
        "utf8_status": utf8_status,
        "utf8_preview": repr(utf8_text[:200]),
        "latin1_status": latin1_status,
        "latin1_preview": repr(latin1_text[:200]),
        "looks_jsonish": str(looks_jsonish),
    }


def try_json_encodings(path: Path) -> list[str]:
    raw = path.read_bytes()

    encodings = (
        "utf-8",
        "utf-8-sig",
        "utf-16",
        "utf-16-le",
        "utf-16-be",
        "utf-32",
        "utf-32-le",
        "utf-32-be",
    )

    successful: list[str] = []

    for encoding in encodings:
        try:
            text = raw.decode(encoding)
            json.loads(text)
            successful.append(encoding)
        except Exception:
            continue

    return successful


def main() -> None:
    collection = newest_collection()
    manifests = collection / "manifests"

    integrity_path = manifests / "json_integrity_report.csv"

    if not integrity_path.exists():
        raise FileNotFoundError(
            f"Missing integrity report: {integrity_path}"
        )

    with integrity_path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        rows = list(csv.DictReader(handle))

    unresolved = [
        row
        for row in rows
        if row["parse_status"] in {
            "INVALID_JSON",
            "ENCODING_ERROR",
            "EMPTY",
        }
    ]

    output_path = manifests / "json_unresolved_inspection.csv"

    output_rows: list[dict[str, str]] = []

    for row in unresolved:
        path = Path(row["full_path"])

        result = {
            "relative_path": row["relative_path"],
            "original_status": row["parse_status"],
            "original_encoding": row["detected_encoding"],
            "exists": str(path.exists()),
            "size_bytes": "0",
            "successful_json_encodings": "",
            "first_32_hex": "",
            "utf8_status": "",
            "utf8_preview": "",
            "latin1_status": "",
            "latin1_preview": "",
            "looks_jsonish": "",
        }

        if path.exists():
            metadata = inspect_bytes(path)

            result.update(metadata)
            result["successful_json_encodings"] = ";".join(
                try_json_encodings(path)
            )

        output_rows.append(result)

    fieldnames = [
        "relative_path",
        "original_status",
        "original_encoding",
        "exists",
        "size_bytes",
        "successful_json_encodings",
        "first_32_hex",
        "utf8_status",
        "utf8_preview",
        "latin1_status",
        "latin1_preview",
        "looks_jsonish",
    ]

    with output_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
        )
        writer.writeheader()
        writer.writerows(output_rows)

    print()
    print("===============================================")
    print(" CityRoute Phase 12 Unresolved JSON Inspection")
    print("===============================================")
    print()
    print(f"Unresolved artifacts inspected: {len(output_rows)}")
    print()

    for result in output_rows:
        print(result["relative_path"])
        print(f"  original status: {result['original_status']}")
        print(f"  size: {result['size_bytes']} bytes")
        print(
            "  JSON-compatible encodings: "
            f"{result['successful_json_encodings'] or 'none'}"
        )
        print(
            f"  first bytes: {result['first_32_hex']}"
        )
        print(
            f"  looks JSON-like: {result['looks_jsonish']}"
        )
        print()

    print("Output:")
    print(f"  {output_path}")
    print()
    print("No evidence artifacts were modified.")


if __name__ == "__main__":
    main()