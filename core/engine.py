# core/engine.py
"""Container engine with transaction-safe deployments and rollback capability."""
import time
from typing import Any, Dict, List, Optional

import requests  # type: ignore
from loguru import logger

from core.metrics import ACTIVE_CONTAINERS_GAUGE


class DeploymentError(Exception):
    """Raised when deployment fails."""

    pass


class HealthCheckError(Exception):
    """Raised when health check fails."""

    pass


class Result:
    """Deployment result container with standardized port information."""

    def __init__(
        self,
        status: str,
        host_port: Optional[Any] = None,
        error: Optional[str] = None,
        container_id: Optional[str] = None,
        container_port: Optional[int] = None,
    ):
        self.status = status
        self.host_port = host_port
        self.container_id = container_id or host_port
        self.container_port = container_port
        self.error = error

    def get_host_port(self) -> Optional[int]:
        """Extract host port from various Docker port mapping formats.

        Docker returns ports in different formats:
        - Dict: {'80/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '8080'}]}
        - Dict: {'80/tcp': None} (no mapping)
        - String: '8080' (direct port)
        - Int: 8080

        Returns:
            Integer host port or None if not found
        """
        if self.host_port is None:
            return None

        # Case 1: Already an integer
        if isinstance(self.host_port, int):
            return self.host_port

        # Case 2: String that can be converted to int
        if isinstance(self.host_port, str):
            try:
                return int(self.host_port)
            except (ValueError, TypeError):
                pass

        # Case 3: Docker port mapping dict
        if isinstance(self.host_port, dict):
            # Iterate through all port mappings
            for port_key, port_info in self.host_port.items():
                if port_info is None:
                    continue

                # port_info should be a list of dicts
                if isinstance(port_info, list) and len(port_info) > 0:
                    first_mapping = port_info[0]
                    if isinstance(first_mapping, dict) and 'HostPort' in first_mapping:
                        try:
                            return int(first_mapping['HostPort'])
                        except (ValueError, TypeError, KeyError):
                            continue

        # Case 4: List of port mappings (some edge cases)
        if isinstance(self.host_port, list) and len(self.host_port) > 0:
            first = self.host_port[0]
            if isinstance(first, dict) and 'HostPort' in first:
                try:
                    return int(first['HostPort'])
                except (ValueError, TypeError, KeyError):
                    pass

        return None

    def to_dict(self) -> dict:
        """Convert result to dictionary for JSON serialization."""
        return {
            'status': self.status,
            'host_port': self.get_host_port(),
            'container_port': self.container_port,
            'container_id': self.container_id,
            'error': self.error,
        }


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
        """Basic deploy operation (use deploy_with_rollback for production).

        Args:
            app_name: Application name
            image_tag: Docker image tag
            repo_path: Repository path (unused)
            container_port: Container internal port to expose
            environment: Environment variables

        Returns:
            Result object with deployment status and port information
        """
        client = self.client

        # Default container port if not specified
        if container_port is None:
            container_port = 8080
            logger.info(f"No container_port specified, using default: {container_port}")

        try:
            run_kwargs = {
                "image": image_tag,
                "detach": True,
                "name": f"{app_name}-{int(time.time())}",  # Unique name with timestamp
                "labels": {
                    "app": app_name,
                    "managed_by": "pypaas",
                    "container_port": str(container_port),
                },
            }

            if environment:
                run_kwargs["environment"] = environment

            # Configure port mapping: container_port -> random host port
            try:
                run_kwargs["ports"] = {
                    f"{container_port}/tcp": None
                }  # None = random host port
            except Exception as e:
                logger.warning(f"Failed to configure port mapping: {e}")

            container = client.containers.run(**run_kwargs)

            # Reload container to get fresh port mappings
            container.reload()

            # Update metrics
            try:
                running = len(client.containers.list(filters={"status": "running"}))
                ACTIVE_CONTAINERS_GAUGE.set(running)
            except Exception:  # nosec B110
                pass

            # Extract port information
            ports_dict = getattr(container, "ports", {})
            container_id = getattr(container, "id", None)

            result = Result(
                status="ok",
                host_port=ports_dict,  # Pass full dict to Result
                container_id=container_id,
                container_port=container_port,
            )
            short_id = container_id[:12] if container_id else "unknown"
            # Log port mapping for debugging
            host_port = result.get_host_port()
            if host_port:
                logger.info(
                    f"Container {short_id} mapped: " f"{container_port} -> {host_port}"
                )
            else:
                logger.warning(f"Could not extract host port for container {short_id}")

            return result

        except Exception as e:
            logger.error(f"Deploy failed: {e}")
            return Result(
                status="failed",
                error=str(e),
                container_port=container_port,
            )
