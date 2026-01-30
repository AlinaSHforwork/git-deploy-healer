import asyncio
import os
import re
from contextlib import asynccontextmanager
from typing import Any, List, Optional

import docker
from fastapi import (
    BackgroundTasks,
    Body,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Security,
)
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.security import APIKeyHeader
from fastapi.templating import Jinja2Templates
from loguru import logger
from prometheus_client import make_asgi_app
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from api.middleware.auth import require_api_key
from api.routes.webhook import router as webhook_router

# local imports (lazy imports for heavy modules are done inside functions)
from core.engine import ContainerEngine
from core.git_manager import GitManager
from core.proxy_manager import ProxyManager

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_api_key(api_key: str = Security(api_key_header)):
    if api_key != os.getenv("API_KEY"):
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return api_key


def get_db_manager(*args, **kwargs):
    from core.models import get_db_manager as _get_db_manager

    return _get_db_manager(*args, **kwargs)


# --- Core Component Initialization ---
engine = ContainerEngine()
git_manager = GitManager()
proxy_manager = ProxyManager()


# --- Helper: Robust Container Lookup ---
def get_containers_robust(app_name: str) -> List[Any]:
    """
    Tries to find containers by App Label first.
    If none found, falls back to direct Docker lookup by Container Name.
    This fixes 404s when the dashboard uses the container name (with timestamp).
    """
    # 1. Try standard engine lookup (Label-based)
    containers = engine.list_containers(app_name)
    if containers:
        return containers

    # 2. Fallback: Direct Docker Lookup (Name-based)
    try:
        import docker

        client = docker.from_env()
        # Try to find exact container match
        container = client.containers.get(app_name)
        # Return as a list to match engine.list_containers return type
        return [container]
    except Exception:
        # If both fail, return empty list
        return []


# --- Lifespan Manager (Startup/Shutdown) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        current_apps = engine.list_apps()
        logger.info(f"Observability initialized. Active apps: {len(current_apps)}")
    except Exception as e:
        logger.warning(f"Could not initialize metrics: {e}")

    from core.security import check_secrets_on_startup

    deployment_mode = os.getenv("DEPLOYMENT_MODE", "local")

    try:
        check_secrets_on_startup(strict=(deployment_mode == "aws"))
    except ValueError as e:
        logger.critical(f"Startup aborted: {e}")
        raise

    # Initialize database
    db_manager = None
    try:
        db_manager = get_db_manager()
        if db_manager.health_check():
            logger.info("Database connection healthy")
        else:
            logger.warning("Database health check failed")
    except Exception as e:
        logger.warning(f"Database initialization skipped: {e}")

    # START HEALER DAEMON
    healer_task = None
    if os.getenv("ENABLE_HEALER", "true").lower() == "true":
        from core.healer import ContainerHealer

        healer = ContainerHealer(interval=30, engine=engine)
        healer_task = asyncio.create_task(healer.start())
        logger.info("Healer daemon started")

    yield

    # Cleanup/Shutdown
    logger.info("Starting graceful shutdown...")
    if healer_task:
        healer_task.cancel()
        try:
            await healer_task
        except asyncio.CancelledError:
            pass
        logger.info("Healer daemon stopped")

    if db_manager:
        try:
            from core.models import dispose_db_manager

            dispose_db_manager()
            logger.info("Database connections closed")
        except Exception as e:
            logger.error(f"Error closing database: {e}")
    logger.info("Shutdown complete")


# --- App Definition ---
app = FastAPI(title="PyPaaS API", lifespan=lifespan)
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter


@app.get("/health/db")
async def db_health_check():
    try:
        db_manager = get_db_manager()
        if db_manager.health_check():
            return {"status": "healthy", "database": "connected"}
        else:
            return JSONResponse(
                status_code=503,
                content={"status": "unhealthy", "database": "connection_failed"},
            )
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "database": "not_configured",
                "error": str(e),
            },
        )


