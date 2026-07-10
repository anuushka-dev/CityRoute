# collect_phase9_evidence.py

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_LOCAL_OUTPUT_DIR = PROJECT_ROOT / "benchmarks" / "phase_9" / "local_results"
DEFAULT_DOCKER_OUTPUT_DIR = PROJECT_ROOT / "benchmarks" / "phase_9" / "docker_results"

DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_DOCKER_BASE_URL = "http://127.0.0.1:8001"


EXPECTED_SOURCE_FILES = [
    "app/core/hungarian.py",
    "app/core/greedy_dispatch.py",
    "app/core/dispatch_cost_matrix.py",
    "app/core/dispatch_fairness.py",
    "app/schemas/dispatch.py",
    "app/services/dispatch_service.py",
    "app/api/dispatch.py",
    "app/main.py",
]

EXPECTED_TEST_FILES = [
    "tests/test_hungarian_algorithm.py",
    "tests/test_greedy_dispatch.py",
    "tests/test_dispatch_cost_matrix.py",
    "tests/test_dispatch_fairness.py",
    "tests/test_dispatch_endpoint.py",
]

EXPECTED_BENCHMARK_FILES = [
    "benchmarks/phase_9/phase9_hungarian_correctness_probe.py",
    "benchmarks/phase_9/phase9_hungarian_speed_benchmark.py",
    "benchmarks/phase_9/phase9_dispatch_endpoint_benchmark.py",
    "benchmarks/phase_9/phase9_dispatch_fairness_probe.py",
    "benchmarks/phase_9/phase9_dispatch_cache_probe.py",
    "benchmarks/phase_9/collect_phase9_evidence.py",
]

PHASE9_ENDPOINT = "/dispatch/compare"


@dataclass(frozen=True)
class FileAuditRecord:
    relative_path: str
    exists: bool
    size_bytes: int | None
    modified_utc: str | None
    sha256: str | None


@dataclass(frozen=True)
class JsonEvidenceRecord:
    relative_path: str
    filename: str
    exists: bool
    size_bytes: int
    modified_utc: str
    sha256: str
    json_valid: bool
    parse_error: str | None
    phase: str | None
    benchmark: str | None
    mode: str | None
    is_summary: bool
    quality_flags: dict[str, bool]
    key_metrics: dict[str, Any]


@dataclass(frozen=True)
class CommandResult:
    name: str
    command: list[str]
    returncode: int
    passed: bool
    elapsed_ms: float
    stdout_tail: str
    stderr_tail: str


@dataclass(frozen=True)
class HttpCheckResult:
    name: str
    url: str
    success: bool
    status_code: int | None
    elapsed_ms: float
    error: str | None
    key_values: dict[str, Any]


@dataclass(frozen=True)
class GitEvidence:
    branch: str | None
    commit: str | None
    short_status: str | None
    clean_working_tree: bool | None


@dataclass(frozen=True)
class Phase9EvidenceManifest:
    phase: str
    collector: str
    mode: str
    base_url: str | None
    created_at_utc: str
    project_root: str
    output_manifest_json: str
    output_manifest_txt: str
    source_files: list[FileAuditRecord]
    test_files: list[FileAuditRecord]
    benchmark_files: list[FileAuditRecord]
    result_files: list[JsonEvidenceRecord]
    latest_summary_files: list[JsonEvidenceRecord]
    command_results: list[CommandResult]
    http_checks: list[HttpCheckResult]
    git: GitEvidence
    quality_flags: dict[str, bool]


