import pytest
from httpx import AsyncClient

# import your FastAPI app; adjust path if needed
from api.server import app  # assume app is FastAPI instance


@pytest.mark.asyncio
async def test_health_endpoint():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


@pytest.mark.asyncio
async def test_trigger_endpoint(monkeypatch):
    # mock healer trigger
    from api import healer as healer_module
    monkeypatch.setattr(healer_module, "trigger_heal", lambda: None)

    async with AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.post("/trigger")
    assert r.status_code == 200
    assert "triggered" in r.json().get("message", "").lower()
