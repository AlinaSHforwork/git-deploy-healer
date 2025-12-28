import hashlib
import hmac
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.webhook import _verify_signature, router

# ---------------------------------------------------------------------------
# Test client
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def run_background_tasks_immediately(monkeypatch):
    def immediate_add_task(self, func, *args, **kwargs):
        func(*args, **kwargs)

    monkeypatch.setattr(
        "fastapi.BackgroundTasks.add_task",
        immediate_add_task,
        raising=False,
    )


# ---------------------------------------------------------------------------
# Signature helper
# ---------------------------------------------------------------------------


def _sig(body: bytes, secret: str):
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# ---------------------------------------------------------------------------
# _verify_signature tests
# ---------------------------------------------------------------------------


def test_verify_signature_no_secret():
    assert not _verify_signature(b"{}", "sha256=abc", None)


def test_verify_signature_no_signature():
    assert not _verify_signature(b"{}", None, "secret")


def test_verify_signature_bad_format():
    assert not _verify_signature(b"{}", "invalid", "secret")


def test_verify_signature_wrong_algo():
    assert not _verify_signature(b"{}", "sha1=abc", "secret")


def test_verify_signature_valid():
    body = b'{"x":1}'
    secret = "abc123"
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    sig = f"sha256={digest}"
    assert _verify_signature(body, sig, secret)


# ---------------------------------------------------------------------------
# Webhook endpoint tests (matching actual behavior)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_secret(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "supersecret")


def test_webhook_invalid_signature(client, mock_secret):
    r = client.post(
        "/webhook",
        data=b"{}",
        headers={"X-Hub-Signature-256": "sha256=bad"},
    )
    assert r.status_code == 403


def test_webhook_missing_signature(client, mock_secret):
    r = client.post("/webhook", content=b"{}")
    assert r.status_code == 403


def test_webhook_missing_secret(client, monkeypatch):
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    r = client.post("/webhook", content=b"{}")
    assert r.status_code == 403


def test_webhook_invalid_json(client, mock_secret):
    sig = _sig(b"not-json", "supersecret")
    r = client.post(
        "/webhook",
        content=b"not-json",
        headers={"X-Hub-Signature-256": sig},
    )
    assert r.status_code == 200


def test_webhook_missing_repo(client, mock_secret):
    body = b'{"nope": 1}'
    sig = _sig(body, "supersecret")
    r = client.post(
        "/webhook",
        content=body,
        headers={"X-Hub-Signature-256": sig},
    )
    assert r.status_code == 200


def test_webhook_deploy_exception(client, mock_secret, monkeypatch):
    body = b'{"repository":{"name":"app"}}'
    sig = _sig(body, "supersecret")

    monkeypatch.setattr(
        "api.routes.webhook.GitManager",
        MagicMock(side_effect=Exception("fail")),
    )

    r = client.post(
        "/webhook",
        content=body,
        headers={"X-Hub-Signature-256": sig},
    )
    assert r.status_code == 200


def test_webhook_valid_signature(client, mock_secret, monkeypatch):
    body = b'{"repository":{"name":"app"}}'
    sig = _sig(body, "supersecret")

    monkeypatch.setattr("api.routes.webhook.GitManager", MagicMock())
    monkeypatch.setattr("api.routes.webhook.ContainerEngine", MagicMock())

    r = client.post(
        "/webhook",
        content=body,
        headers={"X-Hub-Signature-256": sig},
    )

    assert r.status_code == 200
    assert r.json() == {"status": "accepted"}


# ---------------------------------------------------------------------------
# Additional tests for full coverage of _deploy_task
# ---------------------------------------------------------------------------


def test_webhook_proxy_failure(client, mock_secret, monkeypatch):
    body = b'{"repository":{"name":"app"}}'
    sig = _sig(body, "supersecret")

    monkeypatch.setattr("api.routes.webhook.GitManager", MagicMock())

    mock_engine = MagicMock()
    mock_engine.deploy.return_value = MagicMock(status="ok", host_port=None)
    monkeypatch.setattr(
        "api.routes.webhook.ContainerEngine", MagicMock(return_value=mock_engine)
    )

    monkeypatch.setitem(
        __import__("sys").modules,
        "core.proxy_manager",
        MagicMock(ProxyManager=lambda: (_ for _ in ()).throw(Exception("proxy fail"))),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "core.network",
        MagicMock(PortManager=lambda: MagicMock()),
    )

    r = client.post(
        "/webhook",
        content=body,
        headers={"X-Hub-Signature-256": sig},
    )

    assert r.status_code == 200


def test_webhook_build_failure(client, mock_secret, monkeypatch):
    body = b'{"repository":{"name":"app"}}'
    sig = _sig(body, "supersecret")

    monkeypatch.setattr("api.routes.webhook.GitManager", MagicMock())

    mock_engine = MagicMock()
    mock_engine.build_image.side_effect = Exception("build fail")
    mock_engine.deploy.return_value = MagicMock(status="ok", host_port=None)
    monkeypatch.setattr(
        "api.routes.webhook.ContainerEngine", MagicMock(return_value=mock_engine)
    )

    monkeypatch.setitem(
        __import__("sys").modules,
        "core.proxy_manager",
        MagicMock(ProxyManager=lambda: MagicMock()),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "core.network",
        MagicMock(PortManager=lambda: MagicMock()),
    )

    r = client.post(
        "/webhook",
        content=body,
        headers={"X-Hub-Signature-256": sig},  # ← FIXED
    )

    assert r.status_code == 200
