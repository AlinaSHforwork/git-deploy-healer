import os
from unittest.mock import MagicMock

import httpx
import pytest

# import your FastAPI app; adjust path if needed
from api.server import app  # assume app is FastAPI instance

os.environ["API_KEY"] = "test-key"


@pytest.mark.asyncio
async def test_health_endpoint():
    async with httpx.AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


@pytest.mark.asyncio
async def test_trigger_endpoint(monkeypatch):
    # mock healer trigger
    from api import healer as healer_module

    monkeypatch.setattr(healer_module, "trigger_heal", lambda: None)

    # set API key for the test environment
    import os

    os.environ["API_KEY"] = "test-key"

    async with httpx.AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.post("/trigger", headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    assert "triggered" in r.json().get("message", "").lower()


@pytest.mark.asyncio
async def test_healer_starts_on_startup(monkeypatch):
    """Test that healer daemon starts when ENABLE_HEALER=true"""
    monkeypatch.setenv("ENABLE_HEALER", "true")
    monkeypatch.setenv("API_KEY", "test")

    from fastapi import FastAPI

    from api.server import lifespan

    app = FastAPI()

    async with lifespan(app):
        pass  # Healer should start and stop cleanly


@pytest.mark.asyncio
async def test_db_health_endpoint_healthy(monkeypatch):
    """Test database health endpoint returns 200 when healthy."""
    # from core.models import DatabaseManager

    mock_manager = MagicMock()
    mock_manager.health_check.return_value = True

    monkeypatch.setattr("api.server.get_db_manager", lambda: mock_manager)

    async with httpx.AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.get("/health/db")

    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_db_health_endpoint_unhealthy(monkeypatch):
    """Test database health endpoint returns 503 when unhealthy."""
    # from core.models import DatabaseManager

    mock_manager = MagicMock()
    mock_manager.health_check.return_value = False

    monkeypatch.setattr("api.server.get_db_manager", lambda: mock_manager)

    async with httpx.AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.get("/health/db")

    assert r.status_code == 503
    assert r.json()["status"] == "unhealthy"


@pytest.mark.asyncio
async def test_db_health_endpoint_not_configured(monkeypatch):
    """Test database health endpoint when DB not configured."""

    def raise_error():
        raise ValueError("DB not configured")

    monkeypatch.setattr("api.server.get_db_manager", raise_error)

    async with httpx.AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.get("/health/db")

    assert r.status_code == 503
    assert "not_configured" in r.json()["database"]
