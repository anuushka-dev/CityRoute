# CityRoute

CityRoute is an open-source last-mile delivery routing backend built with Python, FastAPI, Docker, OSMnx, NetworkX, scikit-learn, and OpenStreetMap data.

Current status: **Tier 1 — Phase 3 complete: Custom A\* Routing with Docker Benchmark Evidence**

This project is being built phase-by-phase. Phase 1 created the FastAPI and Docker foundation. Phase 2 added real graph loading, GraphML persistence, GPS validation, graph metadata, node snapping, and BallTree-based snap optimization. Phase 3 adds custom A\* routing from scratch, Haversine heuristic validation, ETA calculation, route geometry output, route-level failure handling, correctness verification against Dijkstra, and Docker benchmark evidence.

---

## Current Phase Status

| Tier | Phase | Status |
|---|---|---|
| Tier 1 | Phase 1 — Project Foundation | Complete |
| Tier 1 | Phase 2 — Graph Loading & Validation | Complete |
| Tier 1 | Phase 3 — A\* Routing | Complete |
| Tier 1 | Phase 3.5 — Folium Route Verification | Next |
| Tier 1 | Phase 4 — Bidirectional A\* | Not started |

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

---

## What is not implemented yet

The following are intentionally not implemented yet:

- Folium route visualization
- `/route/compare` endpoint
- Bidirectional A\*
- Redis caching
- Distance matrix service
- VRP optimization
- Dispatch optimization
- Grafana/Prometheus observability integration
- Public deployment

These belong to later phases or optional observability extensions.

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
| `/route` | GET | Compute A\* route between two GPS coordinates |
| `/docs` | GET | Swagger UI |

Docker OpenAPI verification showed:

```text
/
/graph/snap
/graph/stats
/graph/validate
/health
/route
```

---

## Active Graph Baseline

Observed Phase 3 graph values:

| Metric | Value |
|---|---:|
| City label | Kanpur Central, Uttar Pradesh, India |
| Active graph | `data/graphs/kanpur_central.graphml` |
| Nodes | 12,969 |
| Edges | 34,996 |
| GraphML file size | 12.74 MB |
| Graph file bytes | 13,359,718 |
| Weakly connected components | 1 |
| Largest weak component nodes | 12,969 |
| Strongly connected components | 12 |
| Largest strong component | 12,948 nodes |
| Snap index loaded | true |
| Snap index build time | ~20.692 ms |

Important note: the graph is weakly connected but not fully strongly connected. This is expected for directed OSM road graphs and explains why some random coordinate pairs return clean `404 No path found`.

---

## Phase 3 Test Summary

Run:

```powershell
python -m pytest -v
```

Observed result:

```text
49 passed in 75.78s
```

Test coverage includes:

| Test area | Purpose |
|---|---|
| A\* unit tests | Shortest path logic, same-node route, missing node, no path, directed edges, parallel edges |
| A\* correctness tests | Compare custom A\* distance against Dijkstra |
| Haversine admissibility test | Verify heuristic does not overestimate sampled real graph routes |
| Route endpoint tests | Verify valid `/route` response |
| Route failure tests | Verify `422`, `404`, and `503` behavior |
| Route geometry tests | Verify geometry points come from graph nodes |
| Graph endpoint tests | Graph stats, validation, snapping, connectivity metadata |
| Health tests | Service status and graph-loaded status |

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

This supports the Phase 3 claim that the Haversine heuristic is admissible for this routing graph sample.

---

## Phase 3 Docker Routeable Benchmark

The accepted benchmark is the routeable benchmark, not the raw random benchmark. It separates clean `404 No path found` cases from real failures.

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

### Route latency

| Metric | Value |
|---|---:|
| Route min | 0.003 ms |
| Route mean | 15.324 ms |
| Route median | 10.05 ms |
| Route p50 | 10.158 ms |
| Route p95 | 44.759 ms |
| Route p99 | 88.015 ms |
| Route max | 100.108 ms |

### External API elapsed time

| Metric | Value |
|---|---:|
| API min | 5.097 ms |
| API mean | 24.93 ms |
| API median | 19.657 ms |
| API p50 | 19.66 ms |
| API p95 | 59.967 ms |
| API p99 | 97.71 ms |
| API max | 135.647 ms |

### Two-snap overhead

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

### Search effort and route size

| Metric | p50 | p95 | p99 | Max |
|---|---:|---:|---:|---:|
| Nodes expanded | 1,242 | 5,543 | 11,115 | 12,731 |
| Distance | 5,989.909 m | 11,467.842 m | 14,476.233 m | 16,641.71 m |
| Path node count | 72 | 138 | 164 | 192 |

---

## Raw Random Route Benchmark

The raw random benchmark is retained as evidence but is not the final acceptance benchmark.

Command:

```powershell
python benchmarks\astar_route_benchmark.py 1000 5
```

Observed result:

| Metric | Value |
|---|---:|
| Requested iterations | 1,000 |
| Successful requests | 992 |
| Failed requests | 8 |
| Error rate | 0.8% |

The 8 failures were clean `404 No path found` responses, not crashes. The corrected routeable benchmark records them as `no_path_404_skipped`.

---

## Docker Concurrent Route Probe

Command:

```powershell
python benchmarks\concurrent_route_probe.py
```

Observed result:

| Metric | Value |
|---|---:|
| Workers | 10 |
| Total requests | 10 |
| Successful requests | 10 |
| Failed requests | 0 |
| Status codes | `[200]` |
| Algorithm | `astar` |
| Snap method | `balltree` |
| Total elapsed | 251.076 ms |

### Concurrent route timing

| Metric | Value |
|---|---:|
| API min | 118.142 ms |
| API mean | 184.665 ms |
| API median | 185.972 ms |
| API max | 240.224 ms |
| Route min | 10.29 ms |
| Route mean | 30.702 ms |
| Route median | 29.26 ms |
| Route max | 54.464 ms |
| Total internal min | 17.599 ms |
| Total internal mean | 43.933 ms |
| Total internal median | 37.888 ms |
| Total internal max | 75.099 ms |

The API latency is higher under concurrency because the current Docker run uses a single Uvicorn worker and A\* is CPU-bound Python work.

---

## Docker Runtime Evidence

Manual Docker run:

```powershell
docker run --rm --name cityroute-tier1-phase3 -p 8001:8000 -v "${PWD}\data:/app/data" cityroute-api:tier1-phase3
```

Docker API base URL:

```text
http://127.0.0.1:8001
```

| Field | Value |
|---|---|
| Container name | `cityroute-tier1-phase3` |
| Image | `cityroute-api:tier1-phase3` |
| Internal port | `8000` |
| Host port | `8001` |
| Runtime command | `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| Data mount | `C:\MYDOWNLOADS\MYPROJECT\CityRoute\data:/app/data` |
| Platform | linux/amd64 |
| Container status | running |
| OOMKilled | false |
| Restart count | 0 |

Docker memory after Phase 3 benchmark activity:

| Metric | Value |
|---|---:|
| Memory usage | 337.3 MiB |
| Memory limit shown by Docker | 7.362 GiB |
| Memory percent | 4.47% |
| CPU | 0.29% |
| PIDs | 36 |

---

## Example `/health` Response

```json
{
  "status": "ok",
  "graph_loaded": true,
  "uptime_s": 4494.81
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
  "load_time_s": 3.18,
  "graph_path": "data/graphs/kanpur_central.graphml",
  "graph_file_size_mb": 12.74,
  "memory_mb": 382.77,
  "weakly_connected_components": 1,
  "largest_component_nodes": 12969,
  "is_weakly_connected": true,
  "snap_index_loaded": true,
  "snap_index_build_time_ms": 20.692
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
  "start": {
    "input": {"lat": 26.44, "lon": 80.3},
    "snapped_node": 5317312245,
    "snapped": {"lat": 26.4400833, "lon": 80.2999386},
    "snap_distance_m": 11.098,
    "snap_method": "balltree",
    "snap_time_ms": 2.04
  },
  "end": {
    "input": {"lat": 26.45, "lon": 80.35},
    "snapped_node": 6288159135,
    "snapped": {"lat": 26.4502842, "lon": 80.3497914},
    "snap_distance_m": 37.815,
    "snap_method": "balltree",
    "snap_time_ms": 0.362
  },
  "distance_m": 6428.798,
  "distance_km": 6.429,
  "eta_seconds": 999.5,
  "eta_minutes": 16.66,
  "path_node_count": 77,
  "nodes_expanded": 2622,
  "route_time_ms": 31.714,
  "total_time_ms": 34.814,
  "geometry": [
    {"lat": 26.4400833, "lon": 80.2999386},
    {"lat": 26.440297, "lon": 80.3002594}
  ]
}
```

The actual `geometry` array contains all route node coordinates. For this sample route, `path_node_count` is 77.

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
├── concurrent_route_probe.py
├── heuristic_admissibility_probe.py
├── docker_results/
└── results/

tests/
├── test_astar_algorithm_unit.py
├── test_astar_correctness.py
├── test_astar_edge_cases.py
├── test_geo_validation.py
├── test_graph_endpoint.py
├── test_health.py
├── test_heuristic_admissibility.py
├── test_route_endpoint.py
├── test_route_failure_cases.py
└── test_route_geometry.py
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

## Docker Setup

Build the Docker image:

```powershell
docker build -t cityroute-api:tier1-phase3 .
```

Run Docker on port `8001` so local Uvicorn can still use port `8000`:

```powershell
docker run --rm --name cityroute-tier1-phase3 -p 8001:8000 -v "${PWD}\data:/app/data" cityroute-api:tier1-phase3
```

Open Docker Swagger UI:

```text
http://127.0.0.1:8001/docs
```

Check Docker health:

```powershell
Invoke-RestMethod "http://127.0.0.1:8001/health"
```

Run sample route:

```powershell
Invoke-RestMethod "http://127.0.0.1:8001/route?start_lat=26.44&start_lon=80.30&end_lat=26.45&end_lon=80.35" | ConvertTo-Json -Depth 20
```

---

## Tests

Run:

```powershell
python -m pytest -v
```

Expected current result:

```text
49 passed
```

---

## Benchmark Commands

Set environment for Docker benchmark output:

```powershell
$env:PYTHONPATH="$PWD"
$env:CITYROUTE_BASE_URL="http://127.0.0.1:8001"
$env:CITYROUTE_RESULTS_DIR="benchmarks/docker_results"
```

Run A\* correctness probe:

```powershell
python benchmarks\astar_correctness_probe.py
```

Run heuristic admissibility probe:

```powershell
python benchmarks\heuristic_admissibility_probe.py 10000
```

Run accepted routeable benchmark:

```powershell
python benchmarks\astar_route_benchmark_routeable.py 1000 5 3000
```

Run concurrent route probe:

```powershell
python benchmarks\concurrent_route_probe.py
```

Capture Docker memory:

```powershell
docker stats cityroute-tier1-phase3 --no-stream
```

---

## Current Known Risks and Notes

| Risk / note | Status |
|---|---|
| Graph is weakly connected but has 12 strongly connected components | Documented; explains some valid no-path responses |
| Some random coordinate pairs return `404 No path found` | Expected directed routing behavior |
| Docker image size is still high due to OSMnx/geospatial dependencies | Optimization deferred |
| API latency increases under 10 concurrent requests | Expected with single-worker Uvicorn and CPU-bound routing |
| ETA is formula-based, not traffic-aware | Accepted for Phase 3 |
| Grafana/Prometheus is not integrated yet | Deferred observability extension |
| Folium route visualization | Next Phase 3.5 |
| Bidirectional A\* | Phase 4 |

---

## Phase 3 Acceptance Status

Phase 3 is accepted as complete for:

- Custom A\* implementation
- Haversine heuristic
- Route endpoint
- GPS snapping before route computation
- Route distance
- ETA calculation
- Route geometry output
- `404 No path found` handling
- `503 Graph not loaded` handling
- Correctness verification against Dijkstra
- Haversine admissibility verification
- Docker route benchmark
- Concurrent route probe
- Docker runtime evidence
- Test evidence
- Benchmark evidence under `benchmarks/`

Phase 3 does not claim traffic-aware routing, bidirectional A\*, visualization, caching, or dispatch optimization.

---

## Latest Verified Phase 3 Evidence

```text
pytest: 49 passed in 75.78s
A* vs Dijkstra: 500 / 500 passed
Haversine admissibility: 10,000 checked, 0 overestimates
Routeable benchmark: 1,000 successful route measurements
Clean no-path 404 skipped: 8
Real failures: 0
Route p50: 10.158 ms
Route p95: 44.759 ms
Route p99: 88.015 ms
Two-snap p50: 0.574 ms
Two-snap p95: 0.794 ms
Two-snap p99: 0.958 ms
Concurrent route probe: 10 / 10 successful
Docker memory: 337.3 MiB
```

---

## Next Phase

Next planned phase:

```text
Tier 1 — Phase 3.5: Folium Route Verification
```

Phase 3.5 should add:

- Basic Folium route map
- Visual route polyline verification
- Saved HTML route preview
- README screenshot or saved artifact reference

After Phase 3.5, Phase 4 should add:

- Bidirectional A\*
- `/route/compare`
- A\* vs Bidirectional A\* benchmark comparison
