# CityRoute

CityRoute is an open-source last-mile delivery routing backend built with Python, FastAPI, Docker, Redis, OSMnx, NetworkX, scikit-learn, and OpenStreetMap data.

Current status: **Tier 2 complete — Distance Matrix, Redis Cache, Greedy VRP Baseline, 2-Opt Route Improvement, and Cache Telemetry Evidence**

CityRoute is being built phase-by-phase with evidence-backed engineering gates. Phase 1 created the FastAPI and Docker foundation. Phase 2 added real graph loading, GraphML persistence, GPS validation, graph metadata, node snapping, and BallTree-based snap optimization. Phase 3 added custom A* routing from scratch with ETA, route geometry, correctness probes, and Docker benchmarks. Phase 3.5 added Folium route visualization for road-following geometry verification. Phase 4 added Bidirectional A*, `/route/compare`, correctness validation, Docker evidence, and A* vs Bidirectional A* benchmark comparison. Phase 5 added the `/matrix` distance-matrix service, Redis caching, matrix correctness probes, local/Docker benchmark evidence, and a source-wise Dijkstra optimization patch for larger matrix workloads. Phase 6 added a nearest-neighbor greedy multi-stop route-ordering baseline through `/vrp/greedy`. Phase 7 added 2-Opt route improvement from scratch and the real `/vrp/compare` endpoint. Phase 7.1 added accepted cache telemetry evidence proving warm Redis matrix reuse through `/vrp/compare`.

Strict production decision:

* `GET /route` remains normal A* because Phase 4 evidence showed A* is faster overall at p50/p95/p99 route latency.
* `GET /route/compare` retains Bidirectional A* for comparison and algorithm analysis.
* `POST /matrix` supports `source_dijkstra`, `bidirectional_astar`, and `astar`.
* `source_dijkstra` is the preferred matrix algorithm for larger N×N matrices because it scales better than repeated pairwise routing.
* `POST /vrp/greedy` provides the nearest-neighbor baseline route order.
* `POST /vrp/compare` compares Greedy against 2-Opt and returns distance saved, improvement percentage, swaps, iterations, convergence trace, non-regression status, and cache telemetry.
* Greedy and 2-Opt are heuristic optimizers. CityRoute does not claim global VRP optimality.

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
| Tier 2 | Final Deployment Verification | Pending |
| Tier 3 | Phase 8+ — LNS / Dispatch / Advanced Optimization | Not started |

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
* Pytest test setup
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
* Benchmark evidence recorded under `benchmarks/`

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
* Route distance in meters and kilometers
* ETA calculation
* Route geometry output as graph-node coordinates
* Node expansion count
* Internal route timing
* Total route request timing
* Clean `404 No path found` handling
* Clean `503 Graph not loaded` handling
* A* correctness verification against Dijkstra
* Haversine admissibility verification
* Docker route benchmark
* Concurrent Docker route probe

### Phase 3.5 — Folium Route Verification

* Folium route map generation from `/route` geometry
* Route polyline rendered from real graph node coordinates
* Start and end markers
* Route summary marker
* Rejection of missing or invalid geometry
* HTML route map artifact generation
* Visual verification that route geometry follows road-network nodes

### Phase 4 — Bidirectional A* Comparison

* Bidirectional A* implementation from scratch
* Forward and backward graph search
* Directed graph support through successors and predecessors
* MultiDiGraph edge handling
* Meeting-node tracking
* Forward and backward node expansion counters
* Coordinate and edge-length caching in the algorithm path
* Alias function for `bidirectional_a_star_shortest_path`
* `/route/compare` endpoint
* A* and Bidirectional A* run on the same snapped start/end nodes
* Same-distance comparison with tolerance
* Route timing comparison
* Node expansion comparison
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
* Matrix benchmark scripts
* Local and Docker benchmark evidence
* Baseline pairwise matrix using `bidirectional_astar`
* Parallel-vs-serial benchmark evidence
* Source-wise Dijkstra matrix optimization patch
* Graph adjacency builder for matrix workloads
* Multi-target Dijkstra core implementation
* 25x25 stress testing
* Phase 5 full regression coverage: 143 tests passed

