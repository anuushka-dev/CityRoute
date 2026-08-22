# benchmarks/phase_11/phase11_timeout_probe.py

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

# Support both:
#   python benchmarks/phase_11/phase11_timeout_probe.py
#   python -m benchmarks.phase_11.phase11_timeout_probe
PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.phase_11.phase11_common import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT_S,
    PROJECT_PHASE_CODE,
    PROJECT_PHASE_NAME,
    build_result_path,
    collect_runtime_metadata,
    percentile,
    print_json,
    timestamp_slug,
    utc_now_iso,
    wait_for_liveness,
    wait_for_readiness,
    write_json,
)

DEFAULT_BASELINE_ATTEMPTS = 5
DEFAULT_TRIGGER_ATTEMPTS = 3
DEFAULT_MATRIX_SIZE = 25
DEFAULT_RECOVERY_MATRIX_SIZE = 5

TIMEOUT_STATUS_CODE = 504
SUCCESS_STATUS_CODE = 200

TIMEOUT_HEADER_ENFORCED = "x-cityroute-timeout-enforced"
TIMEOUT_HEADER_CATEGORY = "x-cityroute-timeout-category"
TIMEOUT_HEADER_LIMIT_S = "x-cityroute-timeout-limit-s"

CONTROL_ENDPOINTS: tuple[str, ...] = (
    "/health/live",
    "/health/ready",
    "/metrics",
)


@dataclass(frozen=True)
class TimeoutPolicyHeaders:
    enforced: bool | None
    category: str | None
    limit_s: float | None
    raw: dict[str, str]


@dataclass(frozen=True)
class TimeoutAttemptResult:
    stage: str
    attempt_index: int
    algorithm: str
    matrix_size: int
    status_code: int | None
    outcome: str
    elapsed_ms: float
    timeout_headers: TimeoutPolicyHeaders
    response_summary: Any | None
    validation_errors: tuple[str, ...]
    error_type: str | None
    error_message: str | None
    started_at_utc: str
    finished_at_utc: str


