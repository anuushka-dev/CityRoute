from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PHASE = "tier3_phase8"
ADVANCED_ENDPOINT = "/vrp/compare/advanced"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")


def _run_command(command: list[str], *, timeout_s: float = 60.0) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )

        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "ok": completed.returncode == 0,
        }

    except FileNotFoundError as exc:
        return {
            "command": command,
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
            "ok": False,
        }

    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "returncode": None,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or f"Command timed out after {timeout_s}s",
            "ok": False,
        }


def _http_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout_s: float = 60.0,
) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}

    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url=url, data=body, headers=headers, method=method)

    try:
        with urlopen(request, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8")
            return {
                "ok": True,
                "status_code": response.status,
                "body": json.loads(raw) if raw else None,
            }

    except HTTPError as exc:
        raw = exc.read().decode("utf-8")

        try:
            body_json: Any = json.loads(raw)
        except json.JSONDecodeError:
            body_json = raw

        return {
            "ok": False,
            "status_code": exc.code,
            "body": body_json,
        }

    except URLError as exc:
        return {
            "ok": False,
            "status_code": None,
            "body": {
                "error": "URL error",
                "message": str(exc),
            },
        }


def _extract_openapi_paths(openapi_response: dict[str, Any]) -> list[str]:
    if not openapi_response.get("ok"):
        return []

    body = openapi_response.get("body")

    if not isinstance(body, dict):
        return []

    paths = body.get("paths", {})

    if not isinstance(paths, dict):
        return []

    return sorted(paths.keys())


def _list_files(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []

    files: list[dict[str, Any]] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        stat = path.stat()

        files.append(
            {
                "path": str(path).replace("\\", "/"),
                "size_bytes": stat.st_size,
                "modified_utc": datetime.fromtimestamp(
                    stat.st_mtime,
                    tz=UTC,
                ).isoformat(),
            }
        )

    return files


def _read_json_file(path: Path) -> Any | None:
    if not path.exists() or not path.is_file():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _latest_json_files(root: Path, pattern: str, *, limit: int = 5) -> list[Path]:
    if not root.exists():
        return []

    files = [path for path in root.glob(pattern) if path.is_file()]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)

    return files[:limit]


def _summarize_latest_benchmarks(output_dir: Path) -> dict[str, Any]:
    benchmark_summaries = []
    gap_summaries = []

    for path in _latest_json_files(output_dir, "phase8_lns_benchmark_summary_*.json"):
        data = _read_json_file(path)

        if isinstance(data, dict):
            benchmark_summaries.append(
                {
                    "file": str(path).replace("\\", "/"),
                    "created_at_utc": data.get("created_at_utc"),
                    "mode": data.get("mode"),
                    "endpoint": data.get("endpoint"),
                    "sizes": data.get("sizes"),
                    "return_to_start": data.get("return_to_start"),
                    "overall": data.get("overall"),
                    "group_summaries": data.get("group_summaries"),
                }
            )

    for path in _latest_json_files(output_dir, "phase8_lns_optimality_gap_summary_*.json"):
        data = _read_json_file(path)

        if isinstance(data, dict):
            gap_summaries.append(
                {
                    "file": str(path).replace("\\", "/"),
                    "created_at_utc": data.get("created_at_utc"),
                    "mode": data.get("mode"),
                    "sizes": data.get("sizes"),
                    "success_count": data.get("success_count"),
                    "case_count": data.get("case_count"),
                    "success_rate_pct": data.get("success_rate_pct"),
                    "gap_summary_pct": data.get("gap_summary_pct"),
                    "quality_flags": data.get("quality_flags"),
                }
            )

    return {
        "latest_lns_benchmark_summaries": benchmark_summaries,
        "latest_optimality_gap_summaries": gap_summaries,
    }


def _collect_git_evidence() -> dict[str, Any]:
    commands = {
        "status_short": ["git", "status", "--short"],
        "status": ["git", "status"],
        "branch": ["git", "branch", "--show-current"],
        "log_oneline_10": ["git", "log", "--oneline", "-10"],
        "diff_stat": ["git", "diff", "--stat"],
        "diff_cached_stat": ["git", "diff", "--cached", "--stat"],
    }

    return {name: _run_command(command) for name, command in commands.items()}


def _collect_docker_evidence() -> dict[str, Any]:
    commands = {
        "docker_version": ["docker", "--version"],
        "docker_compose_version": ["docker", "compose", "version"],
        "docker_compose_ps": ["docker", "compose", "ps"],
        "docker_ps": ["docker", "ps"],
        "docker_images_cityroute": ["docker", "images", "cityroute-api"],
    }

    return {name: _run_command(command) for name, command in commands.items()}


def _collect_python_evidence() -> dict[str, Any]:
    commands = {
        "python_version": [sys.executable, "--version"],
        "ruff_phase8": [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "app/core/lns.py",
            "tests/test_lns.py",
            "app/schemas/vrp_advanced_compare.py",
            "app/services/vrp_advanced_compare_service.py",
            "app/api/vrp.py",
            "tests/test_vrp_advanced_compare_endpoint.py",
            "benchmarks/phase_8/phase8_lns_benchmark.py",
            "benchmarks/phase_8/phase8_lns_optimality_gap_probe.py",
            "benchmarks/phase_8/phase8_evidence_collector.py",
        ],
        "pytest_lns": [sys.executable, "-m", "pytest", "tests/test_lns.py", "-q"],
        "pytest_advanced_endpoint": [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_vrp_advanced_compare_endpoint.py",
            "-q",
        ],
        "app_import": [
            sys.executable,
            "-c",
            "from app.main import app; print('app import ok')",
        ],
        "vrp_routes": [
            sys.executable,
            "-c",
            "from app.main import app; print([route.path for route in app.routes if 'vrp' in route.path])",
        ],
    }

    return {name: _run_command(command, timeout_s=180.0) for name, command in commands.items()}


def collect_evidence(args: argparse.Namespace) -> dict[str, Any]:
    base_url = args.base_url.rstrip("/")
    output_dir = Path(args.output_dir)

    health = _http_json("GET", f"{base_url}/health", timeout_s=args.timeout_s)
    graph_stats = _http_json("GET", f"{base_url}/graph/stats", timeout_s=args.timeout_s)
    openapi = _http_json("GET", f"{base_url}/openapi.json", timeout_s=args.timeout_s)
    openapi_paths = _extract_openapi_paths(openapi)

    phase8_files = _list_files(Path("benchmarks/phase_8"))

    source_files = [
        "app/core/lns.py",
        "tests/test_lns.py",
        "app/schemas/vrp_advanced_compare.py",
        "app/services/vrp_advanced_compare_service.py",
        "app/api/vrp.py",
        "tests/test_vrp_advanced_compare_endpoint.py",
        "benchmarks/phase_8/phase8_lns_benchmark.py",
        "benchmarks/phase_8/phase8_lns_optimality_gap_probe.py",
        "benchmarks/phase_8/phase8_evidence_collector.py",
    ]

    source_file_status = {
        file_path: Path(file_path).exists()
        for file_path in source_files
    }

    benchmark_summary = _summarize_latest_benchmarks(output_dir)

    evidence = {
        "phase": PHASE,
        "collector": "phase8_evidence_collector",
        "created_at_utc": _utc_now_iso(),
        "mode": args.mode,
        "base_url": base_url,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "python_executable": sys.executable,
            "python_version": platform.python_version(),
        },
        "source_file_status": source_file_status,
        "preflight": {
            "health_ok": bool(health.get("ok")),
            "health": health.get("body"),
            "graph_stats_ok": bool(graph_stats.get("ok")),
            "graph_stats": graph_stats.get("body"),
            "openapi_ok": bool(openapi.get("ok")),
            "advanced_endpoint_available": ADVANCED_ENDPOINT in openapi_paths,
            "openapi_paths": openapi_paths,
        },
        "commands": {
            "git": _collect_git_evidence(),
            "docker": _collect_docker_evidence(),
            "python_quality": _collect_python_evidence(),
        },
        "benchmarks": benchmark_summary,
        "phase8_files": phase8_files,
        "audit_flags": {
            "all_expected_source_files_exist": all(source_file_status.values()),
            "advanced_endpoint_available": ADVANCED_ENDPOINT in openapi_paths,
            "health_ok": bool(health.get("ok")),
            "graph_loaded": bool(
                isinstance(health.get("body"), dict)
                and health["body"].get("graph_loaded")
            ),
            "graph_stats_loaded": bool(
                isinstance(graph_stats.get("body"), dict)
                and graph_stats["body"].get("graph_loaded")
            ),
            "ruff_ok": bool(
                _run_command(
                    [
                        sys.executable,
                        "-m",
                        "ruff",
                        "check",
                        "app/core/lns.py",
                        "tests/test_lns.py",
                        "app/schemas/vrp_advanced_compare.py",
                        "app/services/vrp_advanced_compare_service.py",
                        "app/api/vrp.py",
                        "tests/test_vrp_advanced_compare_endpoint.py",
                        "benchmarks/phase_8/phase8_lns_benchmark.py",
                        "benchmarks/phase_8/phase8_lns_optimality_gap_probe.py",
                        "benchmarks/phase_8/phase8_evidence_collector.py",
                    ],
                    timeout_s=180.0,
                ).get("ok")
            ),
        },
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    evidence_path = output_dir / f"phase8_evidence_manifest_{args.mode}_{timestamp}.json"
    text_path = output_dir / f"phase8_evidence_manifest_{args.mode}_{timestamp}.txt"

    _write_json(evidence_path, evidence)

    readable = [
        f"CityRoute {PHASE} Evidence Manifest",
        f"Created UTC: {evidence['created_at_utc']}",
        f"Mode: {args.mode}",
        f"Base URL: {base_url}",
        "",
        "Audit flags:",
        json.dumps(evidence["audit_flags"], indent=2, sort_keys=True),
        "",
        "OpenAPI paths:",
        "\n".join(openapi_paths),
        "",
        "Expected source files:",
        json.dumps(source_file_status, indent=2, sort_keys=True),
        "",
        "Latest benchmark summaries:",
        json.dumps(benchmark_summary, indent=2, sort_keys=True),
    ]

    _write_text(text_path, "\n".join(readable))

    print(f"Evidence JSON saved: {evidence_path}")
    print(f"Evidence TXT saved: {text_path}")

    return evidence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect Phase 8 audit evidence for CityRoute LNS"
    )

    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--mode", choices=["docker", "local"], default="docker")
    parser.add_argument("--output-dir", default="benchmarks/phase_8/docker_results")
    parser.add_argument("--timeout-s", type=float, default=120.0)

    args = parser.parse_args()

    if args.mode == "local" and args.output_dir == "benchmarks/phase_8/docker_results":
        args.output_dir = "benchmarks/phase_8/local_results"

    return args


def main() -> int:
    args = parse_args()

    try:
        evidence = collect_evidence(args)
    except KeyboardInterrupt:
        print("Evidence collection interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Evidence collection failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    flags = evidence["audit_flags"]

    if not flags["all_expected_source_files_exist"]:
        return 2

    if not flags["advanced_endpoint_available"]:
        return 3

    if not flags["health_ok"]:
        return 4

    if not flags["graph_loaded"]:
        return 5

    if not flags["ruff_ok"]:
        return 6

    return 0


if __name__ == "__main__":
    raise SystemExit(main())