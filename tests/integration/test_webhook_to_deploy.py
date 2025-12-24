import os
import time
import subprocess
from pathlib import Path

import pytest
import requests

pytestmark = pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1",
                                reason="Integration tests disabled (set RUN_INTEGRATION=1)")


def _compose_file():
    return Path("docker-compose.test.yml")


def _up(compose):
    subprocess.check_call(["docker", "compose", "-f", str(compose), "up", "-d"])


def _down(compose):
    subprocess.check_call(["docker", "compose", "-f", str(compose), "down"])


def test_webhook_triggers_deploy():
    compose = _compose_file()
    if not compose.exists():
        pytest.skip("docker-compose.test.yml not found")

    _up(compose)
    try:
        url = "http://localhost:8080/webhook"
        payload = {"ref": "refs/heads/main", "repository": {"name": "example"}}
        for _ in range(20):
            try:
                r = requests.post(url, json=payload, timeout=2)
                if r.status_code in (200, 201, 202):
                    return
            except Exception:
                time.sleep(1)
        pytest.fail("Webhook endpoint did not accept deploy request")
    finally:
        _down(compose)
