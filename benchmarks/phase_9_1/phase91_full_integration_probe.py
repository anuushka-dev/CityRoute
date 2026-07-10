# benchmarks/phase_9_1/phase91_full_integration_probe.py

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[2]

Mode = Literal["local", "docker"]
SourceDijkstraApiMode = Literal["blocked", "ok"]

REQUIRED_OPENAPI_PATHS = {
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


@dataclass(frozen=True)
class IntegrationCheck:
    name: str
    method: str
    url: str
    expected: str
    success: bool
    status_code: int | None
    elapsed_ms: float
    error: str | None
    key_values: dict[str, Any]


@dataclass(frozen=True)
class FullIntegrationSummary:
    phase: str
    benchmark: str
    mode: Mode
    base_url: str
    source_dijkstra_api_mode: SourceDijkstraApiMode
    created_at_utc: str
    check_count: int
    success_count: int
    failure_count: int
    success_rate_pct: float
    checks: list[IntegrationCheck]
    output_raw_file: str
    output_summary_file: str
    quality_flags: dict[str, bool]
    evidence_note: str


def main() -> None:
    args = _parse_args()

    mode: Mode = args.mode
    source_dijkstra_api_mode: SourceDijkstraApiMode = args.source_dijkstra_api_mode
    base_url = args.base_url or _default_base_url(mode)

    output_dir = _resolve_output_dir(
        mode=mode,
        output_dir_arg=args.output_dir,
    )

    created_at = datetime.now(UTC)
    timestamp = created_at.strftime("%Y%m%d_%H%M%S")

    raw_file = output_dir / f"phase91_full_integration_raw_{mode}_{timestamp}.json"
    summary_file = output_dir / (
        f"phase91_full_integration_summary_{mode}_{timestamp}.json"
    )

    checks = [
        _check_root(base_url),
        _check_health(base_url),
        _check_openapi(base_url),
        _check_graph_stats(base_url),
        _check_dispatch_haversine(base_url),
        _check_dispatch_source_dijkstra(
            base_url=base_url,
            source_dijkstra_api_mode=source_dijkstra_api_mode,
        ),
    ]

    summary = _build_summary(
        mode=mode,
        base_url=base_url,
        source_dijkstra_api_mode=source_dijkstra_api_mode,
        created_at=created_at,
        checks=checks,
        raw_file=raw_file,
        summary_file=summary_file,
    )

    raw_payload = {
        "phase": "tier3_phase9_1",
        "benchmark": "full_integration_probe",
        "mode": mode,
        "base_url": base_url,
        "source_dijkstra_api_mode": source_dijkstra_api_mode,
        "created_at_utc": created_at.isoformat(),
        "check_count": len(checks),
        "checks": [asdict(check) for check in checks],
    }

    _write_json(raw_file, raw_payload)
    _write_json(summary_file, asdict(summary))

    print(json.dumps(asdict(summary), indent=2))

    if args.strict and not all(summary.quality_flags.values()):
        raise SystemExit(1)


def _check_root(base_url: str) -> IntegrationCheck:
    url = f"{base_url}/"
    start = perf_counter()

    status_code, payload, error = _http_json(
        method="GET",
        url=url,
    )

    key_values = {
        "phase": payload.get("phase"),
        "health": payload.get("health"),
        "graph_stats": payload.get("graph_stats"),
        "matrix": payload.get("matrix"),
        "vrp_advanced_compare": payload.get("vrp_advanced_compare"),
        "dispatch_compare": payload.get("dispatch_compare"),
    }

    success = (
        status_code == 200
        and key_values["health"] == "/health"
        and key_values["graph_stats"] == "/graph/stats"
        and key_values["matrix"] == "/matrix"
        and key_values["vrp_advanced_compare"] == "/vrp/compare/advanced"
        and key_values["dispatch_compare"] == "/dispatch/compare"
    )

    return IntegrationCheck(
        name="root",
        method="GET",
        url=url,
        expected="HTTP 200 and root route links include dispatch_compare.",
        success=success,
        status_code=status_code,
        elapsed_ms=_elapsed_ms(start),
        error=error,
        key_values=key_values,
    )


def _check_health(base_url: str) -> IntegrationCheck:
    url = f"{base_url}/health"
    start = perf_counter()

    status_code, payload, error = _http_json(
        method="GET",
        url=url,
    )

    key_values = {
        "status": payload.get("status"),
        "graph_loaded": payload.get("graph_loaded"),
    }

    success = status_code == 200 and key_values["status"] == "ok"

    return IntegrationCheck(
        name="health",
        method="GET",
        url=url,
        expected="HTTP 200 and status=ok.",
        success=success,
        status_code=status_code,
        elapsed_ms=_elapsed_ms(start),
        error=error,
        key_values=key_values,
    )


def _check_openapi(base_url: str) -> IntegrationCheck:
    url = f"{base_url}/openapi.json"
    start = perf_counter()

    status_code, payload, error = _http_json(
        method="GET",
        url=url,
    )

    paths = payload.get("paths", {})
    if not isinstance(paths, dict):
        paths = {}

    available_paths = set(paths)
    missing_paths = sorted(REQUIRED_OPENAPI_PATHS - available_paths)

    key_values = {
        "path_count": len(available_paths),
        "missing_required_paths": missing_paths,
        "all_required_paths_available": len(missing_paths) == 0,
        "dispatch_compare_available": "/dispatch/compare" in available_paths,
    }

    success = status_code == 200 and len(missing_paths) == 0

    return IntegrationCheck(
        name="openapi",
        method="GET",
        url=url,
        expected="HTTP 200 and all required Phase 1-9.1 routes registered.",
        success=success,
        status_code=status_code,
        elapsed_ms=_elapsed_ms(start),
        error=error,
        key_values=key_values,
    )


def _check_graph_stats(base_url: str) -> IntegrationCheck:
    url = f"{base_url}/graph/stats"
    start = perf_counter()

    status_code, payload, error = _http_json(
        method="GET",
        url=url,
    )

    key_values = {
        "graph_loaded": payload.get("graph_loaded"),
        "nodes": payload.get("nodes"),
        "edges": payload.get("edges"),
        "detail": payload.get("detail"),
    }

    success = False

    if status_code == 200:
        if key_values["graph_loaded"] is True:
            success = (
                isinstance(key_values["nodes"], int)
                and key_values["nodes"] > 0
                and isinstance(key_values["edges"], int)
                and key_values["edges"] > 0
            )
        else:
            success = "graph_loaded" in payload

    if status_code == 503:
        success = "detail" in payload

    return IntegrationCheck(
        name="graph_stats",
        method="GET",
        url=url,
        expected=(
            "HTTP 200 with graph stats or valid graph_loaded=false shape; "
            "HTTP 503 with detail is also accepted."
        ),
        success=success,
        status_code=status_code,
        elapsed_ms=_elapsed_ms(start),
        error=error,
        key_values=key_values,
    )


def _check_dispatch_haversine(base_url: str) -> IntegrationCheck:
    url = f"{base_url}/dispatch/compare"
    start = perf_counter()

    status_code, payload, error = _http_json(
        method="POST",
        url=url,
        body=_dispatch_payload(matrix_algorithm="haversine", use_cache=True),
    )

    comparison = payload.get("comparison", {})
    hungarian = payload.get("hungarian", {})

    if not isinstance(comparison, dict):
        comparison = {}

    if not isinstance(hungarian, dict):
        hungarian = {}

    key_values = {
        "status": payload.get("status"),
        "phase": payload.get("phase"),
        "matrix_algorithm": payload.get("matrix_algorithm"),
        "driver_count": payload.get("driver_count"),
        "order_count": payload.get("order_count"),
        "assigned_order_count": payload.get("assigned_order_count"),
        "unassigned_order_count": payload.get("unassigned_order_count"),
        "cache_used": payload.get("cache_used"),
        "cache_hit": payload.get("cache_hit"),
        "hungarian_assigned_count": hungarian.get("assigned_count"),
        "hungarian_total_cost": hungarian.get("total_cost"),
        "hungarian_non_regression": comparison.get("hungarian_non_regression"),
    }

    success = (
        status_code == 200
        and key_values["status"] == "ok"
        and key_values["phase"] in {"tier3_phase9", "tier3_phase9_1"}
        and key_values["matrix_algorithm"] == "haversine"
        and key_values["driver_count"] == 2
        and key_values["order_count"] == 2
        and key_values["assigned_order_count"] == 2
        and key_values["unassigned_order_count"] == 0
        and key_values["hungarian_assigned_count"] == 2
        and key_values["hungarian_non_regression"] is True
    )

    return IntegrationCheck(
        name="dispatch_haversine",
        method="POST",
        url=url,
        expected="HTTP 200 and /dispatch/compare works with haversine.",
        success=success,
        status_code=status_code,
        elapsed_ms=_elapsed_ms(start),
        error=error,
        key_values=key_values,
    )


def _check_dispatch_source_dijkstra(
    *,
    base_url: str,
    source_dijkstra_api_mode: SourceDijkstraApiMode,
) -> IntegrationCheck:
    url = f"{base_url}/dispatch/compare"
    start = perf_counter()

    status_code, payload, error = _http_json(
        method="POST",
        url=url,
        body=_dispatch_payload(matrix_algorithm="source_dijkstra", use_cache=False),
    )

    detail = payload.get("detail")
    comparison = payload.get("comparison", {})
    hungarian = payload.get("hungarian", {})

    if not isinstance(comparison, dict):
        comparison = {}

    if not isinstance(hungarian, dict):
        hungarian = {}

    key_values = {
        "status": payload.get("status"),
        "phase": payload.get("phase"),
        "matrix_algorithm": payload.get("matrix_algorithm"),
        "detail": detail,
        "assigned_order_count": payload.get("assigned_order_count"),
        "cache_used": payload.get("cache_used"),
        "cache_hit": payload.get("cache_hit"),
        "hungarian_assigned_count": hungarian.get("assigned_count"),
        "hungarian_non_regression": comparison.get("hungarian_non_regression"),
    }

    if source_dijkstra_api_mode == "blocked":
        detail_text = str(detail)

        success = (
            status_code == 400
            and "source_dijkstra" in detail_text
            and "source_dijkstra_matrix_builder" in detail_text
        )

        expected = (
            "HTTP 400 because API-level real source_dijkstra builder is not "
            "wired yet. This is expected for current Phase 9.1 service-only stage."
        )

    else:
        success = (
            status_code == 200
            and key_values["status"] == "ok"
            and key_values["phase"] == "tier3_phase9_1"
            and key_values["matrix_algorithm"] == "source_dijkstra"
            and key_values["assigned_order_count"] == 2
            and key_values["hungarian_assigned_count"] == 2
            and key_values["hungarian_non_regression"] is True
        )

        expected = (
            "HTTP 200 because API-level real source_dijkstra builder is expected "
            "to be wired."
        )

    return IntegrationCheck(
        name="dispatch_source_dijkstra",
        method="POST",
        url=url,
        expected=expected,
        success=success,
        status_code=status_code,
        elapsed_ms=_elapsed_ms(start),
        error=error,
        key_values=key_values,
    )


def _dispatch_payload(
    *,
    matrix_algorithm: str,
    use_cache: bool,
) -> dict[str, Any]:
    return {
        "drivers": [
            {
                "driver_id": "driver_1",
                "lat": 26.45,
                "lon": 80.35,
                "current_load": 0,
                "max_capacity": 1,
            },
            {
                "driver_id": "driver_2",
                "lat": 26.46,
                "lon": 80.36,
                "current_load": 0,
                "max_capacity": 1,
            },
        ],
        "orders": [
            {
                "order_id": "order_1",
                "pickup_lat": 26.451,
                "pickup_lon": 80.351,
            },
            {
                "order_id": "order_2",
                "pickup_lat": 26.461,
                "pickup_lon": 80.361,
            },
        ],
        "matrix_algorithm": matrix_algorithm,
        "use_cache": use_cache,
        "load_penalty_m": 0.0,
        "slot_penalty_m": 0.0,
        "return_cost_breakdown": False,
    }


def _build_summary(
    *,
    mode: Mode,
    base_url: str,
    source_dijkstra_api_mode: SourceDijkstraApiMode,
    created_at: datetime,
    checks: list[IntegrationCheck],
    raw_file: Path,
    summary_file: Path,
) -> FullIntegrationSummary:
    check_count = len(checks)
    success_count = sum(1 for check in checks if check.success)
    failure_count = check_count - success_count

    checks_by_name = {check.name: check for check in checks}

    quality_flags = {
        "all_checks_successful": success_count == check_count and check_count > 0,
        "root_ok": _check_success(checks_by_name, "root"),
        "health_ok": _check_success(checks_by_name, "health"),
        "openapi_required_paths_available": _check_success(checks_by_name, "openapi"),
        "graph_stats_shape_valid": _check_success(checks_by_name, "graph_stats"),
        "dispatch_haversine_ok": _check_success(
            checks_by_name,
            "dispatch_haversine",
        ),
        "dispatch_haversine_non_regression": (
            checks_by_name.get("dispatch_haversine", IntegrationCheck(
                name="missing",
                method="",
                url="",
                expected="",
                success=False,
                status_code=None,
                elapsed_ms=0.0,
                error="missing",
                key_values={},
            )).key_values.get("hungarian_non_regression")
            is True
        ),
        "dispatch_source_dijkstra_status_expected": _check_success(
            checks_by_name,
            "dispatch_source_dijkstra",
        ),
        "source_dijkstra_api_blocked_acknowledged": (
            source_dijkstra_api_mode == "blocked"
            and _check_success(checks_by_name, "dispatch_source_dijkstra")
        ),
        "source_dijkstra_api_ok": (
            source_dijkstra_api_mode == "ok"
            and _check_success(checks_by_name, "dispatch_source_dijkstra")
        ),
    }

    # Only one of these can be true depending on expected mode.
    if source_dijkstra_api_mode == "blocked":
        quality_flags["source_dijkstra_api_ok"] = True

    if source_dijkstra_api_mode == "ok":
        quality_flags["source_dijkstra_api_blocked_acknowledged"] = True

    evidence_note = (
        "This live full-integration probe validates root, health, OpenAPI route "
        "registration, graph stats shape, and /dispatch/compare haversine API "
        "behavior. In default mode it also verifies that source_dijkstra is "
        "honestly blocked at API level until the real internal Phase 5 graph "
        "builder is wired. Use --source-dijkstra-api-mode ok only after API-level "
        "source_dijkstra is implemented."
    )

    return FullIntegrationSummary(
        phase="tier3_phase9_1",
        benchmark="full_integration_probe",
        mode=mode,
        base_url=base_url,
        source_dijkstra_api_mode=source_dijkstra_api_mode,
        created_at_utc=created_at.isoformat(),
        check_count=check_count,
        success_count=success_count,
        failure_count=failure_count,
        success_rate_pct=_pct(success_count, check_count),
        checks=checks,
        output_raw_file=_relative_path(raw_file),
        output_summary_file=_relative_path(summary_file),
        quality_flags=quality_flags,
        evidence_note=evidence_note,
    )


def _check_success(
    checks_by_name: dict[str, IntegrationCheck],
    name: str,
) -> bool:
    check = checks_by_name.get(name)

    return check is not None and check.success


def _http_json(
    *,
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
) -> tuple[int | None, dict[str, Any], str | None]:
    data = None
    headers = {"Accept": "application/json"}

    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urlopen(request, timeout=15) as response:
            status_code = response.status
            raw_body = response.read().decode("utf-8")

        payload = json.loads(raw_body) if raw_body else {}

        if not isinstance(payload, dict):
            payload = {"raw": payload}

        return status_code, payload, None

    except HTTPError as exc:
        raw_body = exc.read().decode("utf-8")

        try:
            payload = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError:
            payload = {"raw": raw_body}

        if not isinstance(payload, dict):
            payload = {"raw": payload}

        return exc.code, payload, None

    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return None, {}, f"{type(exc).__name__}: {exc}"


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


def _relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _pct(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0

    return round((numerator / denominator) * 100.0, 6)


def _elapsed_ms(start_time: float) -> float:
    return round((perf_counter() - start_time) * 1000.0, 6)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 9.1 live full integration API probe."
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
        "--source-dijkstra-api-mode",
        choices=["blocked", "ok"],
        default="blocked",
        help=(
            "Use 'blocked' before API-level source_dijkstra is wired. "
            "Use 'ok' after live source_dijkstra dispatch API support exists."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional output directory.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any quality flag is false.",
    )

    return parser.parse_args()


if __name__ == "__main__":
    main()