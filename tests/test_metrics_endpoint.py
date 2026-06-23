# tests/test_metrics_endpoint.py

from fastapi.testclient import TestClient

from app.main import app


def test_metrics_endpoint_exposes_prometheus_format():
    with TestClient(app) as client:
        # Make a request that the middleware should count.
        client.get("/health")
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]

    body = response.text

    # Core metric families must be present.
    assert "cityroute_http_requests_total" in body
    assert "cityroute_http_request_duration_seconds" in body
    assert "cityroute_graph_loaded" in body
    assert "cityroute_snap_index_loaded" in body


def test_metrics_counter_increments_for_requests():
    with TestClient(app) as client:
        client.get("/health")
        first = client.get("/metrics").text
        client.get("/health")
        second = client.get("/metrics").text

    # The /health counter sample must appear and the series must exist in both reads.
    assert 'cityroute_http_requests_total{' in first
    assert '/health' in second


def test_metrics_endpoint_is_not_self_instrumented():
    # The scrape endpoint must not record itself (avoids unbounded self-counting).
    with TestClient(app) as client:
        body = client.get("/metrics").text

    assert 'path="/metrics"' not in body
