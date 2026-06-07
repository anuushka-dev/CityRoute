# CityRoute

CityRoute is an open-source last-mile delivery routing backend built with Python, FastAPI, Docker, OSMnx, NetworkX, scikit-learn, and OpenStreetMap data.

Current status: **Tier 1 — Phase 2 complete: Graph Loading, Validation, and Fast Node Snapping**

This project is being built phase-by-phase. Phase 1 created the FastAPI and Docker foundation. Phase 2 added real graph loading, GraphML persistence, GPS validation, node snapping, graph connectivity metadata, and BallTree-based snap optimization.

---

## Current Phase Status

| Tier   | Phase                                 | Status      |
| ------ | ------------------------------------- | ----------- |
| Tier 1 | Phase 1 — Project Foundation          | Complete    |
| Tier 1 | Phase 2 — Graph Loading & Validation  | Complete    |
| Tier 1 | Phase 3 — A* Routing                  | Not started |
| Tier 1 | Phase 3.5 — Folium Route Verification | Not started |
| Tier 1 | Phase 4 — Bidirectional A*            | Not started |

---

## What is implemented

### Phase 1 — Project Foundation

* FastAPI backend
* Router-based API structure
* `/health` endpoint
* `/graph/stats` endpoint
* Configuration through `.env`
* Structured logging
* Dockerfile
* Docker Compose
* Pytest test setup

### Phase 2 — Graph Loading & Validation

* OSMnx graph loading
* GraphML persistence
* Startup graph loading through FastAPI lifespan
* Real graph metadata through `/graph/stats`
* GPS latitude/longitude validation
* Bounding-box validation for the active graph area
* Structured `422` responses for invalid/out-of-bounds coordinates
* Node snapping from GPS coordinate to nearest graph node
* BallTree snap index built at startup for fast nearest-node lookup
* Snap distance returned in meters
* Graph connectivity metadata in `/graph/stats`
* Local and Docker verification
* Phase 2 test suite with 12 passing tests
* Benchmark evidence recorded under `benchmarks/`

---

## What is not implemented yet

The following are intentionally not implemented yet:

* A* routing
* Haversine heuristic
* ETA calculation
* Route geometry output
* `/route` endpoint
* `/route/compare` endpoint
* Bidirectional A*
* Folium route visualization
* Redis caching
* Distance matrix service
* VRP optimization
* Dispatch optimization
* Public deployment

These belong to later phases.

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

This keeps the Docker image separate from local graph data.

The `data/graphs/*.graphml` files are local runtime artifacts and are not committed to Git.

---

## Phase 2 Runtime Baseline

Observed Phase 2 metrics:

| Metric                         |                                Value |
| ------------------------------ | -----------------------------------: |
| Active graph                   | `data/graphs/kanpur_central.graphml` |
| City label                     | Kanpur Central, Uttar Pradesh, India |
| Nodes                          |                               12,969 |
| Edges                          |                               34,996 |
| GraphML size                   |                             12.74 MB |
| Docker graph load time         |                              3.014 s |
| Docker graph memory after load |                            378.76 MB |
| Docker image size              |                               933 MB |
| Weakly connected components    |                                    1 |
| Largest component nodes        |                               12,969 |
| Snap index build time          |                            28.284 ms |
| Snap index nodes               |                               12,969 |

Docker image size is currently high because Phase 2 uses OSMnx and geospatial dependencies. Image optimization is deferred until deployment hardening.

---

## Phase 2 Benchmark Summary

### Local `/graph/snap` API benchmark

Benchmark command:

```powershell
python benchmarks\snap_api_benchmark.py --url "http://127.0.0.1:8000/graph/snap?lat=26.44&lon=80.30" --iterations 100
```

Observed result:

| Metric               |      Value |
| -------------------- | ---------: |
| Iterations           |        100 |
| Status codes         |    `[200]` |
| Snap method          | `balltree` |
| API min              |   4.247 ms |
| API mean             |  11.204 ms |
| API median           |   6.230 ms |
| API max              |  36.029 ms |
| Internal snap min    |   0.236 ms |
| Internal snap mean   |   0.382 ms |
| Internal snap median |   0.356 ms |
| Internal snap max    |   0.801 ms |

### Docker `/graph/snap` API benchmark

Benchmark command:

```powershell
python benchmarks\snap_api_benchmark.py --url "http://127.0.0.1:8001/graph/snap?lat=26.44&lon=80.30" --iterations 100
```

Observed result:

| Metric               |      Value |
| -------------------- | ---------: |
| Iterations           |        100 |
| Status codes         |    `[200]` |
| Snap method          | `balltree` |
| API min              |   6.789 ms |
| API mean             |   8.743 ms |
| API median           |   7.811 ms |
| API max              |  31.511 ms |
| Internal snap min    |   0.324 ms |
| Internal snap mean   |   0.435 ms |
| Internal snap median |   0.429 ms |
| Internal snap max    |   0.657 ms |

### Docker concurrent `/graph/snap` benchmark

Benchmark command:

```powershell
python benchmarks\concurrent_snap_probe.py --url "http://127.0.0.1:8001/graph/snap?lat=26.44&lon=80.30" --requests 10
```

Observed result:

| Metric               |      Value |
| -------------------- | ---------: |
| Total requests       |         10 |
| Status codes         |    `[200]` |
| Snap method          | `balltree` |
| Total elapsed        |   54.61 ms |
| API min              |  30.151 ms |
| API mean             |  39.520 ms |
| API median           |  40.474 ms |
| API max              |  46.642 ms |
| Internal snap min    |   0.262 ms |
| Internal snap mean   |   0.526 ms |
| Internal snap median |   0.410 ms |
| Internal snap max    |   1.245 ms |

### Docker memory after concurrent snap

Observed result:

| Metric       |                    Value |
| ------------ | -----------------------: |
| Container    | `cityroute-tier1-phase2` |
| Memory usage |                329.2 MiB |
| CPU          |                    0.21% |
| PIDs         |                       36 |

---

## Legacy OSMnx Nearest-Node Baseline

The benchmark below measures direct OSMnx `nearest_nodes()` behavior. It is retained only as a baseline comparison.

```powershell
python benchmarks\snap_latency_probe.py
```

Observed result:

| Metric     |      Value |
| ---------- | ---------: |
| Iterations |        100 |
| Min        |  29.391 ms |
| Mean       |  53.381 ms |
| Median     |  31.666 ms |
| Max        | 152.373 ms |

This is **not** the current production snap path. The current `/graph/snap` endpoint uses the BallTree snap index and returns `snap_method: "balltree"`.

---

## Current API Endpoints

| Endpoint          | Method | Purpose                                             |
| ----------------- | -----: | --------------------------------------------------- |
| `/`               |    GET | Service index                                       |
| `/health`         |    GET | Service heartbeat                                   |
| `/graph/stats`    |    GET | Loaded graph metadata                               |
| `/graph/validate` |    GET | Validate GPS coordinate against active graph bounds |
| `/graph/snap`     |    GET | Snap GPS coordinate to nearest graph node           |
| `/docs`           |    GET | Swagger UI                                          |

---

## Example `/health` Response

```json
{
  "status": "ok",
  "graph_loaded": true,
  "uptime_s": 1549.462
}
```

---

## Example `/graph/stats` Response

```json
{
  "city": "Kanpur Central, Uttar Pradesh, India",
  "graph_loaded": true,
  "nodes": 12969,
  "edges": 34996,
  "load_time_s": 3.014,
  "graph_path": "data/graphs/kanpur_central.graphml",
  "graph_file_size_mb": 12.74,
  "memory_mb": 378.76,
  "weakly_connected_components": 1,
  "largest_component_nodes": 12969,
  "is_weakly_connected": true,
  "snap_index_loaded": true,
  "snap_index_build_time_ms": 28.284
}
```

Values such as `load_time_s`, `memory_mb`, and `uptime_s` vary slightly by machine and run.

---

## Example Valid Coordinate

```powershell
curl.exe "http://127.0.0.1:8000/graph/validate?lat=26.45&lon=80.35"
```

Expected response:

```json
{
  "valid": true,
  "lat": 26.45,
  "lon": 80.35,
  "message": "Coordinate is valid and inside the loaded graph area."
}
```

---

## Example Invalid Coordinate

```powershell
curl.exe "http://127.0.0.1:8000/graph/validate?lat=24.40&lon=80.35"
```

Expected behavior:

```text
HTTP 422 Unprocessable Entity
```

Example response:

```json
{
  "detail": {
    "error": "Coordinate outside loaded graph area",
    "message": "Coordinate must be inside the configured central Kanpur graph bounding box.",
    "received": {
      "lat": 24.4,
      "lon": 80.35
    },
    "allowed_bbox": {
      "south": 26.43,
      "north": 26.5,
      "west": 80.28,
      "east": 80.38
    }
  }
}
```

---

## Example `/graph/snap` Response

Request:

```powershell
curl.exe "http://127.0.0.1:8000/graph/snap?lat=26.44&lon=80.30"
```

Example response:

```json
{
  "status": "ok",
  "message": "Coordinate snapped to nearest graph node.",
  "input": {
    "lat": 26.44,
    "lon": 80.3
  },
  "nearest_node": 5317312245,
  "snapped": {
    "lat": 26.4400833,
    "lon": 80.2999386
  },
  "snap_distance_m": 11.098,
  "snap_time_ms": 2.031,
  "snap_method": "balltree"
}
```

`snap_time_ms` varies per request. Benchmark medians are recorded above.

---

## Project Structure

```text
app/
├── api/
│   ├── graph.py
│   └── health.py
├── services/
│   └── graph_service.py
├── utils/
│   ├── geo_validation.py
│   ├── logger.py
│   ├── node_snapper.py
│   └── snap_index.py
├── config.py
└── main.py

benchmarks/
├── concurrent_snap_probe.py
├── concurrent_snap_docker.txt
├── docker_phase2_startup_logs.txt
├── docker_stats_after_concurrent_snap.txt
├── phase2_number_accuracy.txt
├── pytest_phase2_after_balltree.txt
├── snap_api_benchmark.py
├── snap_api_docker.txt
├── snap_api_local.txt
├── snap_latency_docker.txt
├── snap_latency_probe.py
└── snap_latency_probe.txt

data/
└── graphs/
    └── kanpur_central.graphml

tests/
├── test_geo_validation.py
├── test_graph_endpoint.py
└── test_health.py
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

Run the app:

```powershell
uvicorn app.main:app --reload
```

Open Swagger UI:

```text
http://127.0.0.1:8000/docs
```

---

## Docker Setup

Build the Docker image:

```powershell
docker build -t cityroute-api:tier1-phase2 .
```

Run Docker on port `8001` so local Uvicorn can still use port `8000`:

```powershell
docker run --rm --name cityroute-tier1-phase2 -p 8001:8000 -v "${PWD}\data:/app/data" cityroute-api:tier1-phase2
```

Open Docker Swagger UI:

```text
http://127.0.0.1:8001/docs
```

Check Docker Python:

```powershell
docker run --rm cityroute-api:tier1-phase2 python --version
```

Check Docker dependencies:

```powershell
docker run --rm cityroute-api:tier1-phase2 python -c "import osmnx, networkx, psutil, sklearn; print('docker deps ok')"
```

---

## Docker Compose

Run:

```powershell
docker compose up --build
```

Stop:

```powershell
docker compose down
```

The Docker Compose service maps:

```text
8000 -> 8000
```

For running local and Docker at the same time, prefer manual `docker run` with:

```text
8001 -> 8000
```

---

## Tests

Run:

```powershell
pytest -v
```

Expected current result:

```text
12 passed
```

Current test coverage includes:

| Test file                      | Purpose                                                                                         |
| ------------------------------ | ----------------------------------------------------------------------------------------------- |
| `tests/test_geo_validation.py` | Unit tests for valid coordinate, invalid latitude, invalid longitude, and outside-bbox handling |
| `tests/test_graph_endpoint.py` | Integration tests for graph stats, coordinate validation, snapping, and connectivity metadata   |
| `tests/test_health.py`         | Health endpoint and graph stats after startup loading                                           |

---

## Benchmark Commands

Run local API snap benchmark:

```powershell
python benchmarks\snap_api_benchmark.py --url "http://127.0.0.1:8000/graph/snap?lat=26.44&lon=80.30" --iterations 100
```

Run Docker API snap benchmark:

```powershell
python benchmarks\snap_api_benchmark.py --url "http://127.0.0.1:8001/graph/snap?lat=26.44&lon=80.30" --iterations 100
```

Run Docker concurrent snap benchmark:

```powershell
python benchmarks\concurrent_snap_probe.py --url "http://127.0.0.1:8001/graph/snap?lat=26.44&lon=80.30" --requests 10
```

Save all Phase 2 accuracy numbers:

```powershell
type benchmarks\phase2_number_accuracy.txt
```

---

## Current Known Risks

| Risk                                                              | Status                                                      |
| ----------------------------------------------------------------- | ----------------------------------------------------------- |
| Docker image size is high at around 933 MB                        | Documented; optimization deferred                           |
| Runtime memory must still be rechecked under future `/route` load | Phase 3 task                                                |
| Full route-level no-path handling is not implemented              | Deferred to Phase 3 because routing does not exist yet      |
| Full Kanpur graph is not the active runtime graph                 | Central Kanpur graph is used for stable Phase 2 development |
| Public deployment is not live                                     | Later Tier 1 work                                           |

Snap latency is no longer a Phase 2 blocker. The current `/graph/snap` endpoint uses BallTree and benchmarked internal snap median is below 1 ms locally and in Docker.

---

## Phase 2 Audit Status

Phase 2 is accepted as complete for:

* Graph loading
* GraphML persistence/loading
* Startup graph state
* Graph metadata endpoint
* GPS validation
* Structured `422` invalid-coordinate handling
* Node snapping
* BallTree snap optimization
* Connectivity metadata
* Local verification
* Docker verification
* Test verification
* Benchmark evidence

Phase 2 does not claim routing correctness.

---

## Latest Verified Git State

```text
3694226 perf(snap): add BallTree snap index and benchmarks
```

Working tree verified clean after this commit.

---

## Next Phase

Next planned phase:

```text
Tier 1 — Phase 3: A* Routing
```

Phase 3 must add:

* A* implementation from scratch
* Haversine heuristic
* Route endpoint
* Route distance
* ETA calculation
* Route geometry output
* Correctness tests against Dijkstra
* `NetworkXNoPath -> 404` route-level handling
* Initial A* benchmark logging
* Route performance benchmarks
