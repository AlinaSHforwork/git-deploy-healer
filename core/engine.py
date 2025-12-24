# core/engine.py
from typing import Optional, Any, Dict, List


class ContainerEngine:
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
        client = self.client
        try:
            containers = client.containers.list(all=False)
            apps = []
            for c in containers:
                apps.append({
                    "name": getattr(c, "name", None),
                    "status": getattr(c, "status", None),
                    "ports": getattr(c, "ports", None),
                })
            return apps
        except Exception:
            return []

    def build_image(self, path: str, tag: str) -> str:
        client = self.client
        try:
            client.images.build(path=path, tag=tag)
            return tag
        except Exception:
            raise

    def run_container(self, image: str, **kwargs):
        client = self.client
        try:
            container = client.containers.run(image, **kwargs)
            return container
        except Exception:
            raise

    def stop_container(self, container_id: str, timeout: int = 5):
        client = self.client
        try:
            c = client.containers.get(container_id)
            c.stop(timeout=timeout)
        except Exception:
            raise

    def deploy(
        self,
        app_name: str,
        image_tag: str,
        repo_path: Optional[str] = None,
        container_port: Optional[int] = None,
    ):
        client = self.client
        try:
            container = client.containers.run(image_tag, detach=True, labels={"app": app_name})

            class Result:
                status = "ok"
                host_port = getattr(container, "id", None)
            return Result()
        except Exception as e:
            class Result:
                status = "failed"
                error = str(e)
            return Result()
