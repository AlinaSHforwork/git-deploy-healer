"""Tests for enhanced ContainerEngine with rollback capability."""
from unittest.mock import MagicMock, patch

import pytest

from core.engine import ContainerEngine, Result


@pytest.fixture
def mock_docker_client():
    """Create mock Docker client."""
    client = MagicMock()
    client.containers.list.return_value = []
    client.images.build.return_value = ([], {"stream": "built"})
    return client


@pytest.fixture
def engine(mock_docker_client):
    """Create ContainerEngine with mock client."""
    engine = ContainerEngine()
    engine._client = mock_docker_client
    return engine


class TestBasicOperations:
    """Test basic container operations."""

    def test_list_apps(self, engine):
        """Test listing applications."""
        mock_container = MagicMock()
        mock_container.name = "test-app"
        mock_container.status = "running"
        mock_container.ports = {80: 8080}

        engine.client.containers.list.return_value = [mock_container]

        apps = engine.list_apps()
        assert len(apps) == 1
        assert apps[0]["name"] == "test-app"

    def test_list_containers_for_app(self, engine):
        """Test listing containers for specific app."""
        mock_container = MagicMock()
        engine.client.containers.list.return_value = [mock_container]

        containers = engine.list_containers("test-app")

        engine.client.containers.list.assert_called_with(
            all=True, filters={"label": "app=test-app"}
        )
        assert len(containers) == 1

    def test_build_image_success(self, engine):
        """Test successful image build."""
        tag = engine.build_image("/path/to/app", "test-app:latest")

        engine.client.images.build.assert_called_once()
        assert tag == "test-app:latest"

    def test_build_image_failure(self, engine):
        """Test image build failure."""
        engine.client.images.build.side_effect = Exception("Build failed")

        with pytest.raises(Exception, match="Build failed"):
            engine.build_image("/path/to/app", "test-app:latest")


class TestHealthCheck:
    """Test health check functionality."""

    def test_health_check_running_container(self, engine):
        """Test health check on running container."""
        container = MagicMock()
        container.id = "abc123"
        container.status = "running"
        container.ports = {}
        container.reload = MagicMock()

        result = engine.health_check(container, timeout=5)

        assert result is True

    def test_health_check_with_http(self, engine):
        """Test health check with HTTP endpoint."""
        container = MagicMock()
        container.id = "abc123"
        container.status = "running"
        container.ports = {"80/tcp": [{"HostPort": "8080"}]}
        container.reload = MagicMock()

        with patch("core.engine.requests") as mock_requests:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_requests.get.return_value = mock_response

            result = engine.health_check(container, timeout=5)

            assert result is True
            mock_requests.get.assert_called()

    def test_health_check_timeout(self, engine):
        """Test health check timeout."""
        container = MagicMock()
        container.id = "abc123"
        container.status = "stopped"
        container.reload = MagicMock()

        result = engine.health_check(container, timeout=1, interval=0.5)

        assert result is False

    def test_health_check_no_container_id(self, engine):
        """Test health check with invalid container."""
        container = MagicMock()
        container.id = None

        result = engine.health_check(container)

        assert result is False


