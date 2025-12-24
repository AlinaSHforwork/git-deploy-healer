import pytest
from unittest.mock import MagicMock

from core.healer import ContainerHealer as Healer
HealerError = Exception


@pytest.mark.asyncio
async def test_healer_runs_one_cycle(monkeypatch):
    # Create a healer with mocked managers
    healer = Healer()
    healer.git_manager = MagicMock()
    healer.docker_manager = MagicMock()
    healer.proxy_manager = MagicMock()

    # simulate git changes found
    healer.git_manager.has_changes.return_value = True
    healer.git_manager.pull = MagicMock()
    healer.docker_manager.build_image = MagicMock()
    healer.docker_manager.run_container = MagicMock()
    healer.proxy_manager.reload = MagicMock()

    # run a single cycle method (assume method name check_and_heal)
    await healer.check_and_heal()
    healer.git_manager.pull.assert_called_once()
    healer.docker_manager.build_image.assert_called_once()


@pytest.mark.asyncio
async def test_healer_handles_exceptions(monkeypatch):
    healer = Healer()
    healer.git_manager = MagicMock()
    healer.git_manager.has_changes.return_value = True
    healer.git_manager.pull.side_effect = Exception("git fail")
    # ensure exception is caught and logged, not re-raised
    await healer.check_and_heal()
