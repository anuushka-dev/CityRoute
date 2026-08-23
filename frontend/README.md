# CityRoute Frontend

This frontend is split into two views:

- **Product**: the map-first routing, delivery optimization, and dispatch workflows backed by the current FastAPI endpoints.
- **Engineering**: live runtime/graph/readiness/metrics telemetry plus archived Phase 11 evidence and source-archive inventory.

## Backend proxy

The Vite development server forwards `/api/*` to `http://127.0.0.1:8001/*`.

## Start

```powershell
npm install
npm run build
npm run dev
```

## Evidence policy

Live telemetry is fetched from the backend. Archived benchmark evidence bundled under `public/evidence/` was derived from the supplied repository benchmark artifacts. It is displayed as archived evidence, not as current live runtime telemetry.