### Phase 6 — Greedy Multi-Stop Baseline and Hardening

* `POST /vrp/greedy` endpoint
* Nearest-neighbor greedy route-ordering algorithm from scratch
* Greedy solver separated into core algorithm layer
* Service layer using the Phase 5 matrix wrapper instead of bypassing cache/timing logic
* Open-route mode
* Return-to-start / return-to-depot mode
* Deterministic stop ordering with tie-break behavior
* Optimized stop order returned as zero-based stop indexes
* Total greedy route distance returned in meters
* Leg-level route output from start to stops and optionally back to start
* Matrix algorithm selection through request payload
* Redis cache usage preserved through Phase 5 `/matrix` service wrapper
* Matrix generation time exposed
* Greedy optimization time exposed
* Total request time exposed
* 1–24 stop validation because the matrix layer supports 25 total locations including depot
* Invalid 25-stop request rejection with HTTP `422`
* Graph-not-loaded behavior with HTTP `503`
* Snap-index-missing behavior with HTTP `503`
* Edge-case benchmark coverage for clustered, spread-out, near-duplicate, seeded-random, zigzag, and return-to-start cases
* Local and Docker benchmark evidence
* Docker and local 24-stop load probes
* Formal Phase 6 audit and raw evidence pack

### Phase 7 — 2-Opt Route Improvement

* 2-Opt local-search algorithm from scratch
* `POST /vrp/compare` endpoint implemented
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
* Accepted formal Phase 7 audit

### Phase 7.1 — Cache Telemetry and Warm-Matrix Proof

* Cache telemetry added to `/vrp/compare`
* `cache_status` values: `hit`, `miss`, `partial`, `disabled`, `unknown`
* `cache_hits` and `cache_misses` exposed in the compare response
* Nested Phase 5 matrix cache telemetry mapped into VRP compare response
* Accepted Docker cache-observability runs
* Cold matrix miss verified
* Warm matrix hit verified
* `/vrp/compare` cache hit propagation verified
* Rejected pre-fix cache-key mismatch run separated from accepted evidence

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
| Graph load time | ~3.0–3.3 s local/Docker |
| Runtime memory | ~380 MB |

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
  -Uri "http://127.0.0.1:8001/vrp/greedy" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body |
ConvertTo-Json -Depth 20
```

Return-to-start mode:

```powershell
$body.return_to_start = $true
```

When `return_to_start=true`, the response contains one extra final leg from the last selected stop back to the start/depot.

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
  -Uri "http://127.0.0.1:8001/vrp/compare" `
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

### `/vrp/greedy`

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

### `/vrp/compare`

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
| 2-Opt result greater than Greedy | Rejected by non-regression expectation in tests/benchmarks |

---

## Test Summary

Run:

```powershell
python -m pytest -v
```

Latest Tier 2 regression result:

```text
208 passed
```

Earlier milestone test evidence:

```text
Phase 5 full suite: 143 passed in 165.74s
Phase 6 hardening group: 36 passed in 23.11s
Phase 7 targeted group: 29 passed
Phase 7.1 cache telemetry group: 3 passed
```

Phase 7 targeted tests:

```powershell
python -m pytest tests\test_two_opt.py tests\test_vrp_compare_contract.py tests\test_vrp_compare_endpoint.py -v
```

Phase 7.1 cache telemetry tests:

```powershell
python -m pytest tests\test_vrp_compare_cache_telemetry.py -v
```

---

## Phase 5 Benchmark Evidence

### Phase 5 baseline cache benchmark

