# CityRoute

CityRoute is an open-source last-mile delivery routing backend built with Python, FastAPI, Docker, Redis, OSMnx, NetworkX, scikit-learn, NetworkX, and OpenStreetMap road-network data.

Current status: **Tier 3 Phase 9 local evidence complete — LNS optimization, Hungarian dispatch assignment, dispatch integration hardening, source-Dijkstra service-path readiness, and cache-contract evidence. Docker final verification is pending.**

CityRoute is being built phase-by-phase with evidence-backed engineering gates. Phase 1 created the FastAPI and Docker foundation. Phase 2 added real graph loading, GraphML persistence, GPS validation, graph metadata, node snapping, and BallTree-based snap optimization. Phase 3 added custom A* routing from scratch. Phase 4 added Bidirectional A* comparison. Phase 5 added the `/matrix` service, Redis cache integration, and source-wise Dijkstra optimization for larger matrices. Phase 6 added Greedy multi-stop ordering. Phase 7 added 2-Opt route improvement. Phase 7.1 added accepted cache telemetry evidence. Phase 8 added LNS advanced route improvement through `/vrp/compare/advanced`. Phase 9 added Hungarian assignment dispatch through `/dispatch/compare` and local hardening evidence for source-Dijkstra service-path injection and cache-contract behavior.

Strict production decision:

* `GET /route` remains normal A* because earlier evidence showed A* is faster overall for single-route production routing.
* `GET /route/compare` retains Bidirectional A* for comparison and algorithm analysis.
* `POST /matrix` supports `source_dijkstra`, `bidirectional_astar`, and `astar`.
* `source_dijkstra` is the preferred matrix algorithm for larger N×N matrix workloads.
* `POST /vrp/greedy` provides the nearest-neighbor baseline route order.
* `POST /vrp/compare` compares Greedy against 2-Opt.
* `POST /vrp/compare/advanced` compares Greedy, 2-Opt, and LNS.
* `POST /dispatch/compare` compares Greedy dispatch with Hungarian assignment.
* Greedy, 2-Opt, and LNS are heuristic route optimizers. CityRoute does not claim global VRP optimality.
* Hungarian dispatch is exact for the provided dispatch cost matrix, but the current live dispatch API uses haversine dispatch costs. Real road-network `source_dijkstra` dispatch is proven at service-injection level, not yet live API level.

---

## Current Phase Status

| Tier | Phase | Status |
|---|---|---:|
| Tier 1 | Phase 1 — Project Foundation | Complete |
| Tier 1 | Phase 2 — Graph Loading & Validation | Complete |
| Tier 1 | Phase 3 — A* Routing | Complete |
| Tier 1 | Phase 3.5 — Folium Route Verification | Complete |
| Tier 1 | Phase 4 — Bidirectional A* Comparison + Railway Deployment | Complete |
| Tier 2 | Phase 5 — Distance Matrix + Redis Cache + Source-Dijkstra Optimization | Complete |
| Tier 2 | Phase 6 — Greedy Multi-Stop Baseline + Hardening | Complete |
| Tier 2 | Phase 7 — 2-Opt Optimization + `/vrp/compare` | Complete |
| Tier 2 | Phase 7.1 — Cache Telemetry + Warm-Matrix Proof | Complete |
| Tier 3 | Phase 8 — LNS Advanced VRP Comparison | Complete |
| Tier 3 | Phase 9 — Hungarian Dispatch + Integration Hardening | Local evidence complete |
| Tier 3 | Phase 9 Docker Verification | Pending |
| Tier 3 | Real road-network dispatch API wiring | Pending |
| Tier 3 | Real Redis dispatch-cache proof | Pending |

---

## What is Implemented

### Phase 1 — Project Foundation

* FastAPI backend
* Router-based API structure
* `/health` endpoint
* `/graph/stats` endpoint
* Configuration through `.env`
* Structured logging
* Dockerfile and Docker Compose support
* Pytest setup
* Swagger UI through `/docs`

### Phase 2 — Graph Loading, Validation, and Fast Snapping

* OSMnx graph loading
* GraphML persistence
* Startup graph loading through FastAPI lifespan
* Real graph metadata through `/graph/stats`
* GPS latitude/longitude validation
* Bounding-box validation for active graph area
* Structured `422` responses for invalid/out-of-bounds coordinates
* Node snapping from GPS coordinate to nearest graph node
* BallTree snap index built at startup
* Snap distance returned in meters
* Graph connectivity metadata in `/graph/stats`
* Local and Docker verification

### Phase 3 — Custom A* Routing

