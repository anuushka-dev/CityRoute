# benchmarks/phase_9_1/collect_phase91_evidence.py

from __future__ import annotations

import argparse
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

Mode = Literal["local", "docker"]


EXPECTED_SOURCE_FILES = [
    "app/services/dispatch_distance_service.py",
    "app/utils/dispatch_cache_key.py",
    "app/services/dispatch_service.py",
    "app/schemas/dispatch.py",
    "app/core/dispatch_cost_matrix.py",
]

EXPECTED_TEST_FILES = [
    "tests/test_dispatch_endpoint.py",
    "tests/test_dispatch_source_dijkstra.py",
    "tests/test_dispatch_cache_integration.py",
    "tests/test_phase91_integration_routes.py",
]

EXPECTED_BENCHMARK_FILES = [
    "benchmarks/phase_9_1/phase91_dispatch_source_dijkstra_probe.py",
    "benchmarks/phase_9_1/phase91_dispatch_cache_probe.py",
    "benchmarks/phase_9_1/collect_phase91_evidence.py",
    "benchmarks/phase_9_1/phase91_full_integration_probe.py",
]

EXPECTED_SUMMARY_PATTERNS = [
    "phase91_dispatch_source_dijkstra_summary_{mode}_*.json",
    "phase91_dispatch_cache_summary_{mode}_*.json",
    "phase91_full_integration_summary_{mode}_*.json",
]

CRITICAL_SUMMARY_FLAGS_BY_BENCHMARK = {
    "dispatch_source_dijkstra_probe": [
        "all_cases_successful",
        "all_source_dijkstra_used",
        "all_builder_called_once",
        "all_non_regression",
        "all_assignment_counts_valid",
        "all_capacity_counts_valid",
        "all_costs_non_negative",
        "cache_not_used_in_this_probe",
    ],
    "full_integration_probe": [
    "all_checks_successful",
    "root_ok",
    "health_ok",
    "openapi_required_paths_available",
    "graph_stats_shape_valid",
    "dispatch_haversine_ok",
    "dispatch_haversine_non_regression",
    "dispatch_source_dijkstra_status_expected",
    "source_dijkstra_api_blocked_acknowledged",
    ],
    "dispatch_cache_probe": [
        "all_cycles_successful",
        "cache_backend_used",
        "cache_hits_observed",
        "cache_hit_count_matches_second_requests",
        "all_first_requests_miss",
        "all_second_requests_hit",
        "all_cache_keys_stable",
        "all_response_costs_stable",
        "all_assignment_counts_stable",
        "all_builder_not_called_on_hit",
        "all_non_regression_stable",
    ],
}


@dataclass(frozen=True)
class FileEvidence:
    relative_path: str
    exists: bool
    size_bytes: int | None
    modified_utc: str | None


@dataclass(frozen=True)
class JsonEvidence:
    relative_path: str
    filename: str
    exists: bool
    size_bytes: int | None
    modified_utc: str | None
    json_valid: bool
    parse_error: str | None
    phase: str | None
    benchmark: str | None
    mode: str | None
    is_summary: bool
    quality_flags: dict[str, Any]
    key_metrics: dict[str, Any]


@dataclass(frozen=True)
class CommandEvidence:
    name: str
    command: list[str]
    returncode: int | None
    passed: bool
    elapsed_ms: float
    stdout_tail: str
    stderr_tail: str
    error: str | None


@dataclass(frozen=True)
class HttpEvidence:
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
    short_status: str
    clean_working_tree: bool


@dataclass(frozen=True)
class EvidenceManifest:
    phase: str
    collector: str
    mode: Mode
    base_url: str
    created_at_utc: str
    project_root: str
    output_manifest_json: str
    output_manifest_txt: str
    source_files: list[FileEvidence]
    test_files: list[FileEvidence]
    benchmark_files: list[FileEvidence]
    result_files: list[JsonEvidence]
    latest_summary_files: list[JsonEvidence]
    command_results: list[CommandEvidence]
    http_checks: list[HttpEvidence]
    git: GitEvidence
    quality_flags: dict[str, bool]
    evidence_note: str


