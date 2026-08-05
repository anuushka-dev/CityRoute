# benchmarks/phase_11/phase11_common.py

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import socket
import statistics
import subprocess
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


PROJECT_PHASE_CODE = "tier4_phase11"
PROJECT_PHASE_NAME = (
    "Tier 4 Phase 11 - Production Reliability and Concurrency Hardening"
)

DEFAULT_BASE_URL = os.getenv(
    "CITYROUTE_BENCHMARK_BASE_URL",
    "http://127.0.0.1:8001",
).rstrip("/")
DEFAULT_TIMEOUT_S = float(os.getenv("CITYROUTE_BENCHMARK_TIMEOUT_S", "30"))
DEFAULT_STARTUP_TIMEOUT_S = float(
    os.getenv("CITYROUTE_BENCHMARK_STARTUP_TIMEOUT_S", "180")
)
DEFAULT_POLL_INTERVAL_S = float(
    os.getenv("CITYROUTE_BENCHMARK_POLL_INTERVAL_S", "1")
)
PHASE11_ROOT = Path("benchmarks") / "phase_11"
DOCKER_RESULTS_DIR = PHASE11_ROOT / "docker_results"
LOCAL_RESULTS_DIR = PHASE11_ROOT / "local_results"

RESULTS_DIRS: dict[str, Path] = {
    "docker": DOCKER_RESULTS_DIR,
    "local": LOCAL_RESULTS_DIR,
}

DEFAULT_RESULT_TARGET = os.getenv(
    "CITYROUTE_BENCHMARK_RESULT_TARGET",
    "docker",
).strip().lower()

if DEFAULT_RESULT_TARGET not in RESULTS_DIRS:
    raise ValueError(
        "CITYROUTE_BENCHMARK_RESULT_TARGET must be "
        "'docker' or 'local'"
    )

DEFAULT_RESULTS_DIR = RESULTS_DIRS[DEFAULT_RESULT_TARGET]


@dataclass(frozen=True)
class HttpProbeResult:
    method: str
    path: str
    url: str
    status_code: int | None
    elapsed_ms: float
    ok: bool
    expected_status_codes: tuple[int, ...]
    response_json: Any | None
    response_text: str | None
    error_type: str | None
    error_message: str | None
    started_at_utc: str
    finished_at_utc: str


@dataclass(frozen=True)
class LatencySummary:
    count: int
    success_count: int
    failure_count: int
    success_rate: float
    min_ms: float | None
    max_ms: float | None
    mean_ms: float | None
    median_ms: float | None
    p90_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    stdev_ms: float | None


@dataclass(frozen=True)
class RuntimeMetadata:
    phase_code: str
    phase_name: str
    captured_at_utc: str
    python_version: str
    python_executable: str
    platform: str
    machine: str
    processor: str
    hostname: str
    pid: int
    cwd: str
    base_url: str
    git_commit: str | None
    git_branch: str | None
    git_dirty: bool | None


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def timestamp_slug() -> str:
    return utc_now().strftime("%Y%m%d_%H%M%S")


def resolve_results_dir(
    *,
    target: str | None = None,
    results_dir: str | Path | None = None,
) -> Path:
    """
    Resolve the Phase 11 output directory.

    Explicit ``results_dir`` takes priority. Otherwise ``target`` must be
    ``"docker"`` or ``"local"``. When neither is provided, the value from
    ``CITYROUTE_BENCHMARK_RESULT_TARGET`` is used.
    """

    if results_dir is not None:
        return Path(results_dir)

    resolved_target = (
        DEFAULT_RESULT_TARGET
        if target is None
        else target.strip().lower()
    )

    try:
        return RESULTS_DIRS[resolved_target]
    except KeyError as exc:
        raise ValueError(
            "target must be 'docker' or 'local'"
        ) from exc


def ensure_results_dir(
    results_dir: str | Path | None = None,
    *,
    target: str | None = None,
) -> Path:
    path = resolve_results_dir(
        target=target,
        results_dir=results_dir,
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_phase11_result_dirs() -> dict[str, Path]:
    """Create and return both standard Phase 11 result directories."""

    return {
        name: ensure_results_dir(path)
        for name, path in RESULTS_DIRS.items()
    }


def build_result_path(
    stem: str,
    *,
    suffix: str = ".json",
    results_dir: str | Path | None = None,
    target: str | None = None,
    timestamp: str | None = None,
) -> Path:
    clean_stem = stem.strip().replace(" ", "_")
    if not clean_stem:
        raise ValueError("stem must not be empty")

    normalized_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    resolved_timestamp = timestamp or timestamp_slug()
    return ensure_results_dir(
        results_dir,
        target=target,
    ) / (
        f"{clean_stem}_{resolved_timestamp}{normalized_suffix}"
    )


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    raise TypeError(
        f"Object of type {type(value).__name__} is not JSON serializable"
    )


def write_json(
    path: str | Path,
    payload: Any,
    *,
    indent: int = 2,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            payload,
            indent=indent,
            sort_keys=True,
            ensure_ascii=False,
            default=_json_default,
        )
        + "\n",
        encoding="utf-8",
    )
    return destination