* Custom A* implementation from scratch
* Manual priority queue using `heapq`
* Manual `g_score`, `came_from`, closed set, and path reconstruction
* Haversine straight-line heuristic
* MultiDiGraph edge handling for OSMnx parallel edges
* Shortest parallel edge selection for route distance
* Route endpoint: `GET /route`
* Start and end GPS validation
* Start and end snapping through BallTree
* Route distance, ETA, route geometry, node expansion count, and internal timing
* Clean `404 No path found` handling
* Clean `503 Graph not loaded` handling
* A* correctness verification against Dijkstra
* Docker route benchmark and concurrent route probe

### Phase 3.5 — Folium Route Verification

* Folium route map generation from `/route` geometry
* Route polyline rendered from real graph-node coordinates
* Start/end markers and route summary marker
* HTML route map artifact generation
* Visual verification that route geometry follows road-network nodes

### Phase 4 — Bidirectional A* Comparison

* Bidirectional A* implementation from scratch
* Forward and backward graph search
* Directed graph support through successors and predecessors
* MultiDiGraph edge handling
* Meeting-node tracking
* Forward and backward node expansion counters
* `/route/compare` endpoint
* A* and Bidirectional A* run on the same snapped start/end nodes
* Same-distance comparison with tolerance
* Correctness tests against A* and Dijkstra
* 500-pair correctness probe
* 1000-route Docker benchmark
* Railway deployment for Tier 1 route system

### Phase 5 — Distance Matrix Service, Redis Cache, and Source-Dijkstra Optimization

* `POST /matrix` endpoint
* Directed N×N road-distance matrix generation
* Directed N×N ETA matrix generation
* Location ID validation
* Duplicate location ID rejection
* Max matrix size validation
* Redis cache integration
* Cache key generation based on graph identity, algorithm, and ordered coordinates
* Cache hit/miss behavior
* Matrix correctness probes
* Local and Docker benchmark evidence
* Baseline pairwise matrix using `bidirectional_astar`
* Source-wise Dijkstra matrix optimization patch
* Graph adjacency builder for matrix workloads
* Multi-target Dijkstra core implementation
* 25x25 stress testing

### Phase 6 — Greedy Multi-Stop Baseline and Hardening

* `POST /vrp/greedy` endpoint
* Nearest-neighbor greedy route-ordering algorithm from scratch
* Service layer using the Phase 5 matrix wrapper
* Open-route mode
* Return-to-start / return-to-depot mode
* Deterministic stop ordering with tie-break behavior
* Optimized stop order returned as zero-based stop indexes
* Total greedy route distance returned in meters
* Leg-level route output
* Matrix algorithm selection through request payload
* Redis cache usage preserved through Phase 5 matrix service wrapper
* 1–24 stop validation because the matrix layer supports 25 total locations including depot
* Invalid 25-stop request rejection with HTTP `422`
* Graph-not-loaded behavior with HTTP `503`
* Snap-index-missing behavior with HTTP `503`
* Local and Docker benchmark evidence

### Phase 7 — 2-Opt Route Improvement

* 2-Opt local-search algorithm from scratch
* `POST /vrp/compare` endpoint
* Greedy baseline and 2-Opt optimized route returned in one response
* Shared matrix input between Greedy and 2-Opt
* Open-route and return-to-start support
* Distance saved in meters
* Improvement percentage
* Non-regression flag
* Iteration count
* Swap count
* Convergence trace
* Matrix-generation timing
* Greedy optimization timing
* 2-Opt optimization timing
* Cache telemetry exposed through `/vrp/compare`
* Docker and local benchmark evidence
* 10-stop and 24-stop benchmark evidence

### Phase 7.1 — Cache Telemetry and Warm-Matrix Proof

* Cache telemetry added to `/vrp/compare`
* `cache_status` values: `hit`, `miss`, `partial`, `disabled`, `unknown`
* `cache_hits` and `cache_misses` exposed in the compare response
* Nested Phase 5 matrix cache telemetry mapped into VRP compare response
* Cold matrix miss verified
* Warm matrix hit verified
* `/vrp/compare` cache hit propagation verified
* Rejected pre-fix cache-key mismatch run separated from accepted evidence

### Phase 8 — LNS Advanced VRP Comparison

* Large Neighborhood Search implementation from scratch
* Destroy/repair style route improvement loop
* Seeded reproducibility support
* Configurable destroy fraction
* Configurable no-improvement limit
* Open-route and return-to-start route-distance validation
* `/vrp/compare/advanced` endpoint
* Greedy, 2-Opt, and LNS returned in one advanced comparison response
* LNS non-regression checks
* LNS convergence and improvement evidence
* Docker route registration verified for `/vrp/compare/advanced`
* Phase 8 tests and benchmark evidence recorded under `benchmarks/phase_8`

### Phase 9 — Hungarian Dispatch Assignment + Integration Hardening

