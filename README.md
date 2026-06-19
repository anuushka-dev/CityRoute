# CityRoute

CityRoute is an open-source last-mile delivery routing backend built with Python, FastAPI, Docker, Redis, OSMnx, NetworkX, scikit-learn, and OpenStreetMap data.

Current status: **Tier 2 — Phase 6 complete: Greedy Multi-Stop Baseline, Return-to-Depot Support, Edge-Case Hardening, and Phase 7 Readiness**

CityRoute is being built phase-by-phase with evidence-backed engineering gates. Phase 1 created the FastAPI and Docker foundation. Phase 2 added real graph loading, GraphML persistence, GPS validation, graph metadata, node snapping, and BallTree-based snap optimization. Phase 3 added custom A* routing from scratch with ETA, geometry, correctness probes, and Docker benchmarks. Phase 3.5 added Folium route visualization for route geometry verification. Phase 4 added Bidirectional A*, `/route/compare`, correctness validation, Docker evidence, and A* vs Bidirectional A* benchmark comparison. Phase 5 added the `/matrix` distance-matrix service, Redis caching, matrix correctness probes, local/Docker benchmark evidence, and a source-wise Dijkstra optimization patch for larger matrix workloads. Phase 6 added a nearest-neighbor greedy multi-stop route-ordering baseline through `/vrp/greedy`, return-to-depot support, edge-case benchmarks, load probes, improvement-metric readiness, and a Phase 7-ready `/vrp/compare` response contract.

Strict production decision:

* `GET /route` remains normal A* because Phase 4 evidence showed A* is faster overall at p50/p95/p99 route latency.
* `GET /route/compare` retains Bidirectional A* for comparison and algorithm analysis.
* `POST /matrix` supports `source_dijkstra`, `bidirectional_astar`, and `astar`.
* `source_dijkstra` is the preferred matrix algorithm for larger N×N matrices because it scales better than repeated pairwise routing.
* `POST /vrp/greedy` uses the Phase 5 matrix layer as its distance source and returns a valid nearest-neighbor baseline route order.
* Greedy ordering is intentionally treated as a baseline heuristic, not as an optimal VRP solver. Phase 7 will add 2-Opt optimization and `/vrp/compare`.

---

## Current Phase Status

| Tier   | Phase                                                                  | Status      |
| ------ | ---------------------------------------------------------------------- | ----------- |
| Tier 1 | Phase 1 — Project Foundation                                           | Complete    |
| Tier 1 | Phase 2 — Graph Loading & Validation                                   | Complete    |
| Tier 1 | Phase 3 — A* Routing                                                   | Complete    |
| Tier 1 | Phase 3.5 — Folium Route Verification                                  | Complete    |
| Tier 1 | Phase 4 — Bidirectional A* Comparison                                  | Complete    |
| Tier 2 | Phase 5 — Distance Matrix + Redis Cache + Source-Dijkstra Optimization | Complete    |
| Tier 2 | Phase 6 — Greedy Multi-Stop Baseline + Hardening                       | Complete    |
| Tier 2 | Phase 7 — 2-Opt Optimization + VRP Compare                             | Ready to start |
| Tier 3 | Phase 8+ — Advanced Optimization / Dispatch                            | Not started |

---

## What is implemented

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
* Docker code-staleness check proving optimized Phase 4 code is inside the container

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
* Full Phase 5 regression coverage: 143 tests passed

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
* Cache hit/miss visibility through `cache_used`
* 1–24 stop validation because the matrix layer supports 25 total locations including depot
* Invalid 25-stop request rejection with HTTP `422`
* Graph-not-loaded behavior with HTTP `503`
* Snap-index-missing behavior with HTTP `503`
* Edge-case benchmark coverage for clustered, spread-out, near-duplicate, seeded-random, zigzag, and return-to-start cases
* Local and Docker benchmark evidence
* Docker and local 24-stop load probes
* Phase 7 improvement metric utility
* Phase 7-ready `/vrp/compare` schema contract
* Formal Phase 6 audit and raw evidence pack

---

## What is not implemented yet

The following are intentionally not implemented yet:

* 2-Opt route optimization
* Actual `POST /vrp/compare` endpoint
* Large Neighborhood Search
* Driver-order dispatch
* Hungarian assignment algorithm
* Grafana/Prometheus observability integration
* Public production deployment for the latest Tier 2 state
* ALT landmark heuristic
* Smart algorithm selector (`/route/smart`)
* Traffic-aware ETA
* Authentication / user accounts

These belong to later phases or optional advanced routing extensions.

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

| Metric                       |                                Value |
| ---------------------------- | -----------------------------------: |
| City label                   | Kanpur Central, Uttar Pradesh, India |
| Active graph                 | `data/graphs/kanpur_central.graphml` |
| Nodes                        |                               12,969 |
| Edges                        |                               34,996 |
| GraphML file size            |                             12.74 MB |
| Weakly connected components  |                                    1 |
| Largest weak component nodes |                               12,969 |
| Is weakly connected          |                                 true |
| Snap index method            |                             BallTree |
| Graph load time              |                           ~3.0–3.3 s |
| Runtime memory               |                              ~380 MB |

Important note: this is a directed OSM road graph. Some coordinate pairs can still produce clean `404 No path found` responses because one-way road topology can make certain snapped node pairs unreachable.

---

## Current API Endpoints

| Endpoint          | Method | Purpose                                                   |
| ----------------- | -----: | --------------------------------------------------------- |
| `/`               |    GET | Service index                                             |
| `/health`         |    GET | Service heartbeat                                         |
| `/graph/stats`    |    GET | Loaded graph metadata                                     |
| `/graph/validate` |    GET | Validate GPS coordinate against active graph bounds       |
| `/graph/snap`     |    GET | Snap GPS coordinate to nearest graph node                 |
| `/route`          |    GET | Compute production A* route between two GPS coordinates   |
| `/route/compare`  |    GET | Compare A* and Bidirectional A* on the same snapped route |
| `/matrix`         |   POST | Generate directed N×N distance and ETA matrix             |
| `/vrp/greedy`     |   POST | Compute greedy nearest-neighbor multi-stop route order    |
| `/docs`           |    GET | Swagger UI                                                |