@app.get("/api/deployments/{app_name}/status")
async def get_deployment_status(app_name: str, _: bool = Depends(require_api_key)):
    try:
        app_name = _validate_app_name(app_name)

        # Use robust lookup
        containers = get_containers_robust(app_name)

        if not containers:
            return JSONResponse(
                status_code=404,
                content={"error": "No containers found", "app_name": app_name},
            )

        container_info = []
        for c in containers:
            # Handle both Engine objects and raw Docker objects
            ports = getattr(c, "ports", {})
            if not ports and hasattr(c, "attrs"):
                # Fallback for raw Docker object
                ports = c.attrs.get('NetworkSettings', {}).get('Ports', {})

            status = getattr(c, "status", "unknown")
            container_id = getattr(c, "id", "unknown")

            from core.network import parse_docker_port_mapping

            host_port = parse_docker_port_mapping(ports)

            container_info.append(
                {
                    "container_id": container_id[:12] if container_id else "unknown",
                    "status": status,
                    "host_port": host_port,
                    "raw_ports": str(ports)[:200],
                }
            )

        return {
            "app_name": app_name,
            "container_count": len(containers),
            "containers": container_info,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get deployment status error: {e}")
        return JSONResponse(
            status_code=500, content={"error": str(e), "app_name": app_name}
        )


@app.exception_handler(RateLimitExceeded)
def rate_limit_handler(request, exc):
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})


app.add_middleware(SlowAPIMiddleware)
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
templates = Jinja2Templates(directory="templates")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "git-deploy-healer"}


@app.get("/")
def root():
    return {
        "message": "git-deploy-healer API is running",
        "docs": "/docs",
        "dashboard": "/dashboard",
    }


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


