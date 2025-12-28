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


def test_webhook_triggers_deploy():
    compose = Path("docker-compose.test.yml")
    if not compose.exists():
        pytest.skip("docker-compose.test.yml not found")

    subprocess.check_call(["docker", "compose", "-f", str(compose), "up", "-d"])
    try:
        url = "http://localhost:8080/webhook"
        payload = {"repository": {"name": "example"}}

        for _ in range(20):
            try:
                r = requests.post(url, json=payload, timeout=2)
                if r.status_code in (200, 201, 202):
                    return
            except Exception:
                time.sleep(1)

        pytest.fail("Webhook endpoint did not accept deploy request")
    finally:
        subprocess.check_call(["docker", "compose", "-f", str(compose), "down"])
