"""Tests for authentication module with proper JWT exception handling."""
from api import auth
from api.auth import encode_jwt, verify_api_key
from core.rbac import RBAC


def test_verify_api_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "secret-1")
    assert verify_api_key("secret-1", "127.0.0.1") is True
    assert verify_api_key("wrong", "127.0.0.1") is False
    assert verify_api_key(None, "127.0.0.1") is False


def test_verify_api_key_rate_limiting(monkeypatch):
    """Test that rate limiting works after multiple failures."""
    monkeypatch.setenv("API_KEY", "correct-key")

    # Fail 5 times
    for i in range(5):
        assert verify_api_key("wrong", "192.168.1.1") is False

    # 6th attempt should be rate limited
    assert verify_api_key("correct-key", "192.168.1.1") is False


def test_verify_api_key_no_key_configured(monkeypatch):
    """Test behavior when API_KEY is not configured."""
    monkeypatch.delenv("API_KEY", raising=False)
    assert verify_api_key("any-key", "127.0.0.1") is False


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

    # Define exception classes
    class ExpiredSignatureError(Exception):
        pass

    class InvalidTokenError(Exception):
        pass

    @staticmethod
    def encode(payload, secret, algorithm="HS256"):
        return f"encoded:{payload}:{secret}"

    @staticmethod
    def decode(token, secret, algorithms=None):
        if token.startswith("encoded:"):
            return {"decoded": True, "secret": secret}
        elif token == "expired-token":
            raise DummyJWT.ExpiredSignatureError("Token expired")
        elif token == "invalid-token":
            raise DummyJWT.InvalidTokenError("Invalid token")
        raise Exception("invalid token")


def test_jwt_encode_decode_success(monkeypatch):
    monkeypatch.setattr(auth, "jwt", DummyJWT)
    monkeypatch.setenv("JWT_SECRET", "s3cr3t")

    token = auth.encode_jwt({"x": 1})
    assert token.startswith("encoded:")

    decoded = auth.decode_jwt(token)
    assert decoded == {"decoded": True, "secret": "s3cr3t"}


def test_jwt_decode_failure(monkeypatch):
    """Test JWT decode with various failure modes."""
    monkeypatch.setattr(auth, "jwt", DummyJWT)
    monkeypatch.setenv("JWT_SECRET", "s3cr3t")

    # Expired token
    assert auth.decode_jwt("expired-token") is None

    # Invalid token
    assert auth.decode_jwt("invalid-token") is None

    # Generic bad token
    assert auth.decode_jwt("bad-token") is None


def test_jwt_encode_with_expiration(monkeypatch):
    """Test JWT encoding with custom expiration."""
    monkeypatch.setattr(auth, "jwt", DummyJWT)
    monkeypatch.setenv("JWT_SECRET", "s3cr3t")

    token = auth.encode_jwt({"user": "test"}, expiration=7200)
    assert token is not None
    assert token.startswith("encoded:")


def test_jwt_no_secret(monkeypatch):
    """Test JWT operations without secret configured."""
    monkeypatch.setattr(auth, "jwt", DummyJWT)
    monkeypatch.delenv("JWT_SECRET", raising=False)

    assert auth.encode_jwt({"x": 1}) is None
    assert auth.decode_jwt("any-token") is None


def test_jwt_not_installed(monkeypatch):
    """Test JWT operations when PyJWT is not installed."""
    monkeypatch.setattr(auth, "jwt", None)
    monkeypatch.setenv("JWT_SECRET", "s3cr3t")

    assert auth.encode_jwt({"x": 1}) is None
    assert auth.decode_jwt("any-token") is None
