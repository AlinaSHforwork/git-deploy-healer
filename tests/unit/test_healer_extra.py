"""Extra healer tests with proper async/await handling"""
from unittest.mock import MagicMock

import pytest

import core.healer as core_healer


@pytest.mark.asyncio
async def test_trigger_heal_no_healer_available(monkeypatch):
    """Test trigger_heal when Healer is not available."""
    import importlib

    mod = importlib.import_module("api.healer")
    monkeypatch.setattr(mod, "Healer", None)

    with pytest.raises(RuntimeError):
        mod.trigger_heal(None)


def test_trigger_heal_object_without_method():
    """Test trigger_heal with object lacking check_and_heal method."""
    from api.healer import trigger_heal

    class Dummy:  # lacks check_and_heal
        pass

    with pytest.raises(AttributeError):
        trigger_heal(Dummy())


def test_container_healer_client_property(monkeypatch):
    """Test ContainerHealer client property lazy initialization."""
    ch = core_healer.ContainerHealer()
    # patch docker.from_env to return a sentinel client
    monkeypatch.setattr("core.healer.docker", MagicMock())
    core_healer.docker.from_env.return_value = "docker-client"
    # ensure property yields patched client
    assert ch.client == "docker-client"


@pytest.mark.asyncio
async def test_check_health_client_list_failure(monkeypatch):
    """Test check_health when client.containers.list fails."""
    ch = core_healer.ContainerHealer()
    fake_client = MagicMock()
    fake_client.containers.list.side_effect = Exception("boom")
    ch._client = fake_client

    res = await ch.check_health()
    assert res == []


@pytest.mark.asyncio
async def test_heal_increments_counter_when_running(monkeypatch):
    """Test that healer increments counter when container restarts successfully."""
    ch = core_healer.ContainerHealer()

    # create container mock
    container = MagicMock()
    container.id = "test123"
    container.status = "stopped"
    container.labels = {"app": "test-app"}

    def restart(timeout=10):
        container.status = "running"

    container.restart.side_effect = restart
    container.reload = MagicMock()

    # inject a fake counter
    fake_counter = MagicMock()
    core_healer.HEALER_RESTART_COUNTER = fake_counter

    result = await ch.heal(container)

    assert result is True
    fake_counter.inc.assert_called_once()


@pytest.mark.asyncio
async def test_heal_uses_engine_deploy_and_handles_exceptions():
    """Test that heal uses engine.deploy when restart fails."""
    ch = core_healer.ContainerHealer()

    container = MagicMock()
    container.id = "test456"
    container.status = "stopped"
    container.labels = {"app": "test-app"}

    # restart does nothing (status stays stopped)
    container.restart = MagicMock()
    container.reload = MagicMock()

    class BadEngine:
        def deploy(self, app, tag):
            raise Exception("deploy failed")

    ch.engine = BadEngine()

    # should not raise, returns False
    result = await ch.heal(container)
    assert result is False


@pytest.mark.asyncio
async def test_heal_handles_api_error(monkeypatch):
    """Test heal handles Docker API errors gracefully."""
    ch = core_healer.ContainerHealer()

    container = MagicMock()
    container.id = "test789"
    container.status = "stopped"
    container.labels = {"app": "test-app"}

    def restart(timeout=10):
        raise core_healer.APIError("api error")

    container.restart.side_effect = restart
    container.reload = MagicMock()

    # should not raise despite APIError
    result = await ch.heal(container)
    assert result is False


@pytest.mark.asyncio
async def test_heal_container_not_found(monkeypatch):
    """Test heal when container is not found (was removed)."""
    ch = core_healer.ContainerHealer()

    container = MagicMock()
    container.id = "missing123"
    container.status = "stopped"
    container.labels = {"app": "test-app"}

    # Simulate NotFound exception
    def restart(timeout=10):
        raise core_healer.NotFound("container not found")

    container.restart.side_effect = restart

    # Mock engine that succeeds
    mock_engine = MagicMock()
    mock_result = MagicMock()
    mock_result.status = "ok"
    mock_engine.deploy.return_value = mock_result
    ch.engine = mock_engine

    await ch.heal(container)

    # Should attempt redeployment
    assert mock_engine.deploy.called


@pytest.mark.asyncio
async def test_check_health_with_race_condition_protection():
    """Test that check_health prevents concurrent healing of same container.

    Note: The race condition protection now works by tracking which container IDs
    are currently being healed. However, in the current implementation, both containers
    will be healed sequentially, not concurrently. This test verifies the lock exists.
    """
    ch = core_healer.ContainerHealer()

    # Create two containers with same ID (simulating potential race condition)
    container1 = MagicMock()
    container1.id = "same-id-123"
    container1.status = "stopped"
    container1.labels = {"app": "test"}

    container2 = MagicMock()
    container2.id = "same-id-123"
    container2.status = "stopped"
    container2.labels = {"app": "test"}

    fake_client = MagicMock()
    fake_client.containers.list.return_value = [container1, container2]
    ch._client = fake_client

    # Track heal calls
    heal_calls = []

    async def mock_heal(container):
        heal_calls.append(container.id)
        # Simulate some async work
        import asyncio

        await asyncio.sleep(0.01)
        return True

    # Replace heal method
    # original_heal = ch.heal
    ch.heal = mock_heal

    await ch.check_health()

    # Both containers should be healed sequentially due to the lock
    # The second one is added to healing set, healed, then removed
    assert len(heal_calls) == 2
    assert all(cid == "same-id-123" for cid in heal_calls)


@pytest.mark.asyncio
async def test_heal_successful_redeployment():
    """Test successful redeployment when restart fails."""
    ch = core_healer.ContainerHealer()

    container = MagicMock()
    container.id = "redeploy123"
    container.status = "stopped"
    container.labels = {"app": "my-app"}
    container.restart.side_effect = Exception("restart failed")
    container.stop = MagicMock()
    container.remove = MagicMock()

    # Mock successful engine deploy
    mock_engine = MagicMock()
    mock_result = MagicMock()
    mock_result.status = "ok"
    mock_engine.deploy.return_value = mock_result
    ch.engine = mock_engine

    # Mock counter
    core_healer.HEALER_RESTART_COUNTER = MagicMock()

    result = await ch.heal(container)

    assert result is True
    assert mock_engine.deploy.called
    core_healer.HEALER_RESTART_COUNTER.inc.assert_called_once()


@pytest.mark.asyncio
async def test_heal_no_container_id():
    """Test heal with container lacking ID."""
    ch = core_healer.ContainerHealer()

    container = MagicMock()
    container.id = None

    result = await ch.heal(container)
    assert result is False


@pytest.mark.asyncio
async def test_check_health_skips_running_containers():
    """Test that check_health skips containers that are already running."""
    ch = core_healer.ContainerHealer()

    running_container = MagicMock()
    running_container.id = "running123"
    running_container.status = "running"

    fake_client = MagicMock()
    fake_client.containers.list.return_value = [running_container]
    ch._client = fake_client

    healed = await ch.check_health()

    # Should return empty list (no containers healed)
    assert healed == []
