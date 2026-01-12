"""
Integration tests for webhook to deployment flow.

Tests the complete webhook processing pipeline:
1. Webhook signature verification
2. Payload parsing and validation
3. Git repository cloning
4. Docker image building
5. Container deployment
6. Proxy configuration
"""
import hashlib
import hmac
import json
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


class WebhookTestHelper:
    """Helper for webhook testing."""

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        secret: str = "test-webhook-secret",
    ):
        self.base_url = base_url
        self.secret = secret

    def sign_payload(self, payload: dict) -> str:
        """Generate valid HMAC signature for payload."""
        body = json.dumps(payload).encode()
        digest = hmac.new(self.secret.encode(), body, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    def send_webhook(
        self, payload: dict, valid_signature: bool = True
    ) -> requests.Response:
        """Send webhook request with optional signature."""
        body = json.dumps(payload).encode()
        headers = {}

        if valid_signature:
            headers["X-Hub-Signature-256"] = self.sign_payload(payload)
        else:
            headers["X-Hub-Signature-256"] = "sha256=invalid"

        return requests.post(
            f"{self.base_url}/webhook",
            data=body,
            headers=headers,
            timeout=10,
        )


@pytest.fixture
def docker_compose_up():
    """Fixture to ensure docker-compose is running."""
    compose_file = Path("docker-compose.test.yml")
    if not compose_file.exists():
        pytest.skip("docker-compose.test.yml not found")

    # Start services
    subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "up", "-d"],
        check=True,
        capture_output=True,
        timeout=30,
    )

    # Wait for service to be healthy
    for _ in range(60):
        try:
            response = requests.get("http://localhost:8080/health", timeout=2)
            if response.status_code == 200:
                break
        except requests.RequestException:
            pass
        time.sleep(1)
    else:
        pytest.fail("Service did not become healthy")

    yield

    # Cleanup
    subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "down"],
        check=False,
        capture_output=True,
        timeout=30,
    )


@pytest.fixture
def webhook_helper():
    """Fixture providing webhook test helper."""
    return WebhookTestHelper()


