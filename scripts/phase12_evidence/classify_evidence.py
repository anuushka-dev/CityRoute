from __future__ import annotations

import csv
import json
import re
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


def normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip().lower()


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        return data if isinstance(data, dict) else None

    except Exception:
        return None


def phase_from_path(path: str) -> str:
    normalized = normalize_path(path)

    patterns = [
        r"benchmarks/(phase_\d+_\d+)",
        r"benchmarks/(phase_\d+)",
        r"benchmarks/(phase\d+_\d+)",
        r"benchmarks/(phase\d+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, normalized)

        if match:
            return match.group(1)

    return "unassigned"


def historical_layout(path: str) -> str:
    normalized = normalize_path(path)

    if re.search(r"benchmarks/phase_\d+", normalized):
        return "explicit_phase_directory"

    if re.search(r"benchmarks/phase\d+", normalized):
        return "historical_phase_directory"

    if normalized.startswith("benchmarks/"):
        return "pre_phase_directory"

    return "outside_benchmark_tree"


def environment_from_path(path: str) -> str:
    normalized = normalize_path(path)

    if "/docker_results/" in normalized:
        return "docker"

    if "/local_results/" in normalized:
        return "local"

    name = Path(path).name.lower()

    if "docker" in name:
        return "docker"

    if "local" in name:
        return "local"

    return "unspecified"


def filename_role(filename: str) -> str:
    name = filename.lower()

    if "error" in name or "failure" in name or "failed" in name:
        return "failure"

    if "manifest" in name:
        return "manifest"

    if "summary" in name:
        return "summary"

    if "raw" in name:
        return "raw"

    if "correctness" in name:
        return "correctness"

    if "compare" in name or "comparison" in name:
        return "comparison"

    if "benchmark" in name:
        return "benchmark"

    if "probe" in name:
        return "probe"

    if (
        "load" in name
        or "concurrent" in name
        or "overload" in name
    ):
        return "load_or_concurrency"

    if "stress" in name:
        return "stress"

    if "health" in name:
        return "health"

    if "log" in name:
        return "log"

    return "unclassified"


def classify_python(filename: str) -> tuple[str, str]:
    name = filename.lower()

    if "correctness" in name:
        return "correctness_source", "source"

    if "compare" in name or "comparison" in name:
        return "comparison_source", "source"

    if "probe" in name:
        return "benchmark_probe_source", "source"

    if "benchmark" in name:
        return "benchmark_source", "source"

    if "stress" in name:
        return "stress_source", "source"

    return "python_artifact", "source"


def classify_text(filename: str) -> tuple[str, str]:
    name = filename.lower()

    if "manifest" in name:
        return "evidence_manifest_text", "text"

    if "summary" in name:
        return "summary_text", "text"

    if "log" in name:
        return "execution_log", "text"

    if "console" in name:
        return "console_output", "text"

    if "evidence" in name:
        return "evidence_text", "text"

    if "probe" in name:
        return "probe_output", "text"

    if "error" in name or "failure" in name:
        return "failure_text", "text"

    return "text_artifact", "text"


def structural_signals(
    data: dict[str, Any],
) -> list[str]:

    keys = {
        str(key).lower()
        for key in data.keys()
    }

    signals: list[str] = []

    signal_keys = {
        "timestamp": {
            "timestamp_utc",
            "timestamp",
            "created_at",
            "collected_at",
        },
        "base_url": {
            "base_url",
        },
        "iteration_count": {
            "iterations_requested",
            "iterations",
        },
        "success_count": {
            "successful_requests",
            "success_count",
        },
        "failure_count": {
            "failed_requests",
            "failure_count",
        },
        "error_rate": {
            "error_rate_pct",
        },
        "acceptance_targets": {
            "targets",
        },
        "acceptance_checks": {
            "acceptance_checks",
        },
        "validation": {
            "validation",
        },
        "verification": {
            "verification",
        },
        "comparison": {
            "comparison",
        },
        "graph_stats": {
            "graph_stats",
        },
        "health": {
            "health",
        },
        "cache_behavior": {
            "cache_hit",
            "cache_miss",
        },
        "multiple_runs": {
            "runs",
        },
    }

    for signal, candidates in signal_keys.items():

        if keys.intersection(candidates):
            signals.append(signal)

    return signals


def classify_json(
    filename: str,
    data: dict[str, Any] | None,
) -> tuple[str, str, list[str]]:

    role = filename_role(filename)

    signals = (
        structural_signals(data)
        if data is not None
        else []
    )

    if "acceptance_checks" in signals:
        if role == "failure":
            return (
                "failure_result_with_acceptance_checks",
                "result",
                signals,
            )

        return (
            "result_with_acceptance_checks",
            "result",
            signals,
        )

    if "verification" in signals:
        return (
            "verification_result",
            "result",
            signals,
        )

    if "comparison" in signals:
        return (
            "comparison_result",
            "result",
            signals,
        )

    if "validation" in signals:
        return (
            "validated_result",
            "result",
            signals,
        )

    if "multiple_runs" in signals:
        return (
            "multi_run_result",
            "result",
            signals,
        )

    if role == "failure":
        return "failure_result", "result", signals

    if role == "summary":
        return "summary", "result", signals

    if role == "raw":
        return "raw_result", "result", signals

    if role == "benchmark":
        return "benchmark_result", "result", signals

    if role == "probe":
        return "probe_result", "result", signals

    return "json_artifact", "result", signals


def classify_artifact(
    relative_path: str,
    extension: str,
    data: dict[str, Any] | None,
) -> tuple[str, str, list[str]]:

    filename = Path(relative_path).name

    if extension == ".pyc":
        return (
            "generated_bytecode",
            "non_canonical",
            [],
        )

    if extension == ".py":
        artifact_class, artifact_layer = classify_python(filename)
        return (
            artifact_class,
            artifact_layer,
            [],
        )

    if extension in {".txt", ".log"}:
        artifact_class, artifact_layer = classify_text(filename)
        return (
            artifact_class,
            artifact_layer,
            [],
        )

    if extension == ".csv":
        return (
            "structured_data",
            "data",
            [],
        )

    if extension == ".html":
        return (
            "generated_report",
            "report",
            [],
        )

    if extension == ".json":
        return classify_json(filename, data)

    return (
        filename_role(filename),
        "unknown",
        [],
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
        manifests / "evidence_classification.csv"
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

        hashes = list(
            csv.DictReader(f)
        )

    hash_map = {
        normalize_path(row["relative_path"]): row
        for row in hashes
    }

    output: list[dict[str, Any]] = []

    for row in inventory:

        relative_path = row["relative_path"]
        full_path = Path(row["full_path"])
        extension = row["extension"].lower()

        data = None

        if (
            extension == ".json"
            and full_path.exists()
        ):
            data = load_json(full_path)

        artifact_class, artifact_layer, signals = (
            classify_artifact(
                relative_path,
                extension,
                data,
            )
        )

        hash_row = hash_map.get(
            normalize_path(relative_path),
            {},
        )

        output.append(
            {
                "relative_path": relative_path,
                "phase": phase_from_path(
                    relative_path
                ),
                "historical_layout": historical_layout(
                    relative_path
                ),
                "environment": environment_from_path(
                    relative_path
                ),
                "extension": extension,
                "artifact_class": artifact_class,
                "artifact_layer": artifact_layer,
                "filename_role": filename_role(
                    Path(relative_path).name
                ),
                "json_parseable": (
                    "yes"
                    if (
                        extension == ".json"
                        and data is not None
                    )
                    else (
                        "no"
                        if extension == ".json"
                        else "not_applicable"
                    )
                ),
                "structural_signals": ";".join(
                    signals
                ),
                "sha256": hash_row.get(
                    "sha256",
                    "",
                ),
                "hash_status": hash_row.get(
                    "hash_status",
                    "",
                ),
            }
        )

    fieldnames = [
        "relative_path",
        "phase",
        "historical_layout",
        "environment",
        "extension",
        "artifact_class",
        "artifact_layer",
        "filename_role",
        "json_parseable",
        "structural_signals",
        "sha256",
        "hash_status",
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
        writer.writerows(output)

    phases = Counter(
        row["phase"]
        for row in output
    )

    layouts = Counter(
        row["historical_layout"]
        for row in output
    )

    classes = Counter(
        row["artifact_class"]
        for row in output
    )

    environments = Counter(
        row["environment"]
        for row in output
    )

    hash_status = Counter(
        row["hash_status"]
        for row in output
    )

    print()
    print("===============================================")
    print(" CityRoute Phase 12 Evidence Classification")
    print("===============================================")
    print()
    print(f"Artifacts classified: {len(output)}")
    print()

    print("By phase:")
    for key, value in sorted(phases.items()):
        print(f"  {key}: {value}")

    print()

    print("Historical layout:")
    for key, value in sorted(
        layouts.items()
    ):
        print(f"  {key}: {value}")

    print()

    print("Environment:")
    for key, value in sorted(
        environments.items()
    ):
        print(f"  {key}: {value}")

    print()

    print("Artifact classes:")
    for key, value in classes.most_common():
        print(f"  {key}: {value}")

    print()

    print("Hash linkage:")
    for key, value in sorted(
        hash_status.items()
    ):
        print(f"  {key}: {value}")

    print()

    print("Output:")
    print(f"  {output_path}")
    print()

    print("No evidence artifacts were modified.")
    print("No benchmark claims were evaluated.")
    print("No acceptance decisions were made.")
    print()


if __name__ == "__main__":
    main()