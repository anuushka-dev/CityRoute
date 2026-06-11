import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path.cwd()

# Phase 3 evidence usually lives in these folders.
EVIDENCE_DIRS = [
    PROJECT_ROOT / "benchmarks" / "docker_results",
    PROJECT_ROOT / "benchmarks" / "results",
]

OUTPUT_DIR = PROJECT_ROOT / "benchmarks" / "phase3_results"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_FILE = OUTPUT_DIR / "phase3_evidence_manifest.json"

manifest = {
    "artifact": "phase3_evidence_manifest",
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "project_root": str(PROJECT_ROOT),
    "phase": "Tier 1 Phase 3 - Custom A* Routing",
    "note": "Manifest generated from existing Phase 3 benchmark/result files. It does not invent benchmark values.",
    "files": [],
}

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

for evidence_dir in EVIDENCE_DIRS:
    if not evidence_dir.exists():
        continue

    for path in sorted(evidence_dir.rglob("*")):
        if not path.is_file():
            continue

        # Skip empty files because they are not valid evidence.
        if path.stat().st_size == 0:
            manifest["files"].append({
                "path": str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                "size_bytes": 0,
                "sha256": None,
                "status": "EMPTY_FILE_NOT_VALID_EVIDENCE",
                "last_modified_utc": datetime.fromtimestamp(
                    path.stat().st_mtime,
                    tz=timezone.utc,
                ).isoformat(),
            })
            continue

        manifest["files"].append({
            "path": str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "status": "OK",
            "last_modified_utc": datetime.fromtimestamp(
                path.stat().st_mtime,
                tz=timezone.utc,
            ).isoformat(),
        })

manifest["summary"] = {
    "total_files_indexed": len(manifest["files"]),
    "valid_files": sum(1 for f in manifest["files"] if f["status"] == "OK"),
    "empty_files": sum(1 for f in manifest["files"] if f["status"] != "OK"),
}

OUTPUT_FILE.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

print(f"wrote: {OUTPUT_FILE}")
print(f"total_files_indexed: {manifest['summary']['total_files_indexed']}")
print(f"valid_files: {manifest['summary']['valid_files']}")
print(f"empty_files: {manifest['summary']['empty_files']}")
