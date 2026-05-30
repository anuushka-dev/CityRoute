# tests/test_health.py

from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_returns_service_status():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "ok"
    assert data["graph_loaded"] is False
    assert "uptime_s" in data


def test_graph_stats_before_graph_loading():
    with TestClient(app) as client:
        response = client.get("/graph/stats")

    assert response.status_code == 200

    data = response.json()

    assert data["graph_loaded"] is False
    assert data["city"] == "Kanpur, Uttar Pradesh, India"
    assert data["nodes"] == 0
    assert data["edges"] == 0
    assert data["graph_path"].replace("\\", "/") == "data/graphs/kanpur.graphml"
    assert data["load_time_s"] is None
    assert data["memory_mb"] is None