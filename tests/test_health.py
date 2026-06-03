# tests/test_health.py

from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_returns_service_status():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "ok"
    assert data["graph_loaded"] is True
    assert "uptime_s" in data
    assert isinstance(data["uptime_s"], float)


def test_graph_stats_after_graph_loading():
    with TestClient(app) as client:
        response = client.get("/graph/stats")

    assert response.status_code == 200

    data = response.json()

    assert data["graph_loaded"] is True
    assert "Kanpur" in data["city"]
    assert data["nodes"] > 0
    assert data["edges"] > 0
    assert data["graph_path"].replace("\\", "/") == "data/graphs/kanpur_central.graphml"
    assert data["load_time_s"] is not None
    assert data["memory_mb"] is not None
    assert data["graph_file_size_mb"] is not None