@dataclass(frozen=True)
class ControlProbeResult:
    stage: str
    path: str
    status_code: int | None
    elapsed_ms: float
    ok: bool
    timeout_headers: TimeoutPolicyHeaders
    response_summary: Any | None
    error_type: str | None
    error_message: str | None
    started_at_utc: str
    finished_at_utc: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Collect Phase 11 timeout-policy evidence. The probe validates "
            "timeout headers on protected matrix requests, measures normal "
            "headroom, optionally attempts to trigger a server-side timeout, "
            "and proves liveness/readiness/recovery afterward."
        )
    )

    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=(
            "CityRoute API base URL. "
            f"Default: {DEFAULT_BASE_URL}"
        ),
    )
    parser.add_argument(
        "--target",
        choices=("docker", "local"),
        default=None,
        help=(
            "Standard Phase 11 result directory. When omitted, "
            "CITYROUTE_BENCHMARK_RESULT_TARGET is used."
        ),
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=None,
        help=(
            "Explicit output directory. Overrides --target when provided."
        ),
    )
    parser.add_argument(
        "--baseline-algorithm",
        choices=("source_dijkstra", "bidirectional_astar"),
        default="source_dijkstra",
        help=(
            "Algorithm for successful timeout-headroom measurements. "
            "Default: source_dijkstra"
        ),
    )
    parser.add_argument(
        "--baseline-matrix-size",
        type=int,
        default=DEFAULT_MATRIX_SIZE,
        help=(
            "Matrix size for normal protected requests. "
            f"Default: {DEFAULT_MATRIX_SIZE}"
        ),
    )
    parser.add_argument(
        "--baseline-attempts",
        type=int,
        default=DEFAULT_BASELINE_ATTEMPTS,
        help=(
            "Number of normal protected requests. "
            f"Default: {DEFAULT_BASELINE_ATTEMPTS}"
        ),
    )
    parser.add_argument(
        "--trigger-algorithm",
        choices=("source_dijkstra", "bidirectional_astar"),
        default="bidirectional_astar",
        help=(
            "Algorithm used for optional timeout-trigger attempts. "
            "Default: bidirectional_astar"
        ),
    )
    parser.add_argument(
        "--trigger-matrix-size",
        type=int,
        default=DEFAULT_MATRIX_SIZE,
        help=(
            "Matrix size for timeout-trigger attempts. "
            f"Default: {DEFAULT_MATRIX_SIZE}"
        ),
    )
    parser.add_argument(
        "--trigger-attempts",
        type=int,
        default=DEFAULT_TRIGGER_ATTEMPTS,
        help=(
            "Number of timeout-trigger attempts. Use zero to skip. "
            f"Default: {DEFAULT_TRIGGER_ATTEMPTS}"
        ),
    )
    parser.add_argument(
        "--require-timeout",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Require at least one HTTP 504 server-side timeout. Disabled by "
            "default because real endpoint runtime depends on hardware and "
            "graph workload."
        ),
    )
    parser.add_argument(
        "--use-cache",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Enable matrix caching. Disabled by default so timeout evidence "
            "uses real computation."
        ),
    )
    parser.add_argument(
        "--payload-file",
        type=Path,
        default=None,
        help=(
            "Optional JSON object used as the /matrix request body. "
            "When omitted, a valid Kanpur Central payload is generated."
        ),
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=max(DEFAULT_TIMEOUT_S, 45.0),
        help=(
            "HTTP client timeout. It must exceed the discovered server "
            "timeout limit. Default: 45"
        ),
    )
    parser.add_argument(
        "--startup-timeout-s",
        type=float,
        default=180.0,
        help="Maximum startup wait in seconds. Default: 180",
    )
    parser.add_argument(
        "--timeout-lower-bound-ratio",
        type=float,
        default=0.70,
        help=(
            "Minimum elapsed/server-limit ratio accepted for a real HTTP "
            "504 timeout. Default: 0.70"
        ),
    )
    parser.add_argument(
        "--timeout-upper-grace-s",
        type=float,
        default=5.0,
        help=(
            "Allowed wall-clock grace above the advertised server timeout "
            "for an HTTP 504 response. Default: 5"
        ),
    )
    parser.add_argument(
        "--fail-on-validation-error",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Exit non-zero when timeout-policy evidence fails validation. "
            "Default: enabled."
        ),
    )

    args = parser.parse_args()

    for argument_name in (
        "baseline_matrix_size",
        "trigger_matrix_size",
    ):
        value = getattr(args, argument_name)

        if not 2 <= value <= 25:
            parser.error(
                f"--{argument_name.replace('_', '-')} must be "
                "between 2 and 25"
            )

    if args.baseline_attempts <= 0:
        parser.error("--baseline-attempts must be greater than zero")

    if args.trigger_attempts < 0:
        parser.error("--trigger-attempts must be zero or greater")

    if args.require_timeout and args.trigger_attempts == 0:
        parser.error(
            "--require-timeout requires --trigger-attempts greater "
            "than zero"
        )

    if args.timeout_s <= 0:
        parser.error("--timeout-s must be greater than zero")

    if args.startup_timeout_s <= 0:
        parser.error("--startup-timeout-s must be greater than zero")

    if not 0.0 < args.timeout_lower_bound_ratio <= 1.0:
        parser.error(
            "--timeout-lower-bound-ratio must be greater than zero "
            "and at most one"
        )

    if args.timeout_upper_grace_s < 0:
        parser.error(
            "--timeout-upper-grace-s must be zero or greater"
        )

    return args


def _load_payload_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise ValueError("--payload-file must contain one JSON object")

    return payload


def _generated_locations(
    *,
    matrix_size: int,
    safe_variant: int,
) -> list[dict[str, Any]]:
    center_lat = 26.4499
    center_lon = 80.3319
    spacing = 0.0016
    shift = (safe_variant % 100) * 0.0000001

    locations: list[dict[str, Any]] = []

    for index in range(matrix_size):
        row, column = divmod(index, 5)

        locations.append(
            {
                "id": f"p{index:02d}",
                "lat": round(
                    center_lat
                    + ((row - 2) * spacing)
                    + shift,
                    7,
                ),
                "lon": round(
                    center_lon
                    + ((column - 2) * spacing)
                    - shift,
                    7,
                ),
            }
        )

    return locations


