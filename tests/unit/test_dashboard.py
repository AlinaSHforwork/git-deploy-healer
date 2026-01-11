from fastapi.testclient import TestClient

from api.server import app


def test_dashboard_page(monkeypatch):
    # Ensure engine.list_apps returns a known value for the dashboard
    monkeypatch.setattr(
        "api.server.engine.list_apps",
        lambda: [{"name": "my-app", "id": "abc123", "status": "running", "ports": {}}],
    )
    client = TestClient(app)
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "PyPaaS Dashboard" in r.text


def test_favicon_returns_204():
    client = TestClient(app)
    r = client.get("/favicon.ico")
    assert r.status_code == 204