* Hungarian assignment algorithm implementation from scratch
* Greedy dispatch baseline
* Driver/order dispatch cost matrix builder
* Fairness metrics for driver assignment load
* `POST /dispatch/compare` endpoint
* Greedy dispatch vs Hungarian dispatch comparison
* Assignment count validation
* Capacity validation
* Duplicate driver/order ID validation
* Invalid GPS validation
* Cost-breakdown response option
* Non-regression check: Hungarian cost must not be worse than Greedy on the same cost matrix
* Haversine dispatch mode works through live `/dispatch/compare`
* Internal `source_dijkstra` dispatch service path supports injected matrix builders
* Dispatch cache key utility added
* Service-level dispatch cache miss→hit contract proven with fake backend
* Full local integration probe confirms root, health, OpenAPI, graph stats, and live dispatch haversine behavior

Phase 9 boundary:

```text
The live /dispatch/compare API currently supports haversine dispatch cost mode.
source_dijkstra dispatch is service-path ready through injected builders, but real graph-backed source_dijkstra dispatch is not yet wired into the live API.
The dispatch cache proof currently validates the service-level cache contract with a fake backend, not real Redis acceleration.
```

---

## Active Runtime Graph

Current active graph:

```text
data/graphs/kanpur_central.graphml
```

The graph file is not baked into the Docker image. It is mounted at runtime through:

```powershell
-v "${PWD}\data:/app/data"
```

The `data/graphs/*.graphml` files are local runtime artifacts and are not committed to Git.

---

## Active Graph Baseline

Observed active graph values:

| Metric | Value |
|---|---:|
| City label | Kanpur Central, Uttar Pradesh, India |
| Active graph | `data/graphs/kanpur_central.graphml` |
| Nodes | 12,969 |
| Edges | 34,996 |
| GraphML file size | 12.74 MB |
| Weakly connected components | 1 |
| Largest weak component nodes | 12,969 |
| Is weakly connected | true |
| Snap index method | BallTree |
| Graph load time | ~3.0–3.6 s local/Docker |
| Runtime memory | ~380–385 MB |

Important note: this is a directed OSM road graph. Some coordinate pairs can still produce clean `404 No path found` responses because one-way road topology can make certain snapped node pairs unreachable.

---

## Current API Endpoints

| Endpoint | Method | Purpose |
|---|---:|---|
| `/` | GET | Service index |
| `/health` | GET | Service heartbeat |
| `/graph/stats` | GET | Loaded graph metadata |
| `/graph/validate` | GET | Validate GPS coordinate against active graph bounds |
| `/graph/snap` | GET | Snap GPS coordinate to nearest graph node |
| `/route` | GET | Compute production A* route between two GPS coordinates |
| `/route/compare` | GET | Compare A* and Bidirectional A* on the same snapped route |
| `/matrix` | POST | Generate directed N×N distance and ETA matrix |
| `/vrp/greedy` | POST | Compute greedy nearest-neighbor multi-stop route order |
| `/vrp/compare` | POST | Compare Greedy baseline with 2-Opt improved route |
| `/vrp/compare/advanced` | POST | Compare Greedy, 2-Opt, and LNS |
| `/dispatch/compare` | POST | Compare Greedy dispatch with Hungarian assignment |
| `/docs` | GET | Swagger UI |

---

## Example `/matrix` Request

```powershell
$body = @{
    locations = @(
        @{ id = "depot"; lat = 26.44; lon = 80.30 },
        @{ id = "stop_1"; lat = 26.45; lon = 80.35 },
        @{ id = "stop_2"; lat = 26.46; lon = 80.33 }
    )
    algorithm = "source_dijkstra"
    use_cache = $true
} | ConvertTo-Json -Depth 10

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/matrix" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body |
ConvertTo-Json -Depth 20
```

Supported matrix algorithms:

```text
source_dijkstra
bidirectional_astar
astar
```

Recommended matrix algorithm:

```text
source_dijkstra
```

Reason: `source_dijkstra` has fixed setup overhead, so it can be slower for tiny matrices, but it scales much better for larger N×N matrix workloads.

---

## Example `/vrp/greedy` Request

```powershell
$body = @{
    start = @{
        lat = 26.44
        lon = 80.30
    }
    stops = @(
        @{ lat = 26.45; lon = 80.35 },
        @{ lat = 26.46; lon = 80.33 },
        @{ lat = 26.47; lon = 80.31 }
    )
    return_to_start = $false
    matrix_algorithm = "source_dijkstra"
    use_cache = $true
} | ConvertTo-Json -Depth 10

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/vrp/greedy" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body |
ConvertTo-Json -Depth 20
```

---

## Example `/vrp/compare` Request

