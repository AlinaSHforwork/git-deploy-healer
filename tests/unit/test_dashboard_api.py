"""Tests for dashboard API endpoints."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_engine():
    with patch('api.server.engine') as mock:
        yield mock


@pytest.fixture
def mock_git_manager():
    with patch('api.server.GitManager') as mock:
        yield mock


@pytest.fixture
def mock_proxy_manager():
    with patch('api.server.ProxyManager') as mock:
        yield mock


class TestDeployEndpoint:
    """Test /api/deploy endpoint."""

    def test_deploy_requires_api_key(self, client):
        """Test deploy endpoint requires API key."""
        response = client.post(
            "/api/deploy",
            json={
                "repository": {
                    "name": "test",
                    "clone_url": "https://github.com/test/test",
                }
            },
        )
        assert response.status_code == 403

    def test_deploy_missing_fields(self, client, monkeypatch):
        """Test deploy with missing required fields."""
        monkeypatch.setenv("API_KEY", "test-key")

        response = client.post(
            "/api/deploy", json={"repository": {}}, headers={"X-API-Key": "test-key"}
        )
        assert response.status_code == 400

    def test_deploy_success(
        self, client, monkeypatch, mock_engine, mock_git_manager, mock_proxy_manager
    ):
        """Test successful deployment."""
        monkeypatch.setenv("API_KEY", "test-key")

        mock_result = MagicMock()
        mock_result.status = "ok"
        mock_result.get_host_port.return_value = 8080
        mock_engine.deploy.return_value = mock_result

        response = client.post(
            "/api/deploy",
            json={
                "repository": {
                    "name": "test-app",
                    "clone_url": "https://github.com/test/app",
                },
                "container_port": 3000,
            },
            headers={"X-API-Key": "test-key"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"


class TestAppManagement:
    """Test app management endpoints."""

    def test_restart_app_not_found(self, client, monkeypatch, mock_engine):
        """Test restart non-existent app."""
        monkeypatch.setenv("API_KEY", "test-key")
        mock_engine.list_containers.return_value = []

        response = client.post(
            "/api/apps/nonexistent/restart", headers={"X-API-Key": "test-key"}
        )
        assert response.status_code == 404

    def test_restart_app_success(self, client, monkeypatch, mock_engine):
        """Test successful app restart."""
        monkeypatch.setenv("API_KEY", "test-key")

        mock_container = MagicMock()
        mock_engine.list_containers.return_value = [mock_container]

        response = client.post(
            "/api/apps/test-app/restart", headers={"X-API-Key": "test-key"}
        )
        assert response.status_code == 200
        mock_container.restart.assert_called_once()

    def test_stop_app_success(self, client, monkeypatch, mock_engine):
        """Test successful app stop."""
        monkeypatch.setenv("API_KEY", "test-key")

        mock_container = MagicMock()
        mock_engine.list_containers.return_value = [mock_container]

        response = client.post(
            "/api/apps/test-app/stop", headers={"X-API-Key": "test-key"}
        )
        assert response.status_code == 200
        mock_container.stop.assert_called_once()

    def test_start_app_success(self, client, monkeypatch, mock_engine):
        """Test successful app start."""
        monkeypatch.setenv("API_KEY", "test-key")

        mock_container = MagicMock()
        mock_engine.list_containers.return_value = [mock_container]

        response = client.post(
            "/api/apps/test-app/start", headers={"X-API-Key": "test-key"}
        )
        assert response.status_code == 200
        mock_container.start.assert_called_once()

    def test_delete_app_success(
        self, client, monkeypatch, mock_engine, mock_git_manager, mock_proxy_manager
    ):
        """Test successful app deletion."""
        monkeypatch.setenv("API_KEY", "test-key")

        mock_container = MagicMock()
        mock_engine.list_containers.return_value = [mock_container]

        response = client.delete(
            "/api/apps/test-app", headers={"X-API-Key": "test-key"}
        )
        assert response.status_code == 200
        mock_container.stop.assert_called_once()
        mock_container.remove.assert_called_once()


class TestLogsEndpoint:
    """Test logs endpoint."""

    def test_get_logs_not_found(self, client, monkeypatch, mock_engine):
        """Test get logs for non-existent app."""
        monkeypatch.setenv("API_KEY", "test-key")
        mock_engine.list_containers.return_value = []

        response = client.get(
            "/api/apps/nonexistent/logs", headers={"X-API-Key": "test-key"}
        )
        assert response.status_code == 404

    def test_get_logs_success(self, client, monkeypatch, mock_engine):
        """Test successful log retrieval."""
        monkeypatch.setenv("API_KEY", "test-key")
        mock_container = MagicMock()
        mock_container.id = "abc123def456"
        mock_container.logs.return_value = b"Log line 1\nLog line 2"
        mock_engine.list_containers.return_value = [mock_container]

        response = client.get(
            "/api/apps/test-app/logs", headers={"X-API-Key": "test-key"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "logs" in data
        assert "Log line 1" in data["logs"]


class TestListAppsEndpoint:
    def test_list_apps_public(self, client, mock_engine):
        """Test list apps is publicly accessible."""
        mock_engine.list_apps.return_value = [
            {"name": "app1", "status": "running"},
            {"name": "app2", "status": "stopped"},
        ]

        response = client.get("/api/apps")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
