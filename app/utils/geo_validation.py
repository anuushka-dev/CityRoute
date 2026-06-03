# app/utils/geo_validation.py

from __future__ import annotations

from fastapi import HTTPException

from app.config import settings


def validate_latitude(lat: float) -> None:
    if lat < -90 or lat > 90:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Invalid latitude",
                "message": "Latitude must be between -90 and 90.",
                "received": lat,
            },
        )


def validate_longitude(lon: float) -> None:
    if lon < -180 or lon > 180:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Invalid longitude",
                "message": "Longitude must be between -180 and 180.",
                "received": lon,
            },
        )


def validate_within_graph_bbox(lat: float, lon: float) -> None:
    if not settings.use_bbox_graph:
        return

    inside_lat = settings.bbox_south <= lat <= settings.bbox_north
    inside_lon = settings.bbox_west <= lon <= settings.bbox_east

    if not inside_lat or not inside_lon:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Coordinate outside loaded graph area",
                "message": "Coordinate must be inside the configured central Kanpur graph bounding box.",
                "received": {
                    "lat": lat,
                    "lon": lon,
                },
                "allowed_bbox": {
                    "south": settings.bbox_south,
                    "north": settings.bbox_north,
                    "west": settings.bbox_west,
                    "east": settings.bbox_east,
                },
            },
        )


def validate_coordinates(lat: float, lon: float) -> None:
    validate_latitude(lat)
    validate_longitude(lon)
    validate_within_graph_bbox(lat, lon)