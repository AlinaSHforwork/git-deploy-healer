"""Authentication helpers with timing-safe comparisons and rate limiting.

Security improvements:
- Constant-time comparison for API keys
- Rate limiting for failed attempts
- Proper JWT validation with expiration
"""
from __future__ import annotations

import os
import secrets
import time
from typing import Optional

from loguru import logger

try:
    import jwt  # type: ignore
except Exception:  # pragma: no cover - optional
    jwt = None  # type: ignore

# Simple in-memory rate limiter (use Redis in production)
_failed_attempts: dict[str, list[float]] = {}
MAX_FAILED_ATTEMPTS = 5
RATE_LIMIT_WINDOW = 300  # 5 minutes


def _check_rate_limit(identifier: str) -> bool:
    """Check if identifier is rate limited."""
    now = time.time()

    # Clean old attempts
    if identifier in _failed_attempts:
        _failed_attempts[identifier] = [
            t for t in _failed_attempts[identifier] if now - t < RATE_LIMIT_WINDOW
        ]

    # Check if rate limited
    attempts = _failed_attempts.get(identifier, [])
    if len(attempts) >= MAX_FAILED_ATTEMPTS:
        logger.warning(f"Rate limit exceeded for {identifier}")
        return False

    return True


def _record_failed_attempt(identifier: str) -> None:
    """Record a failed authentication attempt."""
    now = time.time()
    if identifier not in _failed_attempts:
        _failed_attempts[identifier] = []
    _failed_attempts[identifier].append(now)


def verify_api_key(key: Optional[str], remote_addr: str = "unknown") -> bool:
    """Return True if provided key matches configured API_KEY.

    Uses constant-time comparison to prevent timing attacks.
    Implements rate limiting on failed attempts.

    Args:
        key: API key to verify
        remote_addr: IP address for rate limiting

    Returns:
        True if key is valid and not rate limited
    """
    # Check rate limit first
    if not _check_rate_limit(remote_addr):
        return False

    if not key:
        _record_failed_attempt(remote_addr)
        return False

    expected = os.getenv("API_KEY")
    if not expected:
        logger.error("API_KEY environment variable not configured")
        _record_failed_attempt(remote_addr)
        return False

    # Constant-time comparison to prevent timing attacks
    is_valid = secrets.compare_digest(key, expected)

    if not is_valid:
        _record_failed_attempt(remote_addr)
        logger.warning(f"Invalid API key attempt from {remote_addr}")

    return is_valid


def encode_jwt(
    payload: dict, secret: Optional[str] = None, expiration: int = 3600
) -> Optional[str]:
    """Encode JWT with expiration.

    Args:
        payload: Data to encode
        secret: JWT secret (defaults to JWT_SECRET env var)
        expiration: Token expiration in seconds (default 1 hour)

    Returns:
        Encoded JWT token or None if jwt/secret unavailable
    """
    secret = secret or os.getenv("JWT_SECRET")
    if jwt is None or not secret:
        return None

    # Add expiration claim
    import time

    payload_with_exp = {
        **payload,
        "exp": int(time.time()) + expiration,
        "iat": int(time.time()),
    }

    return jwt.encode(payload_with_exp, secret, algorithm="HS256")


def decode_jwt(token: str, secret: Optional[str] = None) -> Optional[dict]:
    """Decode and validate JWT.

    Args:
        token: JWT token to decode
        secret: JWT secret (defaults to JWT_SECRET env var)

    Returns:
        Decoded payload or None if invalid/expired
    """
    secret = secret or os.getenv("JWT_SECRET")
    if jwt is None or not secret:
        return None

    try:
        # Verify expiration automatically
        return jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid JWT token: {e}")
        return None
    except Exception as e:
        logger.error(f"JWT decode error: {e}")
        return None
