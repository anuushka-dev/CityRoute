# tests/test_geo_validation.py

import pytest
from fastapi import HTTPException

from app.config import settings
from app.utils.geo_validation import validate_coordinates


def test_valid_coordinate_inside_graph_bbox_passes():
    lat = (settings.bbox_south + settings.bbox_north) / 2
    lon = (settings.bbox_west + settings.bbox_east) / 2

    validate_coordinates(lat=lat, lon=lon)


def test_invalid_latitude_returns_422():
    with pytest.raises(HTTPException) as exc_info:
        validate_coordinates(lat=999, lon=80.35)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error"] == "Invalid latitude"


def test_invalid_longitude_returns_422():
    with pytest.raises(HTTPException) as exc_info:
        validate_coordinates(lat=26.45, lon=999)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error"] == "Invalid longitude"


def test_coordinate_outside_graph_bbox_returns_422():
    outside_lat = settings.bbox_south - 1
    valid_lon = (settings.bbox_west + settings.bbox_east) / 2

    with pytest.raises(HTTPException) as exc_info:
        validate_coordinates(lat=outside_lat, lon=valid_lon)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error"] == "Coordinate outside loaded graph area"
    assert "allowed_bbox" in exc_info.value.detail