def write_text(path: str | Path, text: str) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")
    return destination


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256_file(
    path: str | Path,
    *,
    chunk_size: int = 1024 * 1024,
) -> str:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def percentile(values: Sequence[float], percentile_value: float) -> float:
    if not values:
        raise ValueError("values must not be empty")
    if not 0.0 <= percentile_value <= 100.0:
        raise ValueError("percentile_value must be between 0 and 100")

    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]

    rank = (len(ordered) - 1) * (percentile_value / 100.0)
    lower_index = math.floor(rank)
    upper_index = math.ceil(rank)
    if lower_index == upper_index:
        return ordered[lower_index]

    lower_value = ordered[lower_index]
    upper_value = ordered[upper_index]
    fraction = rank - lower_index
    return lower_value + ((upper_value - lower_value) * fraction)


def summarize_latencies(
    probes: Sequence[HttpProbeResult],
) -> LatencySummary:
    successful_latencies = [probe.elapsed_ms for probe in probes if probe.ok]
    total_count = len(probes)
    success_count = len(successful_latencies)
    failure_count = total_count - success_count

    if not successful_latencies:
        return LatencySummary(
            count=total_count,
            success_count=0,
            failure_count=failure_count,
            success_rate=0.0 if total_count else 1.0,
            min_ms=None,
            max_ms=None,
            mean_ms=None,
            median_ms=None,
            p90_ms=None,
            p95_ms=None,
            p99_ms=None,
            stdev_ms=None,
        )

    return LatencySummary(
        count=total_count,
        success_count=success_count,
        failure_count=failure_count,
        success_rate=success_count / total_count if total_count else 1.0,
        min_ms=min(successful_latencies),
        max_ms=max(successful_latencies),
        mean_ms=statistics.fmean(successful_latencies),
        median_ms=statistics.median(successful_latencies),
        p90_ms=percentile(successful_latencies, 90.0),
        p95_ms=percentile(successful_latencies, 95.0),
        p99_ms=percentile(successful_latencies, 99.0),
        stdev_ms=(
            statistics.pstdev(successful_latencies)
            if len(successful_latencies) > 1
            else 0.0
        ),
    )


def request_probe(
    *,
    method: str,
    path: str,
    base_url: str = DEFAULT_BASE_URL,
    expected_status_codes: Iterable[int] = (200,),
    json_body: Any | None = None,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    client: httpx.Client | None = None,
) -> HttpProbeResult:
    normalized_method = method.upper().strip()
    if not normalized_method:
        raise ValueError("method must not be empty")

    normalized_path = path if path.startswith("/") else f"/{path}"
    url = f"{base_url.rstrip('/')}{normalized_path}"
    expected = tuple(sorted({int(code) for code in expected_status_codes}))
    if not expected:
        raise ValueError("expected_status_codes must not be empty")

    started_at = utc_now()
    started = time.perf_counter()
    owns_client = client is None
    resolved_client = client or httpx.Client(timeout=timeout_s)

    status_code: int | None = None
    response_json: Any | None = None
    response_text: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    ok = False

    try:
        response = resolved_client.request(
            normalized_method,
            url,
            json=json_body,
            params=params,
            headers=headers,
            timeout=timeout_s,
        )
        status_code = response.status_code
        response_text = response.text
        try:
            response_json = response.json()
        except ValueError:
            response_json = None
        ok = status_code in expected
    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        finished_at = utc_now()
        if owns_client:
            resolved_client.close()

    return HttpProbeResult(
        method=normalized_method,
        path=normalized_path,
        url=url,
        status_code=status_code,
        elapsed_ms=elapsed_ms,
        ok=ok,
        expected_status_codes=expected,
        response_json=response_json,
        response_text=response_text,
        error_type=error_type,
        error_message=error_message,
        started_at_utc=started_at.isoformat(),
        finished_at_utc=finished_at.isoformat(),
    )


def wait_for_liveness(
    *,
    base_url: str = DEFAULT_BASE_URL,
    startup_timeout_s: float = DEFAULT_STARTUP_TIMEOUT_S,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
) -> HttpProbeResult:
    return _wait_for_health_state(
        path="/health/live",
        base_url=base_url,
        startup_timeout_s=startup_timeout_s,
        poll_interval_s=poll_interval_s,
        accepted_statuses={"alive"},
        require_ready=False,
    )


def wait_for_readiness(
    *,
    base_url: str = DEFAULT_BASE_URL,
    startup_timeout_s: float = DEFAULT_STARTUP_TIMEOUT_S,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    allow_degraded: bool = True,
) -> HttpProbeResult:
    accepted_statuses = {"ready"}
    if allow_degraded:
        accepted_statuses.add("degraded")

    return _wait_for_health_state(
        path="/health/ready",
        base_url=base_url,
        startup_timeout_s=startup_timeout_s,
        poll_interval_s=poll_interval_s,
        accepted_statuses=accepted_statuses,
        require_ready=True,
    )