def _build_matrix_payload(
    *,
    matrix_size: int,
    algorithm: str,
    use_cache: bool,
    safe_variant: int,
    payload_template: dict[str, Any] | None,
) -> dict[str, Any]:
    if payload_template is not None:
        payload = json.loads(json.dumps(payload_template))
        payload["algorithm"] = algorithm
        payload["use_cache"] = use_cache
        return payload

    return {
        "locations": _generated_locations(
            matrix_size=matrix_size,
            safe_variant=safe_variant,
        ),
        "algorithm": algorithm,
        "use_cache": use_cache,
    }


def _parse_bool_header(raw_value: str | None) -> bool | None:
    if raw_value is None:
        return None

    normalized = raw_value.strip().lower()

    if normalized == "true":
        return True

    if normalized == "false":
        return False

    return None


def _parse_float_header(raw_value: str | None) -> float | None:
    if raw_value is None:
        return None

    try:
        return float(raw_value)
    except ValueError:
        return None


def _timeout_headers(
    response: httpx.Response,
) -> TimeoutPolicyHeaders:
    raw: dict[str, str] = {}

    for name in (
        TIMEOUT_HEADER_ENFORCED,
        TIMEOUT_HEADER_CATEGORY,
        TIMEOUT_HEADER_LIMIT_S,
    ):
        value = response.headers.get(name)

        if value is not None:
            raw[name] = value

    return TimeoutPolicyHeaders(
        enforced=_parse_bool_header(
            response.headers.get(TIMEOUT_HEADER_ENFORCED)
        ),
        category=response.headers.get(
            TIMEOUT_HEADER_CATEGORY
        ),
        limit_s=_parse_float_header(
            response.headers.get(TIMEOUT_HEADER_LIMIT_S)
        ),
        raw=raw,
    )


def _summarize_response(
    *,
    status_code: int,
    response_json: Any,
    response_text: str,
) -> Any:
    if not isinstance(response_json, dict):
        return {
            "body_preview": response_text[:2000],
        }

    if status_code == SUCCESS_STATUS_CODE:
        return {
            "status": response_json.get("status"),
            "n": response_json.get("n"),
            "algorithm": response_json.get("algorithm"),
            "pair_count": response_json.get("pair_count"),
            "computed_pairs": response_json.get("computed_pairs"),
            "failed_pairs": response_json.get("failed_pairs"),
            "generation_time_ms": response_json.get(
                "generation_time_ms"
            ),
            "parallel_workers": response_json.get(
                "parallel_workers"
            ),
            "cache": response_json.get("cache"),
        }

    return response_json


def _classify_outcome(
    status_code: int | None,
) -> str:
    if status_code == SUCCESS_STATUS_CODE:
        return "completed"

    if status_code == TIMEOUT_STATUS_CODE:
        return "server_timeout"

    if status_code is None:
        return "client_error"

    return "unexpected_response"


def _timeout_body_matches(response_summary: Any) -> bool:
    if not isinstance(response_summary, dict):
        return False

    searchable = json.dumps(
        response_summary,
        sort_keys=True,
    ).lower()

    return (
        "timeout" in searchable
        or "timed out" in searchable
        or "deadline" in searchable
    )


