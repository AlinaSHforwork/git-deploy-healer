import os
import re
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.templating import Jinja2Templates
from loguru import logger
from prometheus_client import make_asgi_app, Counter, Gauge

from core.engine import ContainerEngine
from core.git_manager import GitManager
from core.proxy_manager import ProxyManager
from core.healer import ContainerHealer
from .schemas import PushEvent

# --- Prometheus Metrics Definitions ---
# Counter: Tracks total number of deployments triggered
DEPLOYMENT_COUNTER = Counter(
    'pypaas_deployments_total', 
    'Total number of deployment webhooks received'
)

# Counter: Tracks total containers restarted by the Healer
# Note: Import this in core/healer.py to increment it on restart
HEALER_RESTART_COUNTER = Counter(
    'pypaas_healer_restarts_total', 
    'Total number of containers restarted by the self-healing daemon'
)

# Gauge: Tracks currently active/running containers (Goes up and down)
ACTIVE_CONTAINERS_GAUGE = Gauge(
    'pypaas_active_containers', 
    'Number of currently running application containers'
)

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
async def get_dashboard(request: Request):
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
        result = engine.deploy(app_name, tag)
        
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
async def receive_webhook(event: PushEvent, background_tasks: BackgroundTasks):
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