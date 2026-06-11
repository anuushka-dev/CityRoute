# CityRoute

CityRoute is an open-source last-mile delivery routing backend built with Python, FastAPI, Docker, OSMnx, NetworkX, scikit-learn, and OpenStreetMap data.

Current status: **Tier 1 — Phase 4 complete: Bidirectional A\* Comparison with Docker Benchmark Evidence**

This project is being built phase-by-phase. Phase 1 created the FastAPI and Docker foundation. Phase 2 added real graph loading, GraphML persistence, GPS validation, graph metadata, node snapping, and BallTree-based snap optimization. Phase 3 added custom A\* routing from scratch with ETA, geometry, correctness probes, and Docker benchmarks. Phase 3.5 added Folium route visualization for visual route verification. Phase 4 added Bidirectional A\*, `/route/compare`, correctness validation, Docker evidence, and A\* vs Bidirectional A\* benchmark comparison.

Strict production decision: **normal A\* remains the production `/route` algorithm**. Bidirectional A\* is retained under `/route/compare` for comparison and algorithm analysis because it matches A\* distance exactly and reduces node expansion, but it is not consistently faster at p50/p95/p99 latency in the 1000-route benchmark.

---

## Current Phase Status

| Tier | Phase | Status |
|---|---|---|
| Tier 1 | Phase 1 — Project Foundation | Complete |
| Tier 1 | Phase 2 — Graph Loading & Validation | Complete |
| Tier 1 | Phase 3 — A\* Routing | Complete |
| Tier 1 | Phase 3.5 — Folium Route Verification | Complete |
| Tier 1 | Phase 4 — Bidirectional A\* Comparison | Complete |
| Tier 2 | Phase 5 — Distance Matrix Service | Next |
| Tier 2 | Phase 6 — Greedy Baseline | Not started |
| Tier 2 | Phase 7 — 2-Opt Optimization | Not started |

---

## What is implemented

### Phase 1 — Project Foundation

- FastAPI backend
- Router-based API structure
- `/health` endpoint
- `/graph/stats` endpoint
- Configuration through `.env`
- Structured logging
- Dockerfile and Docker Compose
- Pytest test setup

### Phase 2 — Graph Loading, Validation, and Fast Snapping

- OSMnx graph loading
- GraphML persistence
- Startup graph loading through FastAPI lifespan
- Real graph metadata through `/graph/stats`
- GPS latitude/longitude validation
- Bounding-box validation for the active graph area
- Structured `422` responses for invalid/out-of-bounds coordinates
- Node snapping from GPS coordinate to nearest graph node
- BallTree snap index built at startup for fast nearest-node lookup
- Snap distance returned in meters
- Graph connectivity metadata in `/graph/stats`
- Local and Docker verification
- Benchmark evidence recorded under `benchmarks/`

### Phase 3 — Custom A\* Routing

- Custom A\* implementation from scratch
- Manual priority queue using `heapq`
- Manual `g_score`, `came_from`, closed set, and path reconstruction
- Haversine straight-line heuristic
- MultiDiGraph edge handling for OSMnx parallel edges
- Shortest parallel edge selection for route distance
- Route endpoint: `GET /route`
- Start and end GPS validation
- Start and end snapping through BallTree
- Route distance in meters and kilometers
- ETA calculation
- Route geometry output as graph-node coordinates
- Node expansion count
- Internal A\* route timing
- Total route request timing
- Clean `404 No path found` handling
- Clean `503 Graph not loaded` handling
- A\* correctness verification against Dijkstra
- Haversine admissibility verification
- Routeable Docker benchmark
- Concurrent Docker route probe
- Docker evidence recorded under `benchmarks/docker_results/`

### Phase 3.5 — Folium Route Verification

- Folium route map generation from `/route` geometry
- Route polyline rendered from real graph node coordinates
- Start and end markers
- Route summary marker
- Rejection of missing or invalid geometry
- HTML route map artifact generation
- Visual verification that route geometry follows road-network nodes

### Phase 4 — Bidirectional A\* Comparison