def main() -> None:
    args = _parse_args()

    mode: Mode = args.mode
    base_url = args.base_url or _default_base_url(mode)

    output_dir = _resolve_output_dir(mode=mode, output_dir_arg=args.output_dir)
    created_at = datetime.now(UTC)
    timestamp = created_at.strftime("%Y%m%d_%H%M%S")

    output_manifest_json = output_dir / (
        f"phase91_evidence_manifest_{mode}_{timestamp}.json"
    )
    output_manifest_txt = output_dir / (
        f"phase91_evidence_manifest_{mode}_{timestamp}.txt"
    )

    source_files = [_file_evidence(path) for path in EXPECTED_SOURCE_FILES]
    test_files = [_file_evidence(path) for path in EXPECTED_TEST_FILES]
    benchmark_files = [_file_evidence(path) for path in EXPECTED_BENCHMARK_FILES]

    result_files = _collect_result_files(output_dir)
    latest_summary_files = _collect_latest_summary_files(
        output_dir=output_dir,
        mode=mode,
    )

    command_results: list[CommandEvidence] = []

    if args.run_pytest:
        command_results.append(_run_phase91_pytest())

    if args.run_ruff:
        command_results.append(_run_phase91_ruff())

    http_checks = [] if args.skip_http else _run_http_checks(base_url)
    git = _collect_git_evidence()

    quality_flags = _build_quality_flags(
        source_files=source_files,
        test_files=test_files,
        benchmark_files=benchmark_files,
        result_files=result_files,
        latest_summary_files=latest_summary_files,
        command_results=command_results,
        http_checks=http_checks,
        git=git,
        strict=args.strict,
        skip_http=args.skip_http,
    )

    manifest = EvidenceManifest(
        phase="tier3_phase9_1",
        collector="collect_phase91_evidence",
        mode=mode,
        base_url=base_url,
        created_at_utc=created_at.isoformat(),
        project_root=str(PROJECT_ROOT),
        output_manifest_json=_relative_path(output_manifest_json),
        output_manifest_txt=_relative_path(output_manifest_txt),
        source_files=source_files,
        test_files=test_files,
        benchmark_files=benchmark_files,
        result_files=result_files,
        latest_summary_files=latest_summary_files,
        command_results=command_results,
        http_checks=http_checks,
        git=git,
        quality_flags=quality_flags,
        evidence_note=(
            "Phase 9.1 evidence validates service-level source_dijkstra dispatch "
            "integration through an injected internal builder and service-level "
            "cache miss-hit behavior using an in-process fake backend. It does "
            "not claim live real-graph dispatch API wiring or real Redis hits "
            "unless separate probes are added later."
        ),
    )

    manifest_dict = asdict(manifest)

    _write_json(output_manifest_json, manifest_dict)
    _write_text_manifest(output_manifest_txt, manifest_dict)

    print(json.dumps(manifest_dict, indent=2))

    if args.strict and not all(quality_flags.values()):
        raise SystemExit(1)


def _build_quality_flags(
    *,
    source_files: list[FileEvidence],
    test_files: list[FileEvidence],
    benchmark_files: list[FileEvidence],
    result_files: list[JsonEvidence],
    latest_summary_files: list[JsonEvidence],
    command_results: list[CommandEvidence],
    http_checks: list[HttpEvidence],
    git: GitEvidence,
    strict: bool,
    skip_http: bool,
) -> dict[str, bool]:
    pytest_results = [
        result for result in command_results if result.name == "phase91_pytest"
    ]
    ruff_results = [
        result for result in command_results if result.name == "phase91_ruff"
    ]

    latest_summary_files_present = len(latest_summary_files) == len(
        EXPECTED_SUMMARY_PATTERNS
    )

    critical_summary_flags_true = _all_critical_summary_quality_flags_true(
        latest_summary_files
    )

    http_checks_passed = True if skip_http else all(
        check.success for check in http_checks
    )

    dispatch_endpoint_available = True if skip_http else _dispatch_endpoint_available(
        http_checks
    )

    health_ok = True if skip_http else _health_ok(http_checks)

    quality_flags = {
        "all_expected_source_files_exist": all(file.exists for file in source_files),
        "all_expected_test_files_exist": all(file.exists for file in test_files),
        "all_expected_benchmark_files_exist": all(
            file.exists for file in benchmark_files
        ),
        "result_json_files_present": len(result_files) > 0,
        "all_result_json_files_valid": bool(result_files)
        and all(file.json_valid for file in result_files),
        "latest_summary_files_present": latest_summary_files_present,
        "all_critical_summary_quality_flags_true": critical_summary_flags_true,
        "pytest_passed": bool(pytest_results)
        and all(result.passed for result in pytest_results),
        "ruff_passed": bool(ruff_results)
        and all(result.passed for result in ruff_results),
        "http_checks_passed": http_checks_passed,
        "dispatch_endpoint_available": dispatch_endpoint_available,
        "health_ok": health_ok,
        "git_commit_available": git.commit is not None,
    }

    if strict:
        quality_flags["git_working_tree_clean"] = git.clean_working_tree

    return quality_flags


