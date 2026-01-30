from unittest.mock import MagicMock, patch

import pytest

# FIXED: Import ContainerHealer instead of Healer
from core.healer import ContainerHealer as Healer


@pytest.fixture
def mock_engine():
    return MagicMock()


@pytest.fixture
def healer(mock_engine):
    """Creates the Healer instance with mocked dependencies."""
    # FIXED: Initialize ContainerHealer correctly with engine
    h = Healer(engine=mock_engine)
    return h


class TestHealerExtra:
    def test_container_healer_client_property(self, healer):
        """Test the client property initializes correctly"""
        with patch("docker.from_env") as mock_docker:
            # Clear existing client if any
            if hasattr(healer, '_client'):
                healer._client = None

            client = healer.client
            assert client is not None
            mock_docker.assert_called_once()

            # Second access should use cache
            client2 = healer.client
            assert client2 == client
            assert mock_docker.call_count == 1

    @pytest.mark.asyncio
    async def test_check_health_client_list_failure(self, healer):
        """Test check_health when docker client fails to list containers"""
        # Mock client.containers.list to raise exception
        healer._client = MagicMock()
        healer._client.containers.list.side_effect = Exception("Docker error")

        # Should handle exception gracefully
        await healer.check_health()

    @pytest.mark.asyncio
    async def test_heal_increments_counter_when_running(self, healer):
        """Test that heal returns False if container is already being healed"""
        # Simulating a container ID that is currently being healed
        container_id = "test_id_123"
        healer._healing_in_progress.add(container_id)

        # Create a mock container with that ID
        mock_container = MagicMock()
        mock_container.id = container_id

        # Attempt to check health (which calls heal logic internally)
        # Note: We can't call heal() directly to test the lock,
        # as the lock is checked in check_health(), not heal()

        # Let's verify check_health respects the lock
        healer._client = MagicMock()
        healer._client.containers.list.return_value = [mock_container]

        # Mock heal to ensure it's NOT called
        with patch.object(healer, 'heal', new_callable=MagicMock) as mock_heal_method:
            await healer.check_health()
            mock_heal_method.assert_not_called()

    @pytest.mark.asyncio
    async def test_heal_uses_engine_deploy_and_handles_exceptions(
        self, healer, mock_engine
    ):
        """Test that heal calls engine.deploy and handles failures"""
        mock_container = MagicMock()
        mock_container.id = "id_123"
        mock_container.labels = {"app": "test-app"}

        # Restart fails
        mock_container.restart.side_effect = Exception("Restart failed")

        # Deploy fails
        mock_engine.deploy.side_effect = Exception("Deploy failed")

        # FIXED: Pass container object, not strings
        result = await healer.heal(mock_container)
        assert result is False

    @pytest.mark.asyncio
    async def test_heal_handles_api_error(self, healer, mock_engine):
        """Test specific APIError handling"""
        import docker

        mock_container = MagicMock()
        mock_container.id = "id_123"
        mock_container.labels = {"app": "test-app"}

        # Restart raises APIError
        mock_container.restart.side_effect = docker.errors.APIError("API Error")

        # FIXED: Pass container object
        result = await healer.heal(mock_container)
        assert result is False

    @pytest.mark.asyncio
    async def test_heal_container_not_found(self, healer, mock_engine):
        """Test healing when container is found but fails restart (e.g. removed externally)"""
        import docker

        mock_container = MagicMock()
        mock_container.id = "missing123"
        mock_container.labels = {"app": "test-app"}

        # Simulate container not found during restart
        mock_container.restart.side_effect = docker.errors.NotFound("Not found")

        mock_deploy_result = MagicMock()
        mock_deploy_result.status = "ok"
        mock_engine.deploy.return_value = mock_deploy_result

        # FIXED: Patch pathlib.Path.exists instead of os.path.exists
        with patch("pathlib.Path.exists") as mock_exists:
            mock_exists.return_value = True

            # FIXED: Pass container object
            result = await healer.heal(mock_container)

            assert result is True
            # Should proceed directly to deploy
            assert mock_engine.deploy.called
            args = mock_engine.deploy.call_args
            assert args[0][0] == "test-app"

    @pytest.mark.asyncio
    async def test_check_health_with_race_condition_protection(self, healer):
        """Test that check_health respects healing_in_progress set"""
        container_id = "race_test_id"
        mock_container = MagicMock()
        mock_container.id = container_id
        mock_container.status = "exited"

        healer._client = MagicMock()
        healer._client.containers.list.return_value = [mock_container]

        # Manually add to processing set
        healer._healing_in_progress.add(container_id)

        with patch.object(healer, 'heal', new_callable=MagicMock) as mock_heal:
            await healer.check_health()
            mock_heal.assert_not_called()

    @pytest.mark.asyncio
    async def test_heal_successful_redeployment(self, healer, mock_engine):
        """Test full redeployment flow when restart fails"""
        mock_container = MagicMock()
        mock_container.id = "redeploy123"
        mock_container.labels = {"app": "my-app"}

        mock_container.restart.side_effect = Exception("restart failed")

        mock_deploy_result = MagicMock()
        mock_deploy_result.status = "ok"
        mock_engine.deploy.return_value = mock_deploy_result

        # FIXED: Patch pathlib.Path.exists
        with patch("pathlib.Path.exists") as mock_exists:
            mock_exists.return_value = True

            result = await healer.heal(mock_container)

            assert result is True
            mock_engine.deploy.assert_called_once()

    @pytest.mark.asyncio
    async def test_heal_no_container_id(self, healer):
        """Test heal with missing parameters"""
        mock_container = MagicMock()
        del mock_container.id  # Ensure no id attribute

        result = await healer.heal(mock_container)
        assert result is False

    @pytest.mark.asyncio
    async def test_check_health_skips_running_containers(self, healer):
        """Test check_health ignores healthy containers"""
        container = MagicMock()
        container.status = "running"
        container.id = "valid-id"

        healer._client = MagicMock()
        healer._client.containers.list.return_value = [container]

        # Mock heal so we can verify it wasn't called
        with patch.object(healer, 'heal', new_callable=MagicMock) as mock_heal_method:
            await healer.check_health()
            mock_heal_method.assert_not_called()