```powershell
$body = @{
    start = @{
        lat = 26.44
        lon = 80.30
    }
    stops = @(
        @{ lat = 26.45; lon = 80.35 },
        @{ lat = 26.46; lon = 80.33 },
        @{ lat = 26.47; lon = 80.31 },
        @{ lat = 26.48; lon = 80.32 },
        @{ lat = 26.49; lon = 80.34 }
    )
    return_to_start = $false
    matrix_algorithm = "source_dijkstra"
    use_cache = $true
    two_opt_max_iterations = 100
    improvement_tolerance_m = 0.001
    keep_trace = $true
} | ConvertTo-Json -Depth 10

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/vrp/compare" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body |
ConvertTo-Json -Depth 30
```

Expected response sections:

```text
greedy
two_opt
improvement
convergence_trace
matrix_generation_time_ms
total_time_ms
cache_used
cache_status
cache_hits
cache_misses
```

---

## Example `/vrp/compare/advanced` Request

```powershell
$body = @{
    start = @{
        lat = 26.44
        lon = 80.30
    }
    stops = @(
        @{ lat = 26.45; lon = 80.35 },
        @{ lat = 26.46; lon = 80.33 },
        @{ lat = 26.47; lon = 80.31 },
        @{ lat = 26.48; lon = 80.32 },
        @{ lat = 26.49; lon = 80.34 }
    )
    return_to_start = $false
    matrix_algorithm = "source_dijkstra"
    use_cache = $true
    two_opt_max_iterations = 100
    lns_iterations = 100
    lns_destroy_fraction = 0.35
    lns_no_improvement_limit = 25
    seed = 123
    keep_trace = $true
} | ConvertTo-Json -Depth 10

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/vrp/compare/advanced" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body |
ConvertTo-Json -Depth 40
```

---

## Example `/dispatch/compare` Request

```powershell
$body = @{
    drivers = @(
        @{
            driver_id = "driver_1"
            lat = 26.45
            lon = 80.35
            current_load = 0
            max_capacity = 1
        },
        @{
            driver_id = "driver_2"
            lat = 26.46
            lon = 80.36
            current_load = 0
            max_capacity = 1
        }
    )
    orders = @(
        @{
            order_id = "order_1"
            pickup_lat = 26.451
            pickup_lon = 80.351
        },
        @{
            order_id = "order_2"
            pickup_lat = 26.461
            pickup_lon = 80.361
        }
    )
    matrix_algorithm = "haversine"
    use_cache = $true
    load_penalty_m = 0.0
    slot_penalty_m = 0.0
    return_cost_breakdown = $true
} | ConvertTo-Json -Depth 10

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/dispatch/compare" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body |
ConvertTo-Json -Depth 40
```

Expected response sections:

```text
greedy
hungarian
comparison
greedy_fairness
hungarian_fairness
cost_breakdown
```

Current dispatch algorithm modes:

| Mode | Live API status |
|---|---:|
| `haversine` | Supported |
| `source_dijkstra` | Service-path ready through injected builder; live API returns 400 until real graph builder is wired |

---

## Validation Rules

### `/matrix`

| Rule | Behavior |
|---|---|
| At least 2 locations | Required |
| Max locations | 25 total locations |
| Duplicate location IDs | Rejected |
| Invalid latitude/longitude | Rejected with 422 |
| Graph not loaded | 503 |
| Snap index missing | 503 |

### `/vrp/greedy`, `/vrp/compare`, `/vrp/compare/advanced`

| Rule | Behavior |
|---|---|
| Exactly one start/depot | Required |
| Stop count | 1 to 24 stops |
| 24 stops | Accepted because 24 stops + 1 depot = 25 matrix locations |
| 25 stops | Rejected with HTTP 422 |
| Invalid latitude/longitude | Rejected with 422 |
| Invalid matrix algorithm | Rejected with 422 |
| Graph not loaded | 503 |
| Snap index missing | 503 |
| Optimized result greater than baseline | Rejected by non-regression expectation in tests/benchmarks |

### `/dispatch/compare`

| Rule | Behavior |
|---|---|
| At least 1 driver | Required |
| At least 1 order | Required |
| Duplicate driver IDs | Rejected |
| Duplicate order IDs | Rejected |
| Invalid driver latitude/longitude | Rejected with 422 |
| Invalid order pickup latitude/longitude | Rejected with 422 |
| All drivers at full capacity | Rejected |
| More orders than capacity | Extra orders returned as unassigned |
| More capacity than orders | Extra driver slots returned as unused |
| `matrix_algorithm="haversine"` | Supported in live API |
| `matrix_algorithm="source_dijkstra"` | Rejected in live API until internal graph builder is wired |

---

## Test Summary

Run full test suite:

```powershell
python -m pytest -v
```

Latest Phase 9 targeted evidence:

```text
39 passed
```

Phase 9 targeted command:

```powershell
python -m pytest tests\test_dispatch_endpoint.py `
  tests\test_dispatch_source_dijkstra.py `
  tests\test_dispatch_cache_integration.py `
  tests\test_phase91_integration_routes.py `
  -v
```

