# tests/conftest.py
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# httpx AsyncClient compatibility shim for tests (single definition)
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
        _httpx.AsyncClient = AsyncClient
except Exception:
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
