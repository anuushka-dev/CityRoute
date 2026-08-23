# CityRoute Frontend — Evidence / Data Gaps

This frontend intentionally does not invent backend data. The following items are **not available as current, authoritative evidence in the supplied archives** and are therefore not presented as facts.

## Not available from the supplied current evidence

1. **A newer full-suite pytest result after the supplied historical run.**
   The supplied pasted run collected 611 items and reported 610 passed / 1 failed, but that run is treated as historical evidence only. It is not used as the current system score in this UI.

2. **A current benchmark run newer than the supplied Phase 11 artifacts.**
   The dashboard inventories the supplied benchmark archive and exposes its stored evidence, but does not claim those historical measurements are current runtime measurements.

3. **A live configuration endpoint for every runtime policy.**
   Current readiness and Prometheus gauges expose some runtime state (for example active/waiting capacity and readiness), but the backend does not expose every configured timeout/backoff/Redis policy value through a dedicated read-only configuration endpoint. The dashboard therefore does not fabricate a full configuration panel.

4. **Continuous CPU, process memory, host/network, or container telemetry.**
   The supplied backend exposes application metrics, graph memory metadata, readiness, concurrency, timeout, Redis and reliability metrics, but does not provide a complete host/container telemetry stream. No fake CPU/p95/throughput widgets are included.

5. **A* frontier-by-frontier search trace.**
   The routing response exposes node counts/timings/metadata, but the supplied API contract does not expose the full frontier/visited-node sequence needed for a genuine search-expansion animation. The dashboard shows returned execution evidence instead of inventing a search visualization.

6. **Full live benchmark runner APIs for every historical probe.**
   Phase 11 benchmark evidence is supplied as archived artifacts. The frontend can inspect that evidence, but it does not pretend that every archived Docker probe can be safely re-executed from the browser.

## What is available and used

- Live `/health`, `/health/live`, `/health/ready`, `/graph/stats`, `/graph/validate`, `/graph/snap`, and `/metrics`.
- Live `/route/compare` engineering probe.
- Live `/matrix` engineering probe.
- Live `/vrp/compare/advanced` engineering probe.
- Live `/dispatch/compare` engineering probe.
- Current source inventory from the supplied backend archives.
- Supplied Phase 11 evidence artifacts.
- Supplied benchmark archive inventory.
- Supplied test-archive inventory.

No value labelled LIVE is sourced from the historical benchmark JSON files.
