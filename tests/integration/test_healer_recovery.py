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


def _stop_container(name):
    subprocess.check_call(["docker", "compose", "ps", "--services"])
    subprocess.check_call(["docker", "compose", "stop", name])


def test_healer_restarts_container():
    compose = _compose_file()
    if not compose.exists():
        pytest.skip("docker-compose.test.yml not found")

    service_name = os.getenv(
        "HEALER_TARGET_SERVICE", "app"
    )  # default service name 'app'
    health_url = "http://localhost:8080/health"

    _up(compose)
    try:
        # ensure healthy first
        for _ in range(20):
            try:
                r = requests.get(health_url, timeout=1)
                if r.status_code == 200:
                    break
            except Exception:
                time.sleep(1)
        else:
            pytest.skip("Service not healthy to begin with")

        # stop the target service container
        _stop_container(service_name)

        # wait for healer to bring it back up (health endpoint again)
        for _ in range(60):
            try:
                r = requests.get(health_url, timeout=1)
                if r.status_code == 200:
                    return
            except Exception:
                time.sleep(1)
        pytest.fail("Healer did not recover the service in time")
    finally:
        _down(compose)