def _all_critical_summary_quality_flags_true(
    latest_summary_files: list[JsonEvidence],
) -> bool:
    if len(latest_summary_files) != len(EXPECTED_SUMMARY_PATTERNS):
        return False

    for summary in latest_summary_files:
        if not summary.json_valid:
            return False

        if summary.benchmark not in CRITICAL_SUMMARY_FLAGS_BY_BENCHMARK:
            return False

        required_flags = CRITICAL_SUMMARY_FLAGS_BY_BENCHMARK[summary.benchmark]

        for flag_name in required_flags:
            if summary.quality_flags.get(flag_name) is not True:
                return False

    return True


def _dispatch_endpoint_available(http_checks: list[HttpEvidence]) -> bool:
    for check in http_checks:
        if check.name == "openapi":
            return bool(check.key_values.get("dispatch_compare_available"))

    return False


def _health_ok(http_checks: list[HttpEvidence]) -> bool:
    for check in http_checks:
        if check.name == "health":
            return (
                check.success
                and check.key_values.get("status") == "ok"
            )

    return False


def _collect_result_files(output_dir: Path) -> list[JsonEvidence]:
    result_files = []

    for path in sorted(output_dir.glob("*.json")):
        result_files.append(_json_evidence(path))

    return result_files


def _collect_latest_summary_files(
    *,
    output_dir: Path,
    mode: Mode,
) -> list[JsonEvidence]:
    latest_files: list[JsonEvidence] = []

    for pattern_template in EXPECTED_SUMMARY_PATTERNS:
        pattern = pattern_template.format(mode=mode)
        matching_files = sorted(
            output_dir.glob(pattern),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

        if matching_files:
            latest_files.append(_json_evidence(matching_files[0]))

    return latest_files


def _json_evidence(path: Path) -> JsonEvidence:
    exists = path.exists()
    stat = path.stat() if exists else None

    payload: dict[str, Any] | None = None
    parse_error = None
    json_valid = False

    if exists:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            json_valid = True
        except Exception as exc:
            parse_error = f"{type(exc).__name__}: {exc}"

    payload = payload or {}

    return JsonEvidence(
        relative_path=_relative_path(path),
        filename=path.name,
        exists=exists,
        size_bytes=stat.st_size if stat else None,
        modified_utc=_modified_utc(stat) if stat else None,
        json_valid=json_valid,
        parse_error=parse_error,
        phase=_safe_string(payload.get("phase")),
        benchmark=_safe_string(payload.get("benchmark")),
        mode=_safe_string(payload.get("mode")),
        is_summary=_is_summary_file(path),
        quality_flags=payload.get("quality_flags", {})
        if isinstance(payload.get("quality_flags", {}), dict)
        else {},
        key_metrics=_extract_key_metrics(payload),
    )


def _extract_key_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "case_count",
        "success_count",
        "failure_count",
        "success_rate_pct",
        "cycle_count",
        "successful_cycle_count",
        "failed_cycle_count",
        "request_count",
        "cache_used_count",
        "cache_hit_count",
        "cache_hit_rate_pct",
        "iterations_per_size",
        "cycles_per_size",
        "mode",
    ]

    return {key: payload[key] for key in keys if key in payload}


def _is_summary_file(path: Path) -> bool:
    return "summary" in path.name or "manifest" in path.name


