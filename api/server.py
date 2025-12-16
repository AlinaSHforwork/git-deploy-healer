import os
from fastapi import FastAPI, BackgroundTasks, HTTPException
from contextlib import asynccontextmanager
from loguru import logger
from core.engine import ContainerEngine
from core.git_manager import GitManager  
from core.proxy_manager import ProxyManager
from core.healer import ContainerHealer
from .schemas import PushEvent

@asynccontextmanager
async def lifespan(app: FastAPI):
    healer = ContainerHealer(interval=10)
    task = asyncio.create_task(healer.start())
    yield
    task.cancel()

app = FastAPI(title="PyPaaS API", lifespan=lifespan)
app = FastAPI(title="PyPaaS API")
engine = ContainerEngine()
git_manager = GitManager()  
proxy_manager = ProxyManager()

def handle_deployment(event: PushEvent):
    app_name = event.repository.name
    clone_url = event.repository.clone_url
    
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
            
    except Exception as e:
        logger.exception(f"Critical failure in background task: {e}")

@app.post("/webhook")
async def receive_webhook(event: PushEvent, background_tasks: BackgroundTasks):
    if "refs/heads/main" not in event.ref:
        return {"message": "Ignored non-main branch push"}

    background_tasks.add_task(handle_deployment, event)
    
    return {
        "message": "Deployment queued", 
        "app": event.repository.name,
        "commit": event.after
    }