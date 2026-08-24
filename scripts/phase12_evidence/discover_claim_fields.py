from __future__ import annotations

import csv
import json
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


def load_json(path: Path) -> Any:
    raw = path.read_bytes()

    for encoding in (
        "utf-8",
        "utf-8-sig",
        "utf-16",
    ):
        try:
            return json.loads(raw.decode(encoding))
        except Exception:
            continue

    raise ValueError(
        f"Unable to parse JSON: {path}"
    )


def walk(
    value: Any,
    pointer: str = "$",
):
    """
    Recursively emit every scalar value and useful container.
    """

    if isinstance(value, dict):
        for key, child in value.items():
            child_pointer = (
                f"{pointer}.{key}"
            )

            yield from walk(
                child,
                child_pointer,
            )

    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_pointer = (
                f"{pointer}.{index}"
            )

            yield from walk(
                child,
                child_pointer,
            )

    else:
        yield pointer, value


def interesting(
    pointer: str,
    value: Any,
) -> bool:

    p = pointer.lower()

    keywords = (
        "speed",
        "mismatch",
        "cache",
        "hit",
        "miss",
        "median",
        "latency",
        "elapsed",
        "success",
        "failure",
        "valid",
        "correct",
        "comparison",
        "distance",
        "improvement",
        "target",
        "matrix",
    )

    return (
        any(
            keyword in p
            for keyword in keywords
        )
    )


def format_value(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
    )


def main() -> None:

    collection = newest_collection()
    manifests = (
        collection / "manifests"
    )

    register_path = (
        manifests / "claim_register.csv"
    )

    output_path = (
        manifests /
        "claim_field_discovery.csv"
    )

    if not register_path.exists():
        raise FileNotFoundError(
            f"Missing claim register: {register_path}"
        )

    with register_path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        claims = list(
            csv.DictReader(handle)
        )

    rows = []

    for claim in claims:

        artifact = ROOT / Path(
            claim["artifact_path"]
        )

        data = load_json(artifact)

        discovered = []

        for pointer, value in walk(data):

            if not interesting(
                pointer,
                value,
            ):
                continue

            discovered.append(
                {
                    "claim_id":
                        claim["claim_id"],
                    "artifact_path":
                        claim["artifact_path"],
                    "json_pointer":
                        pointer,
                    "value":
                        format_value(value),
                    "value_type":
                        type(value).__name__,
                }
            )

        for item in discovered:
            rows.append(item)

    fieldnames = [
        "claim_id",
        "artifact_path",
        "json_pointer",
        "value",
        "value_type",
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
        writer.writerows(rows)

    print()
    print("===============================================")
    print(" CityRoute Phase 12 Claim Field Discovery")
    print("===============================================")
    print()

    print(
        f"Claims inspected: {len(claims)}"
    )

    print(
        f"Candidate fields discovered: {len(rows)}"
    )

    print()

    current_claim = None

    for row in rows:

        if row["claim_id"] != current_claim:

            current_claim = row["claim_id"]

            print()
            print(
                f"[{current_claim}]"
            )

        print(
            f"  {row['json_pointer']} "
            f"= {row['value']}"
        )

    print()
    print("Output:")
    print(
        f"  {output_path}"
    )

    print()
    print(
        "No claim was evaluated."
    )
    print(
        "No claim register values were modified."
    )
    print()


if __name__ == "__main__":
    main()