- Bidirectional A\* implementation from scratch
- Forward and backward graph search
- Directed graph support through successors and predecessors
- MultiDiGraph edge handling
- Meeting-node tracking
- Forward and backward node expansion counters
- Optimized runtime code path with coordinate and edge-length caching
- Alias function for `bidirectional_a_star_shortest_path`
- `/route/compare` endpoint
- A\* and Bidirectional A\* run on the same snapped start/end nodes
- Same-distance comparison with tolerance
- Route timing comparison
- Node expansion comparison
- Correctness tests against A\* and Dijkstra
- 500-pair correctness probe
- 1000-route Docker benchmark
- Docker code-staleness check proving optimized Phase 4 code is inside the container

---

## What is not implemented yet

The following are intentionally not implemented yet:

- Redis caching
- Distance matrix service
- Multi-stop delivery optimization
- Greedy delivery baseline
- 2-Opt optimization
- Large Neighborhood Search
- Driver-order dispatch
- Hungarian algorithm
- Grafana/Prometheus observability integration
- Public deployment
- ALT landmark heuristic
- Smart algorithm selector (`/route/smart`)

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

## Current API Endpoints

| Endpoint | Method | Purpose |
|---|---:|---|
| `/` | GET | Service index |
| `/health` | GET | Service heartbeat |
| `/graph/stats` | GET | Loaded graph metadata |
| `/graph/validate` | GET | Validate GPS coordinate against active graph bounds |
| `/graph/snap` | GET | Snap GPS coordinate to nearest graph node |
| `/route` | GET | Compute production A\* route between two GPS coordinates |
| `/route/compare` | GET | Compare A\* and Bidirectional A\* on the same snapped route |
| `/docs` | GET | Swagger UI |

Docker OpenAPI verification showed:

```text
/health
/graph/stats
/graph/validate
/graph/snap
/route/compare
/route
/
```

---

## Active Graph Baseline

Observed Phase 4 Docker graph values:

| Metric | Value |
|---|---:|
| City label | Kanpur Central, Uttar Pradesh, India |
| Active graph | `data/graphs/kanpur_central.graphml` |
| Nodes | 12,969 |
| Edges | 34,996 |
| Graph loaded | true |
| GraphML file size | 12.74 MB |
| Docker graph load time | 3.252 s |
| Docker graph memory | 380.23 MB |
| Weakly connected components | 1 |
| Largest weak component nodes | 12,969 |
| Is weakly connected | true |
| Snap index loaded | true |
| Snap index build time | 23.112 ms |

Important note: this is a directed OSM road graph. Some coordinate pairs can still produce clean `404 No path found` responses because directionality and one-way road structure can make certain snapped node pairs unreachable.

---

## Full Test Summary

Run:

```powershell
python -m pytest -v
```

Observed Phase 4 result:

```text
81 passed in 136.62s (0:02:16)
```

This confirms Phase 4 did not break earlier Phase 1, Phase 2, Phase 3, or Phase 3.5 behavior.

Test coverage includes:

| Test area | Purpose |
|---|---|
| A\* unit tests | Shortest path logic, same-node route, missing node, no path, directed edges, parallel edges |
| A\* correctness tests | Compare custom A\* distance against Dijkstra |
| A\* edge case tests | Disconnected graph, directed graph behavior, fallback edge lengths |
| Bidirectional A\* unit tests | Result object, alias function, same-node route, missing nodes, no path, directed edges, parallel edges, fallback lengths, expansion counters |
| Bidirectional A\* correctness tests | Compare Bidirectional A\* against A\* and Dijkstra on real graph route pairs |
| Haversine admissibility test | Verify heuristic does not overestimate sampled real graph routes |
| Graph endpoint tests | Graph stats, validation, snapping, connectivity metadata |
| Route endpoint tests | Valid `/route` response and error behavior |
| Route compare endpoint tests | `/route/compare` sections, snapping consistency, distance equality, error behavior |
| Route geometry tests | Verify geometry points come from graph nodes |
| Route map tests | Verify Folium map generation and invalid geometry rejection |
| Health tests | Service status and graph-loaded status |

