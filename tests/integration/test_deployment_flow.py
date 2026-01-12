"""
Integration tests for deployment flow.

Tests the complete deployment pipeline:
1. Service startup and health checks
2. API endpoint availability
3. Database connectivity
4. Container deployment lifecycle
"""
import os
import subprocess
import time
from pathlib import Path

import pytest
import requests

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1",
    reason="Integration tests disabled (set RUN_INTEGRATION=1)",
)


class DockerComposeManager:
    """Helper to manage docker-compose services."""

    def __init__(self, compose_file: Path = Path("docker-compose.test.yml")):
        self.compose_file = compose_file
        self.is_up = False

    def up(self, timeout: int = 60):
        """Start services and wait for health."""
        if not self.compose_file.exists():
            pytest.skip(f"{self.compose_file} not found")

        try:
            subprocess.run(
                ["docker", "compose", "-f", str(self.compose_file), "up", "-d"],
                check=True,
                capture_output=True,
                timeout=30,
            )
            self.is_up = True

            # Wait for app service to be healthy
            self._wait_for_service("http://localhost:8080/health", timeout)
        except subprocess.CalledProcessError as e:
            pytest.fail(f"Failed to start services: {e.stderr.decode()}")
        except subprocess.TimeoutExpired:
            pytest.fail("docker-compose up timed out")

    def down(self):
        """Stop and remove services."""
        if self.is_up:
            try:
                subprocess.run(
                    ["docker", "compose", "-f", str(self.compose_file), "down"],
                    check=False,
                    capture_output=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired:
                subprocess.run(
                    [
                        "docker",
                        "compose",
                        "-f",
                        str(self.compose_file),
                        "down",
                        "-t",
                        "5",
                    ],
                    check=False,
                    capture_output=True,
                )
            self.is_up = False

    def _wait_for_service(self, url: str, timeout: int = 60):
        """Wait for service to be healthy."""
        start_time = time.time()
        last_error = None

        while time.time() - start_time < timeout:
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    return
            except requests.RequestException as e:
                last_error = e
            time.sleep(1)

        raise TimeoutError(
            f"Service did not become healthy at {url} within {timeout}s. "
            f"Last error: {last_error}"
        )

    def get_logs(self, service: str = "app") -> str:
        """Get service logs for debugging."""
        try:
            result = subprocess.run(
                ["docker", "compose", "-f", str(self.compose_file), "logs", service],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout + result.stderr
        except Exception as e:
            return f"Failed to get logs: {e}"


@pytest.fixture
def docker_compose():
    """Fixture to manage docker-compose lifecycle."""
    manager = DockerComposeManager()
    manager.up()
    yield manager
    manager.down()


class TestDeploymentFlow:
    """Test complete deployment flow."""

    def test_service_startup_and_health(self, docker_compose):
        """Test that services start and health endpoint responds."""
        response = requests.get("http://localhost:8080/health", timeout=5)
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
        assert "service" in data

    def test_root_endpoint(self, docker_compose):
        """Test root endpoint returns expected structure."""
        response = requests.get("http://localhost:8080/", timeout=5)
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "docs" in data
        assert "dashboard" in data

    def test_dashboard_endpoint(self, docker_compose):
        """Test dashboard endpoint returns HTML."""
        response = requests.get("http://localhost:8080/dashboard", timeout=5)
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        assert len(response.text) > 0

    def test_metrics_endpoint(self, docker_compose):
        """Test Prometheus metrics endpoint is available."""
        response = requests.get("http://localhost:8080/metrics", timeout=5)
        assert response.status_code == 200
        # Prometheus metrics should contain TYPE and HELP comments
        assert "#" in response.text or "pypaas" in response.text.lower()

    def test_api_docs_endpoint(self, docker_compose):
        """Test OpenAPI docs endpoint."""
        response = requests.get("http://localhost:8080/docs", timeout=5)
        assert response.status_code == 200
        assert "swagger" in response.text.lower() or "openapi" in response.text.lower()

    def test_favicon_no_error(self, docker_compose):
        """Test favicon request doesn't cause errors."""
        response = requests.get("http://localhost:8080/favicon.ico", timeout=5)
        # Should return 204 No Content or 404, not 500
        assert response.status_code in (204, 404)

    def test_health_endpoint_consistency(self, docker_compose):
        """Test health endpoint returns consistent results."""
        for _ in range(5):
            response = requests.get("http://localhost:8080/health", timeout=5)
            assert response.status_code == 200
            data = response.json()
            assert data.get("status") == "ok"
            time.sleep(0.5)

    def test_multiple_concurrent_requests(self, docker_compose):
        """Test service handles multiple concurrent requests."""
        import concurrent.futures

        def make_request():
            response = requests.get("http://localhost:8080/health", timeout=5)
            return response.status_code == 200

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request) for _ in range(20)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert all(results), "Some concurrent requests failed"
        assert len(results) == 20

    def test_service_recovery_after_delay(self, docker_compose):
        """Test service remains healthy after some time."""
        # Initial health check
        response = requests.get("http://localhost:8080/health", timeout=5)
        assert response.status_code == 200

        # Wait and check again
        time.sleep(5)
        response = requests.get("http://localhost:8080/health", timeout=5)
        assert response.status_code == 200

    def test_database_connectivity(self, docker_compose):
        """Test that database is accessible from app."""
        # This is tested indirectly through the app's ability to serve requests
        # A more direct test would require app to expose a DB status endpoint
        response = requests.get("http://localhost:8080/health", timeout=5)
        assert response.status_code == 200
        # If DB wasn't connected, the app would likely fail to start

    def test_environment_variables_loaded(self, docker_compose):
        """Test that environment variables are properly loaded."""
        # Check that API key is required for protected endpoints
        response = requests.post(
            "http://localhost:8080/trigger",
            timeout=5,
        )
        # Should fail without API key
        assert response.status_code in (403, 422)

    def test_trigger_endpoint_with_valid_key(self, docker_compose):
        """Test trigger endpoint with valid API key."""
        response = requests.post(
            "http://localhost:8080/trigger",
            headers={"X-API-Key": "test-api-key"},
            timeout=5,
        )
        assert response.status_code == 200
        data = response.json()
        assert "message" in data

    def test_trigger_endpoint_with_invalid_key(self, docker_compose):
        """Test trigger endpoint rejects invalid API key."""
        response = requests.post(
            "http://localhost:8080/trigger",
            headers={"X-API-Key": "wrong-key"},
            timeout=5,
        )
        assert response.status_code == 403

    def test_service_logs_available(self, docker_compose):
        """Test that service logs can be retrieved for debugging."""
        logs = docker_compose.get_logs("app")
        assert len(logs) > 0
        # Should contain some startup messages
        assert "startup" in logs.lower() or "started" in logs.lower() or len(logs) > 100
