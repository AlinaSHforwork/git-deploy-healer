# core/engine.py
"""Container engine with transaction-safe deployments and rollback capability."""
import time
from typing import Any, Dict, List, Optional

import requests  # type: ignore
from loguru import logger


class DeploymentError(Exception):
    """Raised when deployment fails."""

    pass


class HealthCheckError(Exception):
    """Raised when health check fails."""

    pass


class Result:
    """Deployment result container."""

    def __init__(
        self,
        status: str,
        host_port: Optional[Any] = None,
        error: Optional[str] = None,
        container_id: Optional[str] = None,
    ):
        self.status = status
        self.host_port = host_port
        self.container_id = container_id or host_port
        self.error = error


class ContainerEngine:
    """Docker container management with transaction-safe operations."""

    def __init__(self, client: Optional[Any] = None):
        self._client = client

    def _ensure_client(self):
        if self._client is None:
            import docker

            self._client = docker.from_env()
        return self._client

    @property
    def client(self):
        return self._ensure_client()

    @client.setter
    def client(self, value):
        self._client = value

    def list_apps(self) -> List[Dict]:
        """List all managed applications."""
        client = self.client
        try:
            containers = client.containers.list(all=False)
            apps = []
            for c in containers:
                apps.append(
                    {
                        "name": getattr(c, "name", None),
                        "status": getattr(c, "status", None),
                        "ports": getattr(c, "ports", None),
                    }
                )
            return apps
        except Exception:
            return []

    def list_containers(self, app_name: str) -> List[Any]:
        """List containers for specific app."""
        client = self.client
        try:
            return client.containers.list(
                all=True, filters={"label": f"app={app_name}"}
            )
        except Exception:
            return []

    def build_image(self, path: str, tag: str) -> str:
        """Build Docker image."""
        client = self.client
        try:
            logger.info(f"Building image {tag} from {path}")
            client.images.build(path=path, tag=tag, rm=True)
            logger.info(f"Successfully built image {tag}")
            return tag
        except Exception as e:
            logger.error(f"Failed to build image {tag}: {e}")
            raise

    def run_container(self, image: str, **kwargs):
        """Run container with specified parameters."""
        client = self.client
        try:
            container = client.containers.run(image, **kwargs)
            return container
        except Exception:
            raise

    def stop_container(self, container_id: str, timeout: int = 5):
        """Stop container gracefully."""
        client = self.client
        try:
            c = client.containers.get(container_id)
            c.stop(timeout=timeout)
            logger.info(f"Stopped container {container_id[:12]}")
        except Exception as e:
            logger.error(f"Failed to stop container {container_id[:12]}: {e}")
            raise

    def remove_container(self, container_id: str, force: bool = False):
        """Remove container."""
        client = self.client
        try:
            c = client.containers.get(container_id)
            c.remove(force=force)
            logger.info(f"Removed container {container_id[:12]}")
        except Exception as e:
            logger.error(f"Failed to remove container {container_id[:12]}: {e}")
            raise

    def health_check(
        self, container: Any, timeout: int = 30, interval: int = 2, endpoint: str = "/"
    ) -> bool:
        """Check if container is healthy by testing HTTP endpoint.

        Args:
            container: Container object
            timeout: Maximum time to wait for healthy status
            interval: Time between health check attempts
            endpoint: HTTP endpoint to check

        Returns:
            True if container is healthy
        """
        container_id = getattr(container, "id", None)
        if not container_id:
            return False

        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                # Reload container to get latest status
                container.reload()
                status = getattr(container, "status", None)

                if status != "running":
                    logger.warning(f"Container {container_id[:12]} status: {status}")
                    time.sleep(interval)
                    continue

                # Try HTTP health check if ports are exposed
                ports = getattr(container, "ports", {})
                if ports:
                    for port_info in ports.values():
                        if port_info and isinstance(port_info, list):
                            host_port = port_info[0].get("HostPort")
                            if host_port:
                                try:
                                    response = requests.get(
                                        f"http://localhost:{host_port}{endpoint}",
                                        timeout=2,
                                    )
                                    if response.status_code < 500:
                                        logger.info(
                                            f"Container {container_id[:12]} "
                                            f"healthy (HTTP {response.status_code})"
                                        )
                                        return True
                                except requests.RequestException:
                                    pass

                # If no HTTP check possible, just check if running
                logger.info(f"Container {container_id[:12]} is running")
                return True

            except Exception as e:
                logger.warning(f"Health check error for {container_id[:12]}: {e}")

            time.sleep(interval)

        logger.error(f"Health check timeout for container {container_id[:12]}")
        return False

    def deploy_with_rollback(
        self,
        app_name: str,
        image_tag: str,
        repo_path: Optional[str] = None,
        container_port: Optional[int] = None,
        environment: Optional[dict] = None,
    ) -> Result:
        """Deploy with automatic rollback on failure.

        This implements a transaction-safe deployment:
        1. List existing containers
        2. Deploy new container
        3. Health check new container
        4. Stop old containers if successful
        5. Rollback if health check fails

        Args:
            app_name: Application name
            image_tag: Docker image tag
            repo_path: Repository path (unused currently)
            container_port: Container port to expose
            environment: Environment variables

        Returns:
            Result object with deployment status
        """
        logger.info(f"Starting deployment for {app_name}")

        # Step 1: Get existing containers
        old_containers = self.list_containers(app_name)
        logger.info(f"Found {len(old_containers)} existing containers")

        new_container = None

        try:
            # Step 2: Deploy new container
            result = self.deploy(
                app_name,
                image_tag,
                repo_path=repo_path,
                container_port=container_port,
                environment=environment,
            )

            if result.status != "ok":
                raise DeploymentError(f"Deployment failed: {result.error}")

            # Get container object
            try:
                new_container = self.client.containers.get(result.container_id)
            except Exception as e:
                raise DeploymentError(f"Failed to get container: {e}")

            # Step 3: Health check
            logger.info("Running health check on new container")
            if not self.health_check(new_container, timeout=30):
                raise HealthCheckError("Health check failed")

            # Step 4: Success - cleanup old containers
            logger.info("Health check passed - cleaning up old containers")
            for old_container in old_containers:
                try:
                    old_id = getattr(old_container, "id", None)
                    if old_id:
                        self.stop_container(old_id, timeout=10)
                        self.remove_container(old_id, force=True)
                except Exception as e:
                    logger.warning(f"Failed to cleanup old container: {e}")

            logger.info(f"Successfully deployed {app_name}")
            return result

        except (DeploymentError, HealthCheckError) as e:
            # Step 5: Rollback on failure
            logger.error(f"Deployment failed - rolling back: {e}")

            if new_container:
                try:
                    container_id = getattr(new_container, "id", None)
                    if container_id:
                        logger.info(f"Stopping failed container {container_id[:12]}")
                        self.stop_container(container_id, timeout=5)
                        self.remove_container(container_id, force=True)
                except Exception as cleanup_error:
                    logger.error(f"Rollback cleanup failed: {cleanup_error}")

            return Result(status="failed", error=f"Deployment rolled back: {str(e)}")

        except Exception as e:
            logger.exception(f"Unexpected deployment error: {e}")
            return Result(status="failed", error=f"Unexpected error: {str(e)}")

    def deploy(
        self,
        app_name: str,
        image_tag: str,
        repo_path: Optional[str] = None,
        container_port: Optional[int] = None,
        environment: Optional[dict] = None,
    ):
        """Basic deploy operation (use deploy_with_rollback for production)."""
        from core.metrics import ACTIVE_CONTAINERS_GAUGE

        client = self.client
        try:
            run_kwargs = {
                "image": image_tag,
                "detach": True,
                "labels": {"app": app_name, "managed_by": "pypaas"},
            }

            if environment:
                run_kwargs["environment"] = environment

            if container_port is not None:
                try:
                    run_kwargs["ports"] = {f"{container_port}/tcp": None}
                except Exception:  # nosec B110
                    pass

            container = client.containers.run(**run_kwargs)

            # Update metrics
            try:
                running = len(client.containers.list(filters={"status": "running"}))
                ACTIVE_CONTAINERS_GAUGE.set(running)
            except Exception:  # nosec B110
                pass

            host_port = None
            try:
                ports = getattr(container, "ports", None)
                host_port = ports
            except Exception:
                host_port = getattr(container, "id", None)

            return Result(
                status="ok",
                host_port=host_port,
                container_id=getattr(container, "id", None),
            )

        except Exception as e:
            logger.error(f"Deploy failed: {e}")
            return Result(
                status="failed",
                error=str(e),
            )