def main() -> None:
    args = _parse_args()

    mode: Literal["local", "docker"] = args.mode
    output_dir = _resolve_output_dir(mode=mode, output_dir=args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    base_url = _resolve_base_url(
        mode=mode,
        base_url=args.base_url,
        skip_http=args.skip_http_checks,
    )

    source_files = [_audit_file(path) for path in EXPECTED_SOURCE_FILES]
    test_files = [_audit_file(path) for path in EXPECTED_TEST_FILES]
    benchmark_files = [_audit_file(path) for path in EXPECTED_BENCHMARK_FILES]

    result_files = _collect_json_evidence(output_dir)
    latest_summary_files = _latest_summary_files(result_files)

    command_results = _run_optional_commands(
        run_pytest=args.run_pytest,
        run_ruff=args.run_ruff,
    )

    http_checks = []
    if base_url is not None:
        http_checks = _run_http_checks(base_url=base_url, timeout_s=args.timeout_s)

    git_evidence = _collect_git_evidence()

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    manifest_json_path = output_dir / f"phase9_evidence_manifest_{mode}_{timestamp}.json"
    manifest_txt_path = output_dir / f"phase9_evidence_manifest_{mode}_{timestamp}.txt"

    quality_flags = _build_quality_flags(
        source_files=source_files,
        test_files=test_files,
        benchmark_files=benchmark_files,
        result_files=result_files,
        latest_summary_files=latest_summary_files,
        command_results=command_results,
        http_checks=http_checks,
        git_evidence=git_evidence,
        require_cache=args.require_cache,
        skip_http_checks=args.skip_http_checks,
        run_pytest=args.run_pytest,
        run_ruff=args.run_ruff,
    )

    manifest = Phase9EvidenceManifest(
        phase="tier3_phase9",
        collector="collect_phase9_evidence",
        mode=mode,
        base_url=base_url,
        created_at_utc=datetime.now(UTC).isoformat(),
        project_root=str(PROJECT_ROOT),
        output_manifest_json=str(manifest_json_path.relative_to(PROJECT_ROOT)),
        output_manifest_txt=str(manifest_txt_path.relative_to(PROJECT_ROOT)),
        source_files=source_files,
        test_files=test_files,
        benchmark_files=benchmark_files,
        result_files=result_files,
        latest_summary_files=latest_summary_files,
        command_results=command_results,
        http_checks=http_checks,
        git=git_evidence,
        quality_flags=quality_flags,
    )

    manifest_payload = _manifest_to_jsonable_dict(manifest)

    _write_json(manifest_json_path, manifest_payload)
    _write_text(manifest_txt_path, _build_text_manifest(manifest))

    print(json.dumps(manifest_payload, indent=2))

    if args.strict and not all(quality_flags.values()):
        raise SystemExit(1)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect Phase 9 Hungarian dispatch evidence manifest.",
    )
    parser.add_argument(
        "--mode",
        choices=["local", "docker"],
        default="local",
        help="Evidence mode. Controls output folder and default base URL.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=(
            "Optional API base URL. If omitted, local uses 127.0.0.1:8000 "
            "and docker uses 127.0.0.1:8001."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Optional output directory. If omitted, writes to "
            "benchmarks/phase_9/local_results or docker_results."
        ),
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=10.0,
        help="HTTP timeout for endpoint checks.",
    )
    parser.add_argument(
        "--skip-http-checks",
        action="store_true",
        help="Skip /health, /openapi.json, and root endpoint checks.",
    )
    parser.add_argument(
        "--run-pytest",
        action="store_true",
        help="Run Phase 9 pytest suite and include output in manifest.",
    )
    parser.add_argument(
        "--run-ruff",
        action="store_true",
        help="Run Ruff on Phase 9 files and include output in manifest.",
    )
    parser.add_argument(
        "--require-cache",
        action="store_true",
        help="Treat missing dispatch cache hits as a strict failure.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any manifest quality flag is false.",
    )
    return parser.parse_args()


def _resolve_output_dir(*, mode: str, output_dir: str | None) -> Path:
    if output_dir is not None:
        return Path(output_dir)

    if mode == "docker":
        return DEFAULT_DOCKER_OUTPUT_DIR

    return DEFAULT_LOCAL_OUTPUT_DIR


def _resolve_base_url(
    *,
    mode: str,
    base_url: str | None,
    skip_http: bool,
) -> str | None:
    if skip_http:
        return None

    if base_url is not None:
        return base_url.rstrip("/")

    if mode == "docker":
        return DEFAULT_DOCKER_BASE_URL

    return DEFAULT_LOCAL_BASE_URL


def _audit_file(relative_path: str) -> FileAuditRecord:
    path = PROJECT_ROOT / relative_path

    if not path.exists() or not path.is_file():
        return FileAuditRecord(
            relative_path=relative_path,
            exists=False,
            size_bytes=None,
            modified_utc=None,
            sha256=None,
        )

    return FileAuditRecord(
        relative_path=relative_path,
        exists=True,
        size_bytes=path.stat().st_size,
        modified_utc=_modified_utc(path),
        sha256=_sha256(path),
    )


