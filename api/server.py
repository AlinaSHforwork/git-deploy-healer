import os
from fastapi import FastAPI, BackgroundTasks, HTTPException
from loguru import logger
from core.engine import ContainerEngine
from core.git_manager import GitManager  
from .schemas import PushEvent

app = FastAPI(title="PyPaaS API")
engine = ContainerEngine()
git_manager = GitManager()  

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
            logger.success(f"Deployed {app_name} on port {result.host_port}")
            
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