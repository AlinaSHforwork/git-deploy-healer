# tests/conftest.py
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from httpx import AsyncClient as _orig_AsyncClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Custom AsyncClient wrapper
# ---------------------------------------------------------------------------
ASGITransport = getattr(httpx, "ASGITransport", None)


class AsyncClient(_orig_AsyncClient):
    """
    A compatibility shim that injects ASGITransport(app=...) automatically
    when tests pass `app=...` to AsyncClient.
    """

    def __init__(self, *args, app=None, **kwargs):
        if app is not None and ASGITransport is not None and "transport" not in kwargs:
            kwargs["transport"] = ASGITransport(app=app)
        super().__init__(*args, **kwargs)


# ---------------------------------------------------------------------------
# Patch httpx.AsyncClient safely using monkeypatch (mypy‑safe)
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def patch_httpx_async_client(monkeypatch):
    """
    Automatically replace httpx.AsyncClient with our custom AsyncClient
    for all tests, without assigning to a type (mypy‑safe).
    """
    monkeypatch.setattr(httpx, "AsyncClient", AsyncClient)
    yield


# ---------------------------------------------------------------------------
# Patch docker + engine for all tests
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def patch_docker_and_engine():
    """
    Prevent docker.from_env() from contacting the host.
    Patch core.engine.ContainerEngine to return a fake engine instance.
    """
    fake_client = MagicMock()
    fake_client.containers = MagicMock()
    fake_client.images = MagicMock()

    fake_engine = MagicMock()
    fake_engine.list_apps.return_value = []
    fake_engine.build_image.return_value = "test:latest"

    fake_deploy_result = MagicMock()
    fake_deploy_result.status = "ok"
    fake_deploy_result.host_port = 12345
    fake_engine.deploy.return_value = fake_deploy_result

    with (
        patch("docker.from_env", return_value=fake_client),
        patch("docker.APIClient", return_value=MagicMock()),
        patch("core.engine.ContainerEngine", return_value=fake_engine),
    ):
        yield
