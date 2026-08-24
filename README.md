CityRoute

CityRoute is an evidence-backed last-mile delivery routing and optimization backend built with Python, FastAPI, Docker, Redis, OSMnx, NetworkX, scikit-learn, and OpenStreetMap road-network data.

The project evolved phase-by-phase from a basic API and Docker foundation into a custom routing, matrix, VRP, dispatch, caching, concurrency, reliability, and evidence-verification system.

The core engineering loop is:

Implement
   ↓
Benchmark
   ↓
Check correctness + failure behavior
   ↓
Find bottleneck / limitation
   ↓
Change algorithm or architecture
   ↓
Re-run evidence
   ↓
Accept, reject, or explicitly bound the result

Architecture

Client / Frontend
       │
       ▼
   Middleware
       │
       ▼
 FastAPI Routers
       │
       ▼
    Services
       │
       ├────────────► Redis / Cache
       ├────────────► Graph / BallTree
       │
       ▼
 Core Algorithms
       │
       ├── A*
       ├── Bidirectional A*
       ├── Source-Dijkstra
       ├── Greedy
       ├── 2-Opt
       ├── LNS
       └── Hungarian

Main feature flows:

/route
  → validation → BallTree snapping → A* → route geometry / ETA

/route/compare
  → same snapped endpoints → A* + Bidirectional A*

/matrix
  → validation → cache lookup → matrix algorithm → response

/vrp/greedy
  → matrix → Greedy baseline

/vrp/compare
  → matrix → Greedy → 2-Opt

/vrp/compare/advanced
  → matrix → Greedy → 2-Opt → LNS

/dispatch/compare
  → dispatch cost matrix → Greedy → Hungarian

Phase Evolution

Phase 1 — Project Foundation

Created the initial service platform:

FastAPI application and routers

/health and /graph/stats

configuration through .env

structured logging

Docker / Docker Compose

pytest setup

Swagger UI

The goal was to establish a clean application foundation before adding the routing engine.

Phase 2 — Graph Loading, Validation & Snapping

Added the real road-network layer:

OSMnx / GraphML graph loading

FastAPI lifespan startup loading

graph metadata and connectivity information

GPS validation and graph bounding-box validation

nearest-node snapping

BallTree snap index

snap distance reporting

local and Docker verification

A major optimization in this phase replaced the earlier slower snapping path with BallTree-based lookup, producing an improvement on the order of tens of times in the recorded comparisons.

Phase 3 — Custom A* Routing

Implemented the routing core from scratch:

A* with heapq

g_score, predecessor tracking and path reconstruction

Haversine heuristic

directed MultiDiGraph handling

shortest parallel-edge selection

route distance, ETA and geometry

node-expansion and timing metadata

404 No path found

503 Graph not loaded

correctness checks against Dijkstra

Key Docker evidence included 500/500 correctness checks, 1,000 successful route measurements, and 0 real route failures.

Phase 3.5 — Route Map Verification

Connected route results to a Folium visualization layer:

route polyline from real /route geometry

graph-node coordinates

start/end markers

route summary

HTML map artifact generation

The evidence verifies that the map uses the recorded route geometry rather than recomputing a different route.

Phase 4 — Bidirectional A* Comparison

Implemented Bidirectional A* and /route/compare:

forward and backward search

directed predecessor/successor traversal

meeting-node tracking

expansion counters

same snapped endpoints for A* and Bidirectional A*

distance-equivalence checks

correctness comparisons against A* and Dijkstra

large benchmark and Docker deployment evidence

The key engineering conclusion was not “Bidirectional A* is always faster.” Aggregate evidence showed trade-offs, so normal /route remains A* while /route/compare remains the comparison path.

Phase 5 — Distance Matrix, Redis & Source-Dijkstra

Introduced POST /matrix and the matrix layer:

directed N×N distance / ETA matrices

matrix validation

Redis caching

deterministic cache keys

cache hit/miss behavior

matrix correctness probes

local and Docker benchmarks

source-wise / multi-target Dijkstra

adjacency preparation for repeated matrix workloads

