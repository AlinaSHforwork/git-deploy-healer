from unittest.mock import MagicMock

import pytest

import core.healer as core_healer


@pytest.mark.asyncio
async def test_trigger_heal_no_healer_available(monkeypatch):
    # When Healer is not available in module, trigger_heal() should raise
    import importlib

    mod = importlib.import_module("api.healer")
    monkeypatch.setattr(mod, "Healer", None)

    with pytest.raises(RuntimeError):
        mod.trigger_heal(None)


def test_trigger_heal_object_without_method():
    from api.healer import trigger_heal

    class Dummy:  # lacks check_and_heal
        pass

    with pytest.raises(AttributeError):
        trigger_heal(Dummy())


def test_container_healer_client_property(monkeypatch):
    ch = core_healer.ContainerHealer()
    # patch docker.from_env to return a sentinel client
    monkeypatch.setattr("core.healer.docker", MagicMock())
    core_healer.docker.from_env.return_value = "docker-client"
    # ensure property yields patched client
    assert ch.client == "docker-client"


def test_check_health_client_list_failure(monkeypatch):
    ch = core_healer.ContainerHealer()
    fake_client = MagicMock()
    fake_client.containers.list.side_effect = Exception("boom")
    ch._client = fake_client

    res = ch.check_health()
    assert res == []


def test_heal_increments_counter_when_running(monkeypatch):
    ch = core_healer.ContainerHealer()
    # create container mock
    container = MagicMock()
    container.status = "stopped"

    def restart(timeout=10):
        container.status = "running"

    container.restart.side_effect = restart
    container.reload = MagicMock()

    # inject a fake counter
    core_healer.HEALER_RESTART_COUNTER = MagicMock()

    ch.heal(container)

    core_healer.HEALER_RESTART_COUNTER.inc.assert_called_once()


def test_heal_uses_engine_deploy_and_handles_exceptions():
    ch = core_healer.ContainerHealer()
    container = MagicMock()
    container.status = "stopped"
    # restart does nothing (status stays stopped)
    container.restart = MagicMock()
    container.reload = MagicMock()

    class BadEngine:
        def deploy(self, app, tag):
            raise Exception("deploy failed")

    ch.engine = BadEngine()
    # should not raise
    ch.heal(container)


def test_heal_handles_api_error(monkeypatch):
    ch = core_healer.ContainerHealer()
    container = MagicMock()
    container.status = "stopped"

    def restart(timeout=10):
        raise core_healer.APIError("api error")

    container.restart.side_effect = restart
    container.reload = MagicMock()

    # should not raise despite APIError
    ch.heal(container)