@app.get(
    "/dashboard",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def dashboard(request: Request):
    try:
        raw_apps = engine.list_apps()
    except Exception as e:
        logger.debug(f"Failed to list apps for dashboard: {e}")
        raw_apps = []

    apps = []
    for a in raw_apps:
        name = a.get("name") if isinstance(a, dict) else getattr(a, "name", None)
        cid = a.get("id") if isinstance(a, dict) else getattr(a, "id", None)
        status = (
            a.get("status") if isinstance(a, dict) else getattr(a, "status", "unknown")
        )
        ports = a.get("ports") if isinstance(a, dict) else getattr(a, "ports", None)

        host_port = None
        if isinstance(ports, dict):
            for v in ports.values():
                if v and isinstance(v, list) and len(v) > 0:
                    try:
                        host_port = int(v[0].get("HostPort"))
                        break
                    except docker.errors.NotFound:
                        continue
                    except Exception as e:
                        # ERROR WAS HERE: 'e' was defined but not logged
                        logger.warning(f"Fallback removal failed for {name}: {e}")
        url = f"http://localhost:{host_port}" if host_port else None

        # Use ID as fallback for name if name is generic
        display_id = cid or name

        apps.append(
            {
                "name": name or "unknown",
                "id": display_id,  # Ensure we pass something identifying
                "status": status,
                "port": host_port,
                "url": url,
            }
        )

    return templates.TemplateResponse(
        request=request, name="dashboard.html", context={"apps": apps}
    )


@app.post("/trigger", response_model=None, dependencies=[Depends(require_api_key)])
def trigger(background_tasks: BackgroundTasks):
    try:
        import importlib

        healer_mod = importlib.import_module("api.healer")
        trigger_fn = getattr(healer_mod, "trigger_heal", None)
        if trigger_fn is None:
            return {"message": "no trigger available"}
        coro = trigger_fn()
        if asyncio.iscoroutine(coro):
            if background_tasks is not None:
                background_tasks.add_task(asyncio.create_task, coro)
            else:
                asyncio.create_task(coro)
        return {"message": "Triggered"}
    except Exception as e:
        logger.exception(f"Trigger failed: {e}")
        return {"message": "Trigger error"}


app.include_router(webhook_router)


def _validate_app_name(app_name: str) -> str:
    if not app_name:
        raise HTTPException(status_code=400, detail="app_name is required")
    sanitized = app_name.strip()
    if ".." in sanitized or "/" in sanitized or "\\" in sanitized:
        raise HTTPException(
            status_code=400, detail="Invalid app_name: cannot contain path separators"
        )
    if not re.match(r'^[a-zA-Z0-9_-]+$', sanitized):
        raise HTTPException(
            status_code=400,
            detail="Invalid app_name: only alphanumeric, hyphens, and underscores allowed",
        )
    if len(sanitized) > 100:
        raise HTTPException(
            status_code=400, detail="Invalid app_name: too long (max 100 characters)"
        )
    return sanitized


@app.post("/api/deploy", dependencies=[Depends(require_api_key)])
async def deploy_application(
    background_tasks: BackgroundTasks,
    repository: dict = Body(...),
    container_port: int = Body(8080),
    domain: Optional[str] = Body(None),
    environment: Optional[dict] = Body(None),
):
    try:
        app_name = repository.get("name")
        repo_url = repository.get("clone_url")

        if not app_name or not repo_url:
            raise HTTPException(status_code=400, detail="Missing app_name or repo_url")

        app_name = _validate_app_name(app_name)

        if not (1 <= container_port <= 65535):
            raise HTTPException(status_code=400, detail="Invalid container_port")
        if not (repo_url.startswith("http://") or repo_url.startswith("https://")):
            raise HTTPException(status_code=400, detail="Invalid repo_url")

        def _deploy_task():
            try:
                logger.info(f"Starting deployment for {app_name}")
                gm = GitManager()
                try:
                    path = gm.clone_repository(repo_url, app_name)
                    logger.info(f"Repository cloned to {path}")
                except Exception as e:
                    logger.error(f"Git clone failed for {app_name}: {e}")
                    return

                tag = f"{app_name}:latest"
                try:
                    engine.build_image(path, tag)
                    logger.info(f"Image built: {tag}")
                except Exception as e:
                    logger.error(f"Image build failed for {app_name}: {e}")
                    return

                try:
                    result = engine.deploy(
                        app_name,
                        tag,
                        repo_path=path,
                        container_port=container_port,
                        environment=environment,
                    )
                    if result.status != "ok":
                        logger.error(
                            f"Deployment failed for {app_name}: {result.error}"
                        )
                        return
                    logger.info(f"Container deployed: {result.container_id}")
                except Exception as e:
                    logger.error(f"Container deployment failed for {app_name}: {e}")
                    return

                if result.status == "ok":
                    try:
                        pm = ProxyManager()
                        host_port = result.get_host_port()
                        if host_port:
                            target_domain = domain or f"{app_name}.localhost"
                            config = pm.generate_config(
                                app_name, host_port, target_domain
                            )
                            pm.write_config(app_name, config, overwrite=True)
                            pm.enable_config(app_name)
                            try:
                                if pm.reload_nginx():
                                    logger.info(
                                        f"Proxy configured for {app_name} at {target_domain}:{host_port}"
                                    )
                                else:
                                    logger.error(f"Nginx reload failed for {app_name}")
                            except FileNotFoundError:
                                logger.warning(
                                    "Nginx not available - skipping proxy configuration"
                                )
                        else:
                            logger.warning(
                                f"Could not determine host port for {app_name}"
                            )
                    except Exception as e:
                        logger.warning(
                            f"Proxy configuration failed for {app_name}: {e}"
                        )
                logger.info(f"Deployment completed successfully for {app_name}")
            except Exception as e:
                logger.exception(
                    f"Unexpected error in deployment task for {app_name}: {e}"
                )

        background_tasks.add_task(_deploy_task)
        return {
            "status": "accepted",
            "message": f"Deployment started for {app_name}",
            "app_name": app_name,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Deploy endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/apps/{app_name}/restart", dependencies=[Depends(require_api_key)])
async def restart_application(app_name: str):
    try:
        app_name = _validate_app_name(app_name)

        # Use robust lookup
        containers = get_containers_robust(app_name)

        if not containers:
            raise HTTPException(status_code=404, detail="Application not found")

        restarted_count = 0
        errors = []

        for container in containers:
            try:
                container.restart(timeout=10)
                restarted_count += 1
                logger.info(
                    f"Restarted container {getattr(container, 'id', 'unknown')[:12]} for {app_name}"
                )
            except Exception as e:
                error_msg = f"Failed to restart container: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)

        if restarted_count == 0 and errors:
            raise HTTPException(
                status_code=500, detail=f"Failed to restart: {'; '.join(errors)}"
            )

        return {
            "status": "ok",
            "message": f"Restarted {restarted_count} container(s)",
            "restarted": restarted_count,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Restart application error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/apps/{app_name}/stop", dependencies=[Depends(require_api_key)])
async def stop_application(app_name: str):
    try:
        app_name = _validate_app_name(app_name)

        # Use robust lookup
        containers = get_containers_robust(app_name)

        if not containers:
            raise HTTPException(status_code=404, detail="Application not found")

        stopped_count = 0
        errors = []

        for container in containers:
            try:
                container.reload()
                if container.status in ("exited", "stopped"):
                    stopped_count += 1
                    continue
                container.stop(timeout=10)
                stopped_count += 1
                logger.info(
                    f"Stopped container {getattr(container, 'id', 'unknown')[:12]} for {app_name}"
                )
            except Exception as e:
                error_msg = f"Failed to stop container: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)

        if stopped_count == 0 and errors:
            raise HTTPException(
                status_code=500, detail=f"Failed to stop: {'; '.join(errors)}"
            )

        return {
            "status": "ok",
            "message": f"Stopped {stopped_count} container(s)",
            "stopped": stopped_count,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Stop application error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/apps/{app_name}/start", dependencies=[Depends(require_api_key)])
async def start_application(app_name: str):
    try:
        app_name = _validate_app_name(app_name)

        # Use robust lookup
        containers = get_containers_robust(app_name)

        if not containers:
            raise HTTPException(status_code=404, detail="Application not found")

        started_count = 0
        errors = []

        for container in containers:
            try:
                container.reload()
                if container.status == "running":
                    started_count += 1
                    continue
                container.start()
                started_count += 1
                logger.info(
                    f"Started container {getattr(container, 'id', 'unknown')[:12]} for {app_name}"
                )
            except Exception as e:
                error_msg = f"Failed to start container: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)

        if started_count == 0 and errors:
            raise HTTPException(
                status_code=500, detail=f"Failed to start: {'; '.join(errors)}"
            )

        return {
            "status": "ok",
            "message": f"Started {started_count} container(s)",
            "started": started_count,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Start application error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/apps/{app_name}", dependencies=[Depends(require_api_key)])
async def delete_application(app_name: str):
    try:
        app_name = _validate_app_name(app_name)

        # 1. Standard Removal
        containers = engine.list_containers(app_name)
        deleted_containers = 0
        for container in containers:
            try:
                container.stop(timeout=5)
                container.remove(force=True)
                deleted_containers += 1
                logger.info(f"Removed container {container.id[:12]} for {app_name}")
            except Exception as e:
                logger.warning(f"Failed to remove container {container.id[:12]}: {e}")

        # 2. FALLBACK: "Nuclear Option" (Direct Docker Removal)
        if deleted_containers == 0:
            try:
                import docker

                client = docker.from_env()
                zombie = client.containers.get(app_name)
                if zombie.status == "running":
                    zombie.stop(timeout=5)
                zombie.remove(force=True)
                logger.info(
                    f"Force removed zombie container '{app_name}' via direct lookup"
                )
                deleted_containers += 1
            except docker.errors.NotFound:
                pass
            except Exception as e:
                logger.warning(f"Fallback removal failed for {app_name}: {e}")

        # Remove nginx config
        try:
            pm = ProxyManager()
            pm.disable_config(app_name)
            pm.remove_config(app_name)
            pm.reload_nginx()
            logger.info(f"Removed proxy config for {app_name}")
        except FileNotFoundError:
            logger.warning("Nginx not available - skipping proxy cleanup")
        except Exception as e:
            logger.warning(f"Failed to remove proxy config for {app_name}: {e}")

        # Delete repository
        try:
            gm = GitManager()
            gm.delete_repository(app_name)
            logger.info(f"Deleted repository for {app_name}")
        except Exception as e:
            logger.warning(f"Failed to delete repository for {app_name}: {e}")

        return {
            "status": "ok",
            "message": f"Deleted {app_name}",
            "containers_removed": deleted_containers,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Delete application error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/apps/{app_name}/logs", dependencies=[Depends(require_api_key)])
async def get_application_logs(app_name: str, tail: int = 100):
    try:
        app_name = _validate_app_name(app_name)
        if tail < 1:
            tail = 100
        elif tail > 10000:
            tail = 10000

        # Use robust lookup
        containers = get_containers_robust(app_name)

        if not containers:
            raise HTTPException(status_code=404, detail="Application not found")

        logs = []
        for container in containers:
            try:
                container_id = getattr(container, 'id', 'unknown')[:12]
                container_logs = container.logs(tail=tail, timestamps=True)

                if isinstance(container_logs, bytes):
                    try:
                        decoded_logs = container_logs.decode('utf-8')
                    except UnicodeDecodeError:
                        decoded_logs = container_logs.decode('latin-1')
                else:
                    decoded_logs = str(container_logs)

                logs.append(
                    f"=== Container {container_id} ({app_name}) ===\n{decoded_logs}"
                )
            except Exception as e:
                logger.error(f"Failed to fetch logs: {e}")
                logs.append(f"Failed to fetch logs: {str(e)}")

        return {
            "app_name": app_name,
            "container_count": len(containers),
            "logs": "\n\n".join(logs),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Get logs error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/apps")
async def list_applications():
    try:
        apps = engine.list_apps()
        return apps
    except Exception as e:
        logger.error(f"List applications error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