| Mode | 5x5 cache median | 10x10 cache median | 15x15 cache median | Cache confirmed |
|---|---:|---:|---:|---|
| Local | 11.123 ms | 12.174 ms | 13.159 ms | true |
| Docker | 7.436 ms | 7.821 ms | 8.589 ms | true |

### Phase 5 source-Dijkstra optimization

#### Local comparison

| Size | Bidirectional median | Source-Dijkstra median | Speedup | Mismatch count |
|---:|---:|---:|---:|---:|
| 5x5 | 130.777 ms | 173.735 ms | 0.753x | 0 |
| 10x10 | 1255.083 ms | 516.540 ms | 2.430x | 0 |
| 15x15 | 4645.089 ms | 695.695 ms | 6.677x | 0 |

#### Docker comparison

| Size | Bidirectional median | Source-Dijkstra median | Speedup | Mismatch count |
|---:|---:|---:|---:|---:|
| 5x5 | 132.196 ms | 189.519 ms | 0.698x | 0 |
| 10x10 | 1355.156 ms | 502.995 ms | 2.694x | 0 |
| 15x15 | 4637.942 ms | 678.859 ms | 6.832x | 0 |

Verdict:

```text
PASS for larger matrix workloads.
```

Interpretation:

* `source_dijkstra` is slower for 5x5 because adjacency-build and setup overhead dominate.
* `source_dijkstra` becomes faster at 10x10.
* `source_dijkstra` exceeds the 4x speedup target at 15x15 locally and in Docker.
* Matrix mismatch count is 0 at 0.01 m tolerance.

### 25x25 source_dijkstra vs bidirectional_astar

Docker cold compute comparison at concurrency 1:

| Algorithm | Generation median |
|---|---:|
| `bidirectional_astar` | 12362.309 ms |
| `source_dijkstra` | 1110.251 ms |

Improvement:

```text
11.14x faster
```

Verdict:

```text
PASS — Source-Dijkstra reduced 25x25 Docker cold-generation median from 12.36 s to 1.11 s with zero failed pairs.
```

---

## Phase 6 Benchmark Evidence

### Phase 6 Docker route-mode benchmark

| Stops | Route mode | Success | Cache hits | Cache misses | API median | Matrix median | Greedy median | Response median | Distance median |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|
| 5 | open | 5/5 | 4 | 1 | 14.262 ms | 3.920 ms | 0.061 ms | 4.529 ms | 11,475.024 m |
| 5 | return_to_start | 5/5 | 5 | 0 | 13.905 ms | 3.356 ms | 0.060 ms | 3.813 ms | 17,955.980 m |
| 10 | open | 5/5 | 4 | 1 | 12.654 ms | 3.069 ms | 0.102 ms | 3.694 ms | 18,318.919 m |
| 10 | return_to_start | 5/5 | 5 | 0 | 13.360 ms | 3.113 ms | 0.096 ms | 3.772 ms | 27,524.303 m |
| 15 | open | 5/5 | 4 | 1 | 15.086 ms | 3.837 ms | 0.140 ms | 4.649 ms | 26,590.851 m |
| 15 | return_to_start | 5/5 | 5 | 0 | 12.467 ms | 2.841 ms | 0.129 ms | 3.435 ms | 33,976.769 m |
| 24 | open | 5/5 | 4 | 1 | 13.481 ms | 3.579 ms | 0.225 ms | 4.356 ms | 41,486.728 m |
| 24 | return_to_start | 5/5 | 5 | 0 | 13.031 ms | 3.366 ms | 0.221 ms | 4.389 ms | 50,340.083 m |

Verdict:

```text
PASS — Docker greedy endpoint remained stable from 5 to 24 stops. Greedy optimization itself stayed sub-millisecond, including the 24-stop upper boundary.
```

### Phase 6 robustness and load probe

