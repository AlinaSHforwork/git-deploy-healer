# api/server.py
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Security
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


# --- Core Component Initialization (lightweight) ---
engine = ContainerEngine()
git_manager = GitManager()
proxy_manager = ProxyManager()

# --- Lifespan Manager (Startup/Shutdown) ---


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        current_apps = engine.list_apps()
        logger.info(f"Observability initialized. Active apps: {len(current_apps)}")
    except Exception as e:
        logger.warning(f"Could not initialize metrics: {e}")

    # START HEALER DAEMON
    healer_task = None
    if os.getenv("ENABLE_HEALER", "true").lower() == "true":
        from core.healer import ContainerHealer

        healer = ContainerHealer(interval=30, engine=engine)
        healer_task = asyncio.create_task(healer.start())
        logger.info("Healer daemon started")

    yield

    # Cleanup
    if healer_task:
        healer_task.cancel()
        try:
            await healer_task
        except asyncio.CancelledError:
            pass


# --- App Definition ---
app = FastAPI(title="PyPaaS API", lifespan=lifespan)

# --- Rate Limiting (SlowAPI) ---


limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter


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