---

## Phase 4 Targeted Test Summary

| Test file | Result |
|---|---:|
| `tests/test_bidirectional_astar_unit.py` | 12 passed |
| `tests/test_bidirectional_astar_correctness.py` | 3 passed |
| `tests/test_route_compare_endpoint.py` | 11 passed |

Phase 4 targeted total:

```text
26 passed
```

---

## Phase 3 Correctness Evidence

### A\* vs Dijkstra correctness probe

Command:

```powershell
python benchmarks\astar_correctness_probe.py
```

Observed result:

| Metric | Value |
|---|---:|
| Target checks | 500 |
| Passed | 500 |
| Failed | 0 |
| No-path skipped | 0 |
| Distance tolerance | 0.001 m |
| Success rate | 100.0% |
| Runtime | 26.14 s |

This proves the custom A\* route distance matched Dijkstra on 500 sampled route pairs.

---

## Haversine Heuristic Admissibility Evidence

### 1,000-pair smoke probe

```powershell
python benchmarks\heuristic_admissibility_probe.py 1000
```

| Metric | Value |
|---|---:|
| Checked pairs | 1,000 |
| No-path skipped | 3 |
| Overestimates | 0 |
| Worst overestimate | 0.0 m |
| Runtime | 42.205 s |

### 10,000-pair strict probe

```powershell
python benchmarks\heuristic_admissibility_probe.py 10000
```

| Metric | Value |
|---|---:|
| Checked pairs | 10,000 |
| No-path skipped | 18 |
| Overestimates | 0 |
| Worst overestimate | 0.0 m |
| Runtime | 445.858 s |

This supports the Phase 3 claim that the Haversine heuristic is admissible for sampled routes on this graph.

---

## Phase 3 Docker A\* Routeable Benchmark

The accepted Phase 3 benchmark is the routeable benchmark, not the raw random benchmark. It separates clean `404 No path found` cases from real failures.

Command:

```powershell
$env:CITYROUTE_BASE_URL="http://127.0.0.1:8001"
$env:CITYROUTE_RESULTS_DIR="benchmarks/docker_results"
python benchmarks\astar_route_benchmark_routeable.py 1000 5 3000
```

Observed result:

| Metric | Value |
|---|---:|
| Target successful route measurements | 1,000 |
| Attempted requests | 1,008 |
| Successful route measurements | 1,000 |
| Clean no-path `404` skipped | 8 |
| Real failures | 0 |
| Real failure rate | 0.0% |
| No-path rate | 0.794% |
| Zero-distance successes | 3 |
| Runtime | 25.421 s |

### Phase 3 A\* route latency

| Metric | Value |
|---|---:|
| Route min | 0.003 ms |
| Route mean | 15.324 ms |
| Route median | 10.05 ms |
| Route p50 | 10.158 ms |
| Route p95 | 44.759 ms |
| Route p99 | 88.015 ms |
| Route max | 100.108 ms |

### Phase 3 two-snap overhead

Two-snap means start snap + end snap.

| Metric | Value |
|---|---:|
| Two-snap min | 0.439 ms |
| Two-snap mean | 0.600 ms |
| Two-snap median | 0.574 ms |
| Two-snap p50 | 0.574 ms |
| Two-snap p95 | 0.794 ms |
| Two-snap p99 | 0.958 ms |
| Two-snap max | 1.378 ms |

---

## Phase 4 Docker `/route/compare` Sample

Command:

```powershell
python benchmarks\phase4_route_compare_probe.py
```

Sample route:

```text
start_lat=26.44
start_lon=80.30
end_lat=26.45
end_lon=80.35
```

Snapping:

| Metric | Value |
|---|---:|
| Start snapped node | 5,317,312,245 |
| End snapped node | 6,288,159,135 |
| Start snap method | balltree |
| End snap method | balltree |

A\* result:

| Metric | Value |
|---|---:|
| Distance | 6,428.798 m |
| Distance | 6.429 km |
| ETA | 999.5 s |
| ETA | 16.66 min |
| Path node count | 77 |
| Nodes expanded | 2,622 |
| Route time | 34.335 ms |
| Total time | 37.725 ms |

Bidirectional A\* result:

| Metric | Value |
|---|---:|
| Distance | 6,428.798 m |
| Distance | 6.429 km |
| ETA | 999.5 s |
| ETA | 16.66 min |
| Path node count | 77 |
| Nodes expanded | 1,458 |
| Forward nodes expanded | 846 |
| Backward nodes expanded | 612 |
| Route time | 25.036 ms |
| Meeting node | 8,810,239,341 |
| Geometry points | 77 |

Comparison:

| Metric | Value |
|---|---:|
| Distance delta | 0.0 m |
| Same distance | true |
| A\* route time | 34.335 ms |
| Bidirectional A\* route time | 25.036 ms |
| Route-time delta | 9.299 ms |
| Bidirectional faster | true |
| A\* nodes expanded | 2,622 |
| Bidirectional A\* nodes expanded | 1,458 |
| Nodes expanded delta | 1,164 |
| Nodes expanded reduction | 44.394% |
| Route-time reduction | 27.083% |
| Compare total time | 63.84 ms |

Sample route verdict:

```text
PASS — Bidirectional A* produced the same distance, expanded 44.394% fewer nodes, and was 27.083% faster on this fixed sample route.
```

---

## Phase 4 Bidirectional A\* Correctness Probe

Command:

```powershell
python benchmarks\bidirectional_astar_correctness_probe.py 500 2500
```

Observed result:

| Metric | Value |
|---|---:|
| Graph nodes | 12,969 |
| Graph edges | 34,996 |
| Directed graph | true |
| MultiGraph | true |
| Weakly connected | true |
| Target checks | 500 |
| Passed | 500 |
| Failed | 0 |
| No-path skipped | 0 |
| Attempts | 500 |
| Max attempts | 2,500 |
| Distance tolerance | 0.001 m |
| Success rate | 100.0% |
| Runtime | 50.804 s |
| Errors | 0 |

Correctness verdict:

```text
PASS — Bidirectional A* matched the correctness oracle across 500 checked pairs with 0 failures.
```

---

## Phase 4 1000-Route Benchmark

Command:

```powershell
python benchmarks\bidirectional_astar_benchmark.py 1000 5 3000
```

Output file:

```text
benchmarks/phase4_results/phase4_bidirectional_astar_benchmark.json
```

Top-level result:

| Metric | Value |
|---|---:|
| Target successful route measurements | 1,000 |
| Attempted requests | 1,008 |
| Successful route measurements | 1,000 |
| Clean no-path `404` skipped | 8 |
| Real failures | 0 |
| Real failure rate | 0.0% |
| No-path rate | 0.794% |
| Zero-distance successes | 3 |
| Runtime | 57.881 s |

Correctness result:

| Metric | Value |
|---|---:|
| Distance delta min | 0.0 m |
| Distance delta mean | 0.0 m |
| Distance delta median | 0.0 m |
| Distance delta p95 | 0.0 m |
| Distance delta p99 | 0.0 m |
| Distance delta max | 0.0 m |

Correctness verdict:

```text
PASS — A* and Bidirectional A* returned identical route distances across 1000 successful route measurements.
```

### A\* route-time benchmark

| Metric | Value |
|---|---:|
| Min | 0.002 ms |
| Mean | 15.443 ms |
| Median | 10.108 ms |
| p50 | 10.108 ms |
| p95 | 45.044 ms |
| p99 | 87.008 ms |
| Max | 137.109 ms |

### Bidirectional A\* route-time benchmark

| Metric | Value |
|---|---:|
| Min | 0.001 ms |
| Mean | 24.713 ms |
| Median | 15.745 ms |
| p50 | 15.745 ms |
| p95 | 74.384 ms |
| p99 | 157.730 ms |
| Max | 212.528 ms |

Latency verdict:

```text
A* is faster overall in the 1000-route benchmark. Production /route remains normal A*.
```

