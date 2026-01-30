from unittest.mock import MagicMock, patch

import docker.errors
import pytest
from fastapi.testclient import TestClient

try:
    from api.server import app
except ImportError:
    from fastapi import FastAPI

    app = FastAPI()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def api_key_headers():
    return {"X-API-Key": "test-secret-key"}


@pytest.fixture(autouse=True)
def set_env_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-secret-key")


class TestDeployEndpoint:
    def test_deploy_requires_api_key(self, client):
        response = client.post("/api/deploy")
        assert response.status_code == 403

    def test_deploy_missing_fields(self, client, api_key_headers):
        response = client.post("/api/deploy", json={}, headers=api_key_headers)
        assert response.status_code == 422


class TestAppManagement:
    def test_restart_app_not_found(self, client, api_key_headers):
        with patch("api.server.engine") as mock_engine, patch(
            "docker.from_env"
        ) as mock_docker:
            mock_engine.list_containers.return_value = []
            mock_docker.return_value.containers.get.side_effect = (
                docker.errors.NotFound("Not found")
            )

            response = client.post(
                "/api/apps/nonexistent/restart", headers=api_key_headers
            )
            assert response.status_code == 404

    def test_restart_app_success(self, client, api_key_headers):
        with patch("api.server.engine") as mock_engine:
            mock_container = MagicMock()
            mock_engine.list_containers.return_value = [mock_container]

            response = client.post(
                "/api/apps/test-app/restart", headers=api_key_headers
            )

            assert response.status_code == 200
            assert response.json()["restarted"] == 1
            mock_container.restart.assert_called_once()

    def test_stop_app_success(self, client, api_key_headers):
        with patch("api.server.engine") as mock_engine:
            mock_container = MagicMock()
            mock_container.status = "running"
            mock_engine.list_containers.return_value = [mock_container]

            response = client.post("/api/apps/test-app/stop", headers=api_key_headers)

            assert response.status_code == 200
            mock_container.stop.assert_called_once()

    def test_start_app_success(self, client, api_key_headers):
        with patch("api.server.engine") as mock_engine:
            mock_container = MagicMock()
            mock_container.status = "exited"
            mock_engine.list_containers.return_value = [mock_container]

            response = client.post("/api/apps/test-app/start", headers=api_key_headers)

            assert response.status_code == 200
            mock_container.start.assert_called_once()

    def test_delete_app_success(self, client, api_key_headers):
        with patch("api.server.engine") as mock_engine, patch(
            "api.server.ProxyManager"
        ), patch("api.server.GitManager"), patch("docker.from_env"):
            mock_container = MagicMock()
            mock_engine.list_containers.return_value = [mock_container]

            response = client.delete("/api/apps/test-app", headers=api_key_headers)

            assert response.status_code == 200
            mock_container.remove.assert_called_with(force=True)


class TestLogsEndpoint:
    def test_get_logs_not_found(self, client, api_key_headers):
        with patch("api.server.engine") as mock_engine, patch(
            "docker.from_env"
        ) as mock_docker:
            mock_engine.list_containers.return_value = []
            mock_docker.return_value.containers.get.side_effect = (
                docker.errors.NotFound("Not found")
            )

            response = client.get("/api/apps/nonexistent/logs", headers=api_key_headers)
            assert response.status_code == 404

    def test_get_logs_success(self, client, api_key_headers):
        with patch("api.server.engine") as mock_engine:
            mock_container = MagicMock()
            mock_container.logs.return_value = b"log line 1\nlog line 2"
            mock_engine.list_containers.return_value = [mock_container]

            response = client.get("/api/apps/test-app/logs", headers=api_key_headers)

            assert response.status_code == 200
            data = response.json()
            assert "log line 1" in data["logs"]


class TestListAppsEndpoint:
    def test_list_apps_public(self, client):
        with patch("api.server.engine") as mock_engine:
            mock_engine.list_apps.return_value = {"app1": {}}
            response = client.get("/api/apps")
            assert response.status_code == 200
            assert "app1" in response.json()