Important note: `/vrp/compare` is not implemented yet. Phase 6 prepared the response contract for Phase 7, but the real endpoint belongs to Phase 7 after 2-Opt exists.

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
    matrix_algorithm = "bidirectional_astar"
    use_cache = $true
} | ConvertTo-Json -Depth 10

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8001/vrp/greedy" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body |
ConvertTo-Json -Depth 20
```

Example response shape:

```json
{
  "status": "ok",
  "phase": "tier2_phase6",
  "algorithm": "nearest_neighbor_greedy",
  "matrix_algorithm": "bidirectional_astar",
  "stop_count": 3,
  "optimized_order": [1, 0, 2],
  "total_distance_m": 12000.0,
  "return_to_start": false,
  "legs": [],
  "matrix_generation_time_ms": 3.113,
  "optimization_time_ms": 0.096,
  "total_time_ms": 3.772,
  "cache_used": true
}
```

Return-to-start mode:

```powershell
$body.return_to_start = $true
```

When `return_to_start=true`, the response contains one extra final leg from the last selected stop back to the start/depot.

---

## Validation Rules

### `/matrix`

| Rule | Behavior |
| ---- | -------- |
| At least 2 locations | Required |
| Max locations | 25 total locations |
| Duplicate location IDs | Rejected |
| Invalid latitude/longitude | Rejected with 422 |
| Graph not loaded | 503 |
| Snap index missing | 503 |

### `/vrp/greedy`

| Rule | Behavior |
| ---- | -------- |
| Exactly one start/depot | Required |
| Stop count | 1 to 24 stops |
| 24 stops | Accepted because 24 stops + 1 depot = 25 matrix locations |
| 25 stops | Rejected with HTTP 422 |
| Invalid latitude/longitude | Rejected with 422 |
| Invalid matrix algorithm | Rejected with 422 |
| Graph not loaded | 503 |
| Snap index missing | 503 |

---

## Test Summary

Run:

```powershell
python -m pytest -v
```

Latest verified Phase 5 full-suite result:

```text
143 passed in 165.74s (0:02:45)
```

Latest verified Phase 6 targeted hardening result:

```text
36 passed in 23.11s
```

Phase 6 targeted hardening included:

```powershell
python -m pytest tests\test_greedy_algorithm.py tests\test_greedy_return_to_start.py tests\test_vrp_greedy_endpoint.py tests\test_vrp_improvement_metrics.py tests\test_vrp_compare_contract.py -v
```

Phase 6 test breakdown:

| Test area | Verified result | Purpose |
| --------- | --------------: | ------- |
| Greedy core algorithm | 12 passed | Matrix validation, deterministic nearest-neighbor order, leg construction |
| Return-to-start logic | 4 passed | Final depot leg, open-route behavior, single-stop return behavior |
| `/vrp/greedy` endpoint | 7 passed | OpenAPI registration, payload validation, graph/snap-index errors |
| VRP improvement metrics | 8 passed | Distance saved, percentage improvement, strict/non-regression flags |
| VRP compare contract | 5 passed | Phase 7-ready response schema contract |
| Combined Phase 6 hardening suite | 36 passed | Phase 6 start-gate and Phase 7 readiness checks |

Overall test coverage includes:

| Test area                          | Purpose                                                                                                                                      |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| A* unit tests                      | Shortest path logic, same-node route, missing node, no path, directed edges, parallel edges                                                  |
| A* correctness tests               | Compare custom A* distance against Dijkstra                                                                                                  |
| A* edge case tests                 | Disconnected graph, directed graph behavior, fallback edge lengths                                                                           |
| Bidirectional A* unit tests        | Result object, alias function, same-node route, missing nodes, no path, directed edges, parallel edges, fallback lengths, expansion counters |
| Bidirectional A* correctness tests | Compare Bidirectional A* against A* and Dijkstra on real graph route pairs                                                                   |
| Haversine admissibility tests      | Verify heuristic does not overestimate sampled real graph routes                                                                             |
| Graph endpoint tests               | Graph stats, validation, snapping, connectivity metadata                                                                                     |
| Route endpoint tests               | Valid `/route` response and error behavior                                                                                                   |
| Route compare endpoint tests       | `/route/compare` sections, snapping consistency, distance equality, error behavior                                                           |
| Route geometry tests               | Verify geometry points come from graph nodes                                                                                                 |
| Route map tests                    | Verify Folium map generation and invalid geometry rejection                                                                                  |
| Matrix endpoint tests              | `/matrix` API response, graph-not-loaded behavior, snap-index missing behavior, invalid payload rejection                                    |
| Matrix service tests               | Matrix validation and service response behavior                                                                                              |
| Matrix cache key tests             | Stable cache key generation and algorithm-sensitive cache identity                                                                           |
| Redis cache tests                  | Redis get/set/delete, corrupt JSON handling, error behavior                                                                                  |
| Graph adjacency tests              | Directed, undirected, MultiDiGraph, fallback length, isolated nodes                                                                          |
| Multi-target Dijkstra tests        | Source-wise shortest paths, unreachable targets, directionality, count helpers                                                               |
| Source-Dijkstra matrix tests       | Matrix correctness, asymmetry, failures, bidirectional comparison                                                                            |
| Greedy VRP tests                   | Greedy route order, route legs, return-to-depot, endpoint validation, Phase 7 compare contract                                               |

---

## Phase 5 Benchmark Evidence

### Phase 5 baseline cache benchmark

| Mode   | 5x5 cache median | 10x10 cache median | 15x15 cache median | Cache confirmed |
| ------ | ---------------: | -----------------: | -----------------: | --------------- |
| Local  |        11.123 ms |          12.174 ms |          13.159 ms | true            |
| Docker |         7.436 ms |           7.821 ms |           8.589 ms | true            |

### Phase 5 cache probe

| Mode   | 5x5 hit median | 10x10 hit median | 15x15 hit median | Under 20 ms |
| ------ | -------------: | ---------------: | ---------------: | ----------- |
| Local  |      12.780 ms |        11.356 ms |        11.426 ms | true        |
| Docker |       6.717 ms |         7.460 ms |         8.114 ms | true        |

Verdict:

```text
PASS — Redis cache hit behavior is confirmed locally and in Docker. Normal cache-hit medians stay under the 20 ms target.
```

### Phase 5 correctness benchmark

| Mode   |  Size | Shape OK | Diagonal zero | Failed pairs zero | Route mismatch count |
| ------ | ----: | -------- | ------------- | ----------------- | -------------------: |
| Local  |   5x5 | true     | true          | true              |                    0 |
| Local  | 10x10 | true     | true          | true              |                    0 |
| Local  | 15x15 | true     | true          | true              |                    0 |
| Docker |   5x5 | true     | true          | true              |                    0 |
| Docker | 10x10 | true     | true          | true              |                    0 |
| Docker | 15x15 | true     | true          | true              |                    0 |

Verdict:

```text
PASS — Matrix shape, diagonal zero behavior, failed-pair handling, and selected route-pair correctness passed locally and in Docker.
```

### Phase 5 parallel-vs-serial benchmark

| Mode   | 5x5 speedup | 10x10 speedup | 15x15 speedup | 4x target |
| ------ | ----------: | ------------: | ------------: | --------- |
| Local  |      0.896x |        0.831x |        0.674x | fail      |
| Docker |      1.063x |        0.814x |        0.688x | fail      |

Verdict:

```text
FAIL for original threaded pairwise implementation.
```

Interpretation:

The baseline pairwise matrix implementation was correct and cache-fast, but thread-based parallelism did not produce the expected speedup. The workload is CPU-bound and dominated by Python/NetworkX graph traversal, priority-queue operations, and object/dictionary access. ThreadPool overhead and Python GIL contention outweighed the benefit of parallel pair execution.

This finding triggered the Phase 5 source-wise Dijkstra optimization patch.

---

## Phase 5 Source-Dijkstra Optimization Evidence

Source-Dijkstra reduces matrix computation from repeated pairwise routing toward one source-wise shortest-path expansion per unique snapped source node.

### Local comparison

|  Size | Bidirectional median | Source-Dijkstra median | Speedup | Mismatch count |
| ----: | -------------------: | ---------------------: | ------: | -------------: |
|   5x5 |           130.777 ms |             173.735 ms |  0.753x |              0 |
| 10x10 |          1255.083 ms |             516.540 ms |  2.430x |              0 |
| 15x15 |          4645.089 ms |             695.695 ms |  6.677x |              0 |

### Docker comparison

|  Size | Bidirectional median | Source-Dijkstra median | Speedup | Mismatch count |
| ----: | -------------------: | ---------------------: | ------: | -------------: |
|   5x5 |           132.196 ms |             189.519 ms |  0.698x |              0 |
| 10x10 |          1355.156 ms |             502.995 ms |  2.694x |              0 |
| 15x15 |          4637.942 ms |             678.859 ms |  6.832x |              0 |

Verdict:

```text
PASS for larger matrix workloads.
```

Interpretation:

* `source_dijkstra` is slower for 5x5 because adjacency-build and setup overhead dominate.
* `source_dijkstra` becomes faster at 10x10.
* `source_dijkstra` exceeds the 4x speedup target at 15x15 locally and in Docker.
* Matrix mismatch count is 0 at 0.01 m tolerance.

---

## Phase 5 Source-Dijkstra Correctness

| Mode   |  Size | Request 200 | Shape OK | Diagonal zero | Failed pairs zero | Route mismatch count | Bidirectional match |
| ------ | ----: | ----------- | -------- | ------------- | ----------------- | -------------------: | ------------------- |
| Local  |   5x5 | true        | true     | true          | true              |                    0 | true                |
| Local  | 10x10 | true        | true     | true          | true              |                    0 | true                |
| Local  | 15x15 | true        | true     | true          | true              |                    0 | true                |
| Docker |   5x5 | true        | true     | true          | true              |                    0 | true                |
| Docker | 10x10 | true        | true     | true          | true              |                    0 | true                |
| Docker | 15x15 | true        | true     | true          | true              |                    0 | true                |

Correctness tolerance:

```text
0.01 m
```

Reason for tolerance: two valid shortest-path implementations may accumulate floating-point edge lengths in slightly different orders. Earlier mismatch samples were only 0.001–0.004 m, which is millimeter-level noise, not a real route difference.

---

## Phase 5 Stress Test Evidence

Stress testing uses the maximum configured matrix size:

```text
25x25 = 625 directed matrix cells
```

### Source-Dijkstra cold compute stress — cache OFF

#### Local

| Concurrency | Success rate |  API median |      API p95 | Generation median | Generation p95 | Failed pairs zero |
| ----------: | -----------: | ----------: | -----------: | ----------------: | -------------: | ----------------- |
|           1 |         100% |  931.211 ms | 11286.762 ms |        870.096 ms |     961.906 ms | true              |
|           2 |         100% | 3202.097 ms |  4324.134 ms |       2975.529 ms |    3970.184 ms | true              |
|           4 |         100% | 4330.184 ms |  4444.123 ms |       4036.485 ms |    4423.446 ms | true              |

#### Docker

| Concurrency | Success rate |  API median |     API p95 | Generation median | Generation p95 | Failed pairs zero |
| ----------: | -----------: | ----------: | ----------: | ----------------: | -------------: | ----------------- |
|           1 |         100% | 1130.096 ms | 1393.086 ms |       1110.251 ms |    1383.160 ms | true              |
|           2 |         100% | 2447.795 ms | 2565.872 ms |       2407.233 ms |    2544.074 ms | true              |
|           4 |         100% | 4590.977 ms | 4730.360 ms |       4527.346 ms |    4714.668 ms | true              |

Verdict:

```text
PASS for stability and correctness.
```

Interpretation:

Concurrent cold-compute latency increases because each request performs a full 25x25 matrix computation. Multiple matrix requests compete for CPU and graph traversal resources on a single API process.

### Source-Dijkstra cache stress — cache ON

#### Local

| Concurrency | Success rate | API median |     API p95 | Generation median | Generation p95 | Cache all hits | Failed pairs zero |
| ----------: | -----------: | ---------: | ----------: | ----------------: | -------------: | -------------- | ----------------- |
|           1 |         100% | 115.186 ms | 2076.566 ms |          9.309 ms |     949.030 ms | true           | true              |
|           2 |         100% |  15.192 ms |   24.550 ms |          7.835 ms |      10.789 ms | true           | true              |
|           4 |         100% |  27.394 ms |   29.930 ms |         14.239 ms |      16.201 ms | true           | true              |
|           8 |         100% |  39.153 ms |   41.915 ms |         16.697 ms |      21.420 ms | true           | true              |

#### Docker

| Concurrency | Success rate | API median |   API p95 | Generation median | Generation p95 | Cache all hits | Failed pairs zero |
| ----------: | -----------: | ---------: | --------: | ----------------: | -------------: | -------------- | ----------------- |
|           1 |         100% |  10.314 ms | 35.173 ms |          2.982 ms |       4.337 ms | true           | true              |
|           2 |         100% |  12.847 ms | 28.791 ms |          3.142 ms |       5.043 ms | true           | true              |
|           4 |         100% |  24.282 ms | 36.614 ms |          7.819 ms |      15.234 ms | true           | true              |
|           8 |         100% |  52.765 ms | 57.721 ms |         22.789 ms |      29.451 ms | true           | true              |

Verdict:

```text
PASS for cache correctness and stability.
PARTIAL for high-concurrency latency.
```

Important interpretation:

The cache stress probe is primarily a stability and boundary test, not a formal SLA benchmark. The p95 values are based on small request counts and therefore represent outlier sensitivity rather than statistically stable latency guarantees. Normal cache-hit benchmark medians are under 20 ms. Under concurrent 25x25 stress, end-to-end API latency rises because the API still parses requests, builds cache keys, queries Redis, validates response models, serializes 25x25 JSON, and sends the response.

### 25x25 source_dijkstra vs bidirectional_astar

Docker cold compute comparison at concurrency 1:

| Algorithm             | Generation median |
| --------------------- | ----------------: |
| `bidirectional_astar` |      12362.309 ms |
| `source_dijkstra`     |       1110.251 ms |

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

Phase 6 evidence is stored under:

```text
benchmarks/phase_6/docker_results
benchmarks/phase_6/local_results
```

A collector script generated a raw index and full dump from 26 JSON files:

```text
benchmarks/phase_6/phase6_all_results_index.md
benchmarks/phase_6/phase6_all_results_index.csv
benchmarks/phase_6/phase6_all_results_index.json
benchmarks/phase_6/phase6_all_raw_dump.json
```

### Phase 6 normal Docker greedy benchmark

| Stops | Route mode | Success | Orders valid | Legs valid | Cache hits/misses | API median | Matrix median | Greedy median | Response median | Distance median |
| ----: | ---------- | ------- | ------------ | ---------- | ----------------- | ---------: | ------------: | ------------: | --------------: | --------------: |
| 5     | open       | 5/5     | true         | true       | —                 | 12.930 ms  | 3.102 ms      | 0.052 ms      | 3.599 ms        | 11,475.024 m |
| 10    | open       | 5/5     | true         | true       | —                 | 13.546 ms  | 3.113 ms      | 0.088 ms      | 3.715 ms        | 18,318.919 m |
| 15    | open       | 5/5     | true         | true       | —                 | 13.612 ms  | 3.353 ms      | 0.130 ms      | 4.085 ms        | 26,590.851 m |
| 24    | open       | 5/5     | true         | true       | —                 | 13.331 ms  | 3.075 ms      | 0.139 ms      | 3.882 ms        | 41,486.728 m |

### Phase 6 Docker route-mode benchmark

| Stops | Route mode | Success | Cache hits | Cache misses | API median | Matrix median | Greedy median | Response median | Distance median |
| ----: | ---------- | ------- | ---------: | -----------: | ---------: | ------------: | ------------: | --------------: | --------------: |
| 5     | open             | 5/5 | 4 | 1 | 14.262 ms | 3.920 ms | 0.061 ms | 4.529 ms | 11,475.024 m |
| 5     | return_to_start  | 5/5 | 5 | 0 | 13.905 ms | 3.356 ms | 0.060 ms | 3.813 ms | 17,955.980 m |
| 10    | open             | 5/5 | 4 | 1 | 12.654 ms | 3.069 ms | 0.102 ms | 3.694 ms | 18,318.919 m |
| 10    | return_to_start  | 5/5 | 5 | 0 | 13.360 ms | 3.113 ms | 0.096 ms | 3.772 ms | 27,524.303 m |
| 15    | open             | 5/5 | 4 | 1 | 15.086 ms | 3.837 ms | 0.140 ms | 4.649 ms | 26,590.851 m |
| 15    | return_to_start  | 5/5 | 5 | 0 | 12.467 ms | 2.841 ms | 0.129 ms | 3.435 ms | 33,976.769 m |
| 24    | open             | 5/5 | 4 | 1 | 13.481 ms | 3.579 ms | 0.225 ms | 4.356 ms | 41,486.728 m |
| 24    | return_to_start  | 5/5 | 5 | 0 | 13.031 ms | 3.366 ms | 0.221 ms | 4.389 ms | 50,340.083 m |

Verdict:

```text
PASS — Docker greedy endpoint remained stable from 5 to 24 stops. Greedy optimization itself stayed sub-millisecond, including the 24-stop upper boundary.
```

### Phase 6 local return-to-start benchmark

| Stops | Route mode | Success | Cache hits | Cache misses | API median | Matrix median | Greedy median | Response median | Distance median |
| ----: | ---------- | ------- | ---------: | -----------: | ---------: | ------------: | ------------: | --------------: | --------------: |
| 5     | return_to_start  | 5/5 | 5 | 0 | 37.196 ms | 8.396 ms | 0.072 ms | 8.953 ms | 17,955.980 m |
| 10    | return_to_start  | 5/5 | 5 | 0 | 15.440 ms | 8.681 ms | 0.118 ms | 9.205 ms | 27,524.303 m |
| 15    | return_to_start  | 5/5 | 5 | 0 | 17.805 ms | 9.339 ms | 0.152 ms | 10.295 ms | 33,976.769 m |
| 24    | return_to_start  | 5/5 | 5 | 0 | 17.092 ms | 8.631 ms | 0.311 ms | 9.810 ms | 50,340.083 m |

Verdict:

```text
PASS — Local return-to-start benchmark confirmed the same route-distance outputs as Docker, with all orders and leg counts valid.
```

### Phase 6 edge-case benchmark

Edge-case coverage included:

```text
clustered_8
spread_out_10
near_duplicate_8
seeded_random_42_12
seeded_random_123_12
zigzag_order_16
return_to_start_seeded_42_12
```

#### Docker edge cases

| Case | Stops | Return to start | Success | Orders valid | Legs valid | Return leg valid | Cache hits/misses | API median | Matrix median | Greedy median | Distance median |
| ---- | ----: | -------------- | ------- | ------------ | ---------- | ---------------- | ----------------- | ---------: | ------------: | ------------: | --------------: |
| clustered_8 | 8 | false | 5/5 | true | true | — | 4/1 | 13.058 ms | 3.240 ms | 0.077 ms | 14,845.618 m |
| spread_out_10 | 10 | false | 5/5 | true | true | — | 4/1 | 13.060 ms | 3.144 ms | 0.090 ms | 32,139.889 m |
| near_duplicate_8 | 8 | false | 5/5 | true | true | — | 4/1 | 13.653 ms | 3.578 ms | 0.079 ms | 10,334.174 m |
| seeded_random_42_12 | 12 | false | 5/5 | true | true | — | 4/1 | 14.731 ms | 3.556 ms | 0.118 ms | 30,838.768 m |
| seeded_random_123_12 | 12 | false | 5/5 | true | true | — | 4/1 | 13.454 ms | 3.338 ms | 0.116 ms | 24,712.212 m |
| zigzag_order_16 | 16 | false | 5/5 | true | true | — | 4/1 | 14.040 ms | 3.433 ms | 0.135 ms | 29,173.851 m |
| return_to_start_seeded_42_12 | 12 | true | 5/5 | true | true | true | 5/0 | 14.461 ms | 3.395 ms | 0.128 ms | 40,048.614 m |

#### Local edge cases

| Case | Stops | Return to start | Success | Orders valid | Legs valid | Return leg valid | Cache hits/misses | API median | Matrix median | Greedy median | Distance median |
| ---- | ----: | -------------- | ------- | ------------ | ---------- | ---------------- | ----------------- | ---------: | ------------: | ------------: | --------------: |
| clustered_8 | 8 | false | 5/5 | true | true | — | 5/0 | 14.620 ms | 7.697 ms | 0.082 ms | 14,845.618 m |
| spread_out_10 | 10 | false | 5/5 | true | true | — | 5/0 | 16.380 ms | 7.882 ms | 0.113 ms | 32,139.889 m |
| near_duplicate_8 | 8 | false | 5/5 | true | true | — | 5/0 | 15.357 ms | 7.815 ms | 0.097 ms | 10,334.174 m |
| seeded_random_42_12 | 12 | false | 5/5 | true | true | — | 5/0 | 15.825 ms | 8.700 ms | 0.125 ms | 30,838.768 m |
| seeded_random_123_12 | 12 | false | 5/5 | true | true | — | 5/0 | 15.832 ms | 8.747 ms | 0.128 ms | 24,712.212 m |
| zigzag_order_16 | 16 | false | 5/5 | true | true | — | 5/0 | 14.827 ms | 7.945 ms | 0.184 ms | 29,173.851 m |
| return_to_start_seeded_42_12 | 12 | true | 5/5 | true | true | true | 5/0 | 13.973 ms | 7.550 ms | 0.077 ms | 40,048.614 m |

Verdict:

```text
PASS — Edge-case coverage is sufficient for Phase 6. Greedy validity was confirmed across clustered, spread-out, near-duplicate, seeded-random, zigzag, and return-to-start cases in both Docker and local environments.
```

Important interpretation:

Near-duplicate coordinates can produce zero-distance legs if multiple coordinates snap to the same road-network node. This is acceptable if the route order remains valid and the API response is consistent.

### Phase 6 robustness and load probe

| Mode | Route mode | Stops | Requests | Workers | Success | Cache hits/misses | Orders valid | Legs valid | Invalid 25-stop rejection | API median | API p95 | Matrix median | Greedy median | Response median |
| ---- | ---------- | ----: | -------: | ------: | ------- | ----------------- | ------------ | ---------- | ------------------------- | ---------: | ------: | ------------: | ------------: | --------------: |
| Docker | open            | 24 | 20 | 5 | 20/20 | 20/0 | true | true | 422 | 40.951 ms | 76.087 ms | 13.466 ms | 0.223 ms | 16.489 ms |
| Docker | return_to_start | 24 | 20 | 5 | 20/20 | 20/0 | true | true | 422 | 37.646 ms | 50.056 ms | 8.218 ms | 0.248 ms | 9.430 ms |
| Local  | open            | 24 | 20 | 5 | 20/20 | 20/0 | true | true | 422 | 34.679 ms | 44.738 ms | 13.846 ms | 0.324 ms | 15.754 ms |
| Local  | return_to_start | 24 | 20 | 5 | 20/20 | 20/0 | true | true | 422 | 34.093 ms | 50.574 ms | 14.090 ms | 0.293 ms | 16.073 ms |

Verdict:

```text
PASS — 24-stop upper-bound requests passed under repeated 20-request / 5-worker probes locally and in Docker. Invalid 25-stop requests were correctly rejected with HTTP 422.
```

Engineering interpretation:

The configured valid upper boundary is 24 stops because the matrix service supports 25 total matrix locations including the depot. The load probe demonstrates endpoint stability and validation correctness at the configured boundary. It is not a claim of unlimited VRP scale.

---

## Phase 6 Evidence Files

Expected Phase 6 evidence directories:

```text
benchmarks/phase_6/docker_results
benchmarks/phase_6/local_results
```

Important evidence files include:

```text
phase6_greedy_benchmark_5_stops_open.json
phase6_greedy_benchmark_10_stops_open.json
phase6_greedy_benchmark_15_stops_open.json
phase6_greedy_benchmark_24_stops_open.json
phase6_greedy_benchmark_5_stops_return_to_start.json
phase6_greedy_benchmark_10_stops_return_to_start.json
phase6_greedy_benchmark_15_stops_return_to_start.json
phase6_greedy_benchmark_24_stops_return_to_start.json
phase6_greedy_edge_cases_docker.json
phase6_greedy_edge_cases_local.json
phase6_greedy_load_probe_24_stops_open_docker.json
phase6_greedy_load_probe_24_stops_return_to_start_docker.json
phase6_greedy_load_probe_24_stops_open_local.json
phase6_greedy_load_probe_24_stops_return_to_start_local.json
phase6_all_results_index.md
phase6_all_results_index.csv
phase6_all_results_index.json
phase6_all_raw_dump.json
```

---

## Phase 6 Final Verdict

Tier 2 Phase 6 is accepted as complete.

The `/vrp/greedy` endpoint successfully provides a stable nearest-neighbor baseline for multi-stop route ordering. It correctly integrates with the Phase 5 matrix service, preserves cache metadata, supports open-route and return-to-start modes, validates route order and leg count, rejects invalid 25-stop requests with HTTP `422`, and remains stable at the configured 24-stop upper boundary in both local and Docker environments.

Harsh verdict:

| Area | Verdict |
| ---- | ------- |
| `/vrp/greedy` functional response | PASS |
| Greedy core route-ordering logic | PASS |
| Return-to-start/depot logic | PASS |
| Matrix-service integration | PASS |
| Redis cache metadata preservation | PASS |
| Edge-case robustness | PASS |
| 24-stop upper-bound behavior | PASS |
| 25-stop invalid rejection | PASS |
| Docker/local parity | PASS |
| Phase 7 improvement metric readiness | PASS |
| Phase 7 `/vrp/compare` contract readiness | PASS |
| Greedy optimality | NOT CLAIMED |
| Actual 2-Opt optimization | NOT IMPLEMENTED YET |
| Actual `/vrp/compare` endpoint | NOT IMPLEMENTED YET |

Final engineering conclusion:

```text
Phase 6 is functionally complete, benchmarked, edge-case tested, return-to-depot tested, load-probed at the configured boundary, and ready to serve as the baseline for Phase 7 2-Opt optimization.
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

