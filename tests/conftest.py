"""
Test fixtures and global patches to make the test environment safe and deterministic.
This file patches Docker and the ContainerEngine so importing modules does not
attempt to contact the Docker socket.
"""
import sys
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch
from httpx import AsyncClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --- httpx AsyncClient compatibility shim for tests ---
# Wrap httpx.AsyncClient so tests can pass `app=` (ASGI app).
try:
    import httpx as _httpx
    ASGITransport = getattr(_httpx, "ASGITransport", None)
    _orig_AsyncClient = getattr(_httpx, "AsyncClient", None)
    if _orig_AsyncClient is not None:
        class AsyncClient(_orig_AsyncClient):
            def __init__(self, *args, app=None, **kwargs):
                if app is not None and ASGITransport is not None and "transport" not in kwargs:
                    kwargs["transport"] = ASGITransport(app=app)
                super().__init__(*args, **kwargs)
        # inject wrapper into httpx module used by tests
        _httpx.AsyncClient = AsyncClient
except Exception:
    # If httpx isn't available in the environment, tests will fail later with a clear error.
    pass

@pytest.fixture(autouse=True)
def patch_docker_and_engine():
    """
    Autouse fixture that prevents docker.from_env() from contacting the host.
    It also patches core.engine.ContainerEngine to return a fake engine instance.
    """
    # Fake low-level docker client
    fake_client = MagicMock()
    fake_client.containers = MagicMock()
    fake_client.images = MagicMock()

    # Fake engine with common methods used by the app
    fake_engine = MagicMock()
    fake_engine.list_apps.return_value = []
    fake_engine.build_image.return_value = "test:latest"
    fake_deploy_result = MagicMock()
    fake_deploy_result.status = "ok"
    fake_deploy_result.host_port = 12345
    fake_engine.deploy.return_value = fake_deploy_result

    # Patch docker.from_env and docker.APIClient to avoid socket access
    with patch("docker.from_env", return_value=fake_client), \
         patch("docker.APIClient", return_value=MagicMock()), \
         patch("core.engine.ContainerEngine", return_value=fake_engine):
        yield
