"""Authentication helpers: API key check and lightweight JWT helpers.

These helpers are intentionally small so tests can execute without extra
dependencies. If PyJWT is installed it will be used; otherwise JWT helpers
are no-ops for encode/decode (use API key verification in that case).
"""
from __future__ import annotations

import os
from typing import Optional

try:
    import jwt  # type: ignore
except Exception:  # pragma: no cover - optional
    jwt = None  # type: ignore


def verify_api_key(key: Optional[str]) -> bool:
    """Return True if provided key matches configured `API_KEY` env var."""
    if not key:
        return False
    expected = os.getenv("API_KEY")
    return expected is not None and key == expected


def encode_jwt(payload: dict, secret: Optional[str] = None) -> Optional[str]:
    secret = secret or os.getenv("JWT_SECRET")
    if jwt is None or not secret:
        return None
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_jwt(token: str, secret: Optional[str] = None) -> Optional[dict]:
    secret = secret or os.getenv("JWT_SECRET")
    if jwt is None or not secret:
        return None
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except Exception:
        return None