def _collect_json_evidence(output_dir: Path) -> list[JsonEvidenceRecord]:
    if not output_dir.exists():
        return []

    records = []

    for path in sorted(output_dir.glob("*.json")):
        records.append(_audit_json_file(path))

    return records


def _audit_json_file(path: Path) -> JsonEvidenceRecord:
    payload: dict[str, Any] | None = None
    parse_error = None
    json_valid = False

    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        json_valid = isinstance(payload, dict)
    except json.JSONDecodeError as exc:
        parse_error = str(exc)

    quality_flags = {}
    key_metrics: dict[str, Any] = {}
    phase = None
    benchmark = None
    mode = None

    if payload is not None:
        phase = _optional_str(payload.get("phase"))
        benchmark = _optional_str(payload.get("benchmark"))
        mode = _optional_str(payload.get("mode"))
        quality_flags = _bool_dict(payload.get("quality_flags"))
        key_metrics = _extract_key_metrics(payload)

    return JsonEvidenceRecord(
        relative_path=str(path.relative_to(PROJECT_ROOT)),
        filename=path.name,
        exists=True,
        size_bytes=path.stat().st_size,
        modified_utc=_modified_utc(path),
        sha256=_sha256(path),
        json_valid=json_valid,
        parse_error=parse_error,
        phase=phase,
        benchmark=benchmark,
        mode=mode,
        is_summary="summary" in path.name or "manifest" in path.name,
        quality_flags=quality_flags,
        key_metrics=key_metrics,
    )


def _latest_summary_files(
    result_files: list[JsonEvidenceRecord],
) -> list[JsonEvidenceRecord]:
    summaries = [
        item
        for item in result_files
        if item.json_valid and item.is_summary and item.benchmark is not None
    ]

    latest_by_benchmark: dict[str, JsonEvidenceRecord] = {}

    for item in summaries:
        current = latest_by_benchmark.get(item.benchmark or "")
        if current is None or item.modified_utc > current.modified_utc:
            latest_by_benchmark[item.benchmark or ""] = item

    return [
        latest_by_benchmark[key]
        for key in sorted(latest_by_benchmark)
    ]


def _extract_key_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "case_count",
        "success_count",
        "failure_count",
        "success_rate_pct",
        "mismatch_count",
        "cache_hit_count",
        "cache_hit_rate_pct",
        "cycle_count",
        "successful_cycle_count",
        "failed_cycle_count",
        "request_count",
        "scenario_count",
        "policy_count",
        "iterations_per_size",
        "cycles_per_size",
        "mode",
        "base_url",
        "endpoint",
        "matrix_algorithm",
    ]

    return {
        key: payload[key]
        for key in keys
        if key in payload
    }


def _run_optional_commands(
    *,
    run_pytest: bool,
    run_ruff: bool,
) -> list[CommandResult]:
    results = []

    if run_pytest:
        results.append(
            _run_command(
                name="phase9_pytest",
                command=[
                    sys.executable,
                    "-m",
                    "pytest",
                    *EXPECTED_TEST_FILES,
                    "-v",
                ],
            )
        )

    if run_ruff:
        results.append(
            _run_command(
                name="phase9_ruff",
                command=[
                    sys.executable,
                    "-m",
                    "ruff",
                    "check",
                    *EXPECTED_SOURCE_FILES,
                    *EXPECTED_TEST_FILES,
                    *EXPECTED_BENCHMARK_FILES,
                ],
            )
        )

    return results


def _run_command(*, name: str, command: list[str]) -> CommandResult:
    started_at = perf_counter()

    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    elapsed_ms = round((perf_counter() - started_at) * 1000.0, 6)

    return CommandResult(
        name=name,
        command=command,
        returncode=completed.returncode,
        passed=completed.returncode == 0,
        elapsed_ms=elapsed_ms,
        stdout_tail=_tail(completed.stdout),
        stderr_tail=_tail(completed.stderr),
    )


def _run_http_checks(*, base_url: str, timeout_s: float) -> list[HttpCheckResult]:
    return [
        _http_get_json(
            name="root",
            url=f"{base_url}/",
            timeout_s=timeout_s,
        ),
        _http_get_json(
            name="health",
            url=f"{base_url}/health",
            timeout_s=timeout_s,
        ),
        _http_get_json(
            name="openapi",
            url=f"{base_url}/openapi.json",
            timeout_s=timeout_s,
        ),
    ]


