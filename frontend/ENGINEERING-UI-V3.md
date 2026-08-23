# CityRoute Engineering UI v3

This version keeps the existing Product workflow and upgrades the Engineering surface into an engine console.

## Data provenance
- Live runtime panels call the FastAPI backend through the Vite `/api` proxy.
- Archived evidence panels load only the bundled JSON audit artifacts.
- Archived PASS/WARNING states are preserved as supplied; they are not converted into live health claims.
- Test inventory is an archive count, not a claim that a new full-suite run passed.

## Main engineering views
- Overview: system topology, runtime state, core/services/API counts, live graph and evidence posture.
- Routing engine: graph pipeline, validation/snap probe, A*, Bidirectional A*, Multi-target Dijkstra source inventory.
- Optimization: distance matrix, greedy, 2-Opt, LNS, improvement metrics, Redis/cache source inventory.
- Dispatch: greedy, Hungarian, road-network cost matrix, fairness, cost matrix and service inventory.
- Runtime: readiness/liveness/health, admission telemetry, concurrency/timeout/middleware/observability inventory.
- Evidence: Phase 11 probe explorer, benchmark archive, recorded test runs, provenance rules.
