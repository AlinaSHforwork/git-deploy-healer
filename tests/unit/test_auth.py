from api import auth
from api.auth import encode_jwt, verify_api_key
from core.rbac import RBAC


def test_verify_api_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "secret-1")
    assert verify_api_key("secret-1") is True
    assert verify_api_key("wrong") is False
    assert verify_api_key(None) is False


def test_rbac_basic():
    r = RBAC({"admin": ["deploy", "read"], "user": ["read"]})
    assert r.has_permission("admin", "deploy")
    assert not r.has_permission("user", "deploy")


def test_jwt_encode_decode(monkeypatch):
    # If PyJWT missing, encode/decode return None
    monkeypatch.delenv("JWT_SECRET", raising=False)
    assert encode_jwt({"a": 1}) in (None, str)


class DummyJWT:
    """Fake PyJWT implementation for testing encode/decode branches."""

    @staticmethod
    def encode(payload, secret, algorithm="HS256"):
        return f"encoded:{payload}:{secret}"

    @staticmethod
    def decode(token, secret, algorithms=None):
        if token.startswith("encoded:"):
            return {"decoded": True, "secret": secret}
        raise Exception("invalid token")


def test_jwt_encode_decode_success(monkeypatch):
    monkeypatch.setattr(auth, "jwt", DummyJWT)
    monkeypatch.setenv("JWT_SECRET", "s3cr3t")

    token = auth.encode_jwt({"x": 1})
    assert token.startswith("encoded:")

    decoded = auth.decode_jwt(token)
    assert decoded == {"decoded": True, "secret": "s3cr3t"}


def test_jwt_decode_failure(monkeypatch):
    monkeypatch.setattr(auth, "jwt", DummyJWT)
    monkeypatch.setenv("JWT_SECRET", "s3cr3t")

    # invalid token triggers exception → decode_jwt returns None
    assert auth.decode_jwt("bad-token") is None