Run Phase 5 targeted tests:

```powershell
python -m pytest tests\test_matrix_endpoint.py -v
python -m pytest tests\test_matrix_service.py -v
python -m pytest tests\test_matrix_cache_key.py -v
python -m pytest tests\test_redis_cache.py -v
python -m pytest tests\test_graph_adjacency.py -v
python -m pytest tests\test_multi_target_dijkstra.py -v
python -m pytest tests\test_distance_matrix_source_dijkstra.py -v
```

Run Phase 6 targeted tests:

```powershell
python -m pytest tests\test_greedy_algorithm.py -v
python -m pytest tests\test_greedy_return_to_start.py -v
python -m pytest tests\test_vrp_greedy_endpoint.py -v
python -m pytest tests\test_vrp_improvement_metrics.py -v
python -m pytest tests\test_vrp_compare_contract.py -v
```

Run Phase 6 combined hardening tests:

```powershell
python -m pytest tests\test_greedy_algorithm.py tests\test_greedy_return_to_start.py tests\test_vrp_greedy_endpoint.py tests\test_vrp_improvement_metrics.py tests\test_vrp_compare_contract.py -v
```

Run the automated Phase 5 test script:

```powershell
.\scripts\run_phase5_tests.ps1
```

---

## Benchmark Commands

