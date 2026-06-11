# benchmarks/phase4_route_compare_probe.py

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = os.getenv("CITYROUTE_BASE_URL", "http://127.0.0.1:8001")

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "benchmarks"
    / "phase4_results"
    / "phase4_route_compare_sample.json"
)

DEFAULT_SUMMARY_OUTPUT = (
    PROJECT_ROOT
    / "benchmarks"
    / "phase4_results"
    / "phase4_route_compare_summary.json"
)


def fetch_route_compare(
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

    url = f"{base_url.rstrip('/')}/route/compare?{query}"
    request = Request(url, headers={"Accept": "application/json"})

    started_at = time.perf_counter()

    try:
        with urlopen(request, timeout=timeout_s) as response:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            raw_body = response.read().decode("utf-8")
            return json.loads(raw_body), round(elapsed_ms, 3)

    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Route compare API returned HTTP {exc.code}. Body: {body}"
        ) from exc

    except URLError as exc:
        raise RuntimeError(
            f"Could not connect to route compare API at {url}. "
            "Make sure Docker or local Uvicorn is running."
        ) from exc


def validate_route_compare_response(response: dict[str, Any]) -> None:
    if response.get("status") != "ok":
        raise ValueError("Route compare response status must be 'ok'.")

    if "start" not in response:
        raise ValueError("Route compare response is missing start section.")

    if "end" not in response:
        raise ValueError("Route compare response is missing end section.")

    if "astar" not in response:
        raise ValueError("Route compare response is missing astar section.")

    if "bidirectional_astar" not in response:
        raise ValueError(
            "Route compare response is missing bidirectional_astar section."
        )

    if "comparison" not in response:
        raise ValueError("Route compare response is missing comparison section.")

    astar = response["astar"]
    bidirectional = response["bidirectional_astar"]
    comparison = response["comparison"]

    if astar.get("algorithm") != "astar":
        raise ValueError("A* algorithm field must be 'astar'.")

    if bidirectional.get("algorithm") != "bidirectional_astar":
        raise ValueError(
            "Bidirectional algorithm field must be 'bidirectional_astar'."
        )

    if comparison.get("same_distance") is not True:
        raise ValueError("A* and Bidirectional A* distances do not match.")

    if float(comparison.get("distance_delta_m", 999999.0)) > 0.001:
        raise ValueError(
            f"Distance delta exceeds tolerance: {comparison.get('distance_delta_m')}"
        )

    if response["start"].get("snap_method") != "balltree":
        raise ValueError("Start snap method must be 'balltree'.")

    if response["end"].get("snap_method") != "balltree":
        raise ValueError("End snap method must be 'balltree'.")


def build_summary(
    *,
    response: dict[str, Any],
    base_url: str,
    api_elapsed_ms: float,
    output_json: Path,
) -> dict[str, Any]:
    astar = response["astar"]
    bidirectional = response["bidirectional_astar"]
    comparison = response["comparison"]

    return {
        "artifact": "phase4_route_compare_probe",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "status": response.get("status"),
        "api_elapsed_ms": api_elapsed_ms,
        "start_snapped_node": response["start"].get("snapped_node"),
        "end_snapped_node": response["end"].get("snapped_node"),
        "start_snap_method": response["start"].get("snap_method"),
        "end_snap_method": response["end"].get("snap_method"),
        "astar": {
            "algorithm": astar.get("algorithm"),
            "distance_m": astar.get("distance_m"),
            "distance_km": astar.get("distance_km"),
            "path_node_count": astar.get("path_node_count"),
            "nodes_expanded": astar.get("nodes_expanded"),
            "route_time_ms": astar.get("route_time_ms"),
            "total_time_ms": astar.get("total_time_ms"),
        },
        "bidirectional_astar": {
            "algorithm": bidirectional.get("algorithm"),
            "distance_m": bidirectional.get("distance_m"),
            "distance_km": bidirectional.get("distance_km"),
            "path_node_count": bidirectional.get("path_node_count"),
            "nodes_expanded": bidirectional.get("nodes_expanded"),
            "forward_nodes_expanded": bidirectional.get("forward_nodes_expanded"),
            "backward_nodes_expanded": bidirectional.get("backward_nodes_expanded"),
            "route_time_ms": bidirectional.get("route_time_ms"),
            "meeting_node": bidirectional.get("meeting_node"),
            "geometry_points": len(bidirectional.get("geometry", [])),
        },
        "comparison": {
            "distance_delta_m": comparison.get("distance_delta_m"),
            "same_distance": comparison.get("same_distance"),
            "astar_route_time_ms": comparison.get("astar_route_time_ms"),
            "bidirectional_route_time_ms": comparison.get(
                "bidirectional_route_time_ms"
            ),
            "route_time_delta_ms": comparison.get("route_time_delta_ms"),
            "astar_faster": comparison.get("astar_faster"),
            "bidirectional_faster": comparison.get("bidirectional_faster"),
            "astar_nodes_expanded": comparison.get("astar_nodes_expanded"),
            "bidirectional_nodes_expanded": comparison.get(
                "bidirectional_nodes_expanded"
            ),
            "nodes_expanded_delta": comparison.get("nodes_expanded_delta"),
            "nodes_expanded_reduction_pct": comparison.get(
                "nodes_expanded_reduction_pct"
            ),
            "route_time_reduction_pct": comparison.get(
                "route_time_reduction_pct"
            ),
        },
        "compare_total_time_ms": response.get("compare_total_time_ms"),
        "output_json": str(output_json),
        "verification": {
            "route_compare_response_received": True,
            "astar_section_present": "astar" in response,
            "bidirectional_astar_section_present": "bidirectional_astar" in response,
            "comparison_section_present": "comparison" in response,
            "same_distance": comparison.get("same_distance") is True,
            "distance_delta_within_tolerance": (
                float(comparison.get("distance_delta_m", 999999.0)) <= 0.001
            ),
            "uses_balltree_snapping": (
                response["start"].get("snap_method") == "balltree"
                and response["end"].get("snap_method") == "balltree"
            ),
            "docker_api_route_compare_working": True,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe Phase 4 /route/compare endpoint and save evidence."
    )

    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)

    parser.add_argument("--start-lat", type=float, default=26.44)
    parser.add_argument("--start-lon", type=float, default=80.30)
    parser.add_argument("--end-lat", type=float, default=26.45)
    parser.add_argument("--end-lon", type=float, default=80.35)

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )

    parser.add_argument(
        "--summary-output",
        type=Path,
        default=DEFAULT_SUMMARY_OUTPUT,
    )

    parser.add_argument("--timeout-s", type=float, default=30.0)

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)

    response, api_elapsed_ms = fetch_route_compare(
        base_url=args.base_url,
        start_lat=args.start_lat,
        start_lon=args.start_lon,
        end_lat=args.end_lat,
        end_lon=args.end_lon,
        timeout_s=args.timeout_s,
    )

    validate_route_compare_response(response)

    args.output.write_text(
        json.dumps(response, indent=2),
        encoding="utf-8",
    )

    summary = build_summary(
        response=response,
        base_url=args.base_url,
        api_elapsed_ms=api_elapsed_ms,
        output_json=args.output,
    )

    args.summary_output.write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(summary, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())