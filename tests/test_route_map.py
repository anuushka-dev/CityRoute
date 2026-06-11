# tests/test_route_map.py

from __future__ import annotations

from pathlib import Path

import pytest

from app.utils.route_map import generate_route_map


def _sample_route_result() -> dict:
    return {
        "status": "ok",
        "algorithm": "astar",
        "start": {
            "input": {
                "lat": 26.44,
                "lon": 80.30,
            },
            "snapped_node": 5317312245,
            "snapped": {
                "lat": 26.4400833,
                "lon": 80.2999386,
            },
            "snap_distance_m": 11.098,
            "snap_method": "balltree",
            "snap_time_ms": 0.5,
        },
        "end": {
            "input": {
                "lat": 26.45,
                "lon": 80.35,
            },
            "snapped_node": 6288159135,
            "snapped": {
                "lat": 26.4502842,
                "lon": 80.3497914,
            },
            "snap_distance_m": 37.815,
            "snap_method": "balltree",
            "snap_time_ms": 0.4,
        },
        "distance_m": 6428.798,
        "distance_km": 6.429,
        "eta_seconds": 999.5,
        "eta_minutes": 16.66,
        "path_node_count": 4,
        "nodes_expanded": 2622,
        "route_time_ms": 31.714,
        "total_time_ms": 34.814,
        "geometry": [
            {"lat": 26.4400833, "lon": 80.2999386},
            {"lat": 26.440297, "lon": 80.3002594},
            {"lat": 26.4454078, "lon": 80.303679},
            {"lat": 26.4502842, "lon": 80.3497914},
        ],
    }


def test_generate_route_map_creates_html_file(tmp_path: Path) -> None:
    route_result = _sample_route_result()
    output_path = tmp_path / "phase3_5_route_map.html"

    generated_path = generate_route_map(
        route_result=route_result,
        output_path=output_path,
    )

    assert generated_path == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0


def test_generate_route_map_html_contains_route_markers_and_summary(tmp_path: Path) -> None:
    route_result = _sample_route_result()
    output_path = tmp_path / "route_map.html"

    generate_route_map(
        route_result=route_result,
        output_path=output_path,
    )

    html = output_path.read_text(encoding="utf-8")

    assert "CityRoute Phase 3.5 Route Verification" in html
    assert "A* route geometry" in html
    assert "Start" in html
    assert "End" in html
    assert "astar" in html
    assert "balltree" in html


def test_generate_route_map_uses_route_geometry_coordinates(tmp_path: Path) -> None:
    route_result = _sample_route_result()
    output_path = tmp_path / "route_map.html"

    generate_route_map(
        route_result=route_result,
        output_path=output_path,
    )

    html = output_path.read_text(encoding="utf-8")

    assert "26.4400833" in html
    assert "80.2999386" in html
    assert "26.4502842" in html
    assert "80.3497914" in html


def test_generate_route_map_rejects_missing_geometry(tmp_path: Path) -> None:
    route_result = _sample_route_result()
    route_result.pop("geometry")

    with pytest.raises(ValueError, match="geometry list"):
        generate_route_map(
            route_result=route_result,
            output_path=tmp_path / "bad_map.html",
        )


def test_generate_route_map_rejects_geometry_with_less_than_two_points(tmp_path: Path) -> None:
    route_result = _sample_route_result()
    route_result["geometry"] = [
        {"lat": 26.4400833, "lon": 80.2999386},
    ]

    with pytest.raises(ValueError, match="at least 2 points"):
        generate_route_map(
            route_result=route_result,
            output_path=tmp_path / "bad_map.html",
        )


def test_generate_route_map_rejects_geometry_point_without_lat_lon(tmp_path: Path) -> None:
    route_result = _sample_route_result()
    route_result["geometry"] = [
        {"lat": 26.4400833, "lon": 80.2999386},
        {"lat": 26.4502842},
    ]

    with pytest.raises(ValueError, match="lat and lon"):
        generate_route_map(
            route_result=route_result,
            output_path=tmp_path / "bad_map.html",
        )