def _validate_attempt(
    *,
    outcome: str,
    elapsed_ms: float,
    headers: TimeoutPolicyHeaders,
    response_summary: Any,
    timeout_lower_bound_ratio: float,
    timeout_upper_grace_s: float,
) -> list[str]:
    errors: list[str] = []

    if headers.enforced is not True:
        errors.append(
            "Protected /matrix response must advertise "
            "x-cityroute-timeout-enforced=true"
        )

    if headers.category != "matrix":
        errors.append(
            "Protected /matrix response must advertise timeout "
            "category 'matrix'"
        )

    if headers.limit_s is None or headers.limit_s <= 0:
        errors.append(
            "Protected /matrix response must advertise a positive "
            "timeout limit"
        )

    if outcome == "completed":
        if (
            not isinstance(response_summary, dict)
            or response_summary.get("status") != "ok"
        ):
            errors.append(
                "HTTP 200 matrix response must report status='ok'"
            )

        return errors

    if outcome == "server_timeout":
        if not _timeout_body_matches(response_summary):
            errors.append(
                "HTTP 504 response body does not identify timeout or "
                "deadline enforcement"
            )

        if headers.limit_s is not None:
            elapsed_s = elapsed_ms / 1000.0
            minimum_elapsed_s = (
                headers.limit_s
                * timeout_lower_bound_ratio
            )
            maximum_elapsed_s = (
                headers.limit_s
                + timeout_upper_grace_s
            )

            if elapsed_s < minimum_elapsed_s:
                errors.append(
                    "HTTP 504 returned much earlier than the advertised "
                    "timeout limit"
                )

            if elapsed_s > maximum_elapsed_s:
                errors.append(
                    "HTTP 504 returned too far beyond the advertised "
                    "timeout limit"
                )

        return errors

    if outcome == "client_error":
        errors.append(
            "The HTTP client timed out or failed before CityRoute "
            "returned a server response"
        )
    else:
        errors.append(
            "Protected /matrix request returned an unexpected status"
        )

    return errors


async def _execute_matrix_attempt(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    stage: str,
    attempt_index: int,
    algorithm: str,
    matrix_size: int,
    use_cache: bool,
    payload_template: dict[str, Any] | None,
    timeout_lower_bound_ratio: float,
    timeout_upper_grace_s: float,
    safe_variant: int,
) -> TimeoutAttemptResult:
    payload = _build_matrix_payload(
        matrix_size=matrix_size,
        algorithm=algorithm,
        use_cache=use_cache,
        safe_variant=safe_variant,
        payload_template=payload_template,
    )

    started_at_utc = utc_now_iso()
    started = time.perf_counter()

    status_code: int | None = None
    response_summary: Any | None = None
    headers = TimeoutPolicyHeaders(
        enforced=None,
        category=None,
        limit_s=None,
        raw={},
    )
    error_type: str | None = None
    error_message: str | None = None

    try:
        response = await client.post(
            f"{base_url}/matrix",
            json=payload,
        )
        status_code = response.status_code
        headers = _timeout_headers(response)

        try:
            response_json: Any | None = response.json()
        except ValueError:
            response_json = None

        response_summary = _summarize_response(
            status_code=response.status_code,
            response_json=response_json,
            response_text=response.text,
        )
    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    elapsed_ms = (
        time.perf_counter() - started
    ) * 1000.0
    outcome = _classify_outcome(status_code)

    validation_errors = _validate_attempt(
        outcome=outcome,
        elapsed_ms=elapsed_ms,
        headers=headers,
        response_summary=response_summary,
        timeout_lower_bound_ratio=(
            timeout_lower_bound_ratio
        ),
        timeout_upper_grace_s=timeout_upper_grace_s,
    )

    return TimeoutAttemptResult(
        stage=stage,
        attempt_index=attempt_index,
        algorithm=algorithm,
        matrix_size=matrix_size,
        status_code=status_code,
        outcome=outcome,
        elapsed_ms=elapsed_ms,
        timeout_headers=headers,
        response_summary=response_summary,
        validation_errors=tuple(validation_errors),
        error_type=error_type,
        error_message=error_message,
        started_at_utc=started_at_utc,
        finished_at_utc=utc_now_iso(),
    )


async def _control_probe(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    stage: str,
    path: str,
) -> ControlProbeResult:
    started_at_utc = utc_now_iso()
    started = time.perf_counter()

    status_code: int | None = None
    response_summary: Any | None = None
    headers = TimeoutPolicyHeaders(
        enforced=None,
        category=None,
        limit_s=None,
        raw={},
    )
    error_type: str | None = None
    error_message: str | None = None

    try:
        response = await client.get(f"{base_url}{path}")
        status_code = response.status_code
        headers = _timeout_headers(response)

        if path == "/metrics":
            response_summary = {
                "content_type": response.headers.get(
                    "content-type"
                ),
                "body_size_bytes": len(response.content),
            }
        else:
            try:
                response_summary = response.json()
            except ValueError:
                response_summary = {
                    "body_preview": response.text[:1000],
                }
    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    ok = status_code == 200

    if path == "/health/live":
        ok = (
            ok
            and isinstance(response_summary, dict)
            and response_summary.get("status") == "alive"
        )

    if path == "/health/ready":
        ok = (
            ok
            and isinstance(response_summary, dict)
            and response_summary.get("ready") is True
            and response_summary.get(
                "accepting_requests"
            )
            is True
            and response_summary.get("shutting_down") is False
        )

    return ControlProbeResult(
        stage=stage,
        path=path,
        status_code=status_code,
        elapsed_ms=(
            time.perf_counter() - started
        )
        * 1000.0,
        ok=ok,
        timeout_headers=headers,
        response_summary=response_summary,
        error_type=error_type,
        error_message=error_message,
        started_at_utc=started_at_utc,
        finished_at_utc=utc_now_iso(),
    )


