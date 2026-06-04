# CityRoute

CityRoute is an open-source last-mile delivery routing backend built with Python, FastAPI, Docker, OSMnx, NetworkX, and OpenStreetMap data.

Current status: **Tier 1 — Phase 2 complete: Graph Loading & Validation**

This project is being built phase-by-phase. Phase 1 created the FastAPI and Docker foundation. Phase 2 added real graph loading, coordinate validation, and node snapping.

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
* Graph connectivity metadata in `/graph/stats`
* Local and Docker verification
* Phase 2 test suite with 12 passing tests

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

---

## Phase 2 Runtime Baseline

Observed Phase 2 metrics:

| Metric                   |                                Value |
| ------------------------ | -----------------------------------: |
| Active graph             | `data/graphs/kanpur_central.graphml` |
| City label               | Kanpur Central, Uttar Pradesh, India |
| Nodes                    |                               12,969 |
| Edges                    |                               34,996 |
| GraphML size             |                             12.74 MB |
| Local graph load time    |                              2.804 s |
| Docker graph load time   |                              3.254 s |
| Local memory after load  |                            370.17 MB |
| Docker memory after load |                            376.89 MB |
| Docker image size        |                               933 MB |

Docker image size is currently high because Phase 2 uses OSMnx and geospatial dependencies. Image optimization is deferred until deployment hardening.

---

## Snap Latency Baseline

Isolated node snapping benchmark:

| Metric          |      Value |
| --------------- | ---------: |
| Iterations      |        100 |
| Input latitude  |      26.44 |
| Input longitude |      80.30 |
| Minimum latency |  29.793 ms |
| Mean latency    |  59.349 ms |
| Median latency  |  38.848 ms |
| Maximum latency | 162.016 ms |

This is a measured baseline, not an optimized target. Snap latency optimization remains a later performance task.

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
  "uptime_s": 8.514
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
  "load_time_s": 3.254,
  "graph_path": "data/graphs/kanpur_central.graphml",
  "graph_file_size_mb": 12.74,
  "memory_mb": 376.89,
  "weakly_connected_components": 1,
  "largest_component_nodes": 12969,
  "is_weakly_connected": true
}
```

Values such as `load_time_s` and `memory_mb` vary slightly by machine and run.

---

## Example Valid Coordinate

```powershell
curl "http://127.0.0.1:8000/graph/validate?lat=26.45&lon=80.35"
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
curl "http://127.0.0.1:8000/graph/validate?lat=24.40&lon=80.35"
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
curl "http://127.0.0.1:8000/graph/snap?lat=26.44&lon=80.30"
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
  "snap_time_ms": 127.394
}
```

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
│   └── node_snapper.py
├── config.py
└── main.py

benchmarks/
├── snap_latency_probe.py
└── snap_latency.txt

data/
└── graphs/
    └── kanpur_central.graphml

tests/
├── test_geo_validation.py
├── test_graph_endpoint.py
└── test_health.py
```

The `data/graphs/*.graphml` files are local runtime artifacts and are not committed to Git.

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

## Benchmark Probe

Run isolated snap latency probe:

```powershell
python benchmarks\snap_latency_probe.py
```

Save benchmark output:

```powershell
python benchmarks\snap_latency_probe.py > benchmarks\snap_latency.txt
```

Latest observed result:

```text
snap_latency_probe
graph_path=data\graphs\kanpur_central.graphml
graph_load_time_s=2.349
iterations=100
input_lat=26.44
input_lon=80.3
min_ms=29.793
mean_ms=59.349
median_ms=38.848
max_ms=162.016
```

---

## Current Known Risks

| Risk                                                 | Status                                                        |
| ---------------------------------------------------- | ------------------------------------------------------------- |
| Docker image size is high at around 933 MB           | Documented; optimization deferred                             |
| Runtime memory is around 370–377 MB                  | Acceptable for Phase 2; must monitor before public deployment |
| Snap latency is measured but not optimized           | Benchmark baseline recorded; optimization deferred            |
| Full route-level no-path handling is not implemented | Deferred to Phase 3 because routing does not exist yet        |
| Full Kanpur graph is not the active runtime graph    | Central Kanpur graph is used for stable Phase 2 development   |

---

## Phase 2 Audit Status

Phase 2 is accepted as complete for:

* Graph loading
* GraphML persistence/loading
* Startup graph state
* Graph metadata endpoint
* GPS validation
* Structured 422 invalid-coordinate handling
* Node snapping
* Connectivity metadata
* Local verification
* Docker verification
* Test verification

Phase 2 does not claim routing correctness.

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
* Initial benchmark logging
* `/benchmarks` folder expansion

```
```