### Phase 5 automated benchmark runner

Run local Phase 5 + Phase 5 optimization benchmarks:

```powershell
.\scripts\run_phase5_benchmarks.ps1 -Mode local
```

Run Docker Phase 5 + Phase 5 optimization benchmarks:

```powershell
.\scripts\run_phase5_benchmarks.ps1 -Mode docker
```

Run only Phase 5 optimization benchmarks:

```powershell
.\scripts\run_phase5_benchmarks.ps1 -Mode local -SkipPhase5
.\scripts\run_phase5_benchmarks.ps1 -Mode docker -SkipPhase5
```

Run only baseline Phase 5 benchmarks:

```powershell
.\scripts\run_phase5_benchmarks.ps1 -Mode local -SkipPhase51
.\scripts\run_phase5_benchmarks.ps1 -Mode docker -SkipPhase51
```

### Phase 5 stress probes

Local cold 25x25 source-Dijkstra stress:

```powershell
python benchmarks\phase5_stress_probe.py --mode local --n 25 --algorithm source_dijkstra --concurrency-levels 1,2,4 --requests-per-level 4
```

Local cache-hit 25x25 stress:

```powershell
python benchmarks\phase5_stress_probe.py --mode local --n 25 --algorithm source_dijkstra --use-cache --prewarm-cache --concurrency-levels 1,2,4,8 --requests-per-level 8
```