def _wait_for_health_state(
    *,
    path: str,
    base_url: str,
    startup_timeout_s: float,
    poll_interval_s: float,
    accepted_statuses: set[str],
    require_ready: bool,
) -> HttpProbeResult:
    if startup_timeout_s <= 0:
        raise ValueError("startup_timeout_s must be greater than zero")
    if poll_interval_s <= 0:
        raise ValueError("poll_interval_s must be greater than zero")

    deadline = time.monotonic() + startup_timeout_s
    last_probe: HttpProbeResult | None = None

    while time.monotonic() < deadline:
        last_probe = request_probe(
            method="GET",
            path=path,
            base_url=base_url,
            expected_status_codes=(200,),
            timeout_s=min(DEFAULT_TIMEOUT_S, 10.0),
        )
        payload = last_probe.response_json
        accepted = (
            last_probe.ok
            and isinstance(payload, dict)
            and payload.get("status") in accepted_statuses
        )
        if require_ready:
            accepted = accepted and payload.get("ready") is True
        if accepted:
            return last_probe
        time.sleep(poll_interval_s)

    raise TimeoutError(
        f"CityRoute did not reach an accepted state for {path}. "
        f"Last probe: {asdict(last_probe) if last_probe else None}"
    )


def extract_prometheus_sample(
    metrics_text: str,
    metric_name: str,
    *,
    required_labels: Mapping[str, str] | None = None,
) -> float | None:
    labels = dict(required_labels or {})

    for raw_line in metrics_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or not line.startswith(metric_name):
            continue

        sample_part, separator, value_part = line.rpartition(" ")
        if not separator:
            continue

        if labels:
            if "{" not in sample_part or "}" not in sample_part:
                continue
            label_text = sample_part.split("{", 1)[1].rsplit("}", 1)[0]
            parsed_labels: dict[str, str] = {}
            for item in label_text.split(","):
                key, equals, raw_value = item.partition("=")
                if equals:
                    parsed_labels[key.strip()] = raw_value.strip().strip('"')
            if any(
                parsed_labels.get(key) != value
                for key, value in labels.items()
            ):
                continue

        try:
            return float(value_part)
        except ValueError:
            continue

    return None


def _run_git_command(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return None

    output = result.stdout.strip()
    return output or None


def collect_runtime_metadata(
    *,
    base_url: str = DEFAULT_BASE_URL,
) -> RuntimeMetadata:
    dirty_output = _run_git_command("status", "--porcelain")
    return RuntimeMetadata(
        phase_code=PROJECT_PHASE_CODE,
        phase_name=PROJECT_PHASE_NAME,
        captured_at_utc=utc_now_iso(),
        python_version=sys.version,
        python_executable=sys.executable,
        platform=platform.platform(),
        machine=platform.machine(),
        processor=platform.processor(),
        hostname=socket.gethostname(),
        pid=os.getpid(),
        cwd=str(Path.cwd()),
        base_url=base_url,
        git_commit=_run_git_command("rev-parse", "HEAD"),
        git_branch=_run_git_command("rev-parse", "--abbrev-ref", "HEAD"),
        git_dirty=None if dirty_output is None else bool(dirty_output),
    )


def build_evidence_manifest(
    files: Iterable[str | Path],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []

    for raw_path in sorted({Path(path) for path in files}, key=str):
        if not raw_path.exists():
            entries.append({"path": str(raw_path), "exists": False})
            continue

        entries.append(
            {
                "path": str(raw_path),
                "exists": True,
                "size_bytes": raw_path.stat().st_size,
                "sha256": sha256_file(raw_path),
            }
        )

    return {
        "phase_code": PROJECT_PHASE_CODE,
        "phase_name": PROJECT_PHASE_NAME,
        "generated_at_utc": utc_now_iso(),
        "metadata": dict(metadata or {}),
        "files": entries,
    }


def assert_probe_success(
    probe: HttpProbeResult,
    *,
    context: str | None = None,
) -> None:
    if probe.ok:
        return

    prefix = f"{context}: " if context else ""
    raise AssertionError(
        f"{prefix}HTTP probe failed | method={probe.method} | "
        f"path={probe.path} | status={probe.status_code} | "
        f"expected={probe.expected_status_codes} | "
        f"error={probe.error_type}: {probe.error_message} | "
        f"response={probe.response_text!r}"
    )


def probes_to_dicts(
    probes: Sequence[HttpProbeResult],
) -> list[dict[str, Any]]:
    return [asdict(probe) for probe in probes]


def print_json(payload: Any) -> None:
    print(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            default=_json_default,
        )
    )