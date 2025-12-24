import os
import re
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.templating import Jinja2Templates
from loguru import logger
from prometheus_client import make_asgi_app, Counter, Gauge
from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

from core.engine import ContainerEngine
from core.git_manager import GitManager
from core.proxy_manager import ProxyManager
from core.healer import ContainerHealer
from .schemas import PushEvent

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def get_api_key(api_key: str = Security(api_key_header)):
    if api_key != os.getenv("API_KEY"):  # Set API_KEY in env
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return api_key

# --- Prometheus Metrics Definitions ---
from core.metrics import DEPLOYMENT_COUNTER, HEALER_RESTART_COUNTER, ACTIVE_CONTAINERS_GAUGE

# --- Core Component Initialization ---
engine = ContainerEngine()
git_manager = GitManager()
proxy_manager = ProxyManager()

# --- Lifespan Manager (Startup/Shutdown) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Initialize Metrics based on existing state
    try:
        current_apps = engine.list_apps()
        ACTIVE_CONTAINERS_GAUGE.set(len(current_apps))
        logger.info(f"Observability initialized. Active apps: {len(current_apps)}")
    except Exception as e:
        logger.warning(f"Could not initialize metrics: {e}")

    # 2. Start Self-Healing Daemon
    healer = ContainerHealer(interval=10)
    task = asyncio.create_task(healer.start())
    
    yield
    
    # 3. Cleanup
    task.cancel()

# --- App Definition ---
app = FastAPI(title="PyPaaS API", lifespan=lifespan)

# Mount Prometheus Metrics Endpoint
# Prometheus will scrape http://localhost:8085/metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

templates = Jinja2Templates(directory="templates")

# --- Routes ---

@app.get("/")
async def dashboard(api_key: str = Depends(get_api_key)):
    apps = engine.list_apps()
    return templates.TemplateResponse("dashboard.html", {"request": request, "apps": apps})

def handle_deployment(event: PushEvent):
    app_name = event.repository.name
    clone_url = event.repository.clone_url

    if not re.match(r"^[a-zA-Z0-9_-]+$", app_name):
        logger.error(f"Security Alert: Invalid app name '{app_name}'")
        return
    
    logger.info(f"Background task started for {app_name}")

    try:
        repo_path = git_manager.update_repo(app_name, clone_url)
        tag = engine.build_image(repo_path, app_name)
        result = engine.deploy(app_name, tag, repo_path)
        
        if result.status == "failed":
            logger.error(f"Deployment failed: {result.error}")
        else:
            proxy_manager.register_app(app_name, result.host_port)
            logger.success(f"Deployed {app_name} on port {result.host_port}")
            logger.success(f"URL: http://{app_name}.localhost")
            
            # Update Metrics: Sync gauge with actual count
            try:
                current_apps = engine.list_apps()
                ACTIVE_CONTAINERS_GAUGE.set(len(current_apps))
            except Exception:
                # Fallback if list fails
                ACTIVE_CONTAINERS_GAUGE.inc()
            
    except Exception as e:
        logger.exception(f"Critical failure in background task: {e}")

@app.post("/webhook")
async def webhook(payload: dict, api_key: str = Depends(get_api_key)):
    if "refs/heads/main" not in event.ref:
        return {"message": "Ignored non-main branch push"}

    # Update Metrics
    DEPLOYMENT_COUNTER.inc()

    background_tasks.add_task(handle_deployment, event)
    
    return {
        "message": "Deployment queued", 
        "app": event.repository.name,
        "commit": event.after
    }