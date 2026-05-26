Step 6 — **Create README.md**

Create this file in project root:

```text
README.md
```

Put this inside:

````markdown
# CityRoute

CityRoute is an open-source last-mile delivery routing backend built with Python, FastAPI, Docker, and open-source map data.

Current status: **Tier 1 — Phase 1: Project Foundation**

---

## What Phase 1 includes

- FastAPI backend skeleton
- Clean router-based architecture
- `/health` endpoint
- `/graph/stats` endpoint
- Configuration system using `.env`
- Structured logging
- Dockerfile
- Docker Compose
- Basic pytest test suite

---

## What Phase 1 does not include yet

- Real OSM graph loading
- GPS node snapping
- A* routing
- Bidirectional A*
- ETA calculation
- Route geometry
- Redis cache
- Dashboard

These come in later phases.

---

## Project structure

```text
app/
├── api/
│   ├── health.py
│   └── graph.py
├── core/
├── models/
├── services/
├── utils/
│   └── logger.py
├── config.py
└── main.py

data/
└── graphs/

tests/
└── test_health.py
````

---

## Local setup

Create virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\activate
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

Open:

```text
http://127.0.0.1:8000/docs
http://127.0.0.1:8000/health
http://127.0.0.1:8000/graph/stats
```

---

## Docker setup

Build and run:

```powershell
docker compose up --build
```

Open:

```text
http://127.0.0.1:8000/docs
```

Stop:

```powershell
docker compose down
```

---

## Tests

Run:

```powershell
pytest
```

Expected result:

```text
2 passed
```

---

## Current endpoints

| Endpoint       | Method | Purpose                    |
| -------------- | -----: | -------------------------- |
| `/`            |    GET | Service index              |
| `/health`      |    GET | Service heartbeat          |
| `/graph/stats` |    GET | Graph metadata placeholder |
| `/docs`        |    GET | Swagger UI                 |

---

## Current `/health` response

```json
{
  "status": "ok",
  "graph_loaded": false,
  "uptime_s": 1.234
}
```

---

## Current `/graph/stats` response

```json
{
  "city": "Kanpur, Uttar Pradesh, India",
  "graph_loaded": false,
  "nodes": 0,
  "edges": 0,
  "load_time_s": null,
  "graph_path": "data/graphs/kanpur.graphml",
  "memory_mb": null
}
```

---

## Current limitations

This phase only proves backend foundation quality. It does not prove routing correctness yet.

Strictly not implemented yet:

* OSMnx graph download
* `.graphml` loading
* node snapping
* coordinate validation
* shortest path algorithms
* route benchmarking

---

## Next phase

Tier 1 — Phase 2: Graph Loading & Validation

Planned work:

* Download Kanpur OSM road graph
* Save graph as `.graphml`
* Load graph once during FastAPI startup
* Populate real graph stats
* Add GPS coordinate validation
* Add nearest-node snapping
