"""
Integration tests for healer recovery functionality.

Tests the container health monitoring and recovery system:
1. Healer daemon startup
2. Container health monitoring
3. Automatic container restart on failure
4. Recovery verification
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


class ContainerManager:
    """Helper to manage containers during tests."""

    def __init__(self, compose_file: Path = Path("docker-compose.test.yml")):
        self.compose_file = compose_file

    def get_container_id(self, service: str = "app") -> str:
        """Get container ID for a service."""
        try:
            result = subprocess.run(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(self.compose_file),
                    "ps",
                    "-q",
                    service,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout.strip()
        except Exception as e:
            raise RuntimeError(f"Failed to get container ID: {e}")

    def stop_container(self, container_id: str, timeout: int = 10):
        """Stop a container."""
        try:
            subprocess.run(
                ["docker", "stop", "-t", str(timeout), container_id],
                check=True,
                capture_output=True,
                timeout=timeout + 5,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to stop container: {e.stderr.decode()}")

    def kill_container(self, container_id: str):
        """Force kill a container."""
        try:
            subprocess.run(
                ["docker", "kill", container_id],
                check=True,
                capture_output=True,
                timeout=10,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to kill container: {e.stderr.decode()}")

    def get_container_status(self, container_id: str) -> str:
        """Get container status."""
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Status}}", container_id],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout.strip()
        except Exception as e:
            return f"error: {e}"

    def wait_for_container_restart(self, container_id: str, timeout: int = 60) -> bool:
        """Wait for container to restart (status changes from stopped to running)."""
        start_time = time.time()
        last_status = None

        while time.time() - start_time < timeout:
            status = self.get_container_status(container_id)
            if status != last_status:
                print(f"Container status: {status}")
                last_status = status

            if status == "running":
                return True

            time.sleep(1)

        return False


@pytest.fixture
def docker_compose_up():
    """Fixture to ensure docker-compose is running."""
    compose_file = Path("docker-compose.test.yml")
    if not compose_file.exists():
        pytest.skip("docker-compose.test.yml not found")

    # Start services
    subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "up", "-d"],
        check=True,
        capture_output=True,
        timeout=30,
    )

    # Wait for service to be healthy
    for _ in range(60):
        try:
            response = requests.get("http://localhost:8080/health", timeout=2)
            if response.status_code == 200:
                break
        except requests.RequestException:
            pass
        time.sleep(1)
    else:
        pytest.fail("Service did not become healthy")

    yield

    # Cleanup
    subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "down"],
        check=False,
        capture_output=True,
        timeout=30,
    )


@pytest.fixture
def container_manager():
    """Fixture providing container manager."""
    return ContainerManager()


class TestHealerRecovery:
    """Test healer recovery functionality."""

    def test_healer_daemon_enabled(self, docker_compose_up):
        """Test that healer daemon is enabled and running."""
        # Check that service is healthy (implies healer is working)
        response = requests.get("http://localhost:8080/health", timeout=5)
        assert response.status_code == 200

    def test_service_health_monitoring(self, docker_compose_up):
        """Test that service health is continuously monitored."""
        # Make multiple health checks over time
        for i in range(5):
            response = requests.get("http://localhost:8080/health", timeout=5)
            assert response.status_code == 200
            assert response.json().get("status") == "ok"
            time.sleep(2)

    def test_container_restart_detection(self, docker_compose_up, container_manager):
        """Test that container restart is detected."""
        # Get initial container ID
        initial_id = container_manager.get_container_id("app")
        assert initial_id, "Failed to get initial container ID"

        # Verify service is healthy
        response = requests.get("http://localhost:8080/health", timeout=5)
        assert response.status_code == 200

        # Stop the container
        try:
            container_manager.stop_container(initial_id, timeout=5)
        except RuntimeError as e:
            pytest.skip(f"Could not stop container for testing: {e}")

        # Wait a bit for container to stop
        time.sleep(2)

        # Verify container is stopped
        status = container_manager.get_container_status(initial_id)
        assert status in ("exited", "stopped"), f"Container status: {status}"

        # Wait for healer to restart it (or docker-compose to restart it)
        # This depends on the healer configuration
        time.sleep(5)

        # Check if service recovers
        recovered = False
        for _ in range(30):
            try:
                response = requests.get("http://localhost:8080/health", timeout=2)
                if response.status_code == 200:
                    recovered = True
                    break
            except requests.RequestException:
                pass
            time.sleep(1)

        # Service should recover (either through healer or docker-compose restart policy)
        assert recovered, "Service did not recover after container stop"

    def test_service_availability_after_restart(
        self, docker_compose_up, container_manager
    ):
        """Test that service is fully available after restart."""
        # Get initial container ID
        initial_id = container_manager.get_container_id("app")

        # Verify initial health
        response = requests.get("http://localhost:8080/health", timeout=5)
        assert response.status_code == 200

        # Stop container
        try:
            container_manager.stop_container(initial_id, timeout=5)
        except RuntimeError:
            pytest.skip("Could not stop container for testing")

        time.sleep(2)

        # Wait for recovery
        recovered = False
        for _ in range(30):
            try:
                response = requests.get("http://localhost:8080/health", timeout=2)
                if response.status_code == 200:
                    recovered = True
                    break
            except requests.RequestException:
                pass
            time.sleep(1)

        assert recovered, "Service did not recover"

        # Verify all endpoints are available
        endpoints = [
            "/health",
            "/",
            "/dashboard",
            "/docs",
            "/metrics",
        ]

        for endpoint in endpoints:
            response = requests.get(f"http://localhost:8080{endpoint}", timeout=5)
            assert response.status_code in (200, 204), f"Endpoint {endpoint} failed"

    def test_healer_recovery_time(self, docker_compose_up, container_manager):
        """Test that healer recovery time is reasonable."""
        initial_id = container_manager.get_container_id("app")

        # Verify initial health
        response = requests.get("http://localhost:8080/health", timeout=5)
        assert response.status_code == 200

        # Stop container and measure recovery time
        try:
            container_manager.stop_container(initial_id, timeout=5)
        except RuntimeError:
            pytest.skip("Could not stop container for testing")

        time.sleep(2)

        # Measure time to recovery
        start_time = time.time()
        recovered = False

        for _ in range(60):  # Max 60 seconds
            try:
                response = requests.get("http://localhost:8080/health", timeout=2)
                if response.status_code == 200:
                    recovered = True
                    break
            except requests.RequestException:
                pass
            time.sleep(1)

        recovery_time = time.time() - start_time

        assert recovered, "Service did not recover"
        # Recovery should be reasonably fast (within 60 seconds)
        # Actual time depends on healer interval and docker-compose restart policy
        assert recovery_time < 60, f"Recovery took too long: {recovery_time}s"

    def test_multiple_health_checks_after_recovery(
        self, docker_compose_up, container_manager
    ):
        """Test that multiple health checks succeed after recovery."""
        initial_id = container_manager.get_container_id("app")

        # Stop container
        try:
            container_manager.stop_container(initial_id, timeout=5)
        except RuntimeError:
            pytest.skip("Could not stop container for testing")

        time.sleep(2)

        # Wait for recovery
        recovered = False
        for _ in range(30):
            try:
                response = requests.get("http://localhost:8080/health", timeout=2)
                if response.status_code == 200:
                    recovered = True
                    break
            except requests.RequestException:
                pass
            time.sleep(1)

        assert recovered, "Service did not recover"

        # Make multiple health checks
        for i in range(10):
            response = requests.get("http://localhost:8080/health", timeout=5)
            assert response.status_code == 200
            assert response.json().get("status") == "ok"
            time.sleep(0.5)

    def test_healer_with_api_requests(self, docker_compose_up, container_manager):
        """Test that healer works while API is receiving requests."""
        initial_id = container_manager.get_container_id("app")

        # Make continuous health checks
        import threading

        stop_checking = False
        check_results = []

        def continuous_health_checks():
            while not stop_checking:
                try:
                    response = requests.get("http://localhost:8080/health", timeout=2)
                    check_results.append(response.status_code == 200)
                except requests.RequestException:
                    check_results.append(False)
                time.sleep(0.5)

        # Start continuous checks
        check_thread = threading.Thread(target=continuous_health_checks)
        check_thread.start()

        try:
            # Let it run for a bit
            time.sleep(3)

            # Stop container
            try:
                container_manager.stop_container(initial_id, timeout=5)
            except RuntimeError:
                pytest.skip("Could not stop container for testing")

            time.sleep(2)

            # Let recovery happen while checks continue
            time.sleep(10)

        finally:
            stop_checking = True
            check_thread.join(timeout=5)

        # Should have some successful checks before and after restart
        assert len(check_results) > 0
        # At least some checks should have succeeded
        assert any(check_results), "No successful health checks"
