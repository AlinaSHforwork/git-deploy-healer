# tests/conftest.py
"""Enhanced test configuration with better mocks and fixtures."""
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
# Custom AsyncClient wrapper (adds ASGITransport when app=... is passed)
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
# Patch httpx.AsyncClient for ALL tests (mypy‑safe)
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def patch_httpx_async_client(monkeypatch):
    """
    Replace httpx.AsyncClient with our custom AsyncClient for all tests.
    This avoids assigning to a type directly (mypy‑safe).
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


# ---------------------------------------------------------------------------
# Database fixture for tests that need it
# ---------------------------------------------------------------------------
@pytest.fixture
def test_db_url():
    """Provide test database URL."""
    return "sqlite:///:memory:"


@pytest.fixture
def db_manager(test_db_url):
    """Create test database manager."""
    from core.models import DatabaseManager

    manager = DatabaseManager(test_db_url)
    manager.create_tables()
    yield manager
    manager.drop_tables()


@pytest.fixture
def db_session(db_manager):
    """Create database session for tests."""
    session = db_manager.get_session()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# Mock requests for health checks
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_requests(monkeypatch):
    """Mock requests library for HTTP health checks."""
    mock = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock.get.return_value = mock_response

    monkeypatch.setattr("core.engine.requests", mock)
    return mock


# ---------------------------------------------------------------------------
# Clean environment for each test
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Ensure clean environment variables for each test."""
    # Set default test values
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "test-webhook-secret")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    yield

    # Reset any modified global state
    import api.auth

    if hasattr(api.auth, "_failed_attempts"):
        api.auth._failed_attempts.clear()