class TestDeployWithRollback:
    """Test transaction-safe deployment with rollback."""

    def test_deploy_with_rollback_success(self, engine):
        """Test successful deployment with rollback capability."""
        # Mock old container
        old_container = MagicMock()
        old_container.id = "old123"
        engine.client.containers.list.return_value = [old_container]

        # Mock new container
        new_container = MagicMock()
        new_container.id = "new456"
        new_container.status = "running"
        new_container.ports = {}

        # Mock successful deployment
        with patch.object(
            engine, 'deploy', return_value=Result(status="ok", container_id="new456")
        ):
            engine.client.containers.get.return_value = new_container

            # Mock stop and remove as MagicMock methods
            with patch.object(engine, 'stop_container') as mock_stop:
                with patch.object(engine, 'remove_container') as mock_remove:
                    # Mock health check success
                    with patch.object(engine, "health_check", return_value=True):
                        result = engine.deploy_with_rollback(
                            "test-app", "test-app:latest", container_port=8080
                        )

                    assert result.status == "ok"
                    # Verify old container was stopped and removed
                    assert mock_stop.called
                    assert mock_remove.called

    def test_deploy_with_rollback_health_check_fails(self, engine):
        """Test rollback when health check fails."""
        # Mock no old containers
        engine.client.containers.list.return_value = []

        # Mock new container
        new_container = MagicMock()
        new_container.id = "new456"

        # Mock successful deploy but failed health check
        with patch.object(
            engine, 'deploy', return_value=Result(status="ok", container_id="new456")
        ):
            engine.client.containers.get.return_value = new_container

            # Mock health check failure
            with patch.object(engine, "health_check", return_value=False):
                result = engine.deploy_with_rollback("test-app", "test-app:latest")

        assert result.status == "failed"
        assert "rolled back" in result.error.lower()

    def test_deploy_with_rollback_deploy_fails(self, engine):
        """Test rollback when initial deploy fails."""
        engine.client.containers.list.return_value = []

        # Mock deploy failure
        with patch.object(
            engine, 'deploy', return_value=Result(status="failed", error="Deploy error")
        ):
            result = engine.deploy_with_rollback("test-app", "test-app:latest")

        assert result.status == "failed"

    def test_deploy_with_rollback_unexpected_error(self, engine):
        """Test rollback on unexpected error during list."""
        # Make list_containers raise during the initial call
        engine.client.containers.list.side_effect = Exception("Unexpected")

        result = engine.deploy_with_rollback("test-app", "test-app:latest")

        assert result.status == "failed"
        # The exception is caught and wrapped
        assert result.error is not None
        assert len(result.error) > 0


class TestContainerOperations:
    """Test container start/stop/remove operations."""

    def test_run_container(self, engine):
        """Test running a container."""
        mock_container = MagicMock()
        mock_container.id = "abc123"
        engine.client.containers.run.return_value = mock_container

        container = engine.run_container(
            "test-app:latest", detach=True, name="test-container"
        )

        assert container.id == "abc123"

    def test_stop_container(self, engine):
        """Test stopping a container."""
        mock_container = MagicMock()
        engine.client.containers.get.return_value = mock_container

        engine.stop_container("abc123", timeout=5)

        mock_container.stop.assert_called_once_with(timeout=5)

    def test_remove_container(self, engine):
        """Test removing a container."""
        mock_container = MagicMock()
        engine.client.containers.get.return_value = mock_container

        engine.remove_container("abc123", force=True)

        mock_container.remove.assert_called_once_with(force=True)

    def test_stop_container_failure(self, engine):
        """Test stop container error handling."""
        engine.client.containers.get.side_effect = Exception("Not found")

        with pytest.raises(Exception):
            engine.stop_container("abc123")


class TestDeploy:
    """Test basic deploy functionality."""

    def test_deploy_success(self, engine):
        """Test successful deployment."""
        mock_container = MagicMock()
        mock_container.id = "new123"
        mock_container.ports = {"80/tcp": [{"HostPort": "8080"}]}

        engine.client.containers.run.return_value = mock_container
        engine.client.containers.list.return_value = [mock_container]

        result = engine.deploy(
            "test-app",
            "test-app:latest",
            container_port=80,
            environment={"ENV": "prod"},
        )

        assert result.status == "ok"
        assert result.container_id == "new123"

    def test_deploy_with_labels(self, engine):
        """Test deployment includes correct labels."""
        mock_container = MagicMock()
        engine.client.containers.run.return_value = mock_container

        engine.deploy("test-app", "test-app:latest")

        call_kwargs = engine.client.containers.run.call_args[1]
        assert call_kwargs["labels"]["app"] == "test-app"
        assert call_kwargs["labels"]["managed_by"] == "pypaas"

    def test_deploy_failure(self, engine):
        """Test deployment failure."""
        engine.client.containers.run.side_effect = Exception("Deploy error")

        result = engine.deploy("test-app", "test-app:latest")

        assert result.status == "failed"
        assert "Deploy error" in result.error