Latest Phase 9 local evidence collector result:

```text
pytest_passed = true
ruff_passed = true
http_checks_passed = true
dispatch_endpoint_available = true
health_ok = true
all_critical_summary_quality_flags_true = true
```

Earlier milestone test evidence:

```text
Phase 5 full suite: 143 passed
Phase 6 hardening group: 36 passed
Phase 7 targeted group: 29 passed
Phase 7.1 cache telemetry group: 3 passed
Phase 8 LNS targeted group: 16 passed
Phase 9 dispatch hardening group: 39 passed
```

---

## Phase 5 Benchmark Evidence

### Phase 5 source-Dijkstra optimization

| Size | Bidirectional median | Source-Dijkstra median | Speedup | Mismatch count |
|---:|---:|---:|---:|---:|
| 5x5 | 130–190 ms | 173–190 ms | Slower at tiny size | 0 |
| 10x10 | ~1.25–1.36 s | ~503–517 ms | ~2.4–2.7x | 0 |
| 15x15 | ~4.64 s | ~679–696 ms | ~6.7–6.8x | 0 |
| 25x25 Docker cold | 12.36 s | 1.11 s | 11.14x | 0 failed pairs |

Verdict:

```text
PASS — source_dijkstra is the preferred larger-matrix strategy.
```

---

## Phase 6 Benchmark Evidence

Phase 6 Docker route-mode benchmark proved `/vrp/greedy` remained stable from 5 to 24 stops in open and return-to-start modes.

Strongest boundary evidence:

| Mode | Route mode | Stops | Requests | Workers | Success | Invalid 25-stop rejection |
|---|---|---:|---:|---:|---:|---:|
| Docker | open | 24 | 20 | 5 | 20/20 | 422 |
| Docker | return_to_start | 24 | 20 | 5 | 20/20 | 422 |
| Local | open | 24 | 20 | 5 | 20/20 | 422 |
| Local | return_to_start | 24 | 20 | 5 | 20/20 | 422 |

Verdict:

```text
PASS — 24-stop upper-bound requests passed under repeated probes; invalid 25-stop requests were correctly rejected.
```

---

## Phase 7 Benchmark Evidence

Strongest 24-stop route-quality evidence:

| Route mode | Greedy distance | 2-Opt distance | Distance saved | Improvement |
|---|---:|---:|---:|---:|
| Open route | 61,334.020 m | 47,419.957 m | 13,914.063 m | 22.686% |
| Return-to-start | 71,492.535 m | 55,148.656 m | 16,343.879 m | 22.861% |

Verdict:

```text
PASS — Phase 7 implements real Greedy vs 2-Opt comparison, keeps route output valid, enforces non-regression, and shows meaningful route-quality improvement on larger 24-stop cases.
```

---

## Phase 7.1 Cache Telemetry Evidence

Official accepted Docker cache run:

| Metric | Value |
|---|---:|
| Run ID | `71a95ee0` |
| Mode | Docker |
| Algorithm | `source_dijkstra` |
| Location count | 6 |
| Stop count | 5 |
| All validations passed | true |
| Cold matrix cache miss | true |
| Warm matrix cache hit | true |
| `/vrp/compare` cache hit | true |
| Cache hits positive | true |
| Cache misses zero | true |
| VRP non-regression | true |
| Cold `/matrix` generation | 335.327 ms |
| Warm `/matrix` generation | 3.131 ms |
| Warm `/vrp/compare` matrix generation | 3.316 ms |
| `/vrp/compare` cache status | hit |
| Cache hits | 1 |
| Cache misses | 0 |
| Cold-to-warm matrix speedup | 107.099x |

Verdict:

```text
PASS — Phase 7.1 proves repeated/warm matrix optimization and correct cache telemetry propagation through /vrp/compare.
```

Boundary:

```text
Phase 7.1 does not claim that fully cold/new matrix computation is solved.
```

---

## Phase 8 LNS Evidence

Phase 8 added Large Neighborhood Search and `/vrp/compare/advanced`.

Verified Phase 8 facts:

| Item | Result |
|---|---:|
| LNS core tests | 12 passed |
| Advanced endpoint tests | 4 passed |
| Targeted total | 16 passed |
| `/vrp/compare/advanced` route | Registered |
| Docker graph loaded | true |
| Docker graph nodes | 12,969 |
| Docker graph edges | 34,996 |
| Docker snap index | BallTree |

Verdict:

```text
PASS — Phase 8 adds LNS as an advanced route-improvement layer over Greedy and 2-Opt.
```

---

## Phase 9 Dispatch Evidence

### Hungarian correctness