| Mode | Route mode | Stops | Requests | Workers | Success | Cache hits/misses | Orders valid | Legs valid | Invalid 25-stop rejection | API median | API p95 |
|---|---|---:|---:|---:|---|---|---|---|---|---:|---:|
| Docker | open | 24 | 20 | 5 | 20/20 | 20/0 | true | true | 422 | 40.951 ms | 76.087 ms |
| Docker | return_to_start | 24 | 20 | 5 | 20/20 | 20/0 | true | true | 422 | 37.646 ms | 50.056 ms |
| Local | open | 24 | 20 | 5 | 20/20 | 20/0 | true | true | 422 | 34.679 ms | 44.738 ms |
| Local | return_to_start | 24 | 20 | 5 | 20/20 | 20/0 | true | true | 422 | 34.093 ms | 50.574 ms |

Verdict:

```text
PASS — 24-stop upper-bound requests passed under repeated 20-request / 5-worker probes locally and in Docker. Invalid 25-stop requests were correctly rejected with HTTP 422.
```

---

## Phase 7 Benchmark Evidence

### Docker 10-stop open route

| Metric | Value |
|---|---:|
| Mode | Docker |
| Endpoint | `/vrp/compare` |
| Route mode | open |
| Stop count | 10 |
| Iterations | 5 |
| Matrix algorithm | `source_dijkstra` |
| Success count | 5 |
| Failure count | 0 |
| Success rate | 100.0% |
| Expected leg count | 10 |
| Greedy order valid | true |
| 2-Opt order valid | true |
| Greedy leg count valid | true |
| 2-Opt leg count valid | true |
| Non-regression | true |
| Matrix generation median | 3.061 ms |
| Greedy optimization median | 0.113 ms |
| 2-Opt optimization median | 5.469 ms |
| Response total median | 5.624 ms |
| Greedy distance | 23,257.269 m |
| 2-Opt distance | 23,025.306 m |
| Distance saved | 231.963 m |
| Improvement | 0.997% |
| 2-Opt iterations | 3 |
| Swaps applied | 2 |

### Local 10-stop open route

| Metric | Value |
|---|---:|
| Mode | Local |
| Endpoint | `/vrp/compare` |
| Route mode | open |
| Stop count | 10 |
| Iterations | 5 |
| Success count | 5 |
| Failure count | 0 |
| Success rate | 100.0% |
| Expected leg count | 10 |
| Non-regression | true |
| Matrix generation median | 7.207 ms |
| Greedy optimization median | 0.117 ms |
| 2-Opt optimization median | 3.761 ms |
| Response total median | 3.878 ms |
| Greedy distance | 23,257.269 m |
| 2-Opt distance | 23,025.306 m |
| Distance saved | 231.963 m |
| Improvement | 0.997% |
| 2-Opt iterations | 3 |
| Swaps applied | 2 |

### Strongest 24-stop route-quality evidence

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

### Official accepted Docker cache run

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
| Cold-to-VRP warm speedup | 101.124x |

### Supporting accepted cache run

| Metric | Value |
|---|---:|
| Run ID | `59cc8d64` |
| Cold `/matrix` generation | 585.986 ms |
| Warm `/matrix` generation | 2.967 ms |
| Warm `/vrp/compare` matrix generation | 3.147 ms |
| Cache status | hit |
| Cache hits | 1 |
| Cache misses | 0 |
| Cold-to-warm matrix speedup | 197.501x |
| Cold-to-VRP warm speedup | 186.205x |

### Rejected evidence note

One earlier Phase 7.1 benchmark run, `bfc6f13e`, is excluded from accepted evidence.

That run showed:

```text
vrp_compare_cache_hit = false
cache_status = miss
cache_hits = 0
cache_misses = 1
```

This was a pre-fix benchmark-key mismatch run. It is retained only as rejected/debugging evidence and must not be used as final Phase 7.1 acceptance proof.

Verdict:

```text
PASS — Phase 7.1 proves repeated/warm matrix optimization and correct cache telemetry propagation through /vrp/compare.
```

Boundary:

```text
Phase 7.1 does not claim that fully cold/new matrix computation is solved.
```