Docker cold 25x25 source-Dijkstra stress:

```powershell
python benchmarks\phase5_stress_probe.py --mode docker --n 25 --algorithm source_dijkstra --concurrency-levels 1,2,4 --requests-per-level 4
```

Docker cache-hit 25x25 stress:

```powershell
python benchmarks\phase5_stress_probe.py --mode docker --n 25 --algorithm source_dijkstra --use-cache --prewarm-cache --concurrency-levels 1,2,4,8 --requests-per-level 8
```

Docker old-algorithm 25x25 comparison stress:

```powershell
python benchmarks\phase5_stress_probe.py --mode docker --n 25 --algorithm bidirectional_astar --concurrency-levels 1,2 --requests-per-level 2
```

### Phase 6 greedy benchmarks

Docker open-route benchmark:

```powershell
python benchmarks\phase_6\phase6_greedy_benchmark.py --mode docker --sizes 5,10,15,24 --iterations 5 --matrix-algorithm bidirectional_astar --use-cache
```

Docker return-to-start benchmark:

```powershell
python benchmarks\phase_6\phase6_greedy_benchmark.py --mode docker --sizes 5,10,15,24 --iterations 5 --matrix-algorithm bidirectional_astar --use-cache --return-to-start
```

Local open-route benchmark:

```powershell
python benchmarks\phase_6\phase6_greedy_benchmark.py --mode local --sizes 5,10,15,24 --iterations 5 --matrix-algorithm bidirectional_astar --use-cache
```