async def _collect_controls(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    stage: str,
) -> list[ControlProbeResult]:
    return [
        await _control_probe(
            client=client,
            base_url=base_url,
            stage=stage,
            path=path,
        )
        for path in CONTROL_ENDPOINTS
    ]


def _latency_summary(
    values: list[float],
) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "min_ms": None,
            "max_ms": None,
            "mean_ms": None,
            "median_ms": None,
            "p90_ms": None,
            "p95_ms": None,
            "p99_ms": None,
        }

    return {
        "count": len(values),
        "min_ms": min(values),
        "max_ms": max(values),
        "mean_ms": statistics.fmean(values),
        "median_ms": statistics.median(values),
        "p90_ms": percentile(values, 90.0),
        "p95_ms": percentile(values, 95.0),
        "p99_ms": percentile(values, 99.0),
    }


def _timeout_limit_from_attempts(
    attempts: list[TimeoutAttemptResult],
) -> float | None:
    limits = [
        attempt.timeout_headers.limit_s
        for attempt in attempts
        if attempt.timeout_headers.limit_s is not None
    ]

    if not limits:
        return None

    counts = Counter(limits)
    return counts.most_common(1)[0][0]


def _timeout_metric_snapshot(
    metrics_text: str,
) -> dict[str, float]:
    values: dict[str, float] = {}

    for raw_line in metrics_text.splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        sample_name, separator, raw_value = line.rpartition(" ")

        if not separator:
            continue

        metric_name = sample_name.split("{", 1)[0]

        if "timeout" not in metric_name.lower():
            continue

        try:
            value = float(raw_value)
        except ValueError:
            continue

        values[metric_name] = (
            values.get(metric_name, 0.0) + value
        )

    return dict(sorted(values.items()))


async def _fetch_timeout_metrics(
    client: httpx.AsyncClient,
    *,
    base_url: str,
) -> dict[str, Any]:
    try:
        response = await client.get(f"{base_url}/metrics")
    except Exception as exc:
        return {
            "status_code": None,
            "timeout_metrics": {},
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }

    return {
        "status_code": response.status_code,
        "timeout_metrics": _timeout_metric_snapshot(
            response.text
        ),
        "error_type": None,
        "error_message": None,
    }


def _metric_deltas(
    before: dict[str, float],
    after: dict[str, float],
) -> dict[str, float | None]:
    metric_names = sorted(set(before) | set(after))

    return {
        metric_name: (
            None
            if metric_name not in before
            or metric_name not in after
            else after[metric_name] - before[metric_name]
        )
        for metric_name in metric_names
    }


