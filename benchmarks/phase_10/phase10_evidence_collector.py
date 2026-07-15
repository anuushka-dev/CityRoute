# benchmarks/phase_10/phase10_evidence_collector.py

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PHASE = "tier3_phase10"
BENCHMARK = "evidence_collector"

DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_DOCKER_BASE_URL = "http://127.0.0.1:8001"

PHASE_DIRECTORY = Path("benchmarks") / "phase_10"

EXPECTED_EVIDENCE: tuple[
    tuple[str, str, str],
    ...,
] = (
    (
        "road_dispatch",
        "phase10_road_dispatch_raw_",
        "phase10_road_dispatch_summary_",
    ),
    (
        "haversine_vs_road",
        "phase10_haversine_vs_road_raw_",
        "phase10_haversine_vs_road_summary_",
    ),
    (
        "dispatch_cache",
        "phase10_dispatch_cache_raw_",
        "phase10_dispatch_cache_summary_",
    ),
    (
        "unreachable_pair",
        "phase10_unreachable_pair_raw_",
        "phase10_unreachable_pair_summary_",
    ),
    (
        "correctness",
        "phase10_correctness_raw_",
        "phase10_correctness_summary_",
    ),
    (
        "load",
        "phase10_load_raw_",
        "phase10_load_summary_",
    ),
)


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    success: bool
    return_code: int | None
    stdout: str
    stderr: str
    elapsed_ms: float


@dataclass(frozen=True)
class EvidenceArtifact:
    evidence_name: str
    artifact_type: str
    path: Path
    size_bytes: int
    modified_at_utc: str
    sha256: str
    payload: dict[str, Any] | None
    parse_error: str | None


def utc_now_iso() -> str:
    return datetime.now(
        UTC
    ).isoformat()


def path_modified_at_utc(
    path: Path,
) -> str:
    timestamp = path.stat().st_mtime

    return datetime.fromtimestamp(
        timestamp,
        tz=UTC,
    ).isoformat()


def sha256_file(
    path: Path,
) -> str:
    digest = hashlib.sha256()

    with path.open(
        "rb"
    ) as file_handle:
        while True:
            chunk = file_handle.read(
                1024 * 1024
            )

            if not chunk:
                break

            digest.update(
                chunk
            )

    return digest.hexdigest()


def load_json_object(
    path: Path,
) -> tuple[
    dict[str, Any] | None,
    str | None,
]:
    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8-sig"
            )
        )

    except Exception as exc:
        return (
            None,
            (
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
        )

    if not isinstance(
        payload,
        dict,
    ):
        return (
            None,
            (
                "Top-level JSON value is not "
                "an object."
            ),
        )

    return (
        payload,
        None,
    )


def discover_latest_file(
    *,
    directory: Path,
    prefix: str,
) -> Path | None:
    candidates = [
        path
        for path in directory.glob(
            f"{prefix}*.json"
        )
        if path.is_file()
    ]

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda path: (
            path.stat().st_mtime_ns,
            path.name,
        ),
    )


def build_artifact(
    *,
    evidence_name: str,
    artifact_type: str,
    path: Path,
) -> EvidenceArtifact:
    payload, parse_error = (
        load_json_object(
            path
        )
    )

    return EvidenceArtifact(
        evidence_name=evidence_name,
        artifact_type=artifact_type,
        path=path,
        size_bytes=(
            path.stat().st_size
        ),
        modified_at_utc=(
            path_modified_at_utc(
                path
            )
        ),
        sha256=sha256_file(
            path
        ),
        payload=payload,
        parse_error=parse_error,
    )


def artifact_to_dict(
    artifact: EvidenceArtifact,
) -> dict[str, Any]:
    return {
        "evidence_name": (
            artifact.evidence_name
        ),
        "artifact_type": (
            artifact.artifact_type
        ),
        "path": str(
            artifact.path
        ),
        "size_bytes": (
            artifact.size_bytes
        ),
        "modified_at_utc": (
            artifact.modified_at_utc
        ),
        "sha256": (
            artifact.sha256
        ),
        "json_parse_success": (
            artifact.parse_error
            is None
        ),
        "parse_error": (
            artifact.parse_error
        ),
    }