Local return-to-start benchmark:

```powershell
python benchmarks\phase_6\phase6_greedy_benchmark.py --mode local --sizes 5,10,15,24 --iterations 5 --matrix-algorithm bidirectional_astar --use-cache --return-to-start
```

Docker edge-case benchmark:

```powershell
python benchmarks\phase_6\phase6_greedy_edge_cases.py --mode docker --iterations 5 --matrix-algorithm bidirectional_astar --use-cache
```

Local edge-case benchmark:

```powershell
python benchmarks\phase_6\phase6_greedy_edge_cases.py --mode local --iterations 5 --matrix-algorithm bidirectional_astar --use-cache
```

Docker 24-stop load probe:

```powershell
python benchmarks\phase_6\phase6_greedy_load_probe.py --mode docker --stop-count 24 --requests 20 --workers 5 --matrix-algorithm bidirectional_astar --use-cache
python benchmarks\phase_6\phase6_greedy_load_probe.py --mode docker --stop-count 24 --requests 20 --workers 5 --matrix-algorithm bidirectional_astar --use-cache --return-to-start
```

Local 24-stop load probe:

```powershell
python benchmarks\phase_6\phase6_greedy_load_probe.py --mode local --stop-count 24 --requests 20 --workers 5 --matrix-algorithm bidirectional_astar --use-cache
python benchmarks\phase_6\phase6_greedy_load_probe.py --mode local --stop-count 24 --requests 20 --workers 5 --matrix-algorithm bidirectional_astar --use-cache --return-to-start
```

