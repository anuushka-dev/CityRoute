# CityRoute UI evidence provenance

This frontend was built from the supplied current repository archives rather than the stale README milestone.

## Current source contracts used

Verified API router files:

- `api/health.py` — `/health`, `/health/live`, `/health/ready`
- `api/graph.py` — `/graph/stats`, `/graph/validate`, `/graph/snap`
- `api/route.py` — `/route`, `/route/compare`
- `api/matrix.py` — `/matrix`
- `api/vrp.py` — `/vrp/greedy`, `/vrp/compare`, `/vrp/compare/advanced`
- `api/dispatch.py` — `/dispatch/compare`
- `api/metrics.py` — `/metrics`

`main.py` registers those routers and reports `tier4_phase11` as the project phase code.

## Configuration values used in the UI

Taken from `config.py` and request schemas:

- graph bbox: south 26.43, north 26.50, west 80.28, east 80.38
- matrix max locations: 25
- VRP max delivery stops: 24
- matrix workers default: 8
- VRP default matrix algorithm: `source_dijkstra`
- VRP cache default: enabled
- Phase 11 concurrency defaults: active 4, waiting 8
- endpoint timeout defaults: route 5s, route compare 10s, matrix 15s, VRP 20s, advanced VRP 30s, dispatch 20s
- advanced VRP defaults: 2-Opt 100 iterations, tolerance 0.001m, LNS 500 iterations, destroy fraction 0.30, no-improvement limit 100

## Test inventory

The supplied `tests-phase11.zip` contains 58 Python test modules and 576 explicit `test_*` function definitions when statically counted from the archive.

This UI does not claim that 576 is the total collected pytest count and does not claim that 608 tests have passed, because the supplied archives do not contain one unambiguous full current run artifact proving that exact total. Parametrized tests can make the collected count larger than the explicit function count.

## Phase 11 benchmark evidence

The Engineering view includes the 11 Phase 11 summary JSON artifacts from `benchmarks/phase_11/Summary/` exactly as supplied. Their `overall_ok`, validation errors, warnings and detailed measured fields are displayed as archived evidence. A warning/failing evidence artifact is not relabeled as a pass.

Examples of verified archived conditions include concurrency limits of 4 active and 8 waiting, controlled rejections, pause/unpause failure injection recovery, worker restart process-start evidence, timeout policy observations, and Redis fail-open/recovery probes.