def _file_evidence(relative_path: str) -> FileEvidence:
    path = PROJECT_ROOT / relative_path
    exists = path.exists()
    stat = path.stat() if exists else None

    return FileEvidence(
        relative_path=relative_path,
        exists=exists,
        size_bytes=stat.st_size if stat else None,
        modified_utc=_modified_utc(stat) if stat else None,
    )


def _run_phase91_pytest() -> CommandEvidence:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_dispatch_endpoint.py",
        "tests/test_dispatch_source_dijkstra.py",
        "tests/test_dispatch_cache_integration.py",
        "tests/test_phase91_integration_routes.py",
        "-v",
    ]

    return _run_command(
        name="phase91_pytest",
        command=command,
        timeout_seconds=240,
    )


def _run_phase91_ruff() -> CommandEvidence:
    command = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        *EXPECTED_SOURCE_FILES,
        *EXPECTED_TEST_FILES,
        *EXPECTED_BENCHMARK_FILES,
    ]

    return _run_command(
        name="phase91_ruff",
        command=command,
        timeout_seconds=120,
    )


def _run_command(
    *,
    name: str,
    command: list[str],
    timeout_seconds: int,
) -> CommandEvidence:
    start = perf_counter()

    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )

        elapsed_ms = _elapsed_ms(start)

        return CommandEvidence(
            name=name,
            command=command,
            returncode=completed.returncode,
            passed=completed.returncode == 0,
            elapsed_ms=elapsed_ms,
            stdout_tail=_tail(completed.stdout),
            stderr_tail=_tail(completed.stderr),
            error=None,
        )

    except Exception as exc:
        return CommandEvidence(
            name=name,
            command=command,
            returncode=None,
            passed=False,
            elapsed_ms=_elapsed_ms(start),
            stdout_tail="",
            stderr_tail="",
            error=f"{type(exc).__name__}: {exc}",
        )


def _run_http_checks(base_url: str) -> list[HttpEvidence]:
    return [
        _http_get(
            name="root",
            url=f"{base_url}/",
            extractor=_extract_root_key_values,
        ),
        _http_get(
            name="health",
            url=f"{base_url}/health",
            extractor=_extract_health_key_values,
        ),
        _http_get(
            name="openapi",
            url=f"{base_url}/openapi.json",
            extractor=_extract_openapi_key_values,
        ),
    ]


def _http_get(
    *,
    name: str,
    url: str,
    extractor,
) -> HttpEvidence:
    start = perf_counter()

    try:
        request = Request(url, method="GET")
        with urlopen(request, timeout=10) as response:
            status_code = response.status
            raw_body = response.read().decode("utf-8")

        payload = json.loads(raw_body)
        key_values = extractor(payload)

        return HttpEvidence(
            name=name,
            url=url,
            success=200 <= status_code < 300,
            status_code=status_code,
            elapsed_ms=_elapsed_ms(start),
            error=None,
            key_values=key_values,
        )

    except HTTPError as exc:
        return HttpEvidence(
            name=name,
            url=url,
            success=False,
            status_code=exc.code,
            elapsed_ms=_elapsed_ms(start),
            error=f"HTTPError: {exc}",
            key_values={},
        )

    except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return HttpEvidence(
            name=name,
            url=url,
            success=False,
            status_code=None,
            elapsed_ms=_elapsed_ms(start),
            error=f"{type(exc).__name__}: {exc}",
            key_values={},
        )


def _extract_root_key_values(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": payload.get("phase"),
        "dispatch_compare": payload.get("dispatch_compare"),
        "matrix": payload.get("matrix"),
        "vrp_advanced_compare": payload.get("vrp_advanced_compare"),
    }


def _extract_health_key_values(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": payload.get("status"),
        "graph_loaded": payload.get("graph_loaded"),
    }


def _extract_openapi_key_values(payload: dict[str, Any]) -> dict[str, Any]:
    paths = payload.get("paths", {})

    if not isinstance(paths, dict):
        paths = {}

    required_paths = {
        "/health",
        "/graph/stats",
        "/graph/validate",
        "/graph/snap",
        "/route",
        "/route/compare",
        "/matrix",
        "/vrp/greedy",
        "/vrp/compare",
        "/vrp/compare/advanced",
        "/dispatch/compare",
    }

    available_paths = set(paths)
    missing_paths = sorted(required_paths - available_paths)

    return {
        "dispatch_compare_available": "/dispatch/compare" in available_paths,
        "path_count": len(available_paths),
        "missing_required_paths": missing_paths,
        "all_required_paths_available": len(missing_paths) == 0,
    }


