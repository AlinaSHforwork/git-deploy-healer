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
        headers={"x-hub-signature-256": "sha256=bad"},
    )
    assert r.status_code == 403


def test_webhook_missing_signature(client, mock_secret):
    r = client.post("/webhook", content=b"{}")
    assert r.status_code == 403


def test_webhook_missing_secret(client, monkeypatch):
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    r = client.post("/webhook", content=b"{}")
    # Missing secret → verify_signature returns False → 403
    assert r.status_code == 403


def test_webhook_invalid_json(client, mock_secret):
    sig = _sig(b"not-json", "supersecret")
    r = client.post(
        "/webhook",
        content=b"not-json",
        headers={"x-hub-signature-256": sig},
    )
    # Invalid JSON → payload = {} → background task returns early → 200
    assert r.status_code == 200


def test_webhook_missing_repo(client, mock_secret):
    body = b'{"nope": 1}'
    sig = _sig(body, "supersecret")
    r = client.post(
        "/webhook",
        content=body,
        headers={"x-hub-signature-256": sig},
    )
    # Missing repo info → background task returns early → 200
    assert r.status_code == 200


def test_webhook_deploy_exception(client, mock_secret, monkeypatch):
    body = b'{"repository":{"name":"app"}}'
    sig = _sig(body, "supersecret")

    # Force GitManager() to raise
    monkeypatch.setattr(
        "api.routes.webhook.GitManager",
        MagicMock(side_effect=Exception("fail")),
    )

    r = client.post(
        "/webhook",
        content=body,
        headers={"x-hub-signature-256": sig},
    )
    # Exceptions inside background task are swallowed → 200
    assert r.status_code == 200


def test_webhook_valid_signature(client, mock_secret, monkeypatch):
    body = b'{"repository":{"name":"app"}}'
    sig = _sig(body, "supersecret")

    # Mock heavy components
    monkeypatch.setattr("api.routes.webhook.GitManager", MagicMock())
    monkeypatch.setattr("api.routes.webhook.ContainerEngine", MagicMock())

    r = client.post(
        "/webhook",
        content=body,
        headers={"x-hub-signature-256": sig},
    )

    assert r.status_code == 200
    assert r.json() == {"status": "accepted"}