class TestResult:
    """Test Result object."""

    def test_result_success(self):
        """Test successful result."""
        result = Result(status="ok", host_port=8080, container_id="abc123")

        assert result.status == "ok"
        assert result.host_port == 8080
        assert result.container_id == "abc123"

    def test_result_failure(self):
        """Test failure result."""
        result = Result(status="failed", error="Something went wrong")

        assert result.status == "failed"
        assert result.error == "Something went wrong"


class TestIntegration:
    """Integration tests for engine."""

    def test_full_deployment_cycle(self, engine):
        """Test complete deployment cycle."""
        # Setup mocks
        old_container = MagicMock()
        old_container.id = "old123"

        new_container = MagicMock()
        new_container.id = "new456"
        new_container.status = "running"
        new_container.ports = {}

        # First call returns old container, second returns empty
        engine.client.containers.list.side_effect = [
            [old_container],  # List old containers
            [new_container],  # List for metrics
        ]

        engine.client.containers.run.return_value = new_container
        engine.client.containers.get.return_value = new_container

        # Deploy with rollback
        with patch.object(engine, "health_check", return_value=True):
            with patch.object(engine, "stop_container"):
                with patch.object(engine, "remove_container"):
                    result = engine.deploy_with_rollback(
                        "test-app", "test-app:v2.0", container_port=8080
                    )

        assert result.status == "ok"


class TestResultPortExtraction:
    """Test Result.get_host_port() method with various formats."""

    def test_get_host_port_integer(self):
        """Test host port extraction from integer."""
        result = Result(status="ok", host_port=8080)
        assert result.get_host_port() == 8080

    def test_get_host_port_string(self):
        """Test host port extraction from string."""
        result = Result(status="ok", host_port="8080")
        assert result.get_host_port() == 8080

    def test_get_host_port_docker_dict_format(self):
        """Test host port extraction from Docker dict format."""
        ports = {'80/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '8080'}]}
        result = Result(status="ok", host_port=ports)
        assert result.get_host_port() == 8080

    def test_get_host_port_docker_dict_multiple_ports(self):
        """Test extraction from dict with multiple port mappings."""
        ports = {
            '80/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '8080'}],
            '443/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '8443'}],
        }
        result = Result(status="ok", host_port=ports)
        # Should return first valid port found
        assert result.get_host_port() in [8080, 8443]

    def test_get_host_port_docker_dict_no_mapping(self):
        """Test extraction when port not mapped."""
        ports = {'80/tcp': None}
        result = Result(status="ok", host_port=ports)
        assert result.get_host_port() is None

    def test_get_host_port_list_format(self):
        """Test extraction from list format."""
        ports = [{'HostIp': '0.0.0.0', 'HostPort': '9090'}]
        result = Result(status="ok", host_port=ports)
        assert result.get_host_port() == 9090

    def test_get_host_port_none(self):
        """Test extraction when host_port is None."""
        result = Result(status="ok", host_port=None)
        assert result.get_host_port() is None

    def test_get_host_port_invalid_string(self):
        """Test extraction from invalid string."""
        result = Result(status="ok", host_port="not-a-port")
        assert result.get_host_port() is None

    def test_get_host_port_empty_dict(self):
        """Test extraction from empty dict."""
        result = Result(status="ok", host_port={})
        assert result.get_host_port() is None

    def test_get_host_port_malformed_dict(self):
        """Test extraction from malformed dict."""
        ports = {'80/tcp': [{'NoHostPort': 'wrong'}]}
        result = Result(status="ok", host_port=ports)
        assert result.get_host_port() is None

    def test_to_dict_serialization(self):
        """Test Result.to_dict() for JSON serialization."""
        ports = {'80/tcp': [{'HostPort': '8080'}]}
        result = Result(
            status="ok", host_port=ports, container_id="abc123", container_port=80
        )

        d = result.to_dict()

        assert d['status'] == 'ok'
        assert d['host_port'] == 8080
        assert d['container_port'] == 80
        assert d['container_id'] == 'abc123'
        assert d['error'] is None