| Metric | Value |
|---|---:|
| Probe | Hungarian correctness |
| Sizes | 2, 3, 4, 5, 6, 7, 8 |
| Iterations per size | 50 |
| Case count | 350 |
| Success count | 350 |
| Mismatch count | 0 |
| Success rate | 100.0% |
| Max absolute cost difference | 0.0 |

### Dispatch endpoint benchmark

| Metric | Value |
|---|---:|
| Endpoint | `/dispatch/compare` |
| Algorithm | Haversine dispatch cost |
| Case count | 80 |
| Success count | 80 |
| Failure count | 0 |
| Success rate | 100.0% |
| 5x5 median request | ~9.8–16.2 ms |
| 10x10 median request | ~11.2 ms |
| 25x25 median request | ~21.8–30.8 ms |
| 50x50 median request | ~44.8–55.8 ms |
| Assignment counts valid | true |
| Capacity counts valid | true |
| Hungarian non-regression | true |

### Dispatch integration hardening evidence

| Probe | Result |
|---|---:|
| `dispatch_source_dijkstra_probe` | 100/100 successful |
| `dispatch_cache_probe` | 50/50 cycles successful |
| Cache probe requests | 100 |
| Cache hits observed | 50 |
| Cache hit rate | 50.0% |
| Full integration probe | 6/6 checks successful |
| Full integration success rate | 100.0% |
| Phase 9 targeted tests | 39 passed |
| Ruff on Phase 9 files | Passed |

Full integration checked:

```text
root_ok = true
health_ok = true
openapi_required_paths_available = true
graph_stats_shape_valid = true
dispatch_haversine_ok = true
dispatch_haversine_non_regression = true
dispatch_source_dijkstra_status_expected = true
source_dijkstra_api_blocked_acknowledged = true
```

Verdict:

```text
PASS — Phase 9 locally proves Hungarian dispatch, Greedy-vs-Hungarian non-regression, dispatch capacity handling, service-level source_dijkstra readiness, service-level cache contract behavior, and live haversine dispatch API integration.
```

Boundary:

```text
Phase 9 does not yet prove live API real-road source_dijkstra dispatch or real Redis-backed dispatch cache acceleration.
```

---

## Evidence Files

Expected important evidence directories:

```text
benchmarks/phase_5
benchmarks/phase_6
benchmarks/phase_7
benchmarks/phase_7_1
benchmarks/phase_8
benchmarks/phase_9
benchmarks/phase_9_1
```

Phase 9 important evidence:

```text
benchmarks/phase_9/docker_results
benchmarks/phase_9/local_results
benchmarks/phase_9_1/local_results
```

Phase 9 hardening evidence files include:

```text
phase91_dispatch_source_dijkstra_raw_local_*.json
phase91_dispatch_source_dijkstra_summary_local_*.json
phase91_dispatch_cache_raw_local_*.json
phase91_dispatch_cache_summary_local_*.json
phase91_full_integration_raw_local_*.json
phase91_full_integration_summary_local_*.json
phase91_evidence_manifest_local_*.json
phase91_evidence_manifest_local_*.txt
```

The `phase_9_1` folder is treated as internal Phase 9 dispatch hardening evidence. The public milestone remains **Tier 3 Phase 9**.

---

## Current Known Risks and Notes

| Risk / note | Status |
|---|---|
| Some random coordinate pairs return `404 No path found` | Expected directed routing behavior |
| Bidirectional A* p99 is above the 120 ms production route target | Documented; not used as production `/route` algorithm |
| A* remains faster overall than Bidirectional A* for single-route production routing | Documented; `/route` remains A* |
| Original Phase 5 threaded pairwise matrix failed speedup target | Documented; fixed for larger matrices by source-Dijkstra patch |
| `source_dijkstra` is slower for 5x5 matrices | Documented fixed-overhead trade-off |
| Concurrent cold 25x25 matrix requests increase latency | Expected CPU-bound behavior on single API process |
| Greedy is a baseline heuristic, not an optimal VRP solver | Documented |
| 2-Opt is local search, not global optimality proof | Documented |
| LNS is stochastic/local-improvement, not global optimality proof | Documented |
| 24 stops is the configured tested VRP limit | Accepted; 25 stops rejected by validation |
| Near-duplicate stops can snap to same road node | Accepted if order/legs remain valid |
| Phase 7.1 cache proof covers warm/repeated matrix reuse | Accepted |
| Phase 7.1 does not eliminate fully cold/new matrix cost | Documented |
| Dispatch `/source_dijkstra` live API mode | Pending real graph-builder wiring |
| Dispatch cache with real Redis | Pending real Redis proof |
| ETA is formula-based, not traffic-aware | Accepted for current phase |
| Graph covers Kanpur Central bbox, not full city scale | Accepted for current project stage |
| Docker final Phase 9 verification | Pending |
| Grafana/Prometheus | Not integrated yet |

---

## Project Structure

