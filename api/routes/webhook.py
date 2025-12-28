"""Webhook route for GitHub-style webhooks with optional HMAC verification."""
from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any, Dict, Optional, cast

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from core.engine import ContainerEngine
from core.git_manager import GitManager

router = APIRouter()


def _verify_signature(
    body: bytes, signature: Optional[str], secret: Optional[str]
) -> bool:
    """Verify that signature header is present and uses sha256 algorithm.

    Only accept signatures of the form 'sha256=HEX'. If no secret is configured,
    reject the request for safety (require explicit opt-out by setting secret="").
    """
    # if secret is explicitly empty string treat as disabled (unlikely); safer to require secret
    if not secret:
        # No configured secret: reject to avoid silent acceptance
        return False
    if not signature:
        return False

    if "=" not in signature:
        return False
    alg, sig = signature.split("=", 1)
    if alg != "sha256":
        return False

    sig = cast(str, sig)

    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, sig)


limiter = Limiter(key_func=get_remote_address)


@router.post("/webhook")
@limiter.limit("5/minute")
async def webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: Optional[str] = Header(None),
):
    """Receive a webhook, verify signature, and enqueue a deployment task.

    The background task will attempt to clone/pull the repository, build the image,
    and deploy it via the ContainerEngine. This is best-effort and failures are
    logged but do not return errors to the webhook sender.
    """
    body = await request.body()
    secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    if not _verify_signature(body, x_hub_signature_256, secret):
        raise HTTPException(status_code=403, detail="Invalid signature")

    # parse payload conservatively
    try:
        payload: Dict[str, Any] = await request.json()
    except Exception:
        payload = {}

    def _deploy_task(payload: Dict[str, Any]):
        try:
            repo = payload.get("repository", {})
            repo_url = repo.get("clone_url") or repo.get("html_url")
            app_name = repo.get("name") or payload.get("project", {}).get("name")
            if not repo_url or not app_name:
                return

            gm = GitManager()
            path = gm.clone_repository(repo_url, app_name)

            engine = ContainerEngine()
            tag = f"{app_name}:latest"
            try:
                engine.build_image(path, tag)
            except Exception:  # nosec
                # build may fail in local dev; still attempt deploy
                pass

            # Try deploying; choose default port 8080 if not provided
            container_port = payload.get("container_port") or 8080
            engine.deploy(app_name, tag, repo_path=path, container_port=container_port)
        except Exception:
            # swallow exceptions to avoid crashing worker; logs are recorded by server
            import logging

            logging.exception("Webhook deploy task failed")

    # schedule background deploy
    background_tasks.add_task(_deploy_task, payload)
    return {"status": "accepted"}
