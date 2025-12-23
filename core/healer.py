import time
import asyncio
import docker
from loguru import logger
from docker.errors import NotFound, APIError
from .engine import ContainerEngine  # Import for recreation

class ContainerHealer:
    def __init__(self, interval: int = 10):
        self.client = docker.from_env()
        self.interval = interval
        self.namespace = "pypaas"
        self.engine = ContainerEngine()  # For redeploying during heal

    async def start(self):
        logger.info("Healer Daemon started. Watching containers...")
        while True:
            try:
                self.check_health()
            except Exception as e:
                logger.error(f"Healer loop error: {e}")
            
            await asyncio.sleep(self.interval)

    def check_health(self):
        containers = self.client.containers.list(
            all=True,
            filters={"label": f"managed_by={self.namespace}"}
        )

        for container in containers:
            if container.status not in ['running', 'restarting']:
                logger.warning(f"Detected unhealthy app: {container.name} ({container.status})")
                self.heal(container)

    def heal(self, container):
        try:
            logger.info(f"Attempting to heal {container.name}...")
            container.restart(timeout=10)  # Try restart first
            
            container.reload()
            if container.status == 'running':
                logger.success(f"Successfully revived {container.name}")
                return
            else:
                logger.warning(f"Restart failed. Recreating {container.name}...")
                # Recreate logic
                app_name = container.labels.get("app")
                if not app_name:
                    raise ValueError("No 'app' label found on container")
                
                image_tag = container.image.tags[0] if container.image.tags else "latest"
                
                container.stop(timeout=5)
                container.remove()
                
                # Redeploy using engine (assuming default port; pass custom if needed)
                self.engine.deploy(app_name, image_tag)
                logger.success(f"Successfully recreated {container.name}")
                
        except APIError as e:
            logger.error(f"Docker API error while healing: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during heal: {e}")