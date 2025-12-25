import os
import subprocess
import time
from pathlib import Path

import pytest
import requests

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1",
    reason="Integration tests disabled (set RUN_INTEGRATION=1)",
)


def _compose_file():
    return Path("docker-compose.test.yml")


def _up(compose):
    subprocess.check_call(["docker", "compose", "-f", str(compose), "up", "-d"])


def _down(compose):
    subprocess.check_call(["docker", "compose", "-f", str(compose), "down"])


def test_deployment_flow_healthcheck():
    compose = _compose_file()
    if not compose.exists():
        pytest.skip("docker-compose.test.yml not found")

    _up(compose)
    try:
        # wait for service health endpoint
        url = "http://localhost:8080/health"
        for _ in range(30):
            try:
                r = requests.get(url, timeout=1)
                if r.status_code == 200:
                    return
            except Exception:
                time.sleep(1)
        pytest.fail(f"Service did not become healthy at {url}")
    finally:
        _down(compose)