### Node expansion benchmark

| Metric | A\* | Bidirectional A\* |
|---|---:|---:|
| Min | 0 | 0 |
| Mean | 1,891.226 | 1,711.041 |
| Median | 1,239.5 | 1,097.0 |
| p50 | 1,240 | 1,097 |
| p95 | 5,544 | 5,259 |
| p99 | 11,117 | 10,167 |
| Max | 12,731 | 12,201 |

Node expansion verdict:

```text
Bidirectional A* expands fewer nodes on average and at median, but its additional Python overhead makes it slower overall than normal A* at p50, p95, and p99 route latency.
```

### Route-time target interpretation

Production routing target is evaluated against `/route`, which uses normal A\*.

| Metric | Value | Target | Status |
|---|---:|---:|---|
| Production A\* p99 route time | 87.008 ms | < 120 ms | PASS |
| Bidirectional A\* p99 route time | 157.730 ms | < 120 ms | FAIL for production replacement |

Conclusion:

```text
Phase 4 meets the production routing latency target because /route remains A*. Bidirectional A* is not used as the production route algorithm because its p99 route time exceeds the 120 ms target.
```

---

## Docker Runtime Evidence — Phase 4

Manual Docker run:

```powershell
docker run --rm --name cityroute-tier1-phase4 -p 8001:8000 -v "${PWD}\data:/app/data" cityroute-api:tier1-phase4
```

Docker API base URL:

```text
http://127.0.0.1:8001
```

| Field | Value |
|---|---|
| Container name | `cityroute-tier1-phase4` |
| Image | `cityroute-api:tier1-phase4` |
| Internal port | `8000` |
| Host port | `8001` |
| Runtime command | `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| Data mount | `C:\MYDOWNLOADS\MYPROJECT\CityRoute\data:/app/data` |
| Platform | linux/amd64 |
| Container status | running |
| OOMKilled | false |
| Restart count | 0 |
| AutoRemove | true |

Docker runtime stats after benchmark activity:

| Metric | Value |
|---|---:|
| CPU | 0.20% |
| Memory usage | 344.9 MiB |
| Memory limit shown by Docker | 7.362 GiB |
| Memory percent | 4.57% |
| PIDs | 32 |

Docker code check:

```text
coordinate_cache: True
edge_length_cache: True
```

This confirms the running Docker container used the optimized Phase 4 Bidirectional A\* code path, not stale code.

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
  "nodes_expanded": 2622,
  "geometry": [
    {"lat": 26.4400833, "lon": 80.2999386},
    {"lat": 26.440297, "lon": 80.3002594}
  ]
}
```

The actual `geometry` array contains all route node coordinates. For this sample route, `path_node_count` is 77.

---

## Example `/route/compare` Request

```powershell
Invoke-RestMethod "http://127.0.0.1:8001/route/compare?start_lat=26.44&start_lon=80.30&end_lat=26.45&end_lon=80.35" | ConvertTo-Json -Depth 20
```

Example comparison summary:

```json
{
  "status": "ok",
  "astar": {
    "algorithm": "astar",
    "distance_m": 6428.798,
    "path_node_count": 77,
    "nodes_expanded": 2622,
    "route_time_ms": 34.335
  },
  "bidirectional_astar": {
    "algorithm": "bidirectional_astar",
    "distance_m": 6428.798,
    "path_node_count": 77,
    "nodes_expanded": 1458,
    "forward_nodes_expanded": 846,
    "backward_nodes_expanded": 612,
    "route_time_ms": 25.036,
    "meeting_node": 8810239341
  },
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

## Project Structure

```text
app/
├── api/
│   ├── graph.py
│   ├── health.py
│   └── route.py
├── core/
│   ├── a_star.py
│   ├── bidirectional_a_star.py
│   └── eta.py
├── services/
│   ├── graph_service.py
│   └── routing_service.py
├── utils/
│   ├── geo_validation.py
│   ├── logger.py
│   ├── node_snapper.py
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
├── docker_results/
├── phase4_results/
└── results/