```text
app/
├── api/
│   ├── dispatch.py
│   ├── graph.py
│   ├── health.py
│   ├── matrix.py
│   ├── route.py
│   └── vrp.py
├── core/
│   ├── a_star.py
│   ├── bidirectional_a_star.py
│   ├── dispatch_cost_matrix.py
│   ├── dispatch_fairness.py
│   ├── distance_matrix.py
│   ├── eta.py
│   ├── graph_adjacency.py
│   ├── greedy_dispatch.py
│   ├── greedy_nearest_neighbor.py
│   ├── hungarian.py
│   ├── lns.py
│   ├── multi_target_dijkstra.py
│   ├── two_opt.py
│   └── vrp_improvement_metrics.py
├── infrastructure/
│   └── redis_cache.py
├── models/
│   └── matrix_model.py
├── schemas/
│   ├── dispatch.py
│   ├── vrp.py
│   ├── vrp_advanced_compare.py
│   └── vrp_compare.py
├── services/
│   ├── dispatch_distance_service.py
│   ├── dispatch_service.py
│   ├── graph_service.py
│   ├── greedy_service.py
│   ├── matrix_service.py
│   ├── routing_service.py
│   ├── vrp_advanced_compare_service.py
│   └── vrp_compare_service.py
├── utils/
│   ├── dispatch_cache_key.py
│   ├── geo_validation.py
│   ├── logger.py
│   ├── matrix_cache_key.py
│   ├── node_snapper.py
│   ├── route_map.py
│   └── snap_index.py
├── config.py
└── main.py
```

---

## Local Setup

Create and activate virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

Create local environment file:

```powershell
copy .env.example .env
```

Start Redis locally:

```powershell
docker rm -f cityroute-redis 2>$null

docker run -d --rm `
  --name cityroute-redis `
  -p 6379:6379 `
  redis:7-alpine

docker exec cityroute-redis redis-cli ping
```

Expected:

```text
PONG
```

Run the app locally:

```powershell
python -m uvicorn app.main:app --reload --port 8000
```

Open Swagger UI:

```text
http://127.0.0.1:8000/docs
```

---

## Docker Setup

Create Docker network:

```powershell
docker network create cityroute-net
```

If it already exists, ignore the warning.

Start Redis:

```powershell
docker rm -f cityroute-redis 2>$null

docker run -d --rm `
  --name cityroute-redis `
  --network cityroute-net `
  -p 6379:6379 `
  redis:7-alpine

docker exec cityroute-redis redis-cli ping
```

Build API image:

```powershell
docker build -t cityroute-api .
```

Run API on port `8001`:

```powershell
docker rm -f cityroute-api 2>$null

docker run --rm `
  --name cityroute-api `
  --network cityroute-net `
  -p 8001:8000 `
  --env-file .env `
  -e CITYROUTE_REDIS_URL=redis://cityroute-redis:6379/0 `
  -v "${PWD}\data:/app/data" `
  cityroute-api
```

Open Docker Swagger UI:

```text
http://127.0.0.1:8001/docs
```

Check Docker health:

```powershell
Invoke-RestMethod "http://127.0.0.1:8001/health"
Invoke-RestMethod "http://127.0.0.1:8001/graph/stats"
```

---

## Test Commands

Run full test suite:

```powershell
python -m pytest -v
```

Run Phase 8 targeted tests:

```powershell
python -m pytest tests\test_lns.py tests\test_vrp_advanced_compare_endpoint.py -v
```

Run Phase 9 targeted tests:

```powershell
python -m pytest tests\test_dispatch_endpoint.py `
  tests\test_dispatch_source_dijkstra.py `
  tests\test_dispatch_cache_integration.py `
  tests\test_phase91_integration_routes.py `
  -v
```

Run Ruff on Phase 9 touched files:

```powershell
python -m ruff check app/services/dispatch_distance_service.py `
  app/utils/dispatch_cache_key.py `
  app/services/dispatch_service.py `
  app/schemas/dispatch.py `
  app/core/dispatch_cost_matrix.py `
  tests/test_dispatch_endpoint.py `
  tests/test_dispatch_source_dijkstra.py `
  tests/test_dispatch_cache_integration.py `
  tests/test_phase91_integration_routes.py `
  benchmarks/phase_9_1/phase91_dispatch_source_dijkstra_probe.py `
  benchmarks/phase_9_1/phase91_dispatch_cache_probe.py `
  benchmarks/phase_9_1/phase91_full_integration_probe.py `
  benchmarks/phase_9_1/collect_phase91_evidence.py
```

---

## Benchmark Commands

### Phase 8 LNS benchmark

```powershell
python benchmarks\phase_8\phase8_lns_benchmark.py --mode local
```

### Phase 9 source-Dijkstra service-path probe

