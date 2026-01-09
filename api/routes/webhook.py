"""Webhook route with enhanced security and error handling."""
from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from loguru import logger
from slowapi import Limiter
from slowapi.util import get_remote_address

from core.engine import ContainerEngine
from core.git_manager import GitManager
from core.metrics import DEPLOYMENT_COUNTER

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


def _verify_signature(
    body: bytes, signature: Optional[str], secret: Optional[str]
) -> bool:
    """Verify HMAC signature with enhanced validation.

    Args:
        body: Request body bytes
        signature: Signature header value
        secret: Webhook secret

    Returns:
        True if signature is valid
    """
    # Reject if secret not configured (security by default)
    if not secret:
        logger.error("GITHUB_WEBHOOK_SECRET not configured - rejecting webhook")
        return False

    # Reject empty string secret explicitly
    if secret.strip() == "":
        logger.error("GITHUB_WEBHOOK_SECRET is empty - rejecting webhook")
        return False

    if not signature:
        logger.warning("Webhook signature missing")
        return False

    # Validate signature format
    if "=" not in signature:
        logger.warning("Invalid signature format - missing '='")
        return False

    parts = signature.split("=", 1)
    if len(parts) != 2:
        logger.warning("Invalid signature format - wrong number of parts")
        return False

    alg, sig = parts

    # Only accept sha256
    if alg != "sha256":
        logger.warning(f"Unsupported signature algorithm: {alg}")
        return False

    # Compute expected signature
    try:
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    except Exception as e:
        logger.error(f"Failed to compute HMAC: {e}")
        return False

    # Constant-time comparison
    try:
        is_valid = hmac.compare_digest(digest, sig)
        if not is_valid:
            logger.warning("Webhook signature mismatch")
        return is_valid
    except Exception as e:
        logger.error(f"Signature comparison failed: {e}")
        return False


@limiter.limit("10/minute")
@router.post("/webhook")
async def webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: Optional[str] = Header(None),
):
    """Receive webhook, verify signature, and enqueue deployment.

    Rate limited to 10 requests per minute per IP.
    Implements signature verification and comprehensive error handling.
    """
    body = await request.body()
    secret = os.getenv("GITHUB_WEBHOOK_SECRET")

    # Verify signature
    if not _verify_signature(body, x_hub_signature_256, secret):
        raise HTTPException(status_code=403, detail="Invalid or missing signature")

    DEPLOYMENT_COUNTER.inc()

    # Parse payload with error handling
    try:
        payload: Dict[str, Any] = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse webhook payload: {e}")
        # Accept the webhook but don't process
        return {"status": "accepted", "warning": "Invalid JSON payload"}

    def _deploy_task(payload: Dict[str, Any]):
        """Background deployment task with comprehensive error handling."""
        correlation_id = id(payload)  # Simple correlation ID

        try:
            # Extract repository info
            repo = payload.get("repository", {})
            repo_url = repo.get("clone_url") or repo.get("html_url")
            app_name = repo.get("name") or payload.get("project", {}).get("name")

            if not repo_url or not app_name:
                logger.error(
                    f"[{correlation_id}] Missing required fields: "
                    f"repo_url={repo_url}, app_name={app_name}"
                )
                return

            logger.info(f"[{correlation_id}] Starting deployment for {app_name}")

            # Clone/update repository
            try:
                gm = GitManager()
                path = gm.clone_repository(repo_url, app_name)
                logger.info(f"[{correlation_id}] Repository cloned to {path}")
            except Exception as e:
                logger.error(f"[{correlation_id}] Git clone failed: {e}")
                return

            # Build image
            engine = ContainerEngine()
            tag = f"{app_name}:latest"

            try:
                engine.build_image(path, tag)
                logger.info(f"[{correlation_id}] Image built: {tag}")
            except Exception as e:
                logger.error(f"[{correlation_id}] Image build failed: {e}")
                # Continue without raising - deployment will use existing image if available
                pass

            # Deploy container
            container_port = payload.get("container_port") or 8080

            try:
                result = engine.deploy(
                    app_name, tag, repo_path=path, container_port=container_port
                )

                if result.status != "ok":
                    logger.error(
                        f"[{correlation_id}] Deployment failed: {result.error}"
                    )
                    return

                logger.info(f"[{correlation_id}] Container deployed successfully")

            except Exception as e:
                logger.error(f"[{correlation_id}] Deployment failed: {e}")
                return

            # Configure proxy
            if result.status == "ok":
                try:
                    from core.network import PortManager
                    from core.proxy_manager import ProxyManager

                    pm = ProxyManager()
                    port_mgr = PortManager()  # noqa: F841

                    # Extract host port from container
                    host_port = container_port  # fallback

                    if hasattr(result, 'host_port') and result.host_port:
                        if isinstance(result.host_port, dict):
                            # Parse Docker port mapping format
                            for port_key, port_info in result.host_port.items():
                                if (
                                    port_info
                                    and isinstance(port_info, list)
                                    and len(port_info) > 0
                                ):
                                    try:
                                        host_port = int(
                                            port_info[0].get('HostPort', host_port)
                                        )
                                        break
                                    except (KeyError, ValueError, TypeError):
                                        continue

                    domain = f"{app_name}.localhost"
                    config = pm.generate_config(app_name, host_port, domain)
                    pm.write_config(app_name, config, overwrite=True)
                    pm.enable_config(app_name)

                    # Reload nginx with error handling
                    try:
                        if pm.reload_nginx():
                            logger.info(
                                f"[{correlation_id}] Proxy configured for "
                                f"{app_name} at {domain}:{host_port}"
                            )
                        else:
                            logger.error(f"[{correlation_id}] Nginx reload failed")
                    except FileNotFoundError:
                        logger.warning(
                            f"[{correlation_id}] Nginx not available - "
                            "skipping proxy configuration"
                        )
                    except Exception as e:
                        logger.error(f"[{correlation_id}] Nginx reload error: {e}")

                except Exception as e:
                    logger.warning(f"[{correlation_id}] Failed to configure proxy: {e}")

        except Exception as e:
            logger.exception(f"[{correlation_id}] Unexpected error in deploy task: {e}")

    # Schedule background deploy
    background_tasks.add_task(_deploy_task, payload)
    return {"status": "accepted", "message": "Deployment queued"}
