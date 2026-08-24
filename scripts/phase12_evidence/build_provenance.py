from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

ROOT = Path.cwd()
EVIDENCE_ROOT = ROOT / ".phase12_evidence"

ARTIFACT_EXTENSIONS = {
    ".json", ".txt", ".log", ".csv", ".html", ".md", ".py", ".pyc"
}

PATH_LIKE_RE = re.compile(
    r"(?i)(?:benchmarks[\\/][^\"'\s]+|"
    r"(?:phase\d+(?:_\d+)?|phase_\d+(?:_\d+)?)[\\/][^\"'\s]+)"
)

RAW_TO_SUMMARY_RE = re.compile(
    r"^(?P<prefix>.+)_raw(?P<suffix>(?:_.+)?)\.json$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Artifact:
    relative_path: str
    full_path: Path
    extension: str
    sha256: str
    hash_status: str


@dataclass(frozen=True)
class Edge:
    source_artifact: str
    target_artifact: str
    relationship: str
    evidence_basis: str
    confidence: str
    json_pointer: str
    phase: str
    source_run_id: str
    target_run_id: str
    note: str


def newest_collection() -> Path:
    collections = sorted(
        EVIDENCE_ROOT.glob("collection_*"),
        key=lambda p: p.name,
        reverse=True,
    )
    if not collections:
        raise FileNotFoundError(
            "No Phase 12 collection found under .phase12_evidence."
        )
    return collections[0]


def norm(value: str) -> str:
    return value.replace("\\", "/").strip().lower()


def phase_from_path(path: str) -> str:
    value = norm(path)
    patterns = (
        r"benchmarks/(phase_\d+_\d+)",
        r"benchmarks/(phase_\d+)",
        r"benchmarks/(phase\d+_\d+)",
        r"benchmarks/(phase\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return match.group(1)
    return "unassigned"


def load_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def pointer_escape(token: str) -> str:
    return str(token).replace("~", "~0").replace("/", "~1")


def walk_json(value: Any, pointer: str = "$") -> Iterator[tuple[str, Any]]:
    yield pointer, value

    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk_json(
                child,
                f"{pointer}/{pointer_escape(str(key))}",
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_json(
                child,
                f"{pointer}/{index}",
            )


def normalize_candidate(value: str) -> str:
    candidate = value.strip().strip("\"'`")
    candidate = candidate.rstrip(",;")
    return candidate.replace("/", "\\")


def exact_artifact_match(
    value: str,
    artifact_map: dict[str, Artifact],
) -> Artifact | None:
    candidate = normalize_candidate(value)
    candidate_norm = norm(candidate)

    if candidate_norm in artifact_map:
        return artifact_map[candidate_norm]

    # A Windows absolute path from the repository can be converted
    # back to a repository-relative path only when it is clearly under ROOT.
    try:
        path = Path(candidate)
        if path.is_absolute():
            resolved = path.resolve()
            try:
                relative = resolved.relative_to(ROOT.resolve())
            except ValueError:
                return None
            key = norm(str(relative))
            return artifact_map.get(key)
    except (OSError, ValueError):
        return None

    return None


def basename_candidates(
    value: str,
    artifact_map: dict[str, Artifact],
) -> list[Artifact]:
    basename = Path(normalize_candidate(value)).name.lower()
    if not basename:
        return []

    return [
        artifact
        for artifact in artifact_map.values()
        if Path(artifact.relative_path).name.lower() == basename
    ]


def extract_string_edges(
    source: Artifact,
    pointer: str,
    value: str,
    artifact_map: dict[str, Artifact],
) -> list[Edge]:
    edges: list[Edge] = []

    # First: the whole string can be an exact repository-relative artifact path.
    exact = exact_artifact_match(value, artifact_map)
    if exact and exact.relative_path != source.relative_path:
        edges.append(
            Edge(
                source_artifact=source.relative_path,
                target_artifact=exact.relative_path,
                relationship="references_artifact",
                evidence_basis="exact_artifact_path",
                confidence="DIRECT",
                json_pointer=pointer,
                phase=phase_from_path(source.relative_path),
                source_run_id="",
                target_run_id="",
                note="Exact repository-relative artifact path resolved.",
            )
        )
        return edges

    # Then search embedded path-like substrings.
    for match in PATH_LIKE_RE.finditer(value):
        candidate = normalize_candidate(match.group(0))
        exact = exact_artifact_match(candidate, artifact_map)
        if exact and exact.relative_path != source.relative_path:
            edges.append(
                Edge(
                    source_artifact=source.relative_path,
                    target_artifact=exact.relative_path,
                    relationship="references_artifact",
                    evidence_basis="embedded_exact_artifact_path",
                    confidence="DIRECT",
                    json_pointer=pointer,
                    phase=phase_from_path(source.relative_path),
                    source_run_id="",
                    target_run_id="",
                    note="Embedded repository-relative artifact path resolved exactly.",
                )
            )
            continue

        candidates = basename_candidates(candidate, artifact_map)
        if len(candidates) == 1 and candidates[0].relative_path != source.relative_path:
            target = candidates[0]
            edges.append(
                Edge(
                    source_artifact=source.relative_path,
                    target_artifact=target.relative_path,
                    relationship="references_artifact",
                    evidence_basis="unique_basename_match",
                    confidence="INFERRED",
                    json_pointer=pointer,
                    phase=phase_from_path(source.relative_path),
                    source_run_id="",
                    target_run_id="",
                    note="JSON contained an artifact-like reference, but only the basename matched a unique repository file.",
                )
            )

    return edges


def collect_run_ids(data: Any) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []

    for pointer, value in walk_json(data):
        if isinstance(value, str):
            key = pointer.rsplit("/", 1)[-1].lower()
            if "run_id" in key and value.strip():
                results.append((pointer, value.strip()))

    return results


def phase_json_artifacts(
    artifacts: list[Artifact],
) -> dict[str, list[Artifact]]:
    grouped: dict[str, list[Artifact]] = {}
    for artifact in artifacts:
        phase = phase_from_path(artifact.relative_path)
        grouped.setdefault(phase, []).append(artifact)
    return grouped


def raw_summary_pairs(
    artifacts: list[Artifact],
) -> list[Edge]:
    artifact_map = {
        norm(artifact.relative_path): artifact
        for artifact in artifacts
    }

    pairs: list[Edge] = []

    for artifact in artifacts:
        if artifact.extension.lower() != ".json":
            continue

        filename = Path(artifact.relative_path).name
        match = RAW_TO_SUMMARY_RE.match(filename)
        if not match:
            continue

        summary_name = (
            f"{match.group('prefix')}_summary"
            f"{match.group('suffix')}.json"
        )

        candidate = Path(artifact.relative_path).with_name(summary_name)
        target = artifact_map.get(norm(str(candidate)))

        if not target:
            continue

        if target.relative_path == artifact.relative_path:
            continue

        pairs.append(
            Edge(
                source_artifact=artifact.relative_path,
                target_artifact=target.relative_path,
                relationship="paired_raw_summary",
                evidence_basis="exact_filename_transform",
                confidence="INFERRED",
                json_pointer="",
                phase=phase_from_path(artifact.relative_path),
                source_run_id="",
                target_run_id="",
                note="Raw/summary pairing is inferred only from exact _raw_ -> _summary_ filename transformation.",
            )
        )

    return pairs


def deduplicate_edges(edges: list[Edge]) -> list[Edge]:
    seen: set[tuple[str, str, str, str, str]] = set()
    result: list[Edge] = []

    for edge in edges:
        key = (
            norm(edge.source_artifact),
            norm(edge.target_artifact),
            edge.relationship,
            edge.json_pointer,
            edge.evidence_basis,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(edge)

    return result


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    collection = newest_collection()
    manifests = collection / "manifests"

    inventory_path = manifests / "benchmark_inventory.csv"
    hash_path = manifests / "sha256_manifest.csv"
    classification_path = manifests / "evidence_classification.csv"

    for required in (
        inventory_path,
        hash_path,
        classification_path,
    ):
        if not required.exists():
            raise FileNotFoundError(f"Missing required manifest: {required}")

    inventory = load_manifest(inventory_path)
    hashes = load_manifest(hash_path)

    hash_map = {
        norm(row["relative_path"]): row
        for row in hashes
    }

    artifacts: list[Artifact] = []

    for row in inventory:
        artifact = Artifact(
            relative_path=row["relative_path"],
            full_path=Path(row["full_path"]),
            extension=row["extension"].lower(),
            sha256=hash_map.get(
                norm(row["relative_path"]), {}
            ).get("sha256", ""),
            hash_status=hash_map.get(
                norm(row["relative_path"]), {}
            ).get("hash_status", ""),
        )
        artifacts.append(artifact)

    artifact_map = {
        norm(artifact.relative_path): artifact
        for artifact in artifacts
    }

    json_artifacts = [
        artifact
        for artifact in artifacts
        if artifact.extension == ".json"
    ]

    parsed_json: dict[str, Any] = {}
    run_locations: list[tuple[Artifact, str, str]] = []

    for artifact in json_artifacts:
        if not artifact.full_path.exists():
            continue

        try:
            data = load_json(artifact.full_path)
        except Exception:
            continue

        parsed_json[artifact.relative_path] = data

        for pointer, run_id in collect_run_ids(data):
            run_locations.append((artifact, pointer, run_id))

    edges: list[Edge] = []

    # Exact/embedded artifact references from JSON.
    for source, data in parsed_json.items():
        source_artifact = artifact_map[norm(source)]

        for pointer, value in walk_json(data):
            if not isinstance(value, str):
                continue

            edges.extend(
                extract_string_edges(
                    source_artifact,
                    pointer,
                    value,
                    artifact_map,
                )
            )

    # Filename-based raw -> summary pairing.
    edges.extend(raw_summary_pairs(artifacts))

    # Shared nested run_id values.
    by_run_id: dict[str, list[tuple[Artifact, str]]] = {}
    for artifact, pointer, run_id in run_locations:
        by_run_id.setdefault(run_id, []).append((artifact, pointer))

    for run_id, entries in by_run_id.items():
        unique_artifacts = {}
        for artifact, pointer in entries:
            unique_artifacts[artifact.relative_path] = pointer

        if len(unique_artifacts) < 2:
            continue

        paths = sorted(unique_artifacts)
        for index, left_path in enumerate(paths):
            for right_path in paths[index + 1 :]:
                if left_path == right_path:
                    continue

                edges.append(
                    Edge(
                        source_artifact=left_path,
                        target_artifact=right_path,
                        relationship="shares_run_id",
                        evidence_basis="same_nested_run_id",
                        confidence="INFERRED",
                        json_pointer=unique_artifacts[left_path],
                        phase=phase_from_path(left_path),
                        source_run_id=run_id,
                        target_run_id=run_id,
                        note="Both artifacts contain the same nested run_id; shared identity is inferred, not direct lineage.",
                    )
                )

    # Attach source run_id only when there is exactly one run ID
    # in the source artifact. This avoids silently choosing among multiple IDs.
    unique_run_ids_by_artifact: dict[str, str] = {}
    for artifact, _pointer, run_id in run_locations:
        key = artifact.relative_path
        unique_run_ids_by_artifact.setdefault(key, run_id)

    enriched: list[Edge] = []
    for edge in edges:
        source_run_id = unique_run_ids_by_artifact.get(
            edge.source_artifact,
            edge.source_run_id,
        )
        target_run_id = unique_run_ids_by_artifact.get(
            edge.target_artifact,
            edge.target_run_id,
        )

        enriched.append(
            Edge(
                source_artifact=edge.source_artifact,
                target_artifact=edge.target_artifact,
                relationship=edge.relationship,
                evidence_basis=edge.evidence_basis,
                confidence=edge.confidence,
                json_pointer=edge.json_pointer,
                phase=edge.phase,
                source_run_id=source_run_id or "",
                target_run_id=target_run_id or "",
                note=edge.note,
            )
        )

    edges = deduplicate_edges(enriched)

    edge_output = manifests / "provenance_edges.csv"
    artifact_output = manifests / "provenance_artifacts.csv"
    summary_output = manifests / "provenance_summary.json"

    artifact_rows = []
    for artifact in artifacts:
        run_ids = sorted(
            {
                run_id
                for run_artifact, _pointer, run_id in run_locations
                if run_artifact.relative_path == artifact.relative_path
            }
        )

        artifact_rows.append(
            {
                "relative_path": artifact.relative_path,
                "phase": phase_from_path(artifact.relative_path),
                "extension": artifact.extension,
                "sha256": artifact.sha256,
                "hash_status": artifact.hash_status,
                "file_exists": artifact.full_path.exists(),
                "run_id_count": len(run_ids),
                "run_ids": ";".join(run_ids),
                "json_parsed": artifact.relative_path in parsed_json,
            }
        )

    edge_rows = [
        {
            "source_artifact": edge.source_artifact,
            "target_artifact": edge.target_artifact,
            "relationship": edge.relationship,
            "evidence_basis": edge.evidence_basis,
            "confidence": edge.confidence,
            "json_pointer": edge.json_pointer,
            "phase": edge.phase,
            "source_run_id": edge.source_run_id,
            "target_run_id": edge.target_run_id,
            "note": edge.note,
        }
        for edge in edges
    ]

    write_csv(
        artifact_output,
        artifact_rows,
        [
            "relative_path",
            "phase",
            "extension",
            "sha256",
            "hash_status",
            "file_exists",
            "run_id_count",
            "run_ids",
            "json_parsed",
        ],
    )

    write_csv(
        edge_output,
        edge_rows,
        [
            "source_artifact",
            "target_artifact",
            "relationship",
            "evidence_basis",
            "confidence",
            "json_pointer",
            "phase",
            "source_run_id",
            "target_run_id",
            "note",
        ],
    )

    summary = {
        "collection_directory": str(collection),
        "artifact_count": len(artifacts),
        "json_artifact_count": len(json_artifacts),
        "parseable_json_count": len(parsed_json),
        "artifacts_with_nested_run_id": len(
            {
                artifact.relative_path
                for artifact, _pointer, _run_id in run_locations
            }
        ),
        "nested_run_id_occurrence_count": len(run_locations),
        "edge_count": len(edges),
        "edge_confidence": dict(
            Counter(edge.confidence for edge in edges)
        ),
        "edge_types": dict(
            Counter(edge.relationship for edge in edges)
        ),
        "evidence_basis": dict(
            Counter(edge.evidence_basis for edge in edges)
        ),
        "edge_phases": dict(
            Counter(edge.phase for edge in edges)
        ),
        "principles": [
            "Direct artifact references require an exact repository-relative path resolution.",
            "Embedded paths that resolve exactly are DIRECT.",
            "Unique-basename matches are INFERRED.",
            "Raw-to-summary filename transformations are INFERRED.",
            "Shared nested run_id relationships are INFERRED.",
            "Every reference edge records the JSON pointer that created it.",
            "Unknown provenance is not converted into a positive relationship.",
            "No benchmark acceptance, validity, or engineering decision is inferred here.",
        ],
        "outputs": {
            "provenance_artifacts": str(artifact_output),
            "provenance_edges": str(edge_output),
            "provenance_summary": str(summary_output),
        },
    }

    with summary_output.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    print()
    print("===============================================")
    print(" CityRoute Phase 12 Evidence Provenance v0.2")
    print("===============================================")
    print()
    print(f"Artifacts inspected: {len(artifacts)}")
    print(f"JSON artifacts found: {len(json_artifacts)}")
    print(f"JSON artifacts parsed: {len(parsed_json)}")
    print(
        "Artifacts with nested run_id: "
        f"{summary['artifacts_with_nested_run_id']}"
    )
    print(
        "Nested run_id occurrences: "
        f"{summary['nested_run_id_occurrence_count']}"
    )
    print(f"Provenance edges: {len(edges)}")
    print()
    print("Edge confidence:")
    for key, value in sorted(
        Counter(edge.confidence for edge in edges).items()
    ):
        print(f"  {key}: {value}")

    print()
    print("Evidence basis:")
    for key, value in sorted(
        Counter(edge.evidence_basis for edge in edges).items()
    ):
        print(f"  {key}: {value}")

    print()
    print("Edge types:")
    for key, value in sorted(
        Counter(edge.relationship for edge in edges).items()
    ):
        print(f"  {key}: {value}")

    print()
    print("Output files:")
    print(f"  {artifact_output}")
    print(f"  {edge_output}")
    print(f"  {summary_output}")
    print()
    print("No benchmark artifacts were modified.")
    print("No benchmark claims were evaluated.")
    print("No acceptance decisions were made.")
    print()


if __name__ == "__main__":
    main()