def _http_get_json(*, name: str, url: str, timeout_s: float) -> HttpCheckResult:
    started_at = perf_counter()
    status_code = None

    try:
        request = Request(
            url=url,
            headers={"Accept": "application/json"},
            method="GET",
        )

        with urlopen(request, timeout=timeout_s) as response:
            status_code = response.status
            body = response.read().decode("utf-8")

        elapsed_ms = round((perf_counter() - started_at) * 1000.0, 6)
        payload = json.loads(body) if body else {}

        return HttpCheckResult(
            name=name,
            url=url,
            success=_http_payload_success(name=name, payload=payload),
            status_code=status_code,
            elapsed_ms=elapsed_ms,
            error=None,
            key_values=_extract_http_key_values(name=name, payload=payload),
        )

    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        elapsed_ms = round((perf_counter() - started_at) * 1000.0, 6)

        return HttpCheckResult(
            name=name,
            url=url,
            success=False,
            status_code=status_code,
            elapsed_ms=elapsed_ms,
            error=str(exc),
            key_values={},
        )


def _http_payload_success(*, name: str, payload: dict[str, Any]) -> bool:
    if name == "root":
        return payload.get("dispatch_compare") == PHASE9_ENDPOINT

    if name == "health":
        return payload.get("status") == "ok"

    if name == "openapi":
        paths = payload.get("paths", {})
        return PHASE9_ENDPOINT in paths and "post" in paths[PHASE9_ENDPOINT]

    return False