```powershell
python benchmarks\phase_9_1\phase91_dispatch_source_dijkstra_probe.py `
  --mode local `
  --sizes 2,5,10,25,50 `
  --iterations 20
```

Expected quality flags:

```text
all_cases_successful = true
all_source_dijkstra_used = true
all_builder_called_once = true
all_non_regression = true
all_assignment_counts_valid = true
all_capacity_counts_valid = true
all_costs_non_negative = true
cache_not_used_in_this_probe = true
```

### Phase 9 dispatch cache-contract probe

```powershell
python benchmarks\phase_9_1\phase91_dispatch_cache_probe.py `
  --mode local `
  --sizes 2,5,10,25,50 `
  --cycles 10
```

Expected quality flags:

```text
all_cycles_successful = true
cache_backend_used = true
cache_hits_observed = true
cache_hit_count_matches_second_requests = true
all_first_requests_miss = true
all_second_requests_hit = true
all_cache_keys_stable = true
all_response_costs_stable = true
all_assignment_counts_stable = true
all_builder_not_called_on_hit = true
all_non_regression_stable = true
```

### Phase 9 full local integration probe

```powershell
python benchmarks\phase_9_1\phase91_full_integration_probe.py `
  --mode local `
  --source-dijkstra-api-mode blocked `
  --strict
```

Expected quality flags:

```text
all_checks_successful = true
root_ok = true
health_ok = true
openapi_required_paths_available = true
graph_stats_shape_valid = true
dispatch_haversine_ok = true
dispatch_haversine_non_regression = true
dispatch_source_dijkstra_status_expected = true
source_dijkstra_api_blocked_acknowledged = true
```

### Phase 9 evidence collector

```powershell
python benchmarks\phase_9_1\collect_phase91_evidence.py `
  --mode local `
  --run-pytest `
  --run-ruff
```

Expected quality flags:

```text
all_expected_source_files_exist = true
all_expected_test_files_exist = true
all_expected_benchmark_files_exist = true
result_json_files_present = true
all_result_json_files_valid = true
latest_summary_files_present = true
all_critical_summary_quality_flags_true = true
pytest_passed = true
ruff_passed = true
http_checks_passed = true
dispatch_endpoint_available = true
health_ok = true
git_commit_available = true
```

Do not run the collector with `--strict` until the Git working tree is committed and clean.

---

## Example `/health` Response

```json
{
  "status": "ok",
  "graph_loaded": true,
  "uptime_s": 546.305
}
```

`uptime_s` varies by run.

---

## Example `/graph/stats` Response

```json
{
  "city": "Kanpur Central, Uttar Pradesh, India",
  "graph_loaded": true,
  "nodes": 12969,
  "edges": 34996,
  "load_time_s": 3.252,
  "graph_path": "data/graphs/kanpur_central.graphml",
  "graph_file_size_mb": 12.74,
  "memory_mb": 380.23,
  "weakly_connected_components": 1,
  "largest_component_nodes": 12969,
  "is_weakly_connected": true,
  "snap_index_loaded": true,
  "snap_index_build_time_ms": 23.112
}
```

Values such as `load_time_s`, `memory_mb`, `uptime_s`, and `snap_index_build_time_ms` vary slightly by machine and run.

---

## Valid No-Path Behavior

Some random coordinate pairs return:

```text
HTTP 404 Not Found
```

Example response shape:

```json
{
  "detail": {
    "error": "No path found",
    "message": "No path found between 13572796077 and 8813195061",
    "start_node": 13572796077,
    "end_node": 8813195061
  }
}
```

This is expected for some directed graph node pairs. It is not considered a server crash or real failure.

---

## Final Current Verdict

```text
Tier 1: complete
Tier 2: complete
Tier 3 Phase 8: complete
Tier 3 Phase 9 local evidence: complete
Tier 3 Phase 9 Docker evidence: pending
Real road-network source_dijkstra dispatch API: pending
Real Redis-backed dispatch cache proof: pending
```

CityRoute now has a tested routing and optimization backend with custom A*, distance matrices, Redis warm-cache telemetry, Greedy VRP, 2-Opt, LNS, and Hungarian dispatch assignment. The current Phase 9 evidence is local and honest: it proves dispatch correctness, API integration for haversine dispatch, and internal readiness for source-Dijkstra and cache hardening, without claiming unfinished real-road dispatch API wiring or real Redis dispatch acceleration.

---

## Next Phase

Next planned work:

```text
Tier 3 Phase 9 Docker Final Verification and Real Dispatch Integration
```

Next engineering tasks:

* Run Docker Phase 9 evidence after Docker Desktop is stable.
* Wire real Phase 5 source-Dijkstra graph builder into `/dispatch/compare`.
* Add real Redis-backed dispatch-cache proof.
* Update `/dispatch/compare` evidence from service-path readiness to live API source-Dijkstra proof.