def _validate_global_evidence(
    *,
    baseline_attempts: list[TimeoutAttemptResult],
    trigger_attempts: list[TimeoutAttemptResult],
    controls_before: list[ControlProbeResult],
    controls_after: list[ControlProbeResult],
    recovery_attempt: TimeoutAttemptResult,
    require_timeout: bool,
    configured_client_timeout_s: float,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    all_attempts = [
        *baseline_attempts,
        *trigger_attempts,
        recovery_attempt,
    ]

    for attempt in all_attempts:
        errors.extend(attempt.validation_errors)

    if any(
        attempt.outcome != "completed"
        for attempt in baseline_attempts
    ):
        errors.append(
            "One or more normal baseline matrix requests did not "
            "complete successfully"
        )

    if recovery_attempt.outcome != "completed":
        errors.append(
            "Post-timeout recovery matrix request did not complete"
        )

    if any(not probe.ok for probe in controls_before):
        errors.append(
            "One or more control endpoints failed before timeout "
            "attempts"
        )

    if any(not probe.ok for probe in controls_after):
        errors.append(
            "One or more control endpoints failed after timeout "
            "attempts"
        )

    timeout_count = sum(
        attempt.outcome == "server_timeout"
        for attempt in trigger_attempts
    )

    unexpected_trigger_count = sum(
        attempt.outcome
        not in {"completed", "server_timeout"}
        for attempt in trigger_attempts
    )

    if unexpected_trigger_count:
        errors.append(
            "One or more trigger attempts returned an unexpected "
            "response or client error"
        )

    if require_timeout and timeout_count == 0:
        errors.append(
            "No server-side HTTP 504 timeout was observed even though "
            "--require-timeout was enabled"
        )

    if trigger_attempts and timeout_count == 0:
        warnings.append(
            "No HTTP 504 timeout was observed. Timeout policy headers "
            "were proven, but the selected real workload completed "
            "within the configured server limit on this machine."
        )

    timeout_limit_s = _timeout_limit_from_attempts(
        all_attempts
    )

    if (
        timeout_limit_s is not None
        and configured_client_timeout_s
        <= timeout_limit_s
    ):
        errors.append(
            "The HTTP client timeout must exceed the advertised "
            "CityRoute server timeout"
        )

    return errors, warnings


async def async_main(args: argparse.Namespace) -> int:
    base_url = args.base_url.rstrip("/")
    started_at_utc = utc_now_iso()

    startup_liveness = await asyncio.to_thread(
        wait_for_liveness,
        base_url=base_url,
        startup_timeout_s=args.startup_timeout_s,
    )
    startup_readiness = await asyncio.to_thread(
        wait_for_readiness,
        base_url=base_url,
        startup_timeout_s=args.startup_timeout_s,
        allow_degraded=True,
    )

    payload_template = (
        _load_payload_file(args.payload_file)
        if args.payload_file is not None
        else None
    )

    async with httpx.AsyncClient(
        timeout=args.timeout_s,
        limits=httpx.Limits(
            max_connections=20,
            max_keepalive_connections=20,
        ),
    ) as client:
        controls_before = await _collect_controls(
            client=client,
            base_url=base_url,
            stage="before",
        )

        metrics_before = await _fetch_timeout_metrics(
            client,
            base_url=base_url,
        )

        baseline_attempts: list[TimeoutAttemptResult] = []

        for attempt_index in range(args.baseline_attempts):
            baseline_attempts.append(
                await _execute_matrix_attempt(
                    client=client,
                    base_url=base_url,
                    stage="baseline",
                    attempt_index=attempt_index,
                    algorithm=args.baseline_algorithm,
                    matrix_size=args.baseline_matrix_size,
                    use_cache=args.use_cache,
                    payload_template=payload_template,
                    timeout_lower_bound_ratio=(
                        args.timeout_lower_bound_ratio
                    ),
                    timeout_upper_grace_s=(
                        args.timeout_upper_grace_s
                    ),
                    safe_variant=attempt_index,
                )
            )

        discovered_timeout_limit_s = (
            _timeout_limit_from_attempts(
                baseline_attempts
            )
        )

        if (
            discovered_timeout_limit_s is not None
            and args.timeout_s
            <= discovered_timeout_limit_s
        ):
            raise ValueError(
                "--timeout-s must exceed the CityRoute timeout limit "
                f"of {discovered_timeout_limit_s}s"
            )

        trigger_attempts: list[TimeoutAttemptResult] = []

        for attempt_index in range(args.trigger_attempts):
            trigger_attempts.append(
                await _execute_matrix_attempt(
                    client=client,
                    base_url=base_url,
                    stage="trigger",
                    attempt_index=attempt_index,
                    algorithm=args.trigger_algorithm,
                    matrix_size=args.trigger_matrix_size,
                    use_cache=args.use_cache,
                    payload_template=payload_template,
                    timeout_lower_bound_ratio=(
                        args.timeout_lower_bound_ratio
                    ),
                    timeout_upper_grace_s=(
                        args.timeout_upper_grace_s
                    ),
                    safe_variant=(
                        args.baseline_attempts
                        + attempt_index
                        + 10
                    ),
                )
            )

        controls_after = await _collect_controls(
            client=client,
            base_url=base_url,
            stage="after",
        )

        recovery_attempt = await _execute_matrix_attempt(
            client=client,
            base_url=base_url,
            stage="recovery",
            attempt_index=0,
            algorithm="source_dijkstra",
            matrix_size=DEFAULT_RECOVERY_MATRIX_SIZE,
            use_cache=False,
            payload_template=payload_template,
            timeout_lower_bound_ratio=(
                args.timeout_lower_bound_ratio
            ),
            timeout_upper_grace_s=(
                args.timeout_upper_grace_s
            ),
            safe_variant=7,
        )

        metrics_after = await _fetch_timeout_metrics(
            client,
            base_url=base_url,
        )

    validation_errors, warnings = _validate_global_evidence(
        baseline_attempts=baseline_attempts,
        trigger_attempts=trigger_attempts,
        controls_before=controls_before,
        controls_after=controls_after,
        recovery_attempt=recovery_attempt,
        require_timeout=args.require_timeout,
        configured_client_timeout_s=args.timeout_s,
    )

    baseline_completed = [
        attempt
        for attempt in baseline_attempts
        if attempt.outcome == "completed"
    ]
    trigger_completed = [
        attempt
        for attempt in trigger_attempts
        if attempt.outcome == "completed"
    ]
    trigger_timeouts = [
        attempt
        for attempt in trigger_attempts
        if attempt.outcome == "server_timeout"
    ]

    timeout_limit_s = _timeout_limit_from_attempts(
        [
            *baseline_attempts,
            *trigger_attempts,
            recovery_attempt,
        ]
    )

    baseline_latency = _latency_summary(
        [
            attempt.elapsed_ms
            for attempt in baseline_completed
        ]
    )
    trigger_completed_latency = _latency_summary(
        [
            attempt.elapsed_ms
            for attempt in trigger_completed
        ]
    )
    timeout_latency = _latency_summary(
        [
            attempt.elapsed_ms
            for attempt in trigger_timeouts
        ]
    )

    baseline_p99_ms = baseline_latency.get("p99_ms")

    timeout_headroom_ratio = (
        None
        if timeout_limit_s is None
        or not isinstance(baseline_p99_ms, int | float)
        or baseline_p99_ms <= 0
        else (
            timeout_limit_s
            / (baseline_p99_ms / 1000.0)
        )
    )
    timeout_budget_used_pct = (
        None
        if timeout_limit_s is None
        or not isinstance(baseline_p99_ms, int | float)
        or timeout_limit_s <= 0
        else (
            (baseline_p99_ms / 1000.0)
            / timeout_limit_s
            * 100.0
        )
    )

    before_timeout_metrics = metrics_before.get(
        "timeout_metrics",
        {},
    )
    after_timeout_metrics = metrics_after.get(
        "timeout_metrics",
        {},
    )
    timeout_metric_deltas = _metric_deltas(
        before_timeout_metrics,
        after_timeout_metrics,
    )

    overall_ok = not validation_errors
    timestamp = timestamp_slug()

    raw_path = build_result_path(
        "phase11_timeout_probe_raw",
        results_dir=args.results_dir,
        target=args.target,
        timestamp=timestamp,
    )
    summary_path = build_result_path(
        "phase11_timeout_probe_summary",
        results_dir=args.results_dir,
        target=args.target,
        timestamp=timestamp,
    )

    raw_payload: dict[str, Any] = {
        "phase_code": PROJECT_PHASE_CODE,
        "phase_name": PROJECT_PHASE_NAME,
        "benchmark": "phase11_timeout_probe",
        "started_at_utc": started_at_utc,
        "finished_at_utc": utc_now_iso(),
        "base_url": base_url,
        "target": args.target,
        "results_dir_override": (
            None
            if args.results_dir is None
            else str(args.results_dir)
        ),
        "configuration": {
            "baseline_algorithm": args.baseline_algorithm,
            "baseline_matrix_size": (
                args.baseline_matrix_size
            ),
            "baseline_attempts": args.baseline_attempts,
            "trigger_algorithm": args.trigger_algorithm,
            "trigger_matrix_size": args.trigger_matrix_size,
            "trigger_attempts": args.trigger_attempts,
            "require_timeout": args.require_timeout,
            "use_cache": args.use_cache,
            "client_timeout_s": args.timeout_s,
            "startup_timeout_s": args.startup_timeout_s,
            "timeout_lower_bound_ratio": (
                args.timeout_lower_bound_ratio
            ),
            "timeout_upper_grace_s": (
                args.timeout_upper_grace_s
            ),
        },
        "runtime_metadata": asdict(
            collect_runtime_metadata(base_url=base_url)
        ),
        "startup_probes": {
            "liveness": asdict(startup_liveness),
            "readiness": asdict(startup_readiness),
        },
        "controls_before": [
            asdict(probe)
            for probe in controls_before
        ],
        "controls_after": [
            asdict(probe)
            for probe in controls_after
        ],
        "metrics_before": metrics_before,
        "metrics_after": metrics_after,
        "timeout_metric_deltas": timeout_metric_deltas,
        "baseline_attempts": [
            asdict(attempt)
            for attempt in baseline_attempts
        ],
        "trigger_attempts": [
            asdict(attempt)
            for attempt in trigger_attempts
        ],
        "recovery_attempt": asdict(recovery_attempt),
        "timeout_limit_s": timeout_limit_s,
        "baseline_latency": baseline_latency,
        "trigger_completed_latency": (
            trigger_completed_latency
        ),
        "server_timeout_latency": timeout_latency,
        "timeout_headroom_ratio": timeout_headroom_ratio,
        "timeout_budget_used_pct": timeout_budget_used_pct,
        "outcome_counts": dict(
            sorted(
                Counter(
                    attempt.outcome
                    for attempt in [
                        *baseline_attempts,
                        *trigger_attempts,
                        recovery_attempt,
                    ]
                ).items()
            )
        ),
        "validation_errors": validation_errors,
        "warnings": warnings,
        "overall_ok": overall_ok,
    }

    summary_payload: dict[str, Any] = {
        "phase_code": PROJECT_PHASE_CODE,
        "phase_name": PROJECT_PHASE_NAME,
        "benchmark": "phase11_timeout_probe",
        "base_url": base_url,
        "target": args.target,
        "overall_ok": overall_ok,
        "timeout_limit_s": timeout_limit_s,
        "client_timeout_s": args.timeout_s,
        "baseline_algorithm": args.baseline_algorithm,
        "baseline_matrix_size": (
            args.baseline_matrix_size
        ),
        "baseline_attempt_count": len(baseline_attempts),
        "baseline_completed_count": len(
            baseline_completed
        ),
        "baseline_latency": baseline_latency,
        "timeout_headroom_ratio": timeout_headroom_ratio,
        "timeout_budget_used_pct": timeout_budget_used_pct,
        "trigger_algorithm": args.trigger_algorithm,
        "trigger_matrix_size": args.trigger_matrix_size,
        "trigger_attempt_count": len(trigger_attempts),
        "trigger_completed_count": len(
            trigger_completed
        ),
        "server_timeout_count": len(trigger_timeouts),
        "trigger_completed_latency": (
            trigger_completed_latency
        ),
        "server_timeout_latency": timeout_latency,
        "controls_before_ok": all(
            probe.ok
            for probe in controls_before
        ),
        "controls_after_ok": all(
            probe.ok
            for probe in controls_after
        ),
        "recovery_ok": (
            recovery_attempt.outcome == "completed"
        ),
        "timeout_metric_deltas": timeout_metric_deltas,
        "validation_errors": validation_errors,
        "warnings": warnings,
        "raw_result_path": str(raw_path),
        "summary_result_path": str(summary_path),
    }

    write_json(raw_path, raw_payload)
    write_json(summary_path, summary_payload)
    print_json(summary_payload)

    if args.fail_on_validation_error and validation_errors:
        return 1

    return 0 if overall_ok else 1


def main() -> int:
    args = parse_args()
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print(
            "Phase 11 timeout probe interrupted",
            file=sys.stderr,
        )
        raise SystemExit(130) from None