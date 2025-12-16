import docker
from docker.errors import BuildError, APIError
from loguru import logger
from .network import PortManager
from .schemas import DeploymentResult

class ContainerEngine:
    def __init__(self):
        self.client = docker.from_env()
        self.port_manager = PortManager()
        self.namespace = "pypaas"

    def build_image(self, path: str, app_name: str) -> str:
        tag = f"{self.namespace}/{app_name}:latest"
        logger.info(f"Starting build for {tag}...")
        
        try:
            image, _ = self.client.images.build(
                path=path,
                tag=tag,
                rm=True,
                forcerm=True
            )
            return tag
        except (BuildError, APIError) as e:
            logger.error(f"Build failed: {e}")
            raise e

    def deploy(self, app_name: str, image_tag: str) -> DeploymentResult:
        try:
            self._cleanup_old_containers(app_name)
            
            host_port = self.port_manager.find_free_port()
            
            container = self.client.containers.run(
                image_tag,
                detach=True,
                ports={'80/tcp': host_port},
                labels={"managed_by": self.namespace, "app": app_name},
                name=f"{app_name}_{host_port}",
                restart_policy={"Name": "on-failure", "MaximumRetryCount": 5}
            )
            
            container.reload()
            if container.status != 'running' and container.status != 'created':
                 raise RuntimeError(f"Container failed to start. Status: {container.status}")

            return DeploymentResult(
                container_id=container.id, 
                image_tag=image_tag, 
                host_port=host_port, 
                status=container.status
            )

        except Exception as e:
            logger.error(f"Deployment failed: {e}")
            return DeploymentResult(
                container_id="", 
                image_tag=image_tag, 
                host_port=0, 
                status="failed", 
                error=str(e)
            )

    def _cleanup_old_containers(self, app_name: str):
        containers = self.client.containers.list(
            all=True, 
            filters={"label": [f"managed_by={self.namespace}", f"app={app_name}"]}
        )
        for c in containers:
            logger.warning(f"Stopping old container {c.name}")
            try:
                c.stop(timeout=5)
                c.remove()
            except APIError:
                c.kill()