Collect Phase 6 evidence:

```powershell
python benchmarks\phase_6\collect_phase6_evidence.py
```

---

## Evidence Files

Expected Phase 5 evidence directories:

```text
benchmarks/phase5/local_results
benchmarks/phase5/docker_results
benchmarks/phase5_1/local_results
benchmarks/phase5_1/docker_results
```

Important Phase 5 evidence files include:

```text
phase5_matrix_benchmark_5x5.json
phase5_matrix_benchmark_10x10.json
phase5_matrix_benchmark_15x15.json
phase5_cache_probe_5x5.json
phase5_cache_probe_10x10.json
phase5_cache_probe_15x15.json
phase5_parallel_vs_serial_5x5.json
phase5_parallel_vs_serial_10x10.json
phase5_parallel_vs_serial_15x15.json
phase5_matrix_correctness_5x5.json
phase5_matrix_correctness_10x10.json
phase5_matrix_correctness_15x15.json
phase5_stress_source_dijkstra_cache_off_25x25.json
phase5_stress_source_dijkstra_cache_on_25x25.json
phase5_stress_bidirectional_astar_cache_off_25x25.json
phase5_1_algorithm_comparison_5x5.json
phase5_1_algorithm_comparison_10x10.json
phase5_1_algorithm_comparison_15x15.json
phase5_1_source_dijkstra_correctness_5x5.json
phase5_1_source_dijkstra_correctness_10x10.json
phase5_1_source_dijkstra_correctness_15x15.json
```

Note: `phase5_1` is an evidence folder for the optimization patch. The audit should still be treated as **Phase 5**, not a separate phase.

Expected Phase 6 evidence directories:

```text
benchmarks/phase_6/docker_results
benchmarks/phase_6/local_results
```

