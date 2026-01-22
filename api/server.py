# api/server.py
import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional

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


# Expose a module-level get_db_manager so tests can monkeypatch `api.server.get_db_manager`.
# This simply proxies to core.models.get_db_manager and keeps imports lazy.
def get_db_manager(*args, **kwargs):
    from core.models import get_db_manager as _get_db_manager

    return _get_db_manager(*args, **kwargs)


# --- Core Component Initialization (lightweight) ---
engine = ContainerEngine()
git_manager = GitManager()
proxy_manager = ProxyManager()

# --- Lifespan Manager (Startup/Shutdown) ---


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        current_apps = engine.list_apps()
        logger.info(f"Observability initialized. Active apps: {len(current_apps)}")
    except Exception as e:
        logger.warning(f"Could not initialize metrics: {e}")

    # Initialize database (optional, only if using DB features)
    db_manager = None
    try:
        # Use module-level proxy so tests can patch `api.server.get_db_manager`
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

    # Stop healer
    if healer_task:
        healer_task.cancel()
        try:
            await healer_task
        except asyncio.CancelledError:
            pass
        logger.info("Healer daemon stopped")

    # Dispose database connections
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

# --- Rate Limiting (SlowAPI) ---


limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter


@app.get("/health/db")
async def db_health_check():
    """
    Database health check endpoint.
    Returns 200 if DB is accessible, 503 if not.
    """
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
    """
    Get deployment status including port mappings.
    Useful for debugging deployment issues.
    """
    try:
        containers = engine.list_containers(app_name)

        if not containers:
            return JSONResponse(
                status_code=404,
                content={"error": "No containers found", "app_name": app_name},
            )

        container_info = []
        for c in containers:
            ports = getattr(c, "ports", {})
            status = getattr(c, "status", "unknown")
            container_id = getattr(c, "id", "unknown")

            # Use standardized port extraction
            from core.network import parse_docker_port_mapping

            host_port = parse_docker_port_mapping(ports)

            container_info.append(
                {
                    "container_id": container_id[:12] if container_id else "unknown",
                    "status": status,
                    "host_port": host_port,
                    "raw_ports": str(ports)[:200],  # Truncate for safety
                }
            )

        return {
            "app_name": app_name,
            "container_count": len(containers),
            "containers": container_info,
        }

    except Exception as e:
        return JSONResponse(
            status_code=500, content={"error": str(e), "app_name": app_name}
        )


@app.exception_handler(RateLimitExceeded)
def rate_limit_handler(request, exc):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded"},
    )


app.add_middleware(SlowAPIMiddleware)


# Mount Prometheus Metrics Endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

templates = Jinja2Templates(directory="templates")


@app.get("/health")
async def health_check():
    """
    Health check endpoint for AWS Load Balancers and uptime monitoring.
    """
    return {"status": "ok", "service": "git-deploy-healer"}


@app.get("/")
def root():
    """
    Root endpoint that returns a simple message and links to docs and dashboard.
    """
    return {
        "message": "git-deploy-healer API is running",
        "docs": "/docs",
        "dashboard": "/dashboard",
    }


# Add favicon handler to avoid 404 logs
@app.get("/favicon.ico")
async def favicon():
    # Return empty 204 so browsers stop repeatedly requesting a missing favicon
    return Response(status_code=204)