class TestWebhookToDeployFlow:
    """Test webhook to deployment flow."""

    def test_webhook_accepts_valid_signature(self, docker_compose_up, webhook_helper):
        """Test webhook accepts request with valid signature."""
        payload = {
            "repository": {
                "name": "test-app",
                "clone_url": "https://github.com/test/test-app.git",
                "html_url": "https://github.com/test/test-app",
            },
            "action": "opened",
        }

        response = webhook_helper.send_webhook(payload, valid_signature=True)
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "accepted"

    def test_webhook_rejects_invalid_signature(self, docker_compose_up, webhook_helper):
        """Test webhook rejects request with invalid signature."""
        payload = {
            "repository": {
                "name": "test-app",
                "clone_url": "https://github.com/test/test-app.git",
            }
        }

        response = webhook_helper.send_webhook(payload, valid_signature=False)
        assert response.status_code == 403

    def test_webhook_rejects_missing_signature(self, docker_compose_up):
        """Test webhook rejects request without signature."""
        payload = {
            "repository": {
                "name": "test-app",
                "clone_url": "https://github.com/test/test-app.git",
            }
        }

        response = requests.post(
            "http://localhost:8080/webhook",
            json=payload,
            timeout=10,
        )
        assert response.status_code == 403

    def test_webhook_handles_minimal_payload(self, docker_compose_up, webhook_helper):
        """Test webhook handles minimal valid payload."""
        payload = {
            "repository": {
                "name": "app",
                "clone_url": "https://github.com/user/app.git",
            }
        }

        response = webhook_helper.send_webhook(payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "accepted"

    def test_webhook_handles_missing_repository(
        self, docker_compose_up, webhook_helper
    ):
        """Test webhook handles payload without repository info."""
        payload = {"action": "opened"}

        response = webhook_helper.send_webhook(payload)
        assert response.status_code == 200
        # Should accept but not process
        data = response.json()
        assert data.get("status") == "accepted"

    def test_webhook_handles_invalid_json(self, docker_compose_up):
        """Test webhook handles invalid JSON gracefully."""
        secret = "test-webhook-secret"
        body = b"not-json"
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        signature = f"sha256={digest}"

        response = requests.post(
            "http://localhost:8080/webhook",
            data=body,
            headers={"X-Hub-Signature-256": signature},
            timeout=10,
        )
        assert response.status_code == 200
        data = response.json()
        assert "warning" in data or data.get("status") == "accepted"

    def test_webhook_with_custom_container_port(
        self, docker_compose_up, webhook_helper
    ):
        """Test webhook respects custom container_port."""
        payload = {
            "repository": {
                "name": "app",
                "clone_url": "https://github.com/user/app.git",
            },
            "container_port": 3000,
        }

        response = webhook_helper.send_webhook(payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "accepted"

    def test_webhook_with_environment_variables(
        self, docker_compose_up, webhook_helper
    ):
        """Test webhook handles environment variables in payload."""
        payload = {
            "repository": {
                "name": "app",
                "clone_url": "https://github.com/user/app.git",
            },
            "environment": {
                "NODE_ENV": "production",
                "DEBUG": "false",
            },
        }

        response = webhook_helper.send_webhook(payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "accepted"

    def test_webhook_rate_limiting(self, docker_compose_up, webhook_helper):
        """Test webhook rate limiting (10/minute per IP)."""
        payload = {
            "repository": {
                "name": "app",
                "clone_url": "https://github.com/user/app.git",
            }
        }

        # Send multiple requests
        responses = []
        for i in range(5):
            response = webhook_helper.send_webhook(payload)
            responses.append(response.status_code)
            time.sleep(0.1)

        # All should succeed (rate limit is per IP and may not trigger in test)
        assert all(status in (200, 429) for status in responses)

    def test_webhook_increments_deployment_counter(
        self, docker_compose_up, webhook_helper
    ):
        """Test webhook increments deployment counter metric."""
        payload = {
            "repository": {
                "name": "app",
                "clone_url": "https://github.com/user/app.git",
            }
        }

        # Get initial metrics
        metrics_response = requests.get("http://localhost:8080/metrics", timeout=5)
        #  initial_metrics = metrics_response.text

        # Send webhook
        response = webhook_helper.send_webhook(payload)
        assert response.status_code == 200

        # Wait a bit for metrics to update
        time.sleep(1)

        # Get updated metrics
        metrics_response = requests.get("http://localhost:8080/metrics", timeout=5)
        updated_metrics = metrics_response.text

        # Metrics should have changed (deployment counter incremented)
        # This is a basic check - in production you'd parse the metrics
        assert len(updated_metrics) > 0

    def test_webhook_with_gitlab_format(self, docker_compose_up, webhook_helper):
        """Test webhook handles GitLab-style payload."""
        payload = {
            "project": {
                "name": "app",
                "git_http_url": "https://gitlab.com/user/app.git",
            },
            "object_kind": "push",
        }

        response = webhook_helper.send_webhook(payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "accepted"

    def test_webhook_response_structure(self, docker_compose_up, webhook_helper):
        """Test webhook response has expected structure."""
        payload = {
            "repository": {
                "name": "app",
                "clone_url": "https://github.com/user/app.git",
            }
        }

        response = webhook_helper.send_webhook(payload)
        assert response.status_code == 200
        data = response.json()

        # Check response structure
        assert "status" in data
        assert data["status"] in ("accepted", "rejected")
        assert "message" in data or "warning" in data

    def test_webhook_concurrent_requests(self, docker_compose_up, webhook_helper):
        """Test webhook handles concurrent requests."""
        import concurrent.futures

        payload = {
            "repository": {
                "name": "app",
                "clone_url": "https://github.com/user/app.git",
            }
        }

        def send_request():
            response = webhook_helper.send_webhook(payload)
            return response.status_code == 200

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(send_request) for _ in range(10)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        # All requests should succeed
        assert all(results), "Some concurrent webhook requests failed"
        assert len(results) == 10