The original threaded pairwise matrix strategy did not meet its 4× target at 15×15. It was rejected rather than presented as successful.

Source-wise Dijkstra then produced approximately:

6.7–6.8× improvement at 15×15

11.14× improvement at 25×25 Docker

zero mismatches in the corresponding correctness checks

source_dijkstra became the preferred strategy for larger matrices, while smaller matrices retain the fixed-overhead trade-off.

Phase 6 — Greedy Multi-Stop Baseline

Added the first multi-stop routing layer:

POST /vrp/greedy

nearest-neighbor ordering

open and return-to-start modes

deterministic ordering

leg-level output

total route distance

matrix algorithm selection

inherited Redis matrix caching

1–24 stop validation

25-stop rejection with 422

Docker evidence showed successful repeated 24-stop open and return-to-start probes and correct upper-bound rejection.

Phase 7 — 2-Opt Optimization

Added local-search improvement over the Greedy baseline:

POST /vrp/compare

Greedy vs 2-Opt

distance saved

improvement percentage

non-regression

iteration / swap counts

convergence traces

optimization timing

cache telemetry propagation

At 24 stops, the strongest Docker evidence reported approximately:

Mode

Improvement

Open route

22.686%

Return-to-start

22.861%

These are measured improvements on the tested workload, not global VRP optimality proofs.

Phase 7.1 — Cache Telemetry & Warm-Matrix Proof

Made matrix-cache behavior visible through /vrp/compare:

cache_status

cache hits / misses

cold miss verification

warm hit verification

nested Phase 5 telemetry propagation

rejection of a pre-fix cache-key mismatch run

Accepted Docker evidence:

Cold matrix:          335.327 ms
Warm matrix:            3.131 ms
Warm VRP matrix:        3.316 ms
Cache status:           hit
Cache hits:             1
Cache misses:           0
Speedup:              107.099×

This is an application-level warm-cache result, not a claim that Redis itself is 107× faster than another datastore.

Phase 8 — LNS Advanced VRP

Added Large Neighborhood Search through:

POST /vrp/compare/advanced

Implemented:

destroy/repair improvement loop

seeded reproducibility

configurable destroy fraction

configurable no-improvement limit

Greedy / 2-Opt / LNS comparison

convergence evidence

non-regression checks

open and return-to-start support

At 24 stops, Docker evidence reported:

Mode

LNS vs Greedy

LNS vs 2-Opt

Open

13.611%

3.11%

Return-to-start

12.284%

2.952%

The exact-small-case benchmark reported zero worst optimality gap for the six represented cases only. No global VRP optimality claim is made.

Phase 9 — Hungarian Dispatch

Expanded the system from route optimization into dispatch assignment:

Hungarian assignment from scratch

Greedy dispatch baseline

dispatch cost matrix

fairness metrics

POST /dispatch/compare

assignment and capacity validation

duplicate-ID validation

invalid GPS validation

Haversine dispatch cost

service-level Source-Dijkstra dispatch readiness

dispatch cache-key utility

service-level cache contract

local integration probe

Key evidence:

Hungarian correctness: 350 / 350
Cost mismatches:       0
Max cost difference:   0.0

Dispatch endpoint:     80 / 80
Success rate:          100%

The current live API supports Haversine dispatch cost. Real graph-backed Source-Dijkstra dispatch was proven at service-injection level, but is not yet presented as a live API capability. Likewise, service-level cache-contract evidence is not presented as proof of real Redis-backed dispatch acceleration.

Phase 9.1 — Dispatch Hardening

Phase 9.1 is treated as internal Phase 9 hardening.

It covered:

Source-Dijkstra service-path probes

dispatch cache contract probes

full integration checks

local evidence manifests

route / health / OpenAPI integration

Accepted later-run evidence included:

Source-Dijkstra service probe: 100 / 100
Cache cycles:                  50 / 50
Cache requests:               100
Cache hits:                    50
Cache hit rate:              50.0%
Full integration:              6 / 6

Earlier incomplete runs remain preserved as historical evidence rather than being removed.

Phase 10 — Road Dispatch, Correctness, Cache, Load & Formal Evidence

