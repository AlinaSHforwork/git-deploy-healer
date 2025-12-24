import pytest
from unittest.mock import MagicMock, patch
from httpx import AsyncClient

from core.engine import ContainerEngine as DockerManager
DockerError = Exception

def test_build_image_success(monkeypatch):
    dm = DockerManager()
    # mock docker API client
    fake_client = MagicMock()
    fake_client.images.build.return_value = ([], {"stream": "built"})
    monkeypatch.setattr(dm, "client", fake_client)
    image = dm.build_image(path=".", tag="test:latest")
    assert image is not None

def test_build_image_failure(monkeypatch):
    dm = DockerManager()
    fake_client = MagicMock()
    def raise_exc(*a, **k):
        raise Exception("build failed")
    fake_client.images.build.side_effect = raise_exc
    monkeypatch.setattr(dm, "client", fake_client)
    with pytest.raises(DockerError):
        dm.build_image(path=".", tag="bad:tag")

def test_run_container_and_stop(monkeypatch):
    dm = DockerManager()
    fake_client = MagicMock()
    fake_container = MagicMock()
    fake_container.id = "abc123"
    fake_client.containers.run.return_value = fake_container
    monkeypatch.setattr(dm, "client", fake_client)

    container = dm.run_container("test:latest", detach=True, name="c1")
    assert container.id == "abc123"
    dm.stop_container(container.id)
    fake_client.containers.get.assert_called_with("abc123")
    fake_client.containers.get.return_value.stop.assert_called_once()