Important Phase 6 evidence files include:

```text
phase6_greedy_benchmark_5_stops_open.json
phase6_greedy_benchmark_10_stops_open.json
phase6_greedy_benchmark_15_stops_open.json
phase6_greedy_benchmark_24_stops_open.json
phase6_greedy_benchmark_5_stops_return_to_start.json
phase6_greedy_benchmark_10_stops_return_to_start.json
phase6_greedy_benchmark_15_stops_return_to_start.json
phase6_greedy_benchmark_24_stops_return_to_start.json
phase6_greedy_edge_cases_docker.json
phase6_greedy_edge_cases_local.json
phase6_greedy_load_probe_24_stops_open_docker.json
phase6_greedy_load_probe_24_stops_return_to_start_docker.json
phase6_greedy_load_probe_24_stops_open_local.json
phase6_greedy_load_probe_24_stops_return_to_start_local.json
phase6_all_results_index.md
phase6_all_results_index.csv
phase6_all_results_index.json
phase6_all_raw_dump.json
```

---

## Current Known Risks and Notes

| Risk / note                                                                         | Status                                                         |
| ----------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| Some random coordinate pairs return `404 No path found`                             | Expected directed routing behavior                             |
| Bidirectional A* p99 is above the 120 ms production route target                    | Documented; not used as production `/route` algorithm          |
| A* remains faster overall than Bidirectional A* for single-route production routing | Documented; `/route` remains A*                                |
| Original Phase 5 threaded pairwise matrix failed speedup target                     | Documented; fixed for larger matrices by source-Dijkstra patch |
| `source_dijkstra` is slower for 5x5 matrices                                        | Documented fixed-overhead trade-off                            |
| Concurrent cold 25x25 matrix requests increase latency                              | Expected CPU-bound behavior on single API process              |
| Stress p95 is based on small samples                                                | Treated as outlier indicator, not formal SLA                   |
| Cache hit stress remains correct but API latency rises under higher concurrency     | Documented                                                     |
| Greedy is a baseline heuristic, not an optimal VRP solver                           | Documented; Phase 7 adds 2-Opt                                 |
| 24 stops is the configured tested greedy limit                                      | Accepted; 25 stops rejected by validation                      |
| Near-duplicate stops can snap to same road node                                     | Accepted if order/legs remain valid                            |
| Phase 6 load probe is boundary robustness evidence, not unlimited-scale proof       | Documented                                                     |
| Actual `/vrp/compare` endpoint is not implemented yet                               | Correctly deferred to Phase 7                                  |
| ETA is formula-based, not traffic-aware                                             | Accepted for current phase                                     |
| Graph covers Kanpur Central bbox, not full city scale                               | Accepted for current project stage                             |
| Public deployment                                                                   | Not completed in current Tier 2 evidence                       |
| Grafana/Prometheus                                                                  | Not integrated yet                                             |

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
│   └── routing_service.py
├── utils/
│   ├── geo_validation.py
│   ├── logger.py
│   ├── matrix_cache_key.py
│   ├── node_snapper.py
│   ├── route_map.py
│   └── snap_index.py
├── config.py
└── main.py

benchmarks/
├── astar_correctness_probe.py
├── astar_route_benchmark.py
├── astar_route_benchmark_routeable.py
├── bidirectional_astar_benchmark.py
├── bidirectional_astar_correctness_probe.py
├── concurrent_route_probe.py
├── heuristic_admissibility_probe.py
├── phase4_route_compare_probe.py
├── phase5_matrix_benchmark.py
├── phase5_cache_probe.py
├── phase5_parallel_vs_serial_probe.py
├── phase5_matrix_correctness_probe.py
├── phase5_stress_probe.py
├── phase5_1_algorithm_comparison.py
├── phase5_1_source_dijkstra_correctness.py
├── phase_6/
│   ├── collect_phase6_evidence.py
│   ├── phase6_greedy_benchmark.py
│   ├── phase6_greedy_edge_cases.py
│   ├── phase6_greedy_load_probe.py
│   ├── docker_results/
│   └── local_results/
├── phase4_results/
├── phase5/
└── phase5_1/

scripts/
├── run_phase5_benchmarks.ps1
└── run_phase5_tests.ps1

tests/
├── test_astar_algorithm_unit.py
├── test_astar_correctness.py
├── test_astar_edge_cases.py
├── test_bidirectional_astar_correctness.py
├── test_bidirectional_astar_unit.py
├── test_distance_matrix_source_dijkstra.py
├── test_geo_validation.py
├── test_graph_adjacency.py
├── test_graph_endpoint.py
├── test_greedy_algorithm.py
├── test_greedy_return_to_start.py
├── test_health.py
├── test_heuristic_admissibility.py
├── test_matrix_cache_key.py
├── test_matrix_endpoint.py
├── test_matrix_service.py
├── test_multi_target_dijkstra.py
├── test_redis_cache.py
├── test_route_compare_endpoint.py
├── test_route_endpoint.py
├── test_route_failure_cases.py
├── test_route_geometry.py
├── test_route_map.py
├── test_vrp_compare_contract.py
├── test_vrp_greedy_endpoint.py
└── test_vrp_improvement_metrics.py
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

## Next Phase

Next planned phase:

```text
Tier 2 — Phase 7: 2-Opt Optimization + VRP Compare
```

Phase 7 should add:

* 2-Opt route-order optimization
* Actual `POST /vrp/compare` endpoint
* Greedy baseline vs 2-Opt improved route comparison
* Distance saved in meters
* Improvement percentage
* Non-regression flag
* Same matrix input shared between Greedy and 2-Opt
* Open-route and return-to-start support
* Phase 7 correctness tests
* Phase 7 benchmark evidence
* Honest comparison showing where 2-Opt improves and where greedy is already near-stable
