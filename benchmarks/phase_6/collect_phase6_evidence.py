# benchmarks/phase_6/collect_phase6_evidence.py

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PHASE6_ROOT = Path("benchmarks") / "phase_6"

RESULT_DIRS = [
    PHASE6_ROOT / "docker_results",
    PHASE6_ROOT / "local_results",
]

INDEX_JSON_PATH = PHASE6_ROOT / "phase6_all_results_index.json"
INDEX_CSV_PATH = PHASE6_ROOT / "phase6_all_results_index.csv"
INDEX_MD_PATH = PHASE6_ROOT / "phase6_all_results_index.md"
RAW_DUMP_PATH = PHASE6_ROOT / "phase6_all_raw_dump.json"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def nested_get(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = data

    for key in keys:
        if not isinstance(current, dict):
            return default

        if key not in current:
            return default

        current = current[key]

    return current


def metric(data: dict[str, Any], metric_name: str, stat_name: str) -> Any:
    return nested_get(data, metric_name, stat_name)


def detect_result_group(path: Path) -> str:
    parts = {part.lower() for part in path.parts}

    if "docker_results" in parts:
        return "docker"

    if "local_results" in parts:
        return "local"

    return "unknown"


def detect_route_mode(data: dict[str, Any]) -> str:
    if data.get("route_mode"):
        return str(data["route_mode"])

    if data.get("return_to_start") is True:
        return "return_to_start"

    if data.get("return_to_start") is False:
        return "open"

    return "unknown"


def build_summary_row(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    invalid_limit_probe = data.get("invalid_limit_probe") or {}

    return {
        "file": str(path),
        "result_group": detect_result_group(path),
        "benchmark": data.get("benchmark"),
        "phase": data.get("phase"),
        "mode": data.get("mode"),
        "route_mode": detect_route_mode(data),
        "endpoint": data.get("endpoint"),
        "stop_count": data.get("stop_count"),
        "case_count": data.get("case_count"),
        "iterations": data.get("iterations") or data.get("iterations_per_case"),
        "total_requests": data.get("total_requests"),
        "workers": data.get("workers"),
        "matrix_algorithm": data.get("matrix_algorithm"),
        "use_cache": data.get("use_cache"),
        "return_to_start": data.get("return_to_start"),
        "success_count": data.get("success_count"),
        "failure_count": data.get("failure_count"),
        "success_rate_pct": data.get("success_rate_pct"),
        "all_cases_passed": data.get("all_cases_passed"),
        "load_probe_passed": data.get("load_probe_passed"),
        "all_orders_valid": data.get("all_orders_valid"),
        "all_leg_counts_valid": data.get("all_leg_counts_valid"),
        "invalid_25_passed": invalid_limit_probe.get("passed"),
        "invalid_25_status": invalid_limit_probe.get("actual_status_code"),
        "cache_hit_count": data.get("cache_hit_count"),
        "cache_miss_count": data.get("cache_miss_count"),
        "api_median_ms": metric(data, "api_elapsed_ms", "median"),
        "api_p95_ms": metric(data, "api_elapsed_ms", "p95"),
        "api_p99_ms": metric(data, "api_elapsed_ms", "p99"),
        "matrix_median_ms": metric(data, "matrix_generation_time_ms", "median"),
        "matrix_p95_ms": metric(data, "matrix_generation_time_ms", "p95"),
        "greedy_median_ms": metric(data, "optimization_time_ms", "median"),
        "greedy_p95_ms": metric(data, "optimization_time_ms", "p95"),
        "response_total_median_ms": metric(data, "response_total_time_ms", "median"),
        "response_total_p95_ms": metric(data, "response_total_time_ms", "p95"),
        "total_distance_m": data.get("total_distance_m"),
        "created_at_utc": data.get("created_at_utc"),
        "first_failure": data.get("first_failure"),
    }


def build_case_rows(parent_path: Path, data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    cases = data.get("cases")

    if not isinstance(cases, list):
        return rows

    for case in cases:
        if not isinstance(case, dict):
            continue

        rows.append(
            {
                "parent_file": str(parent_path),
                "benchmark": data.get("benchmark"),
                "mode": data.get("mode"),
                "case": case.get("case"),
                "stop_count": case.get("stop_count"),
                "return_to_start": case.get("return_to_start"),
                "success_count": case.get("success_count"),
                "failure_count": case.get("failure_count"),
                "all_orders_valid": case.get("all_orders_valid"),
                "all_leg_counts_valid": case.get("all_leg_counts_valid"),
                "all_return_legs_valid": case.get("all_return_legs_valid"),
                "cache_hit_count": case.get("cache_hit_count"),
                "cache_miss_count": case.get("cache_miss_count"),
                "api_median_ms": metric(case, "api_elapsed_ms", "median"),
                "api_p95_ms": metric(case, "api_elapsed_ms", "p95"),
                "matrix_median_ms": metric(case, "matrix_generation_time_ms", "median"),
                "greedy_median_ms": metric(case, "optimization_time_ms", "median"),
                "response_total_median_ms": metric(case, "response_total_time_ms", "median"),
                "total_distance_m": case.get("total_distance_m"),
            }
        )

    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames = sorted({key for row in rows for key in row.keys()})

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def md_value(value: Any) -> str:
    if value is None:
        return ""

    text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def write_markdown(
    *,
    path: Path,
    summary_rows: list[dict[str, Any]],
    case_rows: list[dict[str, Any]],
    source_file_count: int,
) -> None:
    lines: list[str] = []

    lines.append("# CityRoute Phase 6 Raw JSON Evidence Index")
    lines.append("")
    lines.append(f"Generated at UTC: `{datetime.now(timezone.utc).isoformat()}`")
    lines.append(f"Source JSON files scanned: `{source_file_count}`")
    lines.append("")
    lines.append("This file is generated automatically from:")
    lines.append("")
    lines.append("- `benchmarks/phase_6/docker_results/*.json`")
    lines.append("- `benchmarks/phase_6/local_results/*.json`")
    lines.append("")
    lines.append("## Summary Index")
    lines.append("")

    summary_columns = [
        "file",
        "benchmark",
        "mode",
        "route_mode",
        "stop_count",
        "case_count",
        "iterations",
        "total_requests",
        "workers",
        "success_count",
        "failure_count",
        "success_rate_pct",
        "all_cases_passed",
        "load_probe_passed",
        "all_orders_valid",
        "all_leg_counts_valid",
        "invalid_25_passed",
        "invalid_25_status",
        "cache_hit_count",
        "cache_miss_count",
        "api_median_ms",
        "api_p95_ms",
        "matrix_median_ms",
        "greedy_median_ms",
        "response_total_median_ms",
        "total_distance_m",
    ]

    lines.append("| " + " | ".join(summary_columns) + " |")
    lines.append("| " + " | ".join(["---"] * len(summary_columns)) + " |")

    for row in summary_rows:
        lines.append(
            "| "
            + " | ".join(md_value(row.get(column)) for column in summary_columns)
            + " |"
        )

    if case_rows:
        lines.append("")
        lines.append("## Edge Case Details")
        lines.append("")

        case_columns = [
            "parent_file",
            "case",
            "mode",
            "stop_count",
            "return_to_start",
            "success_count",
            "failure_count",
            "all_orders_valid",
            "all_leg_counts_valid",
            "all_return_legs_valid",
            "cache_hit_count",
            "cache_miss_count",
            "api_median_ms",
            "api_p95_ms",
            "matrix_median_ms",
            "greedy_median_ms",
            "response_total_median_ms",
            "total_distance_m",
        ]

        lines.append("| " + " | ".join(case_columns) + " |")
        lines.append("| " + " | ".join(["---"] * len(case_columns)) + " |")

        for row in case_rows:
            lines.append(
                "| "
                + " | ".join(md_value(row.get(column)) for column in case_columns)
                + " |"
            )

    lines.append("")
    lines.append("## Generated Files")
    lines.append("")
    lines.append(f"- `{INDEX_MD_PATH}`")
    lines.append(f"- `{INDEX_CSV_PATH}`")
    lines.append(f"- `{INDEX_JSON_PATH}`")
    lines.append(f"- `{RAW_DUMP_PATH}`")
    lines.append("")
    lines.append("`phase6_all_raw_dump.json` contains the full JSON payload from every scanned result file.")

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    PHASE6_ROOT.mkdir(parents=True, exist_ok=True)

    json_files: list[Path] = []

    for result_dir in RESULT_DIRS:
        if result_dir.exists():
            json_files.extend(sorted(result_dir.glob("*.json")))

    summary_rows: list[dict[str, Any]] = []
    case_rows: list[dict[str, Any]] = []
    raw_dump: list[dict[str, Any]] = []

    for path in sorted(json_files):
        data = load_json(path)

        summary_rows.append(build_summary_row(path, data))
        case_rows.extend(build_case_rows(path, data))

        raw_dump.append(
            {
                "file": str(path),
                "result_group": detect_result_group(path),
                "content": data,
            }
        )

    combined_index = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_file_count": len(json_files),
        "summary_rows": summary_rows,
        "case_rows": case_rows,
    }

    INDEX_JSON_PATH.write_text(
        json.dumps(combined_index, indent=2),
        encoding="utf-8",
    )

    RAW_DUMP_PATH.write_text(
        json.dumps(
            {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "source_file_count": len(json_files),
                "files": raw_dump,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    write_csv(INDEX_CSV_PATH, summary_rows)

    write_markdown(
        path=INDEX_MD_PATH,
        summary_rows=summary_rows,
        case_rows=case_rows,
        source_file_count=len(json_files),
    )

    print(f"Scanned JSON files: {len(json_files)}")
    print(f"Wrote summary JSON: {INDEX_JSON_PATH}")
    print(f"Wrote summary CSV:  {INDEX_CSV_PATH}")
    print(f"Wrote summary MD:   {INDEX_MD_PATH}")
    print(f"Wrote raw dump:     {RAW_DUMP_PATH}")

    if not json_files:
        print("WARNING: No JSON files found in docker_results or local_results.")


if __name__ == "__main__":
    main()