# Dashboard page - render the Jinja2 template using engine.list_apps()
@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(request: Request):
    """
    Render the dashboard HTML page.
    Access at: http://<host>:<port>/dashboard
    """
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
                    except Exception as e:
                        logger.debug(f"Failed to parse port info for dashboard: {e}")
                        continue
        url = f"http://localhost:{host_port}" if host_port else None

        apps.append(
            {
                "name": name or "unknown",
                "id": cid or name,
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
    """
    Trigger endpoint used by tests. It calls api.healer.trigger_heal() if available.
    """
    try:
        import importlib

        healer_mod = importlib.import_module("api.healer")
        trigger_fn = getattr(healer_mod, "trigger_heal", None)
        if trigger_fn is None:
            return {"message": "no trigger available"}
        coro = trigger_fn()
        if asyncio.iscoroutine(coro):
            if background_tasks is not None:
                # schedule the coroutine in the background
                background_tasks.add_task(asyncio.create_task, coro)
            else:
                asyncio.create_task(coro)
        return {"message": "Triggered"}
    except Exception as e:
        logger.exception(f"Trigger failed: {e}")
        return {"message": "Trigger error"}


app.include_router(webhook_router)


@app.post("/api/deploy", dependencies=[Depends(require_api_key)])
async def deploy_application(
    background_tasks: BackgroundTasks,
    repository: dict = Body(...),
    container_port: int = Body(8080),
    domain: Optional[str] = Body(None),
    environment: Optional[dict] = Body(None),
):
    """Deploy application via dashboard."""
    try:
        app_name = repository.get("name")
        repo_url = repository.get("clone_url")

        if not app_name or not repo_url:
            raise HTTPException(status_code=400, detail="Missing app_name or repo_url")

        def _deploy_task():
            try:
                # Clone repository
                gm = GitManager()
                path = gm.clone_repository(repo_url, app_name)

                # Build image
                tag = f"{app_name}:latest"
                engine.build_image(path, tag)

                # Deploy
                result = engine.deploy(
                    app_name,
                    tag,
                    container_port=container_port,
                    environment=environment,
                )

                if result.status == "ok":
                    # Configure proxy
                    # from core.network import PortManager

                    pm = ProxyManager()
                    # port_mgr = PortManager()

                    host_port = result.get_host_port()
                    if host_port:
                        target_domain = domain or f"{app_name}.localhost"
                        config = pm.generate_config(app_name, host_port, target_domain)
                        pm.write_config(app_name, config, overwrite=True)
                        pm.enable_config(app_name)

                        try:
                            pm.reload_nginx()
                        except FileNotFoundError:
                            logger.warning("Nginx not available")

                logger.info(f"Deployment successful: {app_name}")
            except Exception as e:
                logger.error(f"Deployment failed: {e}")

        background_tasks.add_task(_deploy_task)
        return {"status": "accepted", "message": "Deployment started"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/apps/{app_name}/restart", dependencies=[Depends(require_api_key)])
async def restart_application(app_name: str):
    """Restart an application."""
    try:
        containers = engine.list_containers(app_name)
        if not containers:
            raise HTTPException(status_code=404, detail="Application not found")

        for container in containers:
            container.restart(timeout=10)

        return {"status": "ok", "message": f"Restarted {app_name}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/apps/{app_name}/stop", dependencies=[Depends(require_api_key)])
async def stop_application(app_name: str):
    """Stop an application."""
    try:
        containers = engine.list_containers(app_name)
        if not containers:
            raise HTTPException(status_code=404, detail="Application not found")

        for container in containers:
            container.stop(timeout=10)

        return {"status": "ok", "message": f"Stopped {app_name}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/apps/{app_name}/start", dependencies=[Depends(require_api_key)])
async def start_application(app_name: str):
    """Start a stopped application."""
    try:
        containers = engine.list_containers(app_name)
        if not containers:
            raise HTTPException(status_code=404, detail="Application not found")

        for container in containers:
            container.start()

        return {"status": "ok", "message": f"Started {app_name}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/apps/{app_name}", dependencies=[Depends(require_api_key)])
async def delete_application(app_name: str):
    """Delete an application and clean up resources."""
    try:
        # Stop and remove containers
        containers = engine.list_containers(app_name)
        for container in containers:
            try:
                container.stop(timeout=5)
                container.remove(force=True)
            except Exception as e:
                logger.warning(f"Failed to remove container: {e}")

        # Remove nginx config
        try:
            pm = ProxyManager()
            pm.disable_config(app_name)
            pm.remove_config(app_name)
            pm.reload_nginx()
        except Exception as e:
            logger.warning(f"Failed to remove proxy config: {e}")

        # Delete repository
        try:
            gm = GitManager()
            gm.delete_repository(app_name)
        except Exception as e:
            logger.warning(f"Failed to delete repository: {e}")

        return {"status": "ok", "message": f"Deleted {app_name}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/apps/{app_name}/logs", dependencies=[Depends(require_api_key)])
async def get_application_logs(app_name: str, tail: int = 100):
    """Get application logs."""
    try:
        containers = engine.list_containers(app_name)
        if not containers:
            raise HTTPException(status_code=404, detail="Application not found")

        logs = []
        for container in containers:
            try:
                container_logs = container.logs(tail=tail, timestamps=True).decode(
                    'utf-8'
                )
                logs.append(f"=== Container {container.id[:12]} ===\n{container_logs}")
            except Exception as e:
                logs.append(f"Failed to fetch logs: {e}")

        return {"logs": "\n\n".join(logs)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/apps")
async def list_applications():
    """List all applications (public endpoint for dashboard auto-refresh)."""
    try:
        apps = engine.list_apps()
        return apps
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