Phase 10 formalized the broader dispatch evidence set.

Six evidence groups were accepted:

road_dispatch
haversine_vs_road
dispatch_cache
unreachable_pair
correctness
load

Historical formal acceptance recorded:

Expected groups: 6
Passed groups:   6
Missing groups:  0
Failed groups:   0

Correctness evidence included:

15 scenarios
270 cell cases
270 successful cell cases
0 failed cell cases

This phase also strengthened benchmark provenance with raw artifacts, summaries, runtime information, Git metadata, Docker metadata, and explicit evidence references.

Phase 11 — Reliability & Failure Hardening

Phase 11 moved beyond feature correctness into runtime behavior:

bounded concurrency

overload

timeout behavior

Redis failure

Redis recovery

corrupted-cache recovery

failure injection

graceful shutdown

worker restart

health-state transitions

multi-worker testing

Several reliability probes passed their functional acceptance conditions.

The important limitation is that the phase also exposed real gaps.

For example, the multi-worker probe recorded:

300 requests
32 concurrency
238 successful
62 failed
79.33% success
~772 ms median aggregate latency
~2.83 s p95
~3.21 s p99
~22.98 RPS

Therefore Phase 11 should be described as reliability hardening with known remaining gaps, not as blanket production-readiness proof.

Redis recovery also demonstrated fail-open behavior and recovery of normal matrix requests, while a missing recovery counter prevented a full observability acceptance.

Selected Benchmark Results

Area

Evidence

A* correctness

500 / 500

Routeable successful measurements

1,000

Real route failures

0

Route median

9.892 ms

Route p95

44.371 ms

Route p99

87.893 ms

Snap median

0.569 ms

Snap p95

0.798 ms

Source-Dijkstra @ 15×15

~6.7–6.8×

Source-Dijkstra @ 25×25

11.14×

Warm matrix cache

107.099×

2-Opt @ 24 stops

22.686–22.861%

LNS @ 24 stops

12.284–13.611% vs Greedy

Hungarian correctness

350 / 350

Phase 10 correctness cells

270 / 270

These are phase-specific measurements with their own workloads and should not be treated as universal performance claims.

Active Graph

Current graph:

data/graphs/kanpur_central.graphml

Observed baseline:

Metric

Value

Nodes

12,969

Edges

34,996

GraphML size

12.74 MB

Weak components

1

Largest weak component

12,969

Snap index

BallTree

Graph load

~3.0–3.6 s

Runtime memory

~380–385 MB

The graph is directed. A weakly connected graph can still contain directed no-path pairs, which is why some valid requests return 404 No path found.

API

Endpoint

Method

Purpose

/

GET

Service index

/health

GET

Service heartbeat

/graph/stats

GET

Graph metadata

/graph/validate

GET

GPS validation

/graph/snap

GET

GPS-to-node snapping

/route

GET

Normal A* routing

/route/compare

GET

A* vs Bidirectional A*

/matrix

POST

N×N distance / ETA matrix

/vrp/greedy

POST

Greedy multi-stop baseline

/vrp/compare

POST

Greedy vs 2-Opt

/vrp/compare/advanced

POST

Greedy vs 2-Opt vs LNS

/dispatch/compare

POST

Greedy vs Hungarian

/docs

GET

Swagger UI

Matrix Algorithms

Supported:

source_dijkstra
bidirectional_astar
astar

For larger matrices:

source_dijkstra

is preferred because it avoids repeatedly solving the same source-to-destination graph search.

It is not necessarily faster for very small matrices because of its fixed setup cost.

Validation Boundaries

Matrix

2–25 total locations

duplicate IDs rejected

invalid coordinates rejected with 422

graph-not-loaded returns 503

snap-index-missing returns 503

VRP

1–24 stops

25 stops rejected with 422

open and return-to-start modes

invalid coordinates rejected

invalid matrix algorithm rejected

non-regression expectations enforced

Dispatch

at least one driver and order

duplicate IDs rejected

invalid GPS rejected

capacity checked

Haversine mode supported live

Source-Dijkstra live API mode remains bounded by its current wiring state

Testing & Evidence