---

## Evidence Files

Expected Phase 7 evidence directories:

```text
benchmarks/phase_7/docker_results
benchmarks/phase_7/local_results
benchmarks/phase_7/final_results
```

Important Phase 7 evidence files include:

```text
phase7_2opt_benchmark_5_stops_open.json
phase7_2opt_benchmark_10_stops_open.json
phase7_2opt_benchmark_15_stops_open.json
phase7_2opt_benchmark_24_stops_open.json
phase7_2opt_benchmark_5_stops_return_to_start.json
phase7_2opt_benchmark_10_stops_return_to_start.json
phase7_2opt_benchmark_15_stops_return_to_start.json
phase7_2opt_benchmark_24_stops_return_to_start.json
phase7_all_results_combined.json
phase7_all_results_raw_dump.txt
phase7_benchmark_summary_table.csv
```

Expected Phase 7.1 evidence directories:

```text
benchmarks/phase_7_1/docker_results
benchmarks/phase_7_1/final_results
benchmarks/phase_7_1/rejected_results
```

Important Phase 7.1 accepted evidence files include:

```text
phase7_1_cache_observability_docker_59cc8d64.json
phase7_1_cache_observability_docker_71a95ee0.json
phase7_1_cache_observability_docker_latest.json
phase7_1_ACCEPTED_results_raw_dump.txt
phase7_1_ACCEPTED_results_combined.json
phase7_1_ACCEPTED_cache_summary_table.csv
```

Rejected Phase 7.1 evidence:

```text
phase7_1_cache_observability_docker_bfc6f13e_REJECTED_key_mismatch.json
README_REJECTED_EVIDENCE.md
```

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
| Stress p95 is based on small samples | Treated as outlier indicator, not formal SLA |
| Greedy is a baseline heuristic, not an optimal VRP solver | Documented |
| 2-Opt is local search, not global optimality proof | Documented |
| 24 stops is the configured tested VRP limit | Accepted; 25 stops rejected by validation |
| Near-duplicate stops can snap to same road node | Accepted if order/legs remain valid |
| Phase 7.1 cache proof covers warm/repeated matrix reuse | Accepted |
| Phase 7.1 does not eliminate fully cold/new matrix cost | Documented |
| ETA is formula-based, not traffic-aware | Accepted for current phase |
| Graph covers Kanpur Central bbox, not full city scale | Accepted for current project stage |
| Tier 2 deployment verification | Pending final deployment check |
| Grafana/Prometheus | Not integrated yet |

---

## Project Structure

```text
app/
├── api/
│   ├── graph.py
│   ├── health.py
│   ├── matrix.py
│   ├── route.py
│   └── vrp.py
├── core/
│   ├── a_star.py
│   ├── bidirectional_a_star.py
│   ├── distance_matrix.py
│   ├── eta.py
│   ├── graph_adjacency.py
│   ├── greedy_nearest_neighbor.py
│   ├── multi_target_dijkstra.py
│   ├── two_opt.py
│   └── vrp_improvement_metrics.py
├── infrastructure/
│   └── redis_cache.py
├── models/
│   └── matrix_model.py
├── schemas/
│   ├── vrp.py
│   └── vrp_compare.py
├── services/
│   ├── graph_service.py
│   ├── greedy_service.py
│   ├── matrix_service.py
│   ├── routing_service.py
│   └── vrp_compare_service.py
├── utils/
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

Run Phase 7 targeted tests:

```powershell
python -m pytest tests\test_two_opt.py tests\test_vrp_compare_contract.py tests\test_vrp_compare_endpoint.py -v
```

Run Phase 7.1 cache telemetry tests:

```powershell
python -m pytest tests\test_vrp_compare_cache_telemetry.py -v
```

Run Tier 2 final verification:

```powershell
python -m pytest -v 2>&1 |
Tee-Object benchmarks\tier2_final_pytest_208_passed.txt

