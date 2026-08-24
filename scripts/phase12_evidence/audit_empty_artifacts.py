from __future__ import annotations

import csv
import json
import subprocess
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


def run_git(*args: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

        if result.returncode != 0:
            return []

        return [
            line
            for line in result.stdout.splitlines()
            if line.strip()
        ]

    except Exception:
        return []


def load_json(path: Path) -> Any | None:
    try:
        raw = path.read_bytes()

        if not raw:
            return None

        for encoding in (
            "utf-8",
            "utf-8-sig",
            "utf-16",
        ):
            try:
                return json.loads(raw.decode(encoding))
            except Exception:
                continue

        return None

    except Exception:
        return None


def main() -> None:
    collection = newest_collection()
    manifests = collection / "manifests"

    integrity_path = (
        manifests / "json_integrity_report.csv"
    )

    output_path = (
        manifests / "empty_artifact_audit.csv"
    )

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

    empty_rows = [
        row
        for row in rows
        if row["parse_status"] == "EMPTY"
    ]

    output_rows: list[dict[str, Any]] = []

    for row in empty_rows:

        path = Path(row["full_path"])
        phase_dir = path.parent

        stem = path.stem
        name = path.name

        # --------------------------------------------------
        # Same-directory files
        # --------------------------------------------------

        sibling_files = []

        if phase_dir.exists():
            sibling_files = [
                item
                for item in phase_dir.iterdir()
                if item.is_file()
                and item.name != name
            ]

        # Files with a similar base name.
        stem_tokens = [
            token
            for token in stem.lower().split("_")
            if token
        ]

        related_files = []

        for sibling in sibling_files:
            sibling_name = sibling.name.lower()

            matches = sum(
                1
                for token in stem_tokens
                if token in sibling_name
            )

            if matches >= 3:
                related_files.append(sibling)

        # --------------------------------------------------
        # Phase-wide related files
        # --------------------------------------------------

        phase_root = ROOT / "benchmarks" / "phase_8"

        phase_related = []

        if phase_root.exists():
            for item in phase_root.rglob("*"):
                if not item.is_file():
                    continue

                if item.resolve() == path.resolve():
                    continue

                item_name = item.name.lower()

                if (
                    "phase8" in item_name
                    and (
                        "raw" in item_name
                        or "summary" in item_name
                        or "manifest" in item_name
                        or "result" in item_name
                    )
                ):
                    phase_related.append(item)

        # --------------------------------------------------
        # Git tracking / history
        # --------------------------------------------------

        relative_path = (
            path.relative_to(ROOT)
            .as_posix()
        )

        tracked = bool(
            run_git(
                "ls-files",
                "--error-unmatch",
                relative_path,
            )
        )

        git_history = run_git(
            "log",
            "--all",
            "--follow",
            "--format=%H|%ad|%s",
            "--date=iso-strict",
            "--",
            relative_path,
        )

        # Search commits that mention related Phase 8 raw files.
        git_related_history = run_git(
            "log",
            "--all",
            "--format=%H|%ad|%s",
            "--date=iso-strict",
            "--",
            "benchmarks/phase_8",
        )

        # --------------------------------------------------
        # Non-empty related JSON files
        # --------------------------------------------------

        nonempty_related_json = []

        for candidate in phase_related:
            if candidate.suffix.lower() != ".json":
                continue

            try:
                size = candidate.stat().st_size
            except OSError:
                continue

            if size == 0:
                continue

            data = load_json(candidate)

            nonempty_related_json.append(
                {
                    "path": candidate.relative_to(ROOT).as_posix(),
                    "size_bytes": size,
                    "json_parseable": data is not None,
                    "name": candidate.name,
                }
            )

        output_rows.append(
            {
                "empty_artifact": relative_path,
                "size_bytes": path.stat().st_size
                if path.exists()
                else "",
                "parent_directory":
                    phase_dir.relative_to(ROOT).as_posix(),
                "git_tracked":
                    tracked,
                "git_history_count":
                    len(git_history),
                "same_directory_related_count":
                    len(related_files),
                "phase8_related_count":
                    len(phase_related),
                "nonempty_related_json_count":
                    len(nonempty_related_json),
                "same_directory_related":
                    ";".join(
                        x.relative_to(ROOT).as_posix()
                        for x in related_files
                    ),
                "nonempty_phase8_json":
                    ";".join(
                        x["path"]
                        for x in nonempty_related_json
                    ),
                "git_history":
                    " || ".join(git_history),
                "phase8_git_history_count":
                    len(git_related_history),
            }
        )

    fieldnames = [
        "empty_artifact",
        "size_bytes",
        "parent_directory",
        "git_tracked",
        "git_history_count",
        "same_directory_related_count",
        "phase8_related_count",
        "nonempty_related_json_count",
        "same_directory_related",
        "nonempty_phase8_json",
        "git_history",
        "phase8_git_history_count",
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
    print(" CityRoute Phase 12 Empty Artifact Audit")
    print("===============================================")
    print()

    print(
        f"Empty artifacts inspected: {len(empty_rows)}"
    )

    print()

    for result in output_rows:

        print(
            result["empty_artifact"]
        )

        print(
            f"  size: {result['size_bytes']} bytes"
        )

        print(
            f"  git tracked: {result['git_tracked']}"
        )

        print(
            "  same-directory related: "
            f"{result['same_directory_related_count']}"
        )

        print(
            "  phase-8 related artifacts: "
            f"{result['phase8_related_count']}"
        )

        print(
            "  non-empty related JSON: "
            f"{result['nonempty_related_json_count']}"
        )

        if result["nonempty_phase8_json"]:
            print(
                "  related JSON:"
            )
            for item in result[
                "nonempty_phase8_json"
            ].split(";"):
                print(f"    {item}")

        print(
            "  git history entries: "
            f"{result['git_history_count']}"
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