import docker
from docker.errors import BuildError, APIError
from loguru import logger
from .network import PortManager
from .schemas import DeploymentResult
import os
from dotenv import load_dotenv

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

    def deploy(self, app_name: str, image_tag: str, path: str, container_port: int | None = None) -> DeploymentResult:
        try:
            self._cleanup_old_containers(app_name)
            
            # Detect container port from image if not provided
            if container_port is None:
                image = self.client.images.get(image_tag)
                exposed_ports = image.attrs['Config'].get('ExposedPorts', {})
                if exposed_ports:
                    # Take the first exposed port (e.g., '5000/tcp' -> 5000)
                    container_port = int(list(exposed_ports.keys())[0].split('/')[0])
                else:
                    container_port = 80
                logger.info(f"Detected container port: {container_port} for {app_name}")

            host_port = self.port_manager.find_free_port()
            
            env_path = os.path.join(path, '.env')
            if os.path.exists(env_path):
                load_dotenv(env_path)
                environment = dict(os.environ)  # Pass all loaded envs
            else:
                environment = {}

            container = self.client.containers.run(
                image_tag,
                detach=True,
                ports={f'{container_port}/tcp': host_port},
                labels={"managed_by": self.namespace, "app": app_name},
                name=f"{app_name}_{host_port}",
                restart_policy={"Name": "on-failure", "MaximumRetryCount": 5},
                environment=environment 
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

    def list_apps(self):
        """
        Returns a list of dicts with app details and stats.
        """
        apps = []
        containers = self.client.containers.list(
            all=True,
            filters={"label": f"managed_by={self.namespace}"}
        )

        for container in containers:
            name = container.labels.get("app", "unknown")
            port = "N/A"
            
            ports_dict = container.attrs['NetworkSettings']['Ports']
            if ports_dict:
                for internal_port in ports_dict:
                    if ports_dict[internal_port]:
                        port = ports_dict[internal_port][0]['HostPort']
                        break  # Take the first available port

            stats_summary = "0%"
            if container.status == 'running':
                stats_summary = "Running"
            else:
                stats_summary = "Stopped"

            apps.append({
                "name": name,
                "id": container.short_id,
                "status": container.status,
                "port": port,
                "url": f"http://localhost:{port}" if container.status == 'running' and port != "N/A" else "#"
            })
            
        return apps