def run_command(
    command: list[str],
    *,
    timeout_seconds: float = 30.0,
) -> CommandResult:
    started = time.perf_counter()

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout_seconds,
        )

        elapsed_ms = (
            (
                time.perf_counter()
                - started
            )
            * 1000.0
        )

        return CommandResult(
            command=command,
            success=(
                completed.returncode
                == 0
            ),
            return_code=(
                completed.returncode
            ),
            stdout=(
                completed.stdout.strip()
            ),
            stderr=(
                completed.stderr.strip()
            ),
            elapsed_ms=round(
                elapsed_ms,
                6,
            ),
        )

    except Exception as exc:
        elapsed_ms = (
            (
                time.perf_counter()
                - started
            )
            * 1000.0
        )

        return CommandResult(
            command=command,
            success=False,
            return_code=None,
            stdout="",
            stderr=(
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
            elapsed_ms=round(
                elapsed_ms,
                6,
            ),
        )


def command_result_to_dict(
    result: CommandResult,
) -> dict[str, Any]:
    return {
        "command": (
            result.command
        ),
        "success": (
            result.success
        ),
        "return_code": (
            result.return_code
        ),
        "stdout": (
            result.stdout
        ),
        "stderr": (
            result.stderr
        ),
        "elapsed_ms": (
            result.elapsed_ms
        ),
    }


def safe_http_get_json(
    url: str,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    started = time.perf_counter()

    request = Request(
        url,
        method="GET",
        headers={
            "Accept": (
                "application/json"
            ),
            "User-Agent": (
                "CityRoute-Phase10-"
                "EvidenceCollector"
            ),
        },
    )

    try:
        with urlopen(
            request,
            timeout=timeout_seconds,
        ) as response:
            raw_body = response.read()

            elapsed_ms = (
                (
                    time.perf_counter()
                    - started
                )
                * 1000.0
            )

            text = raw_body.decode(
                "utf-8",
                errors="replace",
            )

            try:
                payload: Any = (
                    json.loads(
                        text
                    )
                )

            except json.JSONDecodeError:
                payload = text

            return {
                "success": (
                    200
                    <= response.status
                    < 300
                ),
                "status_code": (
                    response.status
                ),
                "elapsed_ms": round(
                    elapsed_ms,
                    6,
                ),
                "payload": payload,
            }

    except HTTPError as exc:
        elapsed_ms = (
            (
                time.perf_counter()
                - started
            )
            * 1000.0
        )

        return {
            "success": False,
            "status_code": (
                exc.code
            ),
            "elapsed_ms": round(
                elapsed_ms,
                6,
            ),
            "error": (
                f"HTTPError: {exc}"
            ),
        }

    except (
        URLError,
        TimeoutError,
        OSError,
    ) as exc:
        elapsed_ms = (
            (
                time.perf_counter()
                - started
            )
            * 1000.0
        )

        return {
            "success": False,
            "status_code": 0,
            "elapsed_ms": round(
                elapsed_ms,
                6,
            ),
            "error": (
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
        }


def get_nested(
    payload: dict[str, Any],
    *keys: str,
) -> Any:
    current: Any = payload

    for key in keys:
        if not isinstance(
            current,
            dict,
        ):
            return None

        current = current.get(
            key
        )

    return current


def int_value(
    value: Any,
) -> int | None:
    if (
        isinstance(
            value,
            int,
        )
        and not isinstance(
            value,
            bool,
        )
    ):
        return value

    return None


def number_value(
    value: Any,
) -> float | None:
    if isinstance(
        value,
        bool,
    ):
        return None

    if isinstance(
        value,
        (
            int,
            float,
        ),
    ):
        return float(
            value
        )

    return None


def bool_value(
    value: Any,
) -> bool | None:
    if isinstance(
        value,
        bool,
    ):
        return value

    return None


def evaluate_road_dispatch(
    summary: dict[str, Any],
) -> dict[str, Any]:
    case_count = int_value(
        summary.get(
            "case_count"
        )
    )

    success_count = int_value(
        summary.get(
            "success_count"
        )
    )

    failure_count = int_value(
        summary.get(
            "failure_count"
        )
    )

    passed = (
        case_count is not None
        and success_count
        == case_count
        and failure_count
        == 0
    )

    return {
        "passed": passed,
        "case_count": case_count,
        "success_count": (
            success_count
        ),
        "failure_count": (
            failure_count
        ),
        "success_rate_pct": (
            summary.get(
                "success_rate_pct"
            )
        ),
        "acceptance": (
            "All measured road-dispatch "
            "requests must succeed."
        ),
    }


def evaluate_haversine_vs_road(
    summary: dict[str, Any],
) -> dict[str, Any]:
    case_count = int_value(
        summary.get(
            "case_count"
        )
    )

    success_count = int_value(
        summary.get(
            "success_count"
        )
    )

    failure_count = int_value(
        summary.get(
            "failure_count"
        )
    )

    passed = (
        case_count is not None
        and success_count
        == case_count
        and failure_count
        == 0
    )

    return {
        "passed": passed,
        "case_count": case_count,
        "success_count": (
            success_count
        ),
        "failure_count": (
            failure_count
        ),
        "success_rate_pct": (
            summary.get(
                "success_rate_pct"
            )
        ),
        "acceptance": (
            "All paired Haversine and "
            "road-network requests must succeed."
        ),
    }


def evaluate_dispatch_cache(
    summary: dict[str, Any],
) -> dict[str, Any]:
    cycle_count = int_value(
        summary.get(
            "cycle_count"
        )
    )

    success_count = int_value(
        summary.get(
            "success_count"
        )
    )

    failure_count = int_value(
        summary.get(
            "failure_count"
        )
    )

    all_cold_missed = bool_value(
        summary.get(
            "all_cold_requests_missed"
        )
    )

    all_warm_hit = bool_value(
        summary.get(
            "all_warm_requests_hit"
        )
    )

    all_identical = bool_value(
        summary.get(
            "all_warm_outputs_identical"
        )
    )

    passed = (
        cycle_count is not None
        and success_count
        == cycle_count
        and failure_count
        == 0
        and all_cold_missed
        is True
        and all_warm_hit
        is True
        and all_identical
        is True
    )

    return {
        "passed": passed,
        "cycle_count": cycle_count,
        "success_count": (
            success_count
        ),
        "failure_count": (
            failure_count
        ),
        "cold_miss_count": (
            summary.get(
                "cold_miss_count"
            )
        ),
        "expected_cold_miss_count": (
            summary.get(
                "expected_cold_miss_count"
            )
        ),
        "warm_hit_count": (
            summary.get(
                "warm_hit_count"
            )
        ),
        "expected_warm_hit_count": (
            summary.get(
                "expected_warm_hit_count"
            )
        ),
        "all_cold_requests_missed": (
            all_cold_missed
        ),
        "all_warm_requests_hit": (
            all_warm_hit
        ),
        "all_warm_outputs_identical": (
            all_identical
        ),
        "acceptance": (
            "Every measured cold request must "
            "miss, every warm request must hit, "
            "and cached outputs must be identical."
        ),
    }


def evaluate_unreachable_pair(
    summary: dict[str, Any],
) -> dict[str, Any]:
    verified_pair = bool_value(
        summary.get(
            "verified_pair_found"
        )
    )

    case_count = int_value(
        summary.get(
            "case_count"
        )
    )

    success_count = int_value(
        summary.get(
            "success_count"
        )
    )

    failure_count = int_value(
        summary.get(
            "failure_count"
        )
    )

    greedy_safe = bool_value(
        summary.get(
            "all_greedy_forbidden_pairs_rejected"
        )
    )

    hungarian_safe = bool_value(
        summary.get(
            "all_hungarian_forbidden_pairs_rejected"
        )
    )

    directionality_passed = (
        bool_value(
            summary.get(
                "all_directionality_checks_passed"
            )
        )
    )

    passed = (
        verified_pair
        is True
        and case_count
        is not None
        and success_count
        == case_count
        and failure_count
        == 0
        and greedy_safe
        is True
        and hungarian_safe
        is True
        and directionality_passed
        is True
    )

    return {
        "passed": passed,
        "verified_pair_found": (
            verified_pair
        ),
        "case_count": case_count,
        "success_count": (
            success_count
        ),
        "failure_count": (
            failure_count
        ),
        "all_greedy_forbidden_pairs_rejected": (
            greedy_safe
        ),
        "all_hungarian_forbidden_pairs_rejected": (
            hungarian_safe
        ),
        "all_directionality_checks_passed": (
            directionality_passed
        ),
        "verified_pair": (
            summary.get(
                "verified_pair"
            )
        ),
        "acceptance": (
            "A real directed unreachable pair "
            "must be found and rejected by both "
            "assignment algorithms while the "
            "reachable control succeeds."
        ),
    }


def evaluate_correctness(
    summary: dict[str, Any],
) -> dict[str, Any]:
    graph_consistent = bool_value(
        summary.get(
            "graph_consistency_passed"
        )
    )

    scenario_count = int_value(
        summary.get(
            "scenario_count"
        )
    )

    scenario_success_count = (
        int_value(
            summary.get(
                "scenario_success_count"
            )
        )
    )

    cell_case_count = int_value(
        summary.get(
            "cell_case_count"
        )
    )

    cell_success_count = int_value(
        summary.get(
            "cell_success_count"
        )
    )

    cell_mismatch_count = int_value(
        summary.get(
            "cell_mismatch_count"
        )
    )

    all_cells_matched = bool_value(
        summary.get(
            "all_road_cost_cells_matched_oracle"
        )
    )

    all_optimal = bool_value(
        summary.get(
            "all_hungarian_results_matched_bruteforce_optimum"
        )
    )

    all_non_regression = bool_value(
        summary.get(
            "all_hungarian_non_regression_checks_passed"
        )
    )

    passed = (
        graph_consistent
        is True
        and scenario_count
        is not None
        and scenario_success_count
        == scenario_count
        and cell_case_count
        is not None
        and cell_success_count
        == cell_case_count
        and cell_mismatch_count
        == 0
        and all_cells_matched
        is True
        and all_optimal
        is True
        and all_non_regression
        is True
    )

    return {
        "passed": passed,
        "graph_consistency_passed": (
            graph_consistent
        ),
        "scenario_count": (
            scenario_count
        ),
        "scenario_success_count": (
            scenario_success_count
        ),
        "cell_case_count": (
            cell_case_count
        ),
        "cell_success_count": (
            cell_success_count
        ),
        "cell_mismatch_count": (
            cell_mismatch_count
        ),
        "max_abs_road_cost_error_m": (
            summary.get(
                "max_abs_road_cost_error_m"
            )
        ),
        "all_road_cost_cells_matched_oracle": (
            all_cells_matched
        ),
        "all_hungarian_results_matched_bruteforce_optimum": (
            all_optimal
        ),
        "all_hungarian_non_regression_checks_passed": (
            all_non_regression
        ),
        "absolute_optimality_gap_m": (
            summary.get(
                "absolute_optimality_gap_m"
            )
        ),
        "acceptance": (
            "All independent road-cost cells must "
            "match the NetworkX oracle and every "
            "tested Hungarian result must match "
            "the brute-force optimum."
        ),
    }


def evaluate_load(
    summary: dict[str, Any],
) -> dict[str, Any]:
    total_request_count = int_value(
        summary.get(
            "total_request_count"
        )
    )

    success_count = int_value(
        summary.get(
            "success_count"
        )
    )

    failure_count = int_value(
        summary.get(
            "failure_count"
        )
    )

    all_requests_successful = bool_value(
        summary.get(
            "all_requests_successful"
        )
    )

    all_non_regression = bool_value(
        summary.get(
            "all_hungarian_non_regression_checks_passed"
        )
    )

    passed = (
        total_request_count
        is not None
        and success_count
        == total_request_count
        and failure_count
        == 0
        and all_requests_successful
        is True
        and all_non_regression
        is True
    )

    return {
        "passed": passed,
        "total_request_count": (
            total_request_count
        ),
        "success_count": (
            success_count
        ),
        "failure_count": (
            failure_count
        ),
        "success_rate_pct": (
            summary.get(
                "success_rate_pct"
            )
        ),
        "all_requests_successful": (
            all_requests_successful
        ),
        "all_hungarian_non_regression_checks_passed": (
            all_non_regression
        ),
        "size_summaries": (
            summary.get(
                "size_summaries"
            )
        ),
        "acceptance": (
            "All concurrent load requests must "
            "complete successfully and preserve "
            "Hungarian non-regression. Throughput "
            "scaling is reported separately and "
            "is not hidden by the pass/fail gate."
        ),
    }


def evaluate_summary(
    *,
    evidence_name: str,
    summary: dict[str, Any],
) -> dict[str, Any]:
    phase = summary.get(
        "phase"
    )

    benchmark = summary.get(
        "benchmark"
    )

    metadata_errors: list[
        str
    ] = []

    if phase != PHASE:
        metadata_errors.append(
            
                "Unexpected phase: "
                f"{phase!r}"
            
        )

    if not isinstance(
        benchmark,
        str,
    ):
        metadata_errors.append(
            "Benchmark field is missing."
        )

    evaluators = {
        "road_dispatch": (
            evaluate_road_dispatch
        ),
        "haversine_vs_road": (
            evaluate_haversine_vs_road
        ),
        "dispatch_cache": (
            evaluate_dispatch_cache
        ),
        "unreachable_pair": (
            evaluate_unreachable_pair
        ),
        "correctness": (
            evaluate_correctness
        ),
        "load": (
            evaluate_load
        ),
    }

    evaluator = evaluators.get(
        evidence_name
    )

    if evaluator is None:
        return {
            "passed": False,
            "metadata_errors": [
                (
                    "No evaluator is registered "
                    f"for {evidence_name!r}."
                )
            ],
        }

    result = evaluator(
        summary
    )

    result[
        "metadata_errors"
    ] = metadata_errors

    result[
        "passed"
    ] = (
        result.get(
            "passed"
        )
        is True
        and not metadata_errors
    )

    return result


def recursively_count_key_value(
    value: Any,
    *,
    key_name: str,
    expected_value: Any,
) -> int:
    count = 0

    if isinstance(
        value,
        dict,
    ):
        for key, child in (
            value.items()
        ):
            if (
                key == key_name
                and child
                == expected_value
            ):
                count += 1

            count += (
                recursively_count_key_value(
                    child,
                    key_name=key_name,
                    expected_value=(
                        expected_value
                    ),
                )
            )

    elif isinstance(
        value,
        list,
    ):
        for child in value:
            count += (
                recursively_count_key_value(
                    child,
                    key_name=key_name,
                    expected_value=(
                        expected_value
                    ),
                )
            )

    return count


def collect_telemetry_advisories(
    artifacts: list[
        EvidenceArtifact
    ],
) -> dict[str, Any]:
    api_elapsed_null_count = 0
    matrix_build_null_count = 0
    nested_cache_status_null_count = 0

    for artifact in artifacts:
        if artifact.payload is None:
            continue

        api_elapsed_null_count += (
            recursively_count_key_value(
                artifact.payload,
                key_name=(
                    "api_elapsed_ms"
                ),
                expected_value=None,
            )
        )

        matrix_build_null_count += (
            recursively_count_key_value(
                artifact.payload,
                key_name=(
                    "matrix_build_time_ms"
                ),
                expected_value=None,
            )
        )

        nested_cache_status_null_count += (
            recursively_count_key_value(
                artifact.payload,
                key_name=(
                    "cache_status"
                ),
                expected_value=None,
            )
        )

    advisories: list[
        str
    ] = []

    if (
        api_elapsed_null_count
        > 0
    ):
        advisories.append(
            
                "api_elapsed_ms contains null values "
                "in collected evidence."
            
        )

    if (
        matrix_build_null_count
        > 0
    ):
        advisories.append(
            
                "matrix_build_time_ms contains null "
                "values in collected evidence."
            
        )

    if (
        nested_cache_status_null_count
        > 0
    ):
        advisories.append(
            
                "Some cache_status fields are null "
                "in collected evidence."
            
        )

    return {
        "api_elapsed_ms_null_occurrences": (
            api_elapsed_null_count
        ),
        "matrix_build_time_ms_null_occurrences": (
            matrix_build_null_count
        ),
        "cache_status_null_occurrences": (
            nested_cache_status_null_count
        ),
        "advisories": advisories,
    }


def collect_git_context() -> dict[str, Any]:
    commands = {
        "commit": [
            "git",
            "rev-parse",
            "HEAD",
        ],
        "short_commit": [
            "git",
            "rev-parse",
            "--short",
            "HEAD",
        ],
        "branch": [
            "git",
            "branch",
            "--show-current",
        ],
        "status": [
            "git",
            "status",
            "--short",
        ],
        "latest_log": [
            "git",
            "log",
            "-1",
            "--oneline",
            "--decorate",
        ],
    }

    results = {
        name: run_command(
            command
        )
        for name, command
        in commands.items()
    }

    return {
        "available": (
            results[
                "commit"
            ].success
        ),
        "commit": (
            results[
                "commit"
            ].stdout
            or None
        ),
        "short_commit": (
            results[
                "short_commit"
            ].stdout
            or None
        ),
        "branch": (
            results[
                "branch"
            ].stdout
            or None
        ),
        "working_tree_clean": (
            results[
                "status"
            ].success
            and not results[
                "status"
            ].stdout
        ),
        "status_short": (
            results[
                "status"
            ].stdout
        ),
        "latest_log": (
            results[
                "latest_log"
            ].stdout
            or None
        ),
        "commands": {
            name: (
                command_result_to_dict(
                    result
                )
            )
            for name, result
            in results.items()
        },
    }


def collect_docker_context() -> dict[str, Any]:
    result = run_command(
        [
            "docker",
            "ps",
            "--format",
            (
                "{{.Names}}|"
                "{{.Image}}|"
                "{{.Status}}|"
                "{{.Ports}}"
            ),
        ],
        timeout_seconds=20.0,
    )

    containers: list[
        dict[str, str]
    ] = []

    if result.success:
        for line in (
            result.stdout.splitlines()
        ):
            parts = line.split(
                "|",
                maxsplit=3,
            )

            if len(parts) != 4:
                continue

            containers.append(
                {
                    "name": (
                        parts[0]
                    ),
                    "image": (
                        parts[1]
                    ),
                    "status": (
                        parts[2]
                    ),
                    "ports": (
                        parts[3]
                    ),
                }
            )

    return {
        "available": (
            result.success
        ),
        "containers": (
            containers
        ),
        "command": (
            command_result_to_dict(
                result
            )
        ),
    }


def collect_environment() -> dict[str, Any]:
    return {
        "python_version": (
            sys.version
        ),
        "python_executable": (
            sys.executable
        ),
        "platform": (
            platform.platform()
        ),
        "system": (
            platform.system()
        ),
        "release": (
            platform.release()
        ),
        "machine": (
            platform.machine()
        ),
        "processor": (
            platform.processor()
        ),
        "working_directory": (
            str(
                Path.cwd()
            )
        ),
        "pid": (
            os.getpid()
        ),
    }


def collect_source_snapshot() -> list[
    dict[str, Any]
]:
    source_paths = (
        Path(
            "app/core/"
            "dispatch_road_cost_matrix.py"
        ),
        Path(
            "app/services/"
            "dispatch_road_matrix_service.py"
        ),
        Path(
            "app/services/"
            "dispatch_service.py"
        ),
        Path(
            "app/core/"
            "dispatch_cost_matrix.py"
        ),
        Path(
            "app/core/"
            "multi_target_dijkstra.py"
        ),
        Path(
            "app/core/"
            "graph_adjacency.py"
        ),
        Path(
            "app/core/"
            "hungarian.py"
        ),
        Path(
            "app/core/"
            "greedy_dispatch.py"
        ),
        Path(
            "app/utils/"
            "matrix_cache_key.py"
        ),
        Path(
            "app/utils/"
            "snap_index.py"
        ),
        Path(
            "app/infrastructure/"
            "redis_cache.py"
        ),
        Path(
            "app/schemas/"
            "dispatch.py"
        ),
        Path(
            "app/api/"
            "dispatch.py"
        ),
        Path(
            "app/main.py"
        ),
    )

    records: list[
        dict[str, Any]
    ] = []

    for path in source_paths:
        if not path.exists():
            records.append(
                {
                    "path": str(
                        path
                    ),
                    "exists": False,
                }
            )

            continue

        records.append(
            {
                "path": str(
                    path
                ),
                "exists": True,
                "size_bytes": (
                    path.stat().st_size
                ),
                "modified_at_utc": (
                    path_modified_at_utc(
                        path
                    )
                ),
                "sha256": (
                    sha256_file(
                        path
                    )
                ),
            }
        )

    return records


def build_plain_text_report(
    manifest: dict[str, Any],
) -> str:
    lines: list[str] = []

    separator = (
        "="
        * 88
    )

    lines.append(
        separator
    )

    lines.append(
        
            "CityRoute Tier 3 Phase 10 "
            "Evidence Manifest"
        
    )

    lines.append(
        separator
    )

    lines.append(
        
            "Generated UTC: "
            f"{manifest['created_at_utc']}"
        
    )

    lines.append(
        
            "Mode: "
            f"{manifest['configuration']['mode']}"
        
    )

    lines.append(
        
            "Base URL: "
            f"{manifest['configuration']['base_url']}"
        
    )

    lines.append(
        ""
    )

    lines.append(
        "FINAL ACCEPTANCE"
    )

    lines.append(
        "-"
        * 88
    )

    final_acceptance = manifest[
        "final_acceptance"
    ]

    lines.append(
        
            "Overall status: "
            f"{final_acceptance['status']}"
        
    )

    lines.append(
        
            "Passed evidence groups: "
            f"{final_acceptance['passed_group_count']}/"
            f"{final_acceptance['expected_group_count']}"
        
    )

    lines.append(
        
            "Missing evidence groups: "
            f"{final_acceptance['missing_group_count']}"
        
    )

    lines.append(
        
            "Failed evidence groups: "
            f"{final_acceptance['failed_group_count']}"
        
    )

    lines.append(
        ""
    )

    lines.append(
        "EVIDENCE GROUPS"
    )

    lines.append(
        "-"
        * 88
    )

    for group in manifest[
        "evidence_groups"
    ]:
        evaluation = group.get(
            "evaluation"
        )

        passed = (
            isinstance(
                evaluation,
                dict,
            )
            and evaluation.get(
                "passed"
            )
            is True
        )

        status = (
            "PASS"
            if passed
            else (
                "MISSING"
                if group.get(
                    "missing"
                )
                else "FAIL"
            )
        )

        lines.append(
            
                f"{group['evidence_name']}: "
                f"{status}"
            
        )

        summary_path = group.get(
            "summary_path"
        )

        raw_path = group.get(
            "raw_path"
        )

        if summary_path:
            lines.append(
                
                    "  summary: "
                    f"{summary_path}"
                
            )

        if raw_path:
            lines.append(
                
                    "  raw: "
                    f"{raw_path}"
                
            )

        if isinstance(
            evaluation,
            dict,
        ):
            for key, value in (
                evaluation.items()
            ):
                if key in {
                    "passed",
                    "acceptance",
                    "size_summaries",
                    "metadata_errors",
                    "verified_pair",
                    "absolute_optimality_gap_m",
                }:
                    continue

                lines.append(
                    
                        f"  {key}: "
                        f"{value}"
                    
                )

            metadata_errors = (
                evaluation.get(
                    "metadata_errors"
                )
            )

            if metadata_errors:
                lines.append(
                    
                        "  metadata_errors: "
                        f"{metadata_errors}"
                    
                )

        lines.append(
            ""
        )

    lines.append(
        "RUNTIME PREFLIGHT"
    )

    lines.append(
        "-"
        * 88
    )

    runtime = manifest[
        "runtime_preflight"
    ]

    lines.append(
        
            "Health success: "
            f"{runtime['health'].get('success')}"
        
    )

    lines.append(
        
            "Root success: "
            f"{runtime['root'].get('success')}"
        
    )

    lines.append(
        
            "Graph stats success: "
            f"{runtime['graph_stats'].get('success')}"
        
    )

    lines.append(
        ""
    )

    lines.append(
        "GIT"
    )

    lines.append(
        "-"
        * 88
    )

    git_context = manifest[
        "git"
    ]

    lines.append(
        
            "Commit: "
            f"{git_context.get('commit')}"
        
    )

    lines.append(
        
            "Branch: "
            f"{git_context.get('branch')}"
        
    )

    lines.append(
        
            "Working tree clean: "
            f"{git_context.get('working_tree_clean')}"
        
    )

    lines.append(
        ""
    )

    lines.append(
        "TELEMETRY ADVISORIES"
    )

    lines.append(
        "-"
        * 88
    )

    telemetry = manifest[
        "telemetry_advisories"
    ]

    lines.append(
        
            "api_elapsed_ms null occurrences: "
            f"{telemetry['api_elapsed_ms_null_occurrences']}"
        
    )

    lines.append(
        
            "matrix_build_time_ms null occurrences: "
            f"{telemetry['matrix_build_time_ms_null_occurrences']}"
        
    )

    lines.append(
        
            "cache_status null occurrences: "
            f"{telemetry['cache_status_null_occurrences']}"
        
    )

    for advisory in telemetry[
        "advisories"
    ]:
        lines.append(
            
                "  - "
                f"{advisory}"
            
        )

    lines.append(
        ""
    )

    lines.append(
        "ARTIFACT HASHES"
    )

    lines.append(
        "-"
        * 88
    )

    for artifact in manifest[
        "artifacts"
    ]:
        lines.append(
            
                f"{artifact['sha256']}  "
                f"{artifact['path']}"
            
        )

    lines.append(
        ""
    )

    lines.append(
        separator
    )

    return "\n".join(
        lines
    ) + "\n"


def save_json(
    *,
    path: Path,
    payload: Any,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def save_text(
    *,
    path: Path,
    content: str,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        content,
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Collect, validate, hash, and summarize "
            "CityRoute Tier 3 Phase 10 evidence."
        )
    )

    parser.add_argument(
        "--mode",
        choices=(
            "local",
            "docker",
        ),
        default="docker",
    )

    parser.add_argument(
        "--base-url",
        default=None,
    )

    parser.add_argument(
        "--results-dir",
        type=Path,
        default=None,
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
    )

    parser.add_argument(
        "--http-timeout-seconds",
        type=float,
        default=20.0,
    )

    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Exit non-zero when any required "
            "evidence group is missing or fails."
        ),
    )

    args = parser.parse_args()

    if (
        args.http_timeout_seconds
        <= 0.0
    ):
        parser.error(
            "--http-timeout-seconds must be > 0"
        )

    base_url = (
        args.base_url
        or (
            DEFAULT_DOCKER_BASE_URL
            if args.mode
            == "docker"
            else DEFAULT_LOCAL_BASE_URL
        )
    ).rstrip("/")

    results_directory = (
        args.results_dir
        or (
            PHASE_DIRECTORY
            / f"{args.mode}_results"
        )
    )

    output_directory = (
        args.output_dir
        or results_directory
    )

    timestamp = datetime.now(
        UTC
    ).strftime(
        "%Y%m%d_%H%M%S"
    )

    json_output_path = (
        output_directory
        / (
            "phase10_evidence_manifest_"
            f"{args.mode}_"
            f"{timestamp}.json"
        )
    )

    text_output_path = (
        output_directory
        / (
            "phase10_evidence_manifest_"
            f"{args.mode}_"
            f"{timestamp}.txt"
        )
    )

    print(
        "="
        * 88
    )

    print(
        
            "CityRoute Tier 3 Phase 10 "
            "Evidence Collector"
        
    )

    print(
        "="
        * 88
    )

    print(
        f"mode={args.mode}"
    )

    print(
        f"base_url={base_url}"
    )

    print(
        
            "results_directory="
            f"{results_directory}"
        
    )

    print(
        
            "output_directory="
            f"{output_directory}"
        
    )

    print(
        "="
        * 88
    )

    if not results_directory.exists():
        print(
            
                "ERROR: results directory "
                "does not exist: "
                f"{results_directory}"
            
        )

        return 1

    artifacts: list[
        EvidenceArtifact
    ] = []

    evidence_groups: list[
        dict[str, Any]
    ] = []

    for (
        evidence_name,
        raw_prefix,
        summary_prefix,
    ) in EXPECTED_EVIDENCE:
        raw_path = (
            discover_latest_file(
                directory=(
                    results_directory
                ),
                prefix=raw_prefix,
            )
        )

        summary_path = (
            discover_latest_file(
                directory=(
                    results_directory
                ),
                prefix=(
                    summary_prefix
                ),
            )
        )

        group_record: dict[
            str,
            Any,
        ] = {
            "evidence_name": (
                evidence_name
            ),
            "missing": False,
            "raw_path": (
                str(
                    raw_path
                )
                if raw_path
                is not None
                else None
            ),
            "summary_path": (
                str(
                    summary_path
                )
                if summary_path
                is not None
                else None
            ),
            "evaluation": None,
        }

        if (
            raw_path is None
            or summary_path is None
        ):
            group_record[
                "missing"
            ] = True

        if raw_path is not None:
            raw_artifact = (
                build_artifact(
                    evidence_name=(
                        evidence_name
                    ),
                    artifact_type="raw",
                    path=raw_path,
                )
            )

            artifacts.append(
                raw_artifact
            )

        if summary_path is not None:
            summary_artifact = (
                build_artifact(
                    evidence_name=(
                        evidence_name
                    ),
                    artifact_type=(
                        "summary"
                    ),
                    path=(
                        summary_path
                    ),
                )
            )

            artifacts.append(
                summary_artifact
            )

            if (
                summary_artifact.payload
                is not None
            ):
                group_record[
                    "evaluation"
                ] = (
                    evaluate_summary(
                        evidence_name=(
                            evidence_name
                        ),
                        summary=(
                            summary_artifact.payload
                        ),
                    )
                )

            else:
                group_record[
                    "evaluation"
                ] = {
                    "passed": False,
                    "metadata_errors": [
                        (
                            "Summary JSON could "
                            "not be parsed."
                        )
                    ],
                }

        evidence_groups.append(
            group_record
        )

    passed_group_count = sum(
        1
        for group in evidence_groups
        if (
            isinstance(
                group.get(
                    "evaluation"
                ),
                dict,
            )
            and group[
                "evaluation"
            ].get(
                "passed"
            )
            is True
        )
    )

    missing_group_count = sum(
        1
        for group in evidence_groups
        if group[
            "missing"
        ]
    )

    failed_group_count = sum(
        1
        for group in evidence_groups
        if (
            not group[
                "missing"
            ]
            and (
                not isinstance(
                    group.get(
                        "evaluation"
                    ),
                    dict,
                )
                or group[
                    "evaluation"
                ].get(
                    "passed"
                )
                is not True
            )
        )
    )

    expected_group_count = len(
        EXPECTED_EVIDENCE
    )

    all_required_passed = (
        passed_group_count
        == expected_group_count
        and missing_group_count
        == 0
        and failed_group_count
        == 0
    )

    runtime_preflight = {
        "health": (
            safe_http_get_json(
                f"{base_url}/health",
                timeout_seconds=(
                    args.http_timeout_seconds
                ),
            )
        ),
        "root": (
            safe_http_get_json(
                f"{base_url}/",
                timeout_seconds=(
                    args.http_timeout_seconds
                ),
            )
        ),
        "graph_stats": (
            safe_http_get_json(
                (
                    f"{base_url}"
                    "/graph/stats"
                ),
                timeout_seconds=(
                    args.http_timeout_seconds
                ),
            )
        ),
    }

    runtime_healthy = all(
        result.get(
            "success"
        )
        is True
        for result in (
            runtime_preflight.values()
        )
    )

    manifest = {
        "phase": PHASE,
        "benchmark": BENCHMARK,
        "created_at_utc": (
            utc_now_iso()
        ),
        "configuration": {
            "mode": (
                args.mode
            ),
            "base_url": (
                base_url
            ),
            "results_directory": (
                str(
                    results_directory
                )
            ),
            "output_directory": (
                str(
                    output_directory
                )
            ),
            "strict": (
                args.strict
            ),
        },
        "final_acceptance": {
            "status": (
                "PASS"
                if all_required_passed
                else "FAIL"
            ),
            "all_required_evidence_passed": (
                all_required_passed
            ),
            "expected_group_count": (
                expected_group_count
            ),
            "passed_group_count": (
                passed_group_count
            ),
            "missing_group_count": (
                missing_group_count
            ),
            "failed_group_count": (
                failed_group_count
            ),
            "runtime_preflight_healthy": (
                runtime_healthy
            ),
            "note": (
                "Runtime preflight is recorded "
                "separately from historical benchmark "
                "acceptance so a later stopped container "
                "does not rewrite already-generated "
                "benchmark evidence."
            ),
        },
        "evidence_groups": (
            evidence_groups
        ),
        "runtime_preflight": (
            runtime_preflight
        ),
        "telemetry_advisories": (
            collect_telemetry_advisories(
                artifacts
            )
        ),
        "artifacts": [
            artifact_to_dict(
                artifact
            )
            for artifact
            in artifacts
        ],
        "source_snapshot": (
            collect_source_snapshot()
        ),
        "git": (
            collect_git_context()
        ),
        "docker": (
            collect_docker_context()
        ),
        "environment": (
            collect_environment()
        ),
    }

    save_json(
        path=json_output_path,
        payload=manifest,
    )

    text_report = (
        build_plain_text_report(
            manifest
        )
    )

    save_text(
        path=text_output_path,
        content=text_report,
    )

    print()
    print(
        "="
        * 88
    )

    print(
        "FINAL ACCEPTANCE"
    )

    print(
        "="
        * 88
    )

    print(
        
            "status="
            f"{manifest['final_acceptance']['status']}"
        
    )

    print(
        
            "passed_groups="
            f"{passed_group_count}/"
            f"{expected_group_count}"
        
    )

    print(
        
            "missing_groups="
            f"{missing_group_count}"
        
    )

    print(
        
            "failed_groups="
            f"{failed_group_count}"
        
    )

    print(
        
            "runtime_preflight_healthy="
            f"{runtime_healthy}"
        
    )

    print()

    for group in evidence_groups:
        evaluation = group.get(
            "evaluation"
        )

        if group[
            "missing"
        ]:
            status = "MISSING"

        elif (
            isinstance(
                evaluation,
                dict,
            )
            and evaluation.get(
                "passed"
            )
            is True
        ):
            status = "PASS"

        else:
            status = "FAIL"

        print(
            
                f"{group['evidence_name']}: "
                f"{status}"
            
        )

    print()
    print(
        
            "json_output="
            f"{json_output_path}"
        
    )

    print(
        
            "text_output="
            f"{text_output_path}"
        
    )

    if (
        args.strict
        and not all_required_passed
    ):
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )