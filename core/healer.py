import time
import asyncio
import docker
from loguru import logger
from docker.errors import NotFound, APIError

class ContainerHealer:
    def __init__(self, interval: int = 10):
        self.client = docker.from_env()
        self.interval = interval
        self.namespace = "pypaas"

    async def start(self):
        logger.info("🏥 Healer Daemon started. Watching containers...")
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
                logger.warning(f"⚠️  Detected unhealthy app: {container.name} ({container.status})")
                self.heal(container)

    def heal(self, container):
        try:
            logger.info(f"🚑 Attempting to heal {container.name}...")
            container.start()
            
            container.reload()
            if container.status == 'running':
                logger.success(f"✅ Successfully revived {container.name}")
            else:
                logger.error(f"❌ Failed to revive {container.name}. Status: {container.status}")
                
        except APIError as e:
            logger.error(f"Docker API error while healing: {e}")