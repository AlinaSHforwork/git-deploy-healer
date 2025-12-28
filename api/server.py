# api/server.py
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Security
from fastapi.responses import JSONResponse
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


@app.get("/")
def root():
    return {"message": "git-deploy-healer API is running"}


@app.get("/health")
async def health():
    """
    Lightweight health endpoint used by tests.
    """
    return {"status": "ok"}


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