Run the full test suite:

python -m pytest -v

Phase-specific test groups and benchmark artifacts live under:

benchmarks/phase_5
benchmarks/phase_6
benchmarks/phase_7
benchmarks/phase_7_1
benchmarks/phase_8
benchmarks/phase_9
benchmarks/phase_9_1
benchmarks/phase_10
benchmarks/phase_11

Phase 12 adds:

.phase12_evidence/

The evidence workflow is:

Benchmark artifact
      ↓
SHA-256 / integrity
      ↓
Exact field / JSON pointer
      ↓
Claim register
      ↓
Mechanical verification

Failed approaches remain preserved. This includes the original threaded matrix strategy, rejected benchmark runs, instrumentation gaps, and later corrective runs.

Project Structure

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
├── schemas/
├── services/
└── utils/
benchmarks/
tests/
data/
frontend/

Local Setup

python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env

Start Redis:

docker rm -f cityroute-redis 2>$null

docker run -d --rm `
  --name cityroute-redis `
  -p 6379:6379 `
  redis:7-alpine

docker exec cityroute-redis redis-cli ping

Expected:

PONG

Run the application:

python -m uvicorn app.main:app --reload --port 8000

Swagger:

http://127.0.0.1:8000/docs

Docker

docker network create cityroute-net

docker run -d --rm `
  --name cityroute-redis `
  --network cityroute-net `
  -p 6379:6379 `
  redis:7-alpine

Build:

docker build -t cityroute-api .

Run:

docker run --rm `
  --name cityroute-api `
  --network cityroute-net `
  -p 8001:8000 `
  --env-file .env `
  -e CITYROUTE_REDIS_URL=redis://cityroute-redis:6379/0 `
  -v "${PWD}\data:/app/data" `
  cityroute-api

Docker Swagger:

http://127.0.0.1:8001/docs

Known Limitations

Benchmarks are bounded by the tested Kanpur Central graph and configured workloads.

Some directed node pairs legitimately return 404 No path found.

A* and heuristic claims are empirical, not universal mathematical proofs.

Greedy, 2-Opt and LNS are heuristic optimizers, not global VRP solvers.

Bidirectional A* is not assumed to be faster in every workload.

The 24-stop VRP limit is a configured project boundary.

Warm-cache evidence does not remove fully cold matrix computation cost.

Live Source-Dijkstra dispatch is not yet presented as fully graph-backed API functionality.

Real Redis-backed dispatch-cache acceleration is not yet proven.

Phase 11 still contains multi-worker and observability gaps.

ETA is formula-based rather than traffic-aware.

The current graph does not represent nationwide or unlimited-scale routing.

No production-readiness claim is made solely from these benchmarks.

Why CityRoute Is Technically Interesting

The strongest part of CityRoute is not one headline number.

The project repeatedly uses measurement to make engineering decisions:

Threaded matrix approach
        ↓
0.67–0.69× at 15×15
        ↓
Rejected
        ↓
Source-Dijkstra
        ↓
~6.8× at 15×15
        ↓
11.14× at 25×25

Similarly:

Generic snapping
        ↓
Benchmark
        ↓
BallTree
        ↓
Large snapping-latency reduction

and:

Greedy
   ↓
2-Opt
   ↓
LNS

and:

Feature correctness
        ↓
Concurrency
        ↓
Failure injection
        ↓
Redis recovery
        ↓
Observability
        ↓
Evidence verification

This is the main engineering story of the project: implement, measure, reject weak approaches, improve the architecture, and preserve what the evidence actually proves.

Current Position

Phase 1       Complete
Phase 2       Complete
Phase 3       Complete
Phase 3.5     Complete
Phase 4       Complete
Phase 5       Complete
Phase 6       Complete
Phase 7       Complete
Phase 7.1     Complete
Phase 8       Complete
Phase 9       Evidence complete with bounded pending items
Phase 10      Evidence complete
Phase 11      Reliability hardening complete with known gaps

The project should be presented as a custom routing + optimization systems project with evidence-backed performance engineering, not as a claim that a Python implementation is universally faster than mature routing engines.