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
    """Verify HMAC signature with timing-attack protection.

    Args:
        body: Request body bytes
        signature: Signature header value
        secret: Webhook secret

    Returns:
        True if signature is valid
    """
    # Always compute a signature to prevent timing attacks
    # Use a dummy value if inputs are invalid
    actual_secret = (
        secret if secret and secret.strip() else "dummy-secret-32-chars-long-xxxxx"
    )
    actual_signature = signature if signature else "sha256=dummy"

    # Track if inputs are valid (but don't return early)
    is_valid_input = True

    if not secret or secret.strip() == "":
        logger.error("GITHUB_WEBHOOK_SECRET not configured or empty")
        is_valid_input = False

    if not signature:
        logger.warning("Webhook signature missing")
        is_valid_input = False

    # Parse signature format
    if "=" not in actual_signature:
        logger.warning("Invalid signature format - missing '='")
        is_valid_input = False

    parts = actual_signature.split("=", 1)
    if len(parts) != 2:
        logger.warning("Invalid signature format - wrong number of parts")
        is_valid_input = False

    alg = parts[0] if len(parts) == 2 else "sha256"
    sig = parts[1] if len(parts) == 2 else "dummy"

    # Only accept sha256
    if alg != "sha256":
        logger.warning(f"Unsupported signature algorithm: {alg}")
        is_valid_input = False

    # Always compute expected signature (constant time regardless of errors)
    try:
        digest = hmac.new(actual_secret.encode(), body, hashlib.sha256).hexdigest()
    except Exception as e:
        logger.error(f"Failed to compute HMAC: {e}")
        digest = "0" * 64  # dummy digest
        is_valid_input = False

    # Always perform comparison (constant time)
    try:
        signatures_match = hmac.compare_digest(digest, sig)
    except Exception as e:
        logger.error(f"Signature comparison failed: {e}")
        signatures_match = False
        is_valid_input = False

    # Final result: both inputs must be valid AND signatures must match
    result = is_valid_input and signatures_match

    if not result:
        logger.warning("Webhook signature verification failed")

    return result


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

                    # Extract host port using standardized method
                    host_port = result.get_host_port()

                    if host_port is None:
                        logger.error(
                            f"[{correlation_id}] Could not determine host port for {app_name}"
                        )
                        return

                    domain = f"{app_name}.localhost"

                    # Generate and write config
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