tests/
├── test_astar_algorithm_unit.py
├── test_astar_correctness.py
├── test_astar_edge_cases.py
├── test_bidirectional_astar_correctness.py
├── test_bidirectional_astar_unit.py
├── test_geo_validation.py
├── test_graph_endpoint.py
├── test_health.py
├── test_heuristic_admissibility.py
├── test_route_compare_endpoint.py
├── test_route_endpoint.py
├── test_route_failure_cases.py
├── test_route_geometry.py
└── test_route_map.py
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

Run the app locally:

```powershell
python -m uvicorn app.main:app --reload --port 8000
```

Open Swagger UI:

```text
http://127.0.0.1:8000/docs
```

---

## Docker Setup — Phase 4

Remove old containers:

```powershell
docker rm -f cityroute-tier1-phase3 cityroute-tier1-phase4 2>$null
```

Build the Docker image:

```powershell
docker build --pull=false -t cityroute-api:tier1-phase4 .
```

If Docker tries to reach Docker Hub and internet/DNS fails, use the classic builder:

```powershell
$env:DOCKER_BUILDKIT=0
docker build -t cityroute-api:tier1-phase4 .
```

Run Docker on port `8001` so local Uvicorn can still use port `8000`:

```powershell
docker run --rm --name cityroute-tier1-phase4 -p 8001:8000 -v "${PWD}\data:/app/data" cityroute-api:tier1-phase4
```

Open Docker Swagger UI:

```text
http://127.0.0.1:8001/docs
```

Check Docker health:

```powershell
Invoke-RestMethod "http://127.0.0.1:8001/health"
```

Run sample A\* route:

```powershell
Invoke-RestMethod "http://127.0.0.1:8001/route?start_lat=26.44&start_lon=80.30&end_lat=26.45&end_lon=80.35" | ConvertTo-Json -Depth 20
```

Run sample route comparison:

```powershell
Invoke-RestMethod "http://127.0.0.1:8001/route/compare?start_lat=26.44&start_lon=80.30&end_lat=26.45&end_lon=80.35" | ConvertTo-Json -Depth 20
```

Verify Docker contains the optimized Phase 4 code:

```powershell
docker exec cityroute-tier1-phase4 python -c "from pathlib import Path; text=Path('/app/app/core/bidirectional_a_star.py').read_text(); print('coordinate_cache' in text); print('edge_length_cache' in text)"
```

Expected:

```text
True
True
```

---

## Tests

Run full test suite:

```powershell
python -m pytest -v
```

Expected current result:

```text
81 passed
```

Run Phase 4 targeted tests:

```powershell
python -m pytest tests\test_bidirectional_astar_unit.py tests\test_bidirectional_astar_correctness.py tests\test_route_compare_endpoint.py -v
```

Expected Phase 4 targeted result:

```text
26 passed
```

---

## Benchmark Commands

### Phase 3 A\* correctness

```powershell
python benchmarks\astar_correctness_probe.py
```

### Phase 3 heuristic admissibility

```powershell
python benchmarks\heuristic_admissibility_probe.py 10000
```

### Phase 3 A\* routeable benchmark

```powershell
$env:CITYROUTE_BASE_URL="http://127.0.0.1:8001"
$env:CITYROUTE_RESULTS_DIR="benchmarks/docker_results"
python benchmarks\astar_route_benchmark_routeable.py 1000 5 3000
```

### Phase 4 route compare sample

```powershell
python benchmarks\phase4_route_compare_probe.py
```

### Phase 4 Bidirectional A\* correctness probe

```powershell
python benchmarks\bidirectional_astar_correctness_probe.py 500 2500
```

### Phase 4 1000-route benchmark

```powershell
python benchmarks\bidirectional_astar_benchmark.py 1000 5 3000
```

### Capture Docker memory

```powershell
docker stats cityroute-tier1-phase4 --no-stream
```

---

## Phase 4 Evidence Files

Expected evidence files under:

```text
benchmarks/phase4_results
```

Observed files:

```text
phase4_bidirectional_astar_benchmark.json
phase4_bidirectional_astar_correctness_probe.json
phase4_bidirectional_benchmark_console.txt
phase4_bidirectional_correctness_console.txt
phase4_docker_code_check.txt
phase4_docker_graph_stats.json
phase4_docker_health.json
phase4_docker_inspect.json
phase4_docker_logs_tail300.txt
phase4_docker_openapi_paths.txt
phase4_docker_ps.txt
phase4_docker_stats.txt
phase4_full_pytest.txt
phase4_route_compare_sample.json
phase4_route_compare_summary.json
```

---

## Current Known Risks and Notes

| Risk / note | Status |
|---|---|
| Some random coordinate pairs return `404 No path found` | Expected directed routing behavior |
| Bidirectional A\* p99 is above the 120 ms production target | Documented; not used as production `/route` algorithm |
| A\* remains faster overall in 1000-route benchmark | Documented; `/route` remains A\* |
| Bidirectional A\* reduces median node expansion | Documented; retained under `/route/compare` |
| Docker image size is still high due to OSMnx/geospatial dependencies | Optimization deferred |
| API latency increases under concurrent CPU-bound routing | Expected with single-worker Uvicorn |
| ETA is formula-based, not traffic-aware | Accepted for Tier 1 |
| Redis caching is not integrated yet | Planned for Phase 5 |
| ALT landmark heuristic is not part of the current roadmap | Optional future advanced routing extension |
| Public deployment | Not completed yet |

---

## Phase 4 Acceptance Status

Phase 4 is accepted as complete for:

- Bidirectional A\* implementation
- `/route/compare` endpoint
- Same snapped-node comparison between A\* and Bidirectional A\*
- Distance equality validation
- Node expansion comparison
- Route timing comparison
- Correctness tests against A\* and Dijkstra
- 500-pair correctness probe
- 1000-route Docker benchmark
- Docker runtime evidence
- Docker OpenAPI evidence
- Full project pytest evidence
- Benchmark files under `benchmarks/phase4_results/`

Phase 4 does **not** claim that Bidirectional A\* replaces A\* in production.

Final Phase 4 engineering conclusion:

```text
Bidirectional A* is correct and useful for comparison. It reduces node expansion on average and at median, but normal A* remains faster overall at p50, p95, and p99 route latency. Therefore, /route remains normal A*, while /route/compare remains available for benchmarking and algorithm analysis.
```

---

## Latest Verified Phase 4 Evidence

```text
Full pytest: 81 passed in 136.62s
Docker graph: 12,969 nodes, 34,996 edges
Docker graph load time: 3.252 s
Docker graph memory: 380.23 MB
Snap index build time: 23.112 ms
Docker memory after benchmark: 344.9 MiB
Docker OpenAPI includes /route/compare
Docker code check: coordinate_cache=True, edge_length_cache=True
Route compare sample: same distance true, distance delta 0.0 m
Sample A*: 34.335 ms, 2,622 nodes expanded
Sample Bidirectional A*: 25.036 ms, 1,458 nodes expanded
Sample node reduction: 44.394%
Sample route-time reduction: 27.083%
Bidirectional correctness probe: 500 / 500 passed, 0 failed
1000-route benchmark: 1000 successful route measurements
1000-route benchmark real failures: 0
1000-route benchmark no-path 404 skipped: 8
A* p50 / p95 / p99: 10.108 ms / 45.044 ms / 87.008 ms
Bidirectional A* p50 / p95 / p99: 15.745 ms / 74.384 ms / 157.730 ms
A* p50 nodes expanded: 1,240
Bidirectional A* p50 nodes expanded: 1,097
Distance delta max: 0.0 m
```

---

## Next Phase

Next planned phase:

```text
Tier 2 — Phase 5: Distance Matrix Service
```

Phase 5 should add:

- N×N distance matrix generation
- Reuse production A\* route computation
- Matrix timing benchmarks
- Cache-ready key design
- Redis integration if scope permits
- Cache hit/miss logging if Redis is added
- Matrix correctness and failure handling tests