Invoke-RestMethod http://127.0.0.1:8001/health |
ConvertTo-Json -Depth 10 |
Tee-Object benchmarks\tier2_final_docker_health.json

(Invoke-RestMethod http://127.0.0.1:8001/openapi.json).paths.PSObject.Properties.Name |
Select-String "matrix|vrp" |
Tee-Object benchmarks\tier2_final_openapi_paths.txt
```

Expected OpenAPI paths:

```text
/matrix
/vrp/greedy
/vrp/compare
```

---

## Benchmark Commands

### Phase 7 2-Opt benchmarks

Docker open-route benchmark:

```powershell
python benchmarks\phase_7\phase7_2opt_benchmark.py `
  --mode docker `
  --sizes 5,10,15,24 `
  --iterations 5 `
  --matrix-algorithm source_dijkstra `
  --use-cache
```

Docker return-to-start benchmark:

```powershell
python benchmarks\phase_7\phase7_2opt_benchmark.py `
  --mode docker `
  --sizes 5,10,15,24 `
  --iterations 5 `
  --matrix-algorithm source_dijkstra `
  --use-cache `
  --return-to-start
```

Local open-route benchmark:

```powershell
python benchmarks\phase_7\phase7_2opt_benchmark.py `
  --mode local `
  --sizes 5,10,15,24 `
  --iterations 5 `
  --matrix-algorithm source_dijkstra `
  --use-cache
```

Local return-to-start benchmark:

```powershell
python benchmarks\phase_7\phase7_2opt_benchmark.py `
  --mode local `
  --sizes 5,10,15,24 `
  --iterations 5 `
  --matrix-algorithm source_dijkstra `
  --use-cache `
  --return-to-start
```

### Phase 7.1 cache telemetry benchmark

```powershell
python benchmarks\phase_7_1\phase7_1_cache_observability_benchmark.py --mode docker
```

Expected accepted result:

```text
all_validations_passed = true
cache_status = hit
cache_hits = 1
cache_misses = 0
```

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

## Example `/route` Request

```powershell
curl.exe "http://127.0.0.1:8001/route?start_lat=26.44&start_lon=80.30&end_lat=26.45&end_lon=80.35"
```

Example response summary:

```json
{
  "status": "ok",
  "algorithm": "astar",
  "distance_m": 6428.798,
  "distance_km": 6.429,
  "eta_seconds": 999.5,
  "eta_minutes": 16.66,
  "path_node_count": 77,
  "nodes_expanded": 2622
}
```

---

## Example `/route/compare` Request

```powershell
Invoke-RestMethod "http://127.0.0.1:8001/route/compare?start_lat=26.44&start_lon=80.30&end_lat=26.45&end_lon=80.35" |
ConvertTo-Json -Depth 20
```

Example comparison summary:

```json
{
  "status": "ok",
  "comparison": {
    "distance_delta_m": 0.0,
    "same_distance": true,
    "bidirectional_faster": true,
    "nodes_expanded_reduction_pct": 44.394,
    "route_time_reduction_pct": 27.083
  }
}
```

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

## Final Tier 2 Verdict

```text
Tier 2 Phase 5: accepted
Tier 2 Phase 6: accepted
Tier 2 Phase 7: accepted
Tier 2 Phase 7.1: accepted
Tier 2 status: complete, pending final deployment verification
```

CityRoute now has a tested multi-stop optimization backend with distance matrix generation, Redis warm-cache behavior, Greedy baseline ordering, 2-Opt local search improvement, and evidence-backed `/vrp/compare` benchmarking.

---

## Next Phase

Next planned phase:

```text
Tier 3 — Phase 8: Large Neighborhood Search
```

Phase 8 should add:

* Destroy/repair operators
* Stochastic route improvement
* LNS vs 2-Opt comparison
* Distance saved beyond 2-Opt
* Iteration convergence tracking
* Benchmark evidence for additional improvement over 2-Opt

