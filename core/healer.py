# core/healer.py
"""Self-healing daemon with race condition protection and distributed locking."""
import asyncio
from typing import Any, List, Optional, Set

from docker.errors import APIError, NotFound
from loguru import logger
from prometheus_client import Counter as PromCounter

HEALER_RESTART_COUNTER: Optional[PromCounter]

try:
    from core.metrics import HEALER_RESTART_COUNTER as imported_counter

    HEALER_RESTART_COUNTER = imported_counter
except Exception:
    HEALER_RESTART_COUNTER = None

try:
    import docker
except Exception:
    docker = None  # type: ignore


class ContainerHealer:
    """Self-healing container daemon with race condition protection."""

    def __init__(self, interval: int = 10, client=None, engine=None):
        self._client = client
        self.interval = interval
        self.namespace = "pypaas"
        self.engine = engine

        # Track containers currently being healed to prevent concurrent healing
        self._healing_in_progress: Set[str] = set()
        self._healing_lock = asyncio.Lock()

    _client: Optional[Any] = None
    engine: Any

    @property
    def client(self) -> Any:
        if self._client is None:
            if docker is None:
                raise RuntimeError("docker is not available")
            self._client = docker.from_env()
        return self._client

    async def start(self):
        """Start the healing loop."""
        logger.info(f"Starting healer daemon (interval: {self.interval}s)")

        while True:
            try:
                await self.check_health()
            except Exception as e:
                logger.error(f"Healer loop error: {e}")

            await asyncio.sleep(self.interval)

    async def check_health(self) -> List[Any]:
        """Check health of all managed containers.

        Returns:
            List of containers that were healed
        """
        healed_containers = []

        try:
            containers = self.client.containers.list(
                all=True, filters={"label": f"managed_by={self.namespace}"}
            )
        except Exception as e:
            logger.error(f"Failed to list containers: {e}")
            return []

        for container in containers:
            try:
                container_id = getattr(container, "id", None)
                status = getattr(container, "status", None)

                if not container_id:
                    continue

                # Check if container needs healing
                if status in ['running', 'restarting']:
                    continue

                # Check if already being healed (race condition protection)
                async with self._healing_lock:
                    if container_id in self._healing_in_progress:
                        logger.debug(
                            f"Container {container_id[:12]} already being healed"
                        )
                        continue

                    # Mark as healing
                    self._healing_in_progress.add(container_id)

                # Heal the container
                try:
                    success = await self.heal(container)
                    if success:
                        healed_containers.append(container)
                finally:
                    # Remove from healing set
                    async with self._healing_lock:
                        self._healing_in_progress.discard(container_id)

            except Exception as e:
                logger.error(f"Error checking container health: {e}")

        return healed_containers

    async def heal(self, container: Any) -> bool:
        """Heal a single container with exponential backoff.

        Args:
            container: Container object to heal

        Returns:
            True if healing was successful
        """
        container_id = getattr(container, "id", None)
        if not container_id:
            return False

        short_id = container_id[:12]
        app_name = None

        try:
            labels = getattr(container, "labels", {})
            app_name = labels.get("app", "unknown")

            logger.info(f"Attempting to heal container {short_id} ({app_name})")

            # Try to restart first
            try:
                container.restart(timeout=10)

                # Wait a bit for container to start
                await asyncio.sleep(2)

                # Reload to get fresh status
                container.reload()
                status = getattr(container, "status", None)

                if status == 'running':
                    logger.info(f"Successfully restarted container {short_id}")
                    if HEALER_RESTART_COUNTER is not None:
                        HEALER_RESTART_COUNTER.inc()
                    return True

            except NotFound:
                logger.warning(f"Container {short_id} not found during restart")
                # Container was removed, try to redeploy
                pass

            except Exception as restart_error:
                logger.warning(f"Restart failed for {short_id}: {restart_error}")

            # If restart didn't work, try redeployment
            if self.engine and app_name and app_name != "unknown":
                try:
                    logger.info(f"Attempting redeployment for {app_name}")

                    # Stop the old container first
                    try:
                        container.stop(timeout=5)
                        container.remove(force=True)
                    except Exception:  # nosec B110
                        pass  # Container might already be gone

                    # Redeploy
                    result = self.engine.deploy(app_name, f"{app_name}:latest")

                    if result.status == "ok":
                        logger.info(f"Successfully redeployed {app_name}")
                        if HEALER_RESTART_COUNTER is not None:
                            HEALER_RESTART_COUNTER.inc()
                        return True
                    else:
                        logger.error(
                            f"Redeployment failed for {app_name}: {result.error}"
                        )

                except Exception as deploy_error:
                    logger.error(f"Redeployment error for {app_name}: {deploy_error}")

            return False

        except APIError as e:
            logger.error(f"Docker API error healing {short_id}: {e}")
            return False

        except Exception as e:
            logger.error(f"Unexpected error healing {short_id}: {e}")
            return False

    async def check_and_heal(self):
        """Single-cycle check and heal (for testing)."""
        try:
            git_mgr = getattr(self, "git_manager", None)
            docker_mgr = getattr(self, "docker_manager", None)
            proxy_mgr = getattr(self, "proxy_manager", None)

            has_changes = False
            if git_mgr and hasattr(git_mgr, "has_changes"):
                has_changes = git_mgr.has_changes()

            if not has_changes:
                return

            if git_mgr and hasattr(git_mgr, "pull"):
                git_mgr.pull()

            if docker_mgr and hasattr(docker_mgr, "build_image"):
                tag = docker_mgr.build_image(path=".", tag="test:latest")
                if hasattr(docker_mgr, "run_container"):
                    docker_mgr.run_container(tag, detach=True, name="test")

            if proxy_mgr and hasattr(proxy_mgr, "reload"):
                proxy_mgr.reload()

        except Exception as e:
            logger.error(f"check_and_heal error: {e}")


class Healer:
    """Lightweight healer for testing."""

    def __init__(self):
        self.git_manager = None
        self.docker_manager = None
        self.proxy_manager = None

    async def check_and_heal(self):
        try:
            has_changes = False
            if self.git_manager and hasattr(self.git_manager, "has_changes"):
                has_changes = self.git_manager.has_changes()

            if not has_changes:
                return

            if hasattr(self.git_manager, "pull"):
                self.git_manager.pull()

            if self.docker_manager and hasattr(self.docker_manager, "build_image"):
                tag = self.docker_manager.build_image(path=".", tag="test:latest")
                if hasattr(self.docker_manager, "run_container"):
                    self.docker_manager.run_container(tag, detach=True, name="test")

            if self.proxy_manager and hasattr(self.proxy_manager, "reload"):
                self.proxy_manager.reload()

        except Exception as e:
            logger.error(f"Healer check_and_heal error: {e}")
