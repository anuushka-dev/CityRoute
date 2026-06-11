# benchmarks/phase3_5_route_map_probe.py

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.utils.route_map import generate_route_map  # noqa: E402


DEFAULT_BASE_URL = os.getenv("CITYROUTE_BASE_URL", "http://127.0.0.1:8001")


def fetch_route(
    *,
    base_url: str,
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    timeout_s: float,
) -> tuple[dict[str, Any], float]:
    query = urlencode(
        {
            "start_lat": start_lat,
            "start_lon": start_lon,
            "end_lat": end_lat,
            "end_lon": end_lon,
        }
    )

    url = f"{base_url.rstrip('/')}/route?{query}"
    request = Request(url, headers={"Accept": "application/json"})

    started = time.perf_counter()

    try:
        with urlopen(request, timeout=timeout_s) as response:
            elapsed_ms = (time.perf_counter() - started) * 1000
            raw_body = response.read().decode("utf-8")
            return json.loads(raw_body), round(elapsed_ms, 3)

    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Route API returned HTTP {exc.code}. Body: {body}"
        ) from exc

    except URLError as exc:
        raise RuntimeError(
            f"Could not connect to route API at {url}. "
            "Make sure Docker or local Uvicorn is running."
        ) from exc


def validate_route_response(route_result: dict[str, Any]) -> None:
    if route_result.get("status") != "ok":
        raise ValueError("Route response status must be 'ok'.")

    if route_result.get("algorithm") != "astar":
        raise ValueError("Route response algorithm must be 'astar'.")

    geometry = route_result.get("geometry")

    if not isinstance(geometry, list):
        raise ValueError("Route response must contain a geometry list.")

    if len(geometry) < 2:
        raise ValueError("Route geometry must contain at least 2 points.")

    start = route_result.get("start", {})
    end = route_result.get("end", {})

    if start.get("snap_method") != "balltree":
        raise ValueError("Start snap method must be 'balltree'.")

    if end.get("snap_method") != "balltree":
        raise ValueError("End snap method must be 'balltree'.")


def build_summary(
    *,
    route_result: dict[str, Any],
    base_url: str,
    api_elapsed_ms: float,
    output_html: Path,
    output_json: Path,
) -> dict[str, Any]:
    geometry = route_result["geometry"]

    return {
        "artifact": "phase3_5_route_map_probe",
        "base_url": base_url,
        "status": route_result.get("status"),
        "algorithm": route_result.get("algorithm"),
        "api_elapsed_ms": api_elapsed_ms,
        "distance_m": route_result.get("distance_m"),
        "distance_km": route_result.get("distance_km"),
        "eta_seconds": route_result.get("eta_seconds"),
        "eta_minutes": route_result.get("eta_minutes"),
        "path_node_count": route_result.get("path_node_count"),
        "geometry_points": len(geometry),
        "nodes_expanded": route_result.get("nodes_expanded"),
        "route_time_ms": route_result.get("route_time_ms"),
        "total_time_ms": route_result.get("total_time_ms"),
        "start_snapped_node": route_result.get("start", {}).get("snapped_node"),
        "end_snapped_node": route_result.get("end", {}).get("snapped_node"),
        "start_snap_method": route_result.get("start", {}).get("snap_method"),
        "end_snap_method": route_result.get("end", {}).get("snap_method"),
        "output_html": str(output_html),
        "output_route_json": str(output_json),
        "verification": {
            "route_response_received": True,
            "geometry_present": len(geometry) >= 2,
            "map_html_generated": output_html.exists(),
            "uses_route_endpoint_geometry": True,
            "recomputed_route": False,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a Folium HTML map from the CityRoute /route endpoint."
    )

    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)

    parser.add_argument("--start-lat", type=float, default=26.44)
    parser.add_argument("--start-lon", type=float, default=80.30)
    parser.add_argument("--end-lat", type=float, default=26.45)
    parser.add_argument("--end-lon", type=float, default=80.35)

    parser.add_argument(
        "--output-html",
        default="benchmarks/maps/phase3_5_route_map.html",
    )
    parser.add_argument(
        "--output-json",
        default="benchmarks/maps/phase3_5_route_response.json",
    )
    parser.add_argument(
        "--summary-json",
        default="benchmarks/maps/phase3_5_route_map_summary.json",
    )

    parser.add_argument("--timeout-s", type=float, default=30.0)

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    output_html = Path(args.output_html)
    output_json = Path(args.output_json)
    summary_json = Path(args.summary_json)

    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.parent.mkdir(parents=True, exist_ok=True)

    route_result, api_elapsed_ms = fetch_route(
        base_url=args.base_url,
        start_lat=args.start_lat,
        start_lon=args.start_lon,
        end_lat=args.end_lat,
        end_lon=args.end_lon,
        timeout_s=args.timeout_s,
    )

    validate_route_response(route_result)

    output_json.write_text(
        json.dumps(route_result, indent=2),
        encoding="utf-8",
    )

    generated_html = generate_route_map(
        route_result=route_result,
        output_path=output_html,
    )

    summary = build_summary(
        route_result=route_result,
        base_url=args.base_url,
        api_elapsed_ms=api_elapsed_ms,
        output_html=generated_html,
        output_json=output_json,
    )

    summary_json.write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(summary, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())