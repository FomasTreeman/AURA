from fastapi.testclient import TestClient
from backend.observability.server import app


client = TestClient(app)


def test_root_ok():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_metrics_endpoint():
    r = client.get("/metrics")
    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    assert "text" in ct or "application" in ct


def test_sse_stream():
    r = client.get("/sse")
    assert r.status_code == 200
    lines = r.iter_lines()
    first = next(lines)
    # bytes or str depending on requests implementation
    if isinstance(first, bytes):
        first = first.decode()
    assert "data: observability event" in first
