from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path.cwd()
PHASE11 = ROOT / "benchmarks" / "phase_11"
SUMMARY = PHASE11 / "Summary"
PHASE12 = ROOT / ".phase12_evidence"

FIELDS = [
    "claim_id",
    "phase",
    "claim_text",
    "source_audit",
    "artifact_path",
    "json_pointer",
    "operator",
    "expected_value",
    "tolerance",
    "provenance_source_artifact",
    "notes",
]


def latest_collection() -> Path:
    collections = sorted(
        PHASE12.glob("collection_*"),
        key=lambda p: p.name,
        reverse=True,
    )
    if not collections:
        raise FileNotFoundError(
            "No Phase 12 evidence collection found."
        )
    return collections[0]


def summary(name: str) -> str:
    path = SUMMARY / name
    if not path.exists():
        raise FileNotFoundError(f"Missing Phase 11 summary: {path}")
    return path.relative_to(ROOT).as_posix()


def claim(
    claim_id: str,
    text: str,
    artifact: str,
    pointer: str,
    operator: str,
    expected: str,
    notes: str = "",
    tolerance: str = "",
) -> dict[str, str]:
    return {
        "claim_id": claim_id,
        "phase": "phase_11",
        "claim_text": text,
        "source_audit": (
            "CityRoute Tier 4 Phase 11 - "
            "Production Reliability and Concurrency Hardening"
        ),
        "artifact_path": artifact,
        "json_pointer": pointer,
        "operator": operator,
        "expected_value": expected,
        "tolerance": tolerance,
        "provenance_source_artifact": "",
        "notes": notes,
    }


def build_claims() -> list[dict[str, str]]:
    concurrency = summary(
        "phase11_concurrency_limit_probe_summary_20260821_175126.json"
    )
    corrupted = summary(
        "phase11_corrupted_cache_probe_summary_20260821_175257.json"
    )
    failure = summary(
        "phase11_failure_injection_probe_summary_20260821_175441.json"
    )
    graceful = summary(
        "phase11_graceful_shutdown_probe_summary_20260821_180104.json"
    )
    health = summary(
        "phase11_health_state_probe_summary_20260821_175104.json"
    )
    multiworker = summary(
        "phase11_multiworker_probe_summary_20260821_175603.json"
    )
    overload = summary(
        "phase11_overload_probe_summary_20260821_175142.json"
    )
    redis_failure = summary(
        "phase11_redis_failure_probe_summary_20260821_180952.json"
    )
    redis_recovery = summary(
        "phase11_redis_recovery_probe_summary_20260821_175246.json"
    )
    timeout = summary(
        "phase11_timeout_probe_summary_20260821_175152.json"
    )
    worker_restart = summary(
        "phase11_worker_restart_probe_summary_20260821_180920.json"
    )

    claims: list[dict[str, str]] = []

    # ============================================================
    # CONCURRENCY LIMIT
    # ============================================================

    claims += [
        claim(
            "P11-CONC-001",
            "Phase 11 concurrency-limit probe reported overall_ok=true.",
            concurrency,
            "$.overall_ok",
            "eq",
            "true",
        ),
        claim(
            "P11-CONC-002",
            "Phase 11 concurrency-limit probe respected the active limit.",
            concurrency,
            "$.active_limit_respected",
            "eq",
            "true",
        ),
        claim(
            "P11-CONC-003",
            "Phase 11 concurrency-limit probe respected the waiting limit.",
            concurrency,
            "$.waiting_limit_respected",
            "eq",
            "true",
        ),
        claim(
            "P11-CONC-004",
            "Phase 11 concurrency-limit probe observed peak active requests of 4.",
            concurrency,
            "$.peak_active_requests",
            "eq",
            "4",
        ),
        claim(
            "P11-CONC-005",
            "Phase 11 concurrency-limit probe observed peak waiting requests of 8.",
            concurrency,
            "$.peak_waiting_requests",
            "eq",
            "8",
        ),
        claim(
            "P11-CONC-006",
            "Phase 11 concurrency-limit probe observed peak total in-system requests of 12.",
            concurrency,
            "$.peak_total_in_system",
            "eq",
            "12",
        ),
        claim(
            "P11-CONC-007",
            "Phase 11 concurrency-limit probe completed 144 requests.",
            concurrency,
            "$.total_request_count",
            "eq",
            "144",
        ),
        claim(
            "P11-CONC-008",
            "Phase 11 concurrency-limit probe recorded zero liveness failures.",
            concurrency,
            "$.liveness_failure_count",
            "eq",
            "0",
        ),
        claim(
            "P11-CONC-009",
            "Phase 11 concurrency-limit probe recorded 120 controlled rejections.",
            concurrency,
            "$.outcome_counts.controlled_rejection",
            "eq",
            "120",
        ),
    ]

    # ============================================================
    # CORRUPTED CACHE
    # ============================================================

    claims += [
        claim(
            "P11-CACHE-001",
            "Phase 11 corrupted-cache probe injected a corruption condition.",
            corrupted,
            "$.corruption_injected",
            "eq",
            "true",
        ),
        claim(
            "P11-CACHE-002",
            "Phase 11 corrupted-cache probe rejected the corrupted payload.",
            corrupted,
            "$.corrupted_payload_rejected",
            "eq",
            "true",
        ),
        claim(
            "P11-CACHE-003",
            "Phase 11 corrupted-cache probe successfully recomputed the matrix.",
            corrupted,
            "$.matrix_recomputed_successfully",
            "eq",
            "true",
        ),
        claim(
            "P11-CACHE-004",
            "Phase 11 corrupted-cache probe reported a repaired cache hit.",
            corrupted,
            "$.repaired_cache_hit",
            "eq",
            "true",
        ),
        claim(
            "P11-CACHE-005",
            "Phase 11 corrupted-cache probe reported a valid repaired JSON object.",
            corrupted,
            "$.repaired_value_valid_json_object",
            "eq",
            "true",
        ),
        claim(
            "P11-CACHE-006",
            "Phase 11 corrupted-cache probe reported final health as healthy.",
            corrupted,
            "$.final_healthy",
            "eq",
            "true",
        ),
        claim(
            "P11-CACHE-007",
            "Phase 11 corrupted-cache probe did not satisfy its full acceptance result.",
            corrupted,
            "$.overall_ok",
            "eq",
            "false",
            notes=(
                "Evidence records missing corrupted-cache counter telemetry. "
                "Functional repair succeeded, but full acceptance did not."
            ),
        ),
    ]

    # ============================================================
    # FAILURE INJECTION
    # ============================================================

    claims += [
        claim(
            "P11-FAIL-001",
            "Phase 11 failure-injection probe reported overall_ok=true.",
            failure,
            "$.overall_ok",
            "eq",
            "true",
        ),
        claim(
            "P11-FAIL-002",
            "Phase 11 failure injection observed paused liveness becoming unavailable.",
            failure,
            "$.injection.paused_liveness_unavailable",
            "eq",
            "true",
        ),
        claim(
            "P11-FAIL-003",
            "Phase 11 failure injection observed paused readiness becoming unavailable.",
            failure,
            "$.injection.paused_readiness_unavailable",
            "eq",
            "true",
        ),
        claim(
            "P11-FAIL-004",
            "Phase 11 failure-injection probe recovered liveness.",
            failure,
            "$.recovery.liveness_recovered",
            "eq",
            "true",
        ),
        claim(
            "P11-FAIL-005",
            "Phase 11 failure-injection probe recovered readiness.",
            failure,
            "$.recovery.readiness_recovered",
            "eq",
            "true",
        ),
        claim(
            "P11-FAIL-006",
            "Phase 11 failure-injection probe recovered the protected request path.",
            failure,
            "$.recovery.protected_request_recovered",
            "eq",
            "true",
        ),
        claim(
            "P11-FAIL-007",
            "Phase 11 failure-injection probe recovered metrics.",
            failure,
            "$.recovery.metrics_recovered",
            "eq",
            "true",
        ),
    ]

    # ============================================================
    # GRACEFUL SHUTDOWN
    # ============================================================

    claims += [
        claim(
            "P11-SHUT-001",
            "Phase 11 graceful-shutdown probe reported overall_ok=false.",
            graceful,
            "$.overall_ok",
            "eq",
            "false",
            notes=(
                "The shutdown command and service restart worked, but the "
                "required application shutdown log evidence was absent."
            ),
        ),
        claim(
            "P11-SHUT-002",
            "Phase 11 graceful-shutdown probe confirmed the shutdown command executed.",
            graceful,
            "$.shutdown_command_ok",
            "eq",
            "true",
        ),
        claim(
            "P11-SHUT-003",
            "Phase 11 graceful-shutdown probe observed the service going down after shutdown.",
            graceful,
            "$.service_down_after_shutdown",
            "eq",
            "true",
        ),
        claim(
            "P11-SHUT-004",
            "Phase 11 graceful-shutdown probe recovered the container.",
            graceful,
            "$.recovery.container_running",
            "eq",
            "true",
        ),
        claim(
            "P11-SHUT-005",
            "Phase 11 graceful-shutdown probe reported shutdown_requested log evidence as absent.",
            graceful,
            "$.shutdown_log_evidence.shutdown_requested",
            "eq",
            "false",
        ),
        claim(
            "P11-SHUT-006",
            "Phase 11 graceful-shutdown probe reported graceful_shutdown_started log evidence as absent.",
            graceful,
            "$.shutdown_log_evidence.graceful_shutdown_started",
            "eq",
            "false",
        ),
        claim(
            "P11-SHUT-007",
            "Phase 11 graceful-shutdown probe reported drain_completed log evidence as absent.",
            graceful,
            "$.shutdown_log_evidence.drain_completed",
            "eq",
            "false",
        ),
        claim(
            "P11-SHUT-008",
            "Phase 11 graceful-shutdown probe reported graceful_shutdown_finished_complete log evidence as absent.",
            graceful,
            "$.shutdown_log_evidence.graceful_shutdown_finished_complete",
            "eq",
            "false",
        ),
        claim(
            "P11-SHUT-009",
            "Phase 11 graceful-shutdown probe reported application_shutdown_complete log evidence as absent.",
            graceful,
            "$.shutdown_log_evidence.application_shutdown_complete",
            "eq",
            "false",
        ),
    ]

    # ============================================================
    # HEALTH STATE
    # ============================================================

    claims += [
        claim(
            "P11-HEALTH-001",
            "Phase 11 health-state probe reported overall_ok=true.",
            health,
            "$.overall_ok",
            "eq",
            "true",
        ),
        claim(
            "P11-HEALTH-002",
            "Phase 11 health-state probe recorded zero failed snapshots.",
            health,
            "$.failed_snapshot_count",
            "eq",
            "0",
        ),
        claim(
            "P11-HEALTH-003",
            "Phase 11 health-state probe observed health status ok in all 30 snapshots.",
            health,
            "$.health_status_distribution.ok",
            "eq",
            "30",
        ),
        claim(
            "P11-HEALTH-004",
            "Phase 11 health-state probe observed Redis ready in all 30 snapshots.",
            health,
            "$.component_state_distributions.redis.ready",
            "eq",
            "30",
        ),
        claim(
            "P11-HEALTH-005",
            "Phase 11 health-state probe observed the graph ready in all 30 snapshots.",
            health,
            "$.component_state_distributions.graph.ready",
            "eq",
            "30",
        ),
        claim(
            "P11-HEALTH-006",
            "Phase 11 health-state probe observed the dispatch adjacency ready in all 30 snapshots.",
            health,
            "$.component_state_distributions.dispatch_adjacency.ready",
            "eq",
            "30",
        ),
        claim(
            "P11-HEALTH-007",
            "Phase 11 health-state probe observed the SNAP index ready in all 30 snapshots.",
            health,
            "$.component_state_distributions.snap_index.ready",
            "eq",
            "30",
        ),
    ]

    # ============================================================
    # MULTIWORKER
    # ============================================================

    claims += [
        claim(
            "P11-MW-001",
            "Phase 11 multiworker probe reported overall_ok=false.",
            multiworker,
            "$.overall_ok",
            "eq",
            "false",
            notes=(
                "The probe recorded controlled 429/503 failures and also "
                "failed validation because the request metric was not exposed "
                "before the benchmark."
            ),
        ),
        claim(
            "P11-MW-002",
            "Phase 11 multiworker probe configured concurrency of 32.",
            multiworker,
            "$.configuration.concurrency",
            "eq",
            "32",
        ),
        claim(
            "P11-MW-003",
            "Phase 11 multiworker probe executed 300 total requests.",
            multiworker,
            "$.aggregate.total_requests",
            "eq",
            "300",
        ),
        claim(
            "P11-MW-004",
            "Phase 11 multiworker probe recorded 238 successful requests.",
            multiworker,
            "$.aggregate.successful_requests",
            "eq",
            "238",
        ),
        claim(
            "P11-MW-005",
            "Phase 11 multiworker probe recorded 62 failed requests.",
            multiworker,
            "$.aggregate.failed_requests",
            "eq",
            "62",
        ),
        claim(
            "P11-MW-006",
            "Phase 11 multiworker probe reported route-response consistency as true.",
            multiworker,
            "$.consistency./route.consistency_ok",
            "eq",
            "true",
            notes=(
                "This pointer is intentionally retained only if the JSON "
                "pointer implementation accepts slash-containing object keys."
            ),
        ),
        claim(
            "P11-MW-007",
            "Phase 11 multiworker probe reported matrix-response consistency as true.",
            multiworker,
            "$.consistency./matrix.consistency_ok",
            "eq",
            "true",
            notes=(
                "This pointer is intentionally retained only if the JSON "
                "pointer implementation accepts slash-containing object keys."
            ),
        ),
        claim(
            "P11-MW-008",
            "Phase 11 multiworker runtime reported two workers before the probe.",
            multiworker,
            "$.worker_runtime.before.worker_count",
            "eq",
            "2",
        ),
        claim(
            "P11-MW-009",
            "Phase 11 multiworker runtime reported two workers after the probe.",
            multiworker,
            "$.worker_runtime.after.worker_count",
            "eq",
            "2",
        ),
    ]

    # ============================================================
    # OVERLOAD
    # ============================================================

    claims += [
        claim(
            "P11-OVERLOAD-001",
            "Phase 11 overload probe reported overall_ok=true.",
            overload,
            "$.overall_ok",
            "eq",
            "true",
        ),
        claim(
            "P11-OVERLOAD-002",
            "Phase 11 overload probe respected the active request limit.",
            overload,
            "$.active_limit_respected",
            "eq",
            "true",
        ),
        claim(
            "P11-OVERLOAD-003",
            "Phase 11 overload probe respected the waiting request limit.",
            overload,
            "$.waiting_limit_respected",
            "eq",
            "true",
        ),
        claim(
            "P11-OVERLOAD-004",
            "Phase 11 overload probe observed peak active requests of 4.",
            overload,
            "$.peak_active_requests",
            "eq",
            "4",
        ),
        claim(
            "P11-OVERLOAD-005",
            "Phase 11 overload probe observed peak waiting requests of 8.",
            overload,
            "$.peak_waiting_requests",
            "eq",
            "8",
        ),
        claim(
            "P11-OVERLOAD-006",
            "Phase 11 overload probe observed peak total in-system requests of 12.",
            overload,
            "$.peak_total_in_system",
            "eq",
            "12",
        ),
        claim(
            "P11-OVERLOAD-007",
            "Phase 11 overload probe recorded zero unexpected responses.",
            overload,
            "$.unexpected_response_count",
            "eq",
            "0",
        ),
        claim(
            "P11-OVERLOAD-008",
            "Phase 11 overload probe completed 72 requests.",
            overload,
            "$.total_request_count",
            "eq",
            "72",
        ),
        claim(
            "P11-OVERLOAD-009",
            "Phase 11 overload probe reported successful recovery.",
            overload,
            "$.recovery_ok",
            "eq",
            "true",
        ),
    ]

    # ============================================================
    # REAL REDIS FAILURE
    # ============================================================

    claims += [
        claim(
            "P11-REDIS-FAIL-001",
            "Phase 11 Redis-failure probe reported overall_ok=true.",
            redis_failure,
            "$.overall_ok",
            "eq",
            "true",
        ),
        claim(
            "P11-REDIS-FAIL-002",
            "Phase 11 Redis-failure probe reported Redis healthy before failure injection.",
            redis_failure,
            "$.baseline_redis_healthy",
            "eq",
            "true",
        ),
        claim(
            "P11-REDIS-FAIL-003",
            "Phase 11 Redis-failure probe reached the degraded state.",
            redis_failure,
            "$.degraded_state_reached",
            "eq",
            "true",
        ),
        claim(
            "P11-REDIS-FAIL-004",
            "Phase 11 Redis-failure probe reported fail-open cache-hit as false.",
            redis_failure,
            "$.fail_open_cache_hit",
            "eq",
            "false",
        ),
        claim(
            "P11-REDIS-FAIL-005",
            "Phase 11 Redis-failure probe returned HTTP 200 for the fail-open matrix request.",
            redis_failure,
            "$.fail_open_matrix_status_code",
            "eq",
            "200",
        ),
        claim(
            "P11-REDIS-FAIL-006",
            "Phase 11 Redis-failure probe reported the Redis failure action as successful.",
            redis_failure,
            "$.failure_action_ok",
            "eq",
            "true",
        ),
        claim(
            "P11-REDIS-FAIL-007",
            "Phase 11 Redis-failure probe reported final Redis health recovered.",
            redis_failure,
            "$.final_redis_healthy",
            "eq",
            "true",
        ),
        claim(
            "P11-REDIS-FAIL-008",
            "Phase 11 Redis-failure probe reported application health recovered.",
            redis_failure,
            "$.healthy_state_recovered",
            "eq",
            "true",
        ),
        claim(
            "P11-REDIS-FAIL-009",
            "Phase 11 Redis-failure probe reported the recovery action as successful.",
            redis_failure,
            "$.recovery_action_ok",
            "eq",
            "true",
        ),
    ]

    # ============================================================
    # REAL REDIS RECOVERY -- FUNCTIONAL PASS, TELEMETRY FAILURE
    # ============================================================

    claims += [
        claim(
            "P11-REDIS-REC-001",
            "Phase 11 Redis-recovery probe reached the degraded state.",
            redis_recovery,
            "$.degraded_state_reached",
            "eq",
            "true",
        ),
        claim(
            "P11-REDIS-REC-002",
            "Phase 11 Redis-recovery probe recovered application health.",
            redis_recovery,
            "$.healthy_state_recovered",
            "eq",
            "true",
        ),
        claim(
            "P11-REDIS-REC-003",
            "Phase 11 Redis-recovery probe returned HTTP 200 during fail-open matrix execution.",
            redis_recovery,
            "$.fail_open_matrix_status_code",
            "eq",
            "200",
        ),
        claim(
            "P11-REDIS-REC-004",
            "Phase 11 Redis-recovery probe recorded a successful Redis start action.",
            redis_recovery,
            "$.redis_start_ok",
            "eq",
            "true",
        ),
        claim(
            "P11-REDIS-REC-005",
            "Phase 11 Redis-recovery probe recorded a successful Redis stop action.",
            redis_recovery,
            "$.redis_stop_ok",
            "eq",
            "true",
        ),
        claim(
            "P11-REDIS-REC-006",
            "Phase 11 Redis-recovery probe reported a successful second cache hit after recovery.",
            redis_recovery,
            "$.recovery_second_cache_hit",
            "eq",
            "true",
        ),
        claim(
            "P11-REDIS-REC-007",
            "Phase 11 Redis-recovery probe identified the Redis 7 Alpine container.",
            redis_recovery,
            "$.resolved_redis_container.image",
            "eq",
            "redis:7-alpine",
        ),
        claim(
            "P11-REDIS-REC-008",
            "Phase 11 Redis-recovery probe reported overall_ok=false.",
            redis_recovery,
            "$.overall_ok",
            "eq",
            "false",
            notes=(
                "Functional Redis recovery was observed, but the required "
                "cityroute_redis_recoveries_total increment was not observed."
            ),
        ),
        claim(
            "P11-REDIS-REC-009",
            "Phase 11 Redis-recovery probe recorded zero Redis recovery-counter delta.",
            redis_recovery,
            "$.redis_recovery_counter_delta",
            "eq",
            "0",
            notes=(
                "This is an acceptance limitation, not evidence that Redis "
                "failed to recover functionally."
            ),
        ),
    ]

    # ============================================================
    # TIMEOUT
    # ============================================================

    claims += [
        claim(
            "P11-TIMEOUT-001",
            "Phase 11 timeout probe reported overall_ok=true.",
            timeout,
            "$.overall_ok",
            "eq",
            "true",
        ),
        claim(
            "P11-TIMEOUT-002",
            "Phase 11 timeout probe reported controls valid before the timeout test.",
            timeout,
            "$.controls_before_ok",
            "eq",
            "true",
        ),
        claim(
            "P11-TIMEOUT-003",
            "Phase 11 timeout probe reported controls valid after the timeout test.",
            timeout,
            "$.controls_after_ok",
            "eq",
            "true",
        ),
        claim(
            "P11-TIMEOUT-004",
            "Phase 11 timeout probe reported recovery_ok=true.",
            timeout,
            "$.recovery_ok",
            "eq",
            "true",
        ),
        claim(
            "P11-TIMEOUT-005",
            "Phase 11 timeout probe recorded zero server-side timeout events.",
            timeout,
            "$.server_timeout_count",
            "eq",
            "0",
            notes=(
                "The benchmark warning states that no HTTP 504 was observed "
                "because the selected workload completed inside the limit."
            ),
        ),
        claim(
            "P11-TIMEOUT-006",
            "Phase 11 timeout probe reported the configured server timeout limit as 15 seconds.",
            timeout,
            "$.timeout_limit_s",
            "eq",
            "15",
        ),
    ]

    # ============================================================
    # WORKER RESTART
    # ============================================================

    claims += [
        claim(
            "P11-RESTART-001",
            "Phase 11 worker-restart probe reported overall_ok=true.",
            worker_restart,
            "$.overall_ok",
            "eq",
            "true",
        ),
        claim(
            "P11-RESTART-002",
            "Phase 11 worker-restart probe reported the restart command succeeded.",
            worker_restart,
            "$.restart_command_ok",
            "eq",
            "true",
        ),
        claim(
            "P11-RESTART-003",
            "Phase 11 worker-restart probe observed a restart runtime-state change.",
            worker_restart,
            "$.restart_runtime_state_observed",
            "eq",
            "true",
        ),
        claim(
            "P11-RESTART-004",
            "Phase 11 worker-restart probe observed the process start time change.",
            worker_restart,
            "$.process_start_time_changed",
            "eq",
            "true",
        ),
        claim(
            "P11-RESTART-005",
            "Phase 11 worker-restart probe recovered liveness.",
            worker_restart,
            "$.recovery_liveness_ok",
            "eq",
            "true",
        ),
        claim(
            "P11-RESTART-006",
            "Phase 11 worker-restart probe recovered readiness.",
            worker_restart,
            "$.recovery_readiness_ok",
            "eq",
            "true",
        ),
        claim(
            "P11-RESTART-007",
            "Phase 11 worker-restart probe recorded 8 successful post-restart requests.",
            worker_restart,
            "$.post_restart_successful_requests",
            "eq",
            "8",
        ),
    ]

    return claims


def main() -> None:
    print()
    print("===============================================")
    print(" CityRoute Phase 12 Phase 11 Claim Preparation")
    print("===============================================")
    print()

    collection = latest_collection()
    output = collection / "manifests" / "claim_register_phase11.csv"

    claims = build_claims()

    with output.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(claims)

    print(f"Claims prepared: {len(claims)}")
    print()
    print("Output:")
    print(f"  {output}")
    print()
    print("Status-preserving design:")
    print("  - Successful probes have true-valued acceptance claims.")
    print("  - Failed/incomplete probes retain false-valued overall_ok claims.")
    print("  - Functional recovery is separated from telemetry acceptance.")
    print("  - Real Redis evidence is represented separately from Redis metrics gaps.")
    print("  - No universal production-readiness claim is created.")
    print()
    print("No claims evaluated.")
    print("No Phase 11 benchmark artifacts modified.")
    print()


if __name__ == "__main__":
    main()