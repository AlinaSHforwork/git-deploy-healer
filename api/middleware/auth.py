"""Authentication middleware / dependency helpers for FastAPI routes.

This module provides a `require_api_key` dependency that FastAPI routes can use.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from api.auth import verify_api_key

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(api_key: Optional[str] = Security(api_key_header)) -> bool:
    if not verify_api_key(api_key):
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return True