def _collect_git_evidence() -> GitEvidence:
    branch = _git_output(["branch", "--show-current"])
    commit = _git_output(["rev-parse", "--short", "HEAD"])
    short_status = _git_output(["status", "--short"]) or ""

    return GitEvidence(
        branch=branch,
        commit=commit,
        short_status=short_status,
        clean_working_tree=short_status.strip() == "",
    )


def _git_output(args: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception:
        return None

    if completed.returncode != 0:
        return None

    output = completed.stdout.strip()

    return output or None


def _resolve_output_dir(
    *,
    mode: Mode,
    output_dir_arg: str | None,
) -> Path:
    if output_dir_arg:
        output_dir = Path(output_dir_arg)
    else:
        output_dir = PROJECT_ROOT / "benchmarks" / "phase_9_1" / f"{mode}_results"

    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir

    output_dir.mkdir(parents=True, exist_ok=True)

    return output_dir


def _default_base_url(mode: Mode) -> str:
    if mode == "docker":
        return "http://127.0.0.1:8001"

    return "http://127.0.0.1:8000"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def _write_text_manifest(path: Path, manifest: dict[str, Any]) -> None:
    lines = [
        "CityRoute Phase 9.1 Evidence Manifest",
        "=" * 40,
        f"created_at_utc: {manifest['created_at_utc']}",
        f"mode: {manifest['mode']}",
        f"base_url: {manifest['base_url']}",
        "",
        "Quality flags:",
    ]

    for key, value in manifest["quality_flags"].items():
        lines.append(f"- {key}: {value}")

    lines.extend(
        [
            "",
            "Latest summary files:",
        ]
    )

    for summary in manifest["latest_summary_files"]:
        lines.append(
            f"- {summary['filename']} | benchmark={summary['benchmark']} | "
            f"valid={summary['json_valid']}"
        )

    lines.extend(
        [
            "",
            "Command results:",
        ]
    )

    for command_result in manifest["command_results"]:
        lines.append(
            f"- {command_result['name']}: passed={command_result['passed']} "
            f"returncode={command_result['returncode']}"
        )

    lines.extend(
        [
            "",
            "HTTP checks:",
        ]
    )

    for http_check in manifest["http_checks"]:
        lines.append(
            f"- {http_check['name']}: success={http_check['success']} "
            f"status={http_check['status_code']}"
        )

    lines.extend(
        [
            "",
            "Git:",
            f"- branch: {manifest['git']['branch']}",
            f"- commit: {manifest['git']['commit']}",
            f"- clean_working_tree: {manifest['git']['clean_working_tree']}",
            "",
            "Evidence note:",
            manifest["evidence_note"],
            "",
        ]
    )

    path.write_text("\n".join(lines), encoding="utf-8")


def _tail(value: str, limit: int = 4_000) -> str:
    if len(value) <= limit:
        return value

    return value[-limit:]


def _safe_string(value: Any) -> str | None:
    if value is None:
        return None

    return str(value)


def _modified_utc(stat_result: Any) -> str:
    return datetime.fromtimestamp(stat_result.st_mtime, UTC).isoformat()


def _relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _elapsed_ms(start_time: float) -> float:
    return round((perf_counter() - start_time) * 1000.0, 6)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect Phase 9.1 dispatch integration evidence."
    )

    parser.add_argument(
        "--mode",
        choices=["local", "docker"],
        default="local",
        help="Evidence mode label and default API base URL selector.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override API base URL.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional output directory.",
    )
    parser.add_argument(
        "--run-pytest",
        action="store_true",
        help="Run Phase 9.1 pytest evidence.",
    )
    parser.add_argument(
        "--run-ruff",
        action="store_true",
        help="Run Phase 9.1 Ruff evidence.",
    )
    parser.add_argument(
        "--skip-http",
        action="store_true",
        help="Skip live HTTP checks.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any quality flag is false.",
    )

    return parser.parse_args()


if __name__ == "__main__":
    main()