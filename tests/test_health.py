# tests/test_health.py

from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_returns_service_status() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200

    data = response.json()

    assert data["status"] in {
        "ok",
        "degraded",
    }
    assert data["graph_loaded"] is True
    assert data["uptime_s"] >= 0.0

    assert set(data) == {
        "status",
        "graph_loaded",
        "uptime_s",
    }


def test_graph_stats_after_graph_loading() -> None:
    with TestClient(app) as client:
        response = client.get("/graph/stats")

    assert response.status_code == 200

    data = response.json()

    assert data["graph_loaded"] is True
    assert data["nodes"] > 0
    assert data["edges"] > 0