def _extract_http_key_values(
    *,
    name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if name == "root":
        return {
            "phase": payload.get("phase"),
            "dispatch_compare": payload.get("dispatch_compare"),
        }

    if name == "health":
        return {
            "status": payload.get("status"),
            "graph_loaded": payload.get("graph_loaded"),
        }

    if name == "openapi":
        paths = payload.get("paths", {})
        return {
            "dispatch_compare_available": PHASE9_ENDPOINT in paths,
            "path_count": len(paths),
        }

    return {}


def _collect_git_evidence() -> GitEvidence:
    branch = _git_output(["git", "branch", "--show-current"])
    commit = _git_output(["git", "rev-parse", "--short", "HEAD"])
    short_status = _git_output(["git", "status", "--short"])

    clean_working_tree = None
    if short_status is not None:
        clean_working_tree = short_status.strip() == ""

    return GitEvidence(
        branch=branch,
        commit=commit,
        short_status=short_status,
        clean_working_tree=clean_working_tree,
    )


def _git_output(command: list[str]) -> str | None:
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if completed.returncode != 0:
        return None

    return completed.stdout.strip()


def _build_quality_flags(
    *,
    source_files: list[FileAuditRecord],
    test_files: list[FileAuditRecord],
    benchmark_files: list[FileAuditRecord],
    result_files: list[JsonEvidenceRecord],
    latest_summary_files: list[JsonEvidenceRecord],
    command_results: list[CommandResult],
    http_checks: list[HttpCheckResult],
    git_evidence: GitEvidence,
    require_cache: bool,
    skip_http_checks: bool,
    run_pytest: bool,
    run_ruff: bool,
) -> dict[str, bool]:
    all_json_valid = all(item.json_valid for item in result_files)
    has_results = len(result_files) > 0
    has_latest_summaries = len(latest_summary_files) > 0

    return {
        "all_expected_source_files_exist": all(item.exists for item in source_files),
        "all_expected_test_files_exist": all(item.exists for item in test_files),
        "all_expected_benchmark_files_exist": all(
            item.exists for item in benchmark_files
        ),
        "result_json_files_present": has_results,
        "all_result_json_files_valid": all_json_valid and has_results,
        "latest_summary_files_present": has_latest_summaries,
        "all_critical_summary_quality_flags_true": (
            _all_critical_summary_flags_true(
                latest_summary_files,
                require_cache=require_cache,
            )
            and has_latest_summaries
        ),
        "pytest_passed": _command_passed(
            command_results,
            name="phase9_pytest",
            required=run_pytest,
        ),
        "ruff_passed": _command_passed(
            command_results,
            name="phase9_ruff",
            required=run_ruff,
        ),
        "http_checks_passed": True
        if skip_http_checks
        else all(item.success for item in http_checks) and len(http_checks) == 3,
        "dispatch_endpoint_available": True
        if skip_http_checks
        else _http_check_success(http_checks, "openapi"),
        "health_ok": True
        if skip_http_checks
        else _http_check_success(http_checks, "health"),
        "git_commit_available": git_evidence.commit is not None,
    }


def _all_critical_summary_flags_true(
    summaries: list[JsonEvidenceRecord],
    *,
    require_cache: bool,
) -> bool:
    for summary in summaries:
        if not summary.quality_flags:
            return False

        for key, value in summary.quality_flags.items():
            if _non_critical_quality_flag(key, require_cache=require_cache):
                continue

            if value is not True:
                return False

    return True


def _non_critical_quality_flag(key: str, *, require_cache: bool) -> bool:
    if "_under_" in key:
        return True

    if key == "repeat_faster_or_equal_all_cycles":
        return True

    if key == "cache_hits_observed" and not require_cache:
        return True

    return False


def _command_passed(
    command_results: list[CommandResult],
    *,
    name: str,
    required: bool,
) -> bool:
    if not required:
        return True

    for result in command_results:
        if result.name == name:
            return result.passed

    return False


def _http_check_success(http_checks: list[HttpCheckResult], name: str) -> bool:
    for check in http_checks:
        if check.name == name:
            return check.success

    return False


def _manifest_to_jsonable_dict(manifest: Phase9EvidenceManifest) -> dict[str, Any]:
    return asdict(manifest)


def _build_text_manifest(manifest: Phase9EvidenceManifest) -> str:
    lines = [
        "CityRoute Tier 3 Phase 9 Evidence Manifest",
        "=" * 48,
        f"Created UTC: {manifest.created_at_utc}",
        f"Mode: {manifest.mode}",
        f"Base URL: {manifest.base_url}",
        f"Project root: {manifest.project_root}",
        "",
        "Quality Flags:",
    ]

    for key, value in manifest.quality_flags.items():
        lines.append(f"- {key}: {value}")

    lines.extend(
        [
            "",
            "Expected Source Files:",
            *_format_file_records(manifest.source_files),
            "",
            "Expected Test Files:",
            *_format_file_records(manifest.test_files),
            "",
            "Expected Benchmark Files:",
            *_format_file_records(manifest.benchmark_files),
            "",
            "Latest Summary Files:",
        ]
    )

    for item in manifest.latest_summary_files:
        lines.append(
            "- "
            f"{item.relative_path} | "
            f"benchmark={item.benchmark} | "
            f"quality_flags={item.quality_flags} | "
            f"metrics={item.key_metrics}"
        )

    lines.extend(["", "HTTP Checks:"])
    for check in manifest.http_checks:
        lines.append(
            "- "
            f"{check.name} | success={check.success} | "
            f"status={check.status_code} | url={check.url} | "
            f"values={check.key_values} | error={check.error}"
        )

    lines.extend(["", "Command Results:"])
    for result in manifest.command_results:
        lines.append(
            "- "
            f"{result.name} | passed={result.passed} | "
            f"returncode={result.returncode} | elapsed_ms={result.elapsed_ms}"
        )

    lines.extend(
        [
            "",
            "Git:",
            f"- branch: {manifest.git.branch}",
            f"- commit: {manifest.git.commit}",
            f"- clean_working_tree: {manifest.git.clean_working_tree}",
            f"- short_status: {manifest.git.short_status}",
            "",
            f"Manifest JSON: {manifest.output_manifest_json}",
            f"Manifest TXT: {manifest.output_manifest_txt}",
        ]
    )

    return "\n".join(lines) + "\n"


def _format_file_records(records: list[FileAuditRecord]) -> list[str]:
    return [
        f"- {item.relative_path} | exists={item.exists} | "
        f"size={item.size_bytes} | sha256={item.sha256}"
        for item in records
    ]


def _bool_dict(value: Any) -> dict[str, bool]:
    if not isinstance(value, dict):
        return {}

    return {
        str(key): bool(item)
        for key, item in value.items()
        if isinstance(item, bool)
    }


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None

    return str(value)


def _tail(value: str, *, max_chars: int = 4_000) -> str:
    if len(value) <= max_chars:
        return value

    return value[-max_chars:]


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            hasher.update(chunk)

    return hasher.hexdigest()


def _modified_utc(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()