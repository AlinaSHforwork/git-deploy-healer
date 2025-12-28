"""Webhook route for GitHub-style webhooks with optional HMAC verification."""
from __future__ import annotations

import hashlib
import hmac
import os
from typing import Optional, cast

from fastapi import APIRouter, Header, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

router = APIRouter()


def _verify_signature(
    body: bytes, signature: Optional[str], secret: Optional[str]
) -> bool:
    if not secret:
        return True
    if not signature:
        return False

    alg, sig = signature.split("=", 1) if "=" in signature else (None, signature)
    if alg not in ("sha256", "sha1", None):
        return False

    # mypy fix: sig is Optional[str], but we validated it's not None
    sig = cast(str, sig)

    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, sig)


limiter = Limiter(key_func=get_remote_address)


@router.post("/webhook")
@limiter.limit("5/minute")
async def webhook(request: Request, x_hub_signature_256: Optional[str] = Header(None)):
    body = await request.body()
    secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    if not _verify_signature(body, x_hub_signature_256, secret):
        raise HTTPException(status_code=403, detail="Invalid signature")
    return